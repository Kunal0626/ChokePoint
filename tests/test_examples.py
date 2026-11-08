"""Tests for the shipped example networks and their committed output.

Two jobs:

*   The models stay valid and keep saying what their notes claim they say.
    Every figure quoted in examples/*.md is asserted here, so the prose
    cannot quietly become wrong.
*   The committed contents of examples/output/ stay reproducible. If the
    report format or an algorithm changes and nobody re-runs
    scripts/run_examples.sh, these fail. That is the point: the README
    promises a stranger can reproduce every number.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from chokepoint.loader import load_network
from chokepoint.recommend import analyze, apply_fix, whatif
from chokepoint.report import json_report

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"
NAMES = ["dmz", "home_lab", "small_company"]


def model(name: str):
    return load_network(EXAMPLES / f"{name}.json")


def committed(name: str) -> dict:
    return json.loads((EXAMPLES / "output" / name / "report.json").read_text("utf-8"))


# ---------------------------------------------------------------------------
# All examples
# ---------------------------------------------------------------------------


def test_every_example_is_discovered():
    found = sorted(p.stem for p in EXAMPLES.glob("*.json"))
    assert found == NAMES, "a new example needs notes and tests too"


@pytest.mark.parametrize("name", NAMES)
def test_example_loads_and_validates(name):
    network = model(name)
    assert network.nodes and network.edges and network.entry and network.targets


@pytest.mark.parametrize("name", NAMES)
def test_example_has_notes(name):
    notes = (EXAMPLES / f"{name}.md").read_text("utf-8")
    assert "Why these numbers" in notes
    assert "What the tool found" in notes


@pytest.mark.parametrize("name", NAMES)
def test_committed_report_is_reproducible(name):
    """Re-running the tool must reproduce the committed JSON exactly."""
    fresh = json_report(analyze(model(name), k=3))
    assert fresh == committed(name), (
        f"examples/output/{name}/report.json is stale; "
        "re-run ./scripts/run_examples.sh"
    )


@pytest.mark.parametrize("name", NAMES)
def test_committed_artifacts_exist(name):
    directory = EXAMPLES / "output" / name
    assert (directory / "report.txt").read_text("utf-8").startswith("=")
    assert (directory / "network.dot").read_text("utf-8").startswith("digraph")
    assert len((directory / "network.png").read_bytes()) > 10_000


@pytest.mark.parametrize("name", NAMES)
def test_the_minimum_fix_set_really_disconnects(name):
    """Apply every fix the report recommends and check nothing gets through."""
    network = model(name)
    for entry in analyze(network, k=3).fix_set.entries:
        network = apply_fix(network, entry.name)
    assert analyze(network).baseline_cheapest is None


@pytest.mark.parametrize("name", NAMES)
def test_every_example_reaches_its_target(name):
    """An example with no attack path would demonstrate nothing."""
    assert analyze(model(name), k=3).baseline_cheapest is not None


# ---------------------------------------------------------------------------
# home_lab: the degenerate ranking
# ---------------------------------------------------------------------------


def test_home_lab_has_two_equally_cheap_routes():
    result = analyze(model("home_lab"), k=3)
    assert result.baseline_cheapest == 5
    assert [p.total_difficulty for p in result.paths] == [5, 5, 6]
    assert result.paths[0].nodes == ("guest_wifi", "router", "nas")


def test_home_lab_single_fix_ranking_is_entirely_uninformative():
    """The headline claim of examples/home_lab.md.

    Redundant routes mean no single fix moves the attacker's cost at all,
    which is exactly when a greedy ranking stops being usable and the
    set-based min-cut earns its keep.
    """
    result = analyze(model("home_lab"), k=3)
    assert all(i.delta == 0 for i in result.fix_impacts), [
        (i.name, i.delta) for i in result.fix_impacts
    ]
    assert not any(i.disconnects for i in result.fix_impacts)


def test_home_lab_cut_shares_a_fix_across_two_edges():
    fix_set = analyze(model("home_lab"), k=3).fix_set
    assert fix_set.counts_a_fix_more_than_once
    assert fix_set.edge_count == 4
    assert len(fix_set.entries) == 3
    assert fix_set.cut_capacity == 6
    assert fix_set.deduplicated_cost == 5


# ---------------------------------------------------------------------------
# small_company: the interior cut beats the perimeter
# ---------------------------------------------------------------------------

PERIMETER_FIXES = [
    "Patch web application and deploy a WAF",
    "Enforce MFA on all external logins",
    "Mail filtering and phishing training",
]


def test_small_company_cheapest_route_is_through_the_web_server():
    result = analyze(model("small_company"), k=3)
    assert result.baseline_cheapest == 9
    assert result.paths[0].nodes == ("internet", "web", "db_prod")


def test_small_company_minimum_fix_set_is_interior():
    result = analyze(model("small_company"), k=3)
    assert result.fix_set.deduplicated_cost == 12
    assert {e.name for e in result.fix_set.entries} == {
        "Deploy LAPS and Credential Guard",
        "Move secrets to a vault and restrict the database to the app subnet",
        "Tighten file share permissions",
    }
    # Not one internet-facing control appears in it.
    assert not any(e.name in PERIMETER_FIXES for e in result.fix_set.entries)


def test_small_company_perimeter_would_work_but_costs_more():
    """Verifies the comparison quoted in examples/small_company.md.

    Sealing the perimeter is a valid answer -- it does disconnect -- just a
    dearer one, even though MFA is shared across two edges and so paid once.
    """
    network = model("small_company")
    reduced = network
    for name in PERIMETER_FIXES:
        reduced = apply_fix(reduced, name)
    assert analyze(reduced).baseline_cheapest is None, "the perimeter cut must work"

    fixes = {e.fix.name: e.fix.cost for e in network.edges}
    perimeter_cost = sum(fixes[name] for name in PERIMETER_FIXES)
    assert perimeter_cost == 13
    assert analyze(network, k=3).fix_set.deduplicated_cost == 12
    assert perimeter_cost > 12


# ---------------------------------------------------------------------------
# dmz: the deliberate misconfiguration
# ---------------------------------------------------------------------------

LEGACY_RULE = "Remove the legacy DMZ-to-database firewall rule"


def test_dmz_shortcut_is_found():
    """The example exists to check the tool spots the leftover rule."""
    result = analyze(model("dmz"), k=3)
    assert result.baseline_cheapest == 7
    assert result.paths[0].nodes == ("internet", "fw_ext", "dmz_web", "db_internal")
    assert LEGACY_RULE in result.paths[0].fix_names


def test_dmz_shortcut_is_far_cheaper_than_the_intended_route():
    """The designed route runs through the internal firewall and costs 20."""
    result = analyze(model("dmz"), k=3)
    intended = next(p for p in result.paths if "fw_int" in p.nodes)
    assert intended.total_difficulty == 20
    assert result.baseline_cheapest == 7
    assert intended.total_difficulty > 2 * result.baseline_cheapest


def test_dmz_removing_one_rule_raises_the_cost_by_six():
    outcome = whatif(model("dmz"), LEGACY_RULE, k=3)
    assert outcome.baseline_cheapest == 7
    assert outcome.new_cheapest == 13
    assert outcome.delta == 6
    assert outcome.applied.cost == 1
    assert outcome.original_paths_surviving == 2


def test_dmz_fixing_the_shortcut_does_not_restore_the_design():
    """The admin-phishing route at 13 is still cheaper than the intended 20."""
    reduced = apply_fix(model("dmz"), LEGACY_RULE)
    result = analyze(reduced, k=3)
    assert result.baseline_cheapest == 13
    assert "admin_ws" in result.paths[0].nodes


def test_dmz_unfixable_edge_tops_the_ranking_but_never_the_cut():
    """A prohibitive fix cost keeps a real but unusable edge out of the cut."""
    result = analyze(model("dmz"), k=3)
    top = result.fix_impacts[0]
    assert top.name.startswith("Withdraw all internet-facing services")
    assert top.disconnects, "it is the only fix that fully disconnects"
    assert top.cost == 40
    assert top.name not in {e.name for e in result.fix_set.entries}


def test_dmz_legacy_rule_is_the_best_value_fix():
    """Same effect as the WAF, one fifth of the cost -- the point of dmz.md."""
    impacts = {i.name: i for i in analyze(model("dmz"), k=3).fix_impacts}
    legacy = impacts[LEGACY_RULE]
    waf = impacts["Patch the DMZ web application and deploy a WAF"]
    assert legacy.delta == waf.delta == 6
    assert legacy.cost == 1
    assert waf.cost == 5
