"""Tests for text and JSON rendering."""

from __future__ import annotations

import json

import pytest

from chokepoint.loader import parse_network
from chokepoint.recommend import analyze, whatif
from chokepoint.report import json_report, json_whatif, text_report, text_whatif
from helpers import random_network

DEMO = {
    "name": "demo",
    "nodes": [
        {"id": "internet", "label": "Internet", "type": "external"},
        {"id": "web", "label": "Web server", "type": "server"},
        {"id": "mail", "label": "Mail server", "type": "server"},
        {"id": "db", "label": "Production database", "type": "database"},
    ],
    "entry": ["internet"],
    "targets": ["db"],
    "edges": [
        {"from": "internet", "to": "web", "difficulty": 1, "technique": "unpatched web app",
         "fix": {"name": "Patch web app", "cost": 5}},
        {"from": "web", "to": "db", "difficulty": 1, "technique": "reused DB credentials",
         "fix": {"name": "Rotate DB credentials", "cost": 1}},
        {"from": "internet", "to": "mail", "difficulty": 5, "technique": "phishing",
         "fix": {"name": "Mail filtering", "cost": 1}},
        {"from": "mail", "to": "db", "difficulty": 5, "technique": "SMB exposed",
         "fix": {"name": "Firewall SMB", "cost": 1}},
    ],
}

UNREACHABLE = {
    "name": "safe",
    "nodes": [{"id": "a"}, {"id": "b"}, {"id": "c"}],
    "entry": ["a"],
    "targets": ["c"],
    "edges": [{"from": "a", "to": "b", "difficulty": 2}],
}


def demo():
    return parse_network(DEMO)


# ---------------------------------------------------------------------------
# Text
# ---------------------------------------------------------------------------


def test_text_report_has_all_three_sections():
    text = text_report(analyze(demo(), k=3))
    assert "1. ATTACK PATHS" in text
    assert "2. MINIMUM FIX SET" in text
    assert "3. SINGLE-FIX RANKING" in text


def test_text_report_names_techniques_and_fixes_per_hop():
    text = text_report(analyze(demo(), k=3))
    assert "unpatched web app" in text
    assert "reused DB credentials" in text
    assert "fix: Patch web app (cost 5)" in text


def test_text_report_uses_labels_not_raw_ids():
    text = text_report(analyze(demo(), k=3))
    assert "Internet -> Web server -> Production database" in text


def test_text_report_marks_the_target():
    assert "<-- TARGET" in text_report(analyze(demo(), k=3))


def test_text_report_says_when_fewer_paths_exist_than_requested():
    text = text_report(analyze(demo(), k=9))
    assert "only 2 distinct loopless paths exist" in text


def test_text_report_handles_an_unreachable_target():
    text = text_report(analyze(parse_network(UNREACHABLE)))
    assert "No attack path exists" in text
    assert "Skipped: with no attack path" in text


def test_text_report_flags_a_shared_fix_in_the_cut():
    net = parse_network(
        {
            "name": "shared",
            "nodes": [{"id": n} for n in ("s", "a", "b", "t")],
            "entry": ["s"],
            "targets": ["t"],
            "edges": [
                {"from": "s", "to": "a", "difficulty": 1, "fix": {"name": "Enable MFA", "cost": 3}},
                {"from": "a", "to": "t", "difficulty": 1, "fix": {"name": "Segment db", "cost": 10}},
                {"from": "s", "to": "b", "difficulty": 1, "fix": {"name": "Enable MFA", "cost": 3}},
                {"from": "b", "to": "t", "difficulty": 1, "fix": {"name": "Harden fs", "cost": 10}},
            ],
        }
    )
    text = text_report(analyze(net))
    assert "closes 2 links" in text
    assert "the real bill is" in text
    assert "MINCUT_VS_GREEDY" in text


@pytest.mark.parametrize("seed", range(40))
def test_text_report_never_crashes_on_random_input(seed):
    net = random_network(seed, n_nodes=12, n_edges=28, n_entry=2, n_targets=2)
    assert isinstance(text_report(analyze(net, k=3)), str)


def test_text_whatif_reports_before_and_after():
    text = text_whatif(whatif(demo(), "Rotate DB credentials", k=3))
    assert "Cheapest attack cost before : 2" in text
    assert "Cheapest attack cost after  : 10" in text
    assert "+8" in text


def test_text_whatif_reports_a_full_disconnect():
    net = parse_network(
        {
            "name": "one-link",
            "nodes": [{"id": "s"}, {"id": "t"}],
            "entry": ["s"],
            "targets": ["t"],
            "edges": [{"from": "s", "to": "t", "difficulty": 3, "fix": {"name": "Block", "cost": 1}}],
        }
    )
    text = text_whatif(whatif(net, "Block"))
    assert "no route remains" in text
    assert "disconnects every target" in text


# ---------------------------------------------------------------------------
# JSON
# ---------------------------------------------------------------------------


def test_json_report_is_serialisable():
    payload = json_report(analyze(demo(), k=3))
    assert json.loads(json.dumps(payload)) == payload


def test_json_report_structure():
    payload = json_report(analyze(demo(), k=3))
    assert payload["network"] == "demo"
    assert payload["capacity_mode"] == "fixcost"
    assert payload["target_reachable"] is True
    assert payload["cheapest_attack_cost"] == 2
    assert len(payload["attack_paths"]) == 2
    assert payload["minimum_fix_set"]["total_cost"] == 2
    assert {f["name"] for f in payload["minimum_fix_set"]["fixes"]} == {
        "Mail filtering",
        "Rotate DB credentials",
    }
    assert len(payload["single_fix_ranking"]) == 4


def test_json_hops_carry_technique_and_fix():
    payload = json_report(analyze(demo(), k=1))
    hop = payload["attack_paths"][0]["hops"][0]
    assert hop["from"] == "internet"
    assert hop["technique"] == "unpatched web app"
    assert hop["fix"] == {"name": "Patch web app", "cost": 5}


def test_integer_capacities_are_json_numbers():
    payload = json_report(analyze(demo(), mode="fixcost"))
    assert payload["minimum_fix_set"]["cut_capacity"] == 2
    assert isinstance(payload["minimum_fix_set"]["cut_capacity"], int)


def test_fractional_capacities_are_exact_strings():
    """A float would discard the exactness the pipeline preserves."""
    payload = json_report(analyze(demo(), mode="inverse-difficulty"))
    capacity = payload["minimum_fix_set"]["cut_capacity"]
    assert isinstance(capacity, str)
    assert capacity == "6/5"
    assert json.loads(json.dumps(payload))["minimum_fix_set"]["cut_capacity"] == "6/5"


def test_json_report_declares_its_number_format():
    payload = json_report(analyze(demo()))
    assert "exact" in payload["_format"]


def test_json_report_handles_an_unreachable_target():
    payload = json_report(analyze(parse_network(UNREACHABLE)))
    assert payload["target_reachable"] is False
    assert payload["cheapest_attack_cost"] is None
    assert payload["attack_paths"] == []
    assert payload["minimum_fix_set"]["fixes"] == []


def test_json_whatif_structure():
    payload = json_whatif(whatif(demo(), "Rotate DB credentials", k=3))
    assert json.loads(json.dumps(payload)) == payload
    assert payload["applied_fix"]["name"] == "Rotate DB credentials"
    assert payload["cheapest_before"] == 2
    assert payload["cheapest_after"] == 10
    assert payload["raises_cheapest_by"] == 8
    assert payload["disconnects"] is False
    assert payload["original_paths_surviving"] == 1


@pytest.mark.parametrize("seed", range(40))
def test_json_report_is_always_serialisable(seed):
    net = random_network(seed, n_nodes=12, n_edges=28)
    for mode in ("fixcost", "unit", "inverse-difficulty"):
        payload = json_report(analyze(net, k=3, mode=mode))
        json.dumps(payload)  # must not raise
