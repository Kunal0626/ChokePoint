"""Tests for the recommendation layer and the what-if analysis."""

from __future__ import annotations

from fractions import Fraction

import pytest

from chokepoint.loader import parse_network
from chokepoint.recommend import (
    UnknownFixError,
    analyze,
    apply_fix,
    build_fix_set,
    distinct_fixes,
    whatif,
)
from helpers import random_network


def build(nodes, entry, targets, edges, name="t"):
    """edges entries are (from, to, difficulty, fix_name, fix_cost)."""
    return parse_network(
        {
            "name": name,
            "nodes": [{"id": n} for n in nodes],
            "entry": entry,
            "targets": targets,
            "edges": [
                {
                    "from": s,
                    "to": t,
                    "difficulty": d,
                    "technique": f"technique {s}->{t}",
                    "fix": {"name": fix, "cost": cost},
                }
                for s, t, d, fix, cost in edges
            ],
        }
    )


# Two routes. The cheap route is expensive to fix at its first hop and cheap
# at its second; the slow route is cheap to fix throughout.
TWO_ROUTES = (
    ["s", "a", "b", "t"],
    ["s"],
    ["t"],
    [
        ("s", "a", 1, "Patch web app", 5),
        ("a", "t", 1, "Rotate DB credentials", 1),
        ("s", "b", 5, "Mail filtering", 1),
        ("b", "t", 5, "Firewall SMB", 1),
    ],
)

# One real action closes both routes' first hop.
SHARED_FIX = (
    ["s", "a", "b", "t"],
    ["s"],
    ["t"],
    [
        ("s", "a", 1, "Enable MFA", 3),
        ("a", "t", 1, "Segment database", 10),
        ("s", "b", 1, "Enable MFA", 3),
        ("b", "t", 1, "Harden file server", 10),
    ],
)


# ---------------------------------------------------------------------------
# Fix bookkeeping
# ---------------------------------------------------------------------------


def test_distinct_fixes_collapses_a_shared_name():
    net = build(*SHARED_FIX)
    fixes = distinct_fixes(net)
    assert set(fixes) == {"Enable MFA", "Segment database", "Harden file server"}
    assert fixes["Enable MFA"].edge_count == 2
    assert fixes["Enable MFA"].cost == 3
    assert fixes["Segment database"].edge_count == 1


def test_apply_fix_removes_every_edge_that_names_it():
    net = build(*SHARED_FIX)
    reduced = apply_fix(net, "Enable MFA")
    assert len(reduced.edges) == 2
    assert all(e.fix.name != "Enable MFA" for e in reduced.edges)


def test_apply_fix_leaves_the_original_untouched():
    """Immutability matters: rank_fixes derives one copy per fix."""
    net = build(*SHARED_FIX)
    before = len(net.edges)
    apply_fix(net, "Enable MFA")
    assert len(net.edges) == before


def test_apply_fix_keeps_nodes_entries_and_targets():
    net = build(*TWO_ROUTES)
    reduced = apply_fix(net, "Patch web app")
    assert reduced.node_ids == net.node_ids
    assert reduced.entry == net.entry
    assert reduced.targets == net.targets


def test_unknown_fix_suggests_a_close_match():
    net = build(*TWO_ROUTES)
    with pytest.raises(UnknownFixError, match="did you mean 'Mail filtering'"):
        apply_fix(net, "Mail filterin")


def test_unknown_fix_lists_available_when_nothing_is_close():
    net = build(*TWO_ROUTES)
    with pytest.raises(UnknownFixError, match="available fixes"):
        apply_fix(net, "zzzzzzzzzz")


def test_removing_all_edges_is_allowed():
    """A derived network with no edges is legal; only input must be non-empty."""
    net = build(
        ["s", "t"], ["s"], ["t"], [("s", "t", 1, "Block it", 1)]
    )
    reduced = apply_fix(net, "Block it")
    assert reduced.edges == ()
    assert analyze(reduced).baseline_cheapest is None


# ---------------------------------------------------------------------------
# Path views
# ---------------------------------------------------------------------------


def test_path_view_carries_labels_techniques_and_fixes():
    net = parse_network(
        {
            "name": "t",
            "nodes": [
                {"id": "s", "label": "Internet"},
                {"id": "t", "label": "Database"},
            ],
            "entry": ["s"],
            "targets": ["t"],
            "edges": [
                {
                    "from": "s",
                    "to": "t",
                    "difficulty": 4,
                    "technique": "SQL injection",
                    "fix": {"name": "Parameterise queries", "cost": 2},
                }
            ],
        }
    )
    path = analyze(net).paths[0]
    assert path.nodes == ("s", "t")
    assert path.labels == ("Internet", "Database")
    assert path.fix_names == {"Parameterise queries"}
    hop = path.hops[0]
    assert (hop.technique, hop.fix_name, hop.fix_cost) == ("SQL injection", "Parameterise queries", 2)


# ---------------------------------------------------------------------------
# Section 2: the minimum fix set
# ---------------------------------------------------------------------------


def test_fix_set_is_the_min_cut_as_fixes():
    net = build(*TWO_ROUTES)
    fix_set = build_fix_set(net, "fixcost")
    assert {e.name for e in fix_set.entries} == {"Rotate DB credentials", "Mail filtering"}
    assert fix_set.deduplicated_cost == 2
    assert fix_set.cut_capacity == 2
    assert not fix_set.counts_a_fix_more_than_once


def test_shared_fix_is_counted_once_in_the_real_bill():
    """The capacity double-counts a shared fix; the report must not."""
    net = build(*SHARED_FIX)
    fix_set = build_fix_set(net, "fixcost")
    assert [e.name for e in fix_set.entries] == ["Enable MFA"]
    assert fix_set.edge_count == 2
    # Max-flow minimised 3 + 3; the defender pays 3 once.
    assert fix_set.cut_capacity == 6
    assert fix_set.deduplicated_cost == 3
    assert fix_set.counts_a_fix_more_than_once


def test_fix_set_entries_are_ordered_most_expensive_first():
    net = build(
        ["s", "a", "b", "t"],
        ["s"],
        ["t"],
        [
            ("s", "a", 1, "Cheap", 1),
            ("a", "t", 1, "Pricey", 9),
            ("s", "b", 1, "Mid", 4),
            ("b", "t", 1, "Pricey2", 9),
        ],
    )
    names = [e.name for e in build_fix_set(net, "fixcost").entries]
    assert names == ["Mid", "Cheap"]  # 4 then 1


def test_fix_set_is_empty_when_unreachable():
    net = build(["s", "a", "t"], ["s"], ["t"], [("s", "a", 1, "x", 1)])
    fix_set = build_fix_set(net, "fixcost")
    assert fix_set.entries == ()
    assert fix_set.deduplicated_cost == 0


def test_fix_set_works_in_fractional_mode():
    net = build(*TWO_ROUTES)
    fix_set = build_fix_set(net, "inverse-difficulty")
    assert isinstance(fix_set.cut_capacity, Fraction)


# ---------------------------------------------------------------------------
# Section 3: the single-fix ranking
# ---------------------------------------------------------------------------


def test_ranking_reports_delta_and_reach():
    result = analyze(build(*TWO_ROUTES), k=3)
    by_name = {i.name: i for i in result.fix_impacts}

    # Cutting either hop of the cheap route forces the 10-cost detour.
    assert by_name["Rotate DB credentials"].new_cheapest == 10
    assert by_name["Rotate DB credentials"].delta == 8
    # Cutting the slow route changes nothing for the attacker.
    assert by_name["Firewall SMB"].new_cheapest == 2
    assert by_name["Firewall SMB"].delta == 0
    assert all(i.top_paths_hit == 1 for i in result.fix_impacts)


def test_ranking_puts_disconnecting_fixes_first():
    net = build(["s", "t"], ["s"], ["t"], [("s", "t", 3, "Block it", 7)])
    impact = analyze(net).fix_impacts[0]
    assert impact.disconnects
    assert impact.new_cheapest is None
    assert impact.delta is None


def test_ranking_breaks_delta_ties_by_reach_then_cost():
    """Equal effect, so the cheaper fix should be recommended first."""
    net = build(
        ["s", "a", "t"],
        ["s"],
        ["t"],
        [("s", "a", 1, "Expensive", 9), ("a", "t", 1, "Cheap", 1)],
    )
    # Both fixes disconnect the only route, so cost is the deciding factor.
    assert [i.name for i in analyze(net).fix_impacts] == ["Cheap", "Expensive"]


def test_ranking_counts_a_shared_fix_once_but_reports_its_edges():
    result = analyze(build(*SHARED_FIX), k=5)
    mfa = next(i for i in result.fix_impacts if i.name == "Enable MFA")
    assert mfa.edges_removed == 2
    assert mfa.disconnects  # closing both first hops cuts everything


def test_ranking_is_skipped_cleanly_when_unreachable():
    net = build(["s", "a", "t"], ["s"], ["t"], [("s", "a", 1, "x", 1)])
    result = analyze(net)
    assert not result.reachable
    assert all(i.delta is None for i in result.fix_impacts)


# ---------------------------------------------------------------------------
# What-if
# ---------------------------------------------------------------------------


def test_whatif_reports_the_new_cheapest_cost():
    result = whatif(build(*TWO_ROUTES), "Rotate DB credentials", k=3)
    assert result.baseline_cheapest == 2
    assert result.new_cheapest == 10
    assert result.delta == 8
    assert not result.disconnects


def test_whatif_counts_surviving_original_paths():
    result = whatif(build(*TWO_ROUTES), "Rotate DB credentials", k=3)
    assert result.original_path_count == 2
    assert result.original_paths_surviving == 1


def test_whatif_can_disconnect_entirely():
    result = whatif(build(*SHARED_FIX), "Enable MFA", k=3)
    assert result.disconnects
    assert result.new_cheapest is None
    assert result.delta is None
    assert result.paths == ()


def test_whatif_records_how_many_links_the_fix_closed():
    result = whatif(build(*SHARED_FIX), "Enable MFA")
    assert result.applied.edge_count == 2
    assert result.applied.cost == 3


def test_whatif_rejects_an_unknown_fix():
    with pytest.raises(UnknownFixError):
        whatif(build(*TWO_ROUTES), "No such fix")


# ---------------------------------------------------------------------------
# Properties over random graphs
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("seed", range(80))
def test_a_fix_can_never_help_the_attacker(seed):
    """Removing edges can only raise the cheapest cost, never lower it."""
    net = random_network(seed, n_nodes=14, n_edges=32)
    result = analyze(net, k=3)
    if not result.reachable:
        return
    for impact in result.fix_impacts:
        if impact.new_cheapest is not None:
            assert impact.new_cheapest >= result.baseline_cheapest, (
                f"seed {seed}: fix {impact.name!r} lowered the attacker's cost"
            )
            assert impact.delta is not None and impact.delta >= 0


@pytest.mark.parametrize("seed", range(80))
def test_applying_the_whole_min_cut_always_disconnects(seed):
    """The promise section 2 makes, checked by actually applying the fixes."""
    net = random_network(seed, n_nodes=14, n_edges=32, n_entry=2, n_targets=2)
    result = analyze(net, k=3)
    reduced = net
    for entry in result.fix_set.entries:
        reduced = apply_fix(reduced, entry.name)
    assert analyze(reduced).baseline_cheapest is None, f"seed {seed}"


@pytest.mark.parametrize("seed", range(60))
def test_deduplicated_cost_never_exceeds_the_cut_capacity(seed):
    """Counting a shared fix once can only lower the bill, never raise it."""
    net = random_network(seed, n_nodes=14, n_edges=32)
    fix_set = build_fix_set(net, "fixcost")
    assert fix_set.deduplicated_cost <= fix_set.cut_capacity, f"seed {seed}"


@pytest.mark.parametrize("seed", range(40))
def test_analysis_is_deterministic(seed):
    net = random_network(seed, n_nodes=12, n_edges=28)
    assert analyze(net, k=3) == analyze(net, k=3)
