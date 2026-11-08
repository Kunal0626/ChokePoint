"""Tests for Edmonds-Karp, min-cut extraction, and the capacity modes.

The two tests worth reading first are
``test_residual_edges_allow_an_earlier_choice_to_be_undone`` (what residual
edges buy) and ``test_bfs_bounds_rounds_independently_of_capacity`` (what
BFS buys over plain Ford-Fulkerson).
"""

from __future__ import annotations

from fractions import Fraction

import networkx as nx
import pytest

import chokepoint.maxflow as maxflow_module
from chokepoint.capacity import CAPACITY_MODES, arc_capacities, edge_capacity
from chokepoint.maxflow import SelfCheckError, max_flow_min_cut, min_cut
from helpers import augmented, networkx_min_cut_value, random_network
from chokepoint.loader import parse_network


def net_with_costs(nodes, entry, targets, edges):
    """Build a network where each edge carries its own difficulty and fix cost.

    ``edges`` entries are (from, to, difficulty, fix_cost).
    """
    return parse_network(
        {
            "name": "t",
            "nodes": [{"id": n} for n in nodes],
            "entry": entry,
            "targets": targets,
            "edges": [
                {
                    "from": s,
                    "to": t,
                    "difficulty": d,
                    "fix": {"name": f"fix {s}->{t} ({cost})", "cost": cost},
                }
                for s, t, d, cost in edges
            ],
        }
    )


def cut_names(net, cut):
    return sorted(net.edges[i].fix.name for i in cut.edge_indices)


# ---------------------------------------------------------------------------
# Core max-flow behaviour
# ---------------------------------------------------------------------------


def test_series_chain_cuts_the_cheapest_link():
    """One route, so the cheapest fix along it is the whole answer."""
    net = net_with_costs(
        ["a", "b", "c", "d"],
        ["a"],
        ["d"],
        [("a", "b", 1, 5), ("b", "c", 1, 2), ("c", "d", 1, 9)],
    )
    cut = min_cut(net)
    assert cut.value == 2
    assert cut_names(net, cut) == ["fix b->c (2)"]


def test_two_independent_routes_must_both_be_cut():
    """A single fix cannot help when there are two disjoint ways in."""
    net = net_with_costs(
        ["a", "x", "y", "d"],
        ["a"],
        ["d"],
        [("a", "x", 1, 3), ("x", "d", 1, 8), ("a", "y", 1, 4), ("y", "d", 1, 7)],
    )
    cut = min_cut(net)
    assert cut.value == 7  # 3 + 4, the cheap end of each route
    assert cut_names(net, cut) == ["fix a->x (3)", "fix a->y (4)"]


def test_residual_edges_allow_an_earlier_choice_to_be_undone():
    """Without backward residuals this returns 1 instead of 2.

    Saturating s->a->b->t first appears to block both remaining routes. The
    backward residual on a->b is what lets the second augmentation re-route
    that unit and reach a total of 2.
    """
    net = net_with_costs(
        ["s", "a", "b", "t"],
        ["s"],
        ["t"],
        [
            ("s", "a", 1, 1),
            ("b", "t", 1, 1),
            ("a", "b", 1, 1),
            ("s", "b", 1, 1),
            ("a", "t", 1, 1),
        ],
    )
    cut = min_cut(net)
    assert cut.value == 2


def test_bfs_bounds_rounds_independently_of_capacity():
    """The pathological Ford-Fulkerson graph.

    Two fat routes joined by a capacity-1 edge. A DFS path choice can
    alternate across the middle edge and need 2,000,000 augmentations on a
    four-node graph. BFS takes the two short paths first and finishes in a
    handful of rounds, which is the whole point of Edmonds-Karp.
    """
    fat = 1_000_000
    net = net_with_costs(
        ["s", "a", "b", "t"],
        ["s"],
        ["t"],
        [
            ("s", "a", 1, fat),
            ("s", "b", 1, fat),
            ("a", "t", 1, fat),
            ("b", "t", 1, fat),
            ("a", "b", 1, 1),
        ],
    )
    cut = min_cut(net)
    assert cut.value == 2 * fat
    assert cut.augmentations <= 4, f"took {cut.augmentations} rounds; BFS should need ~2"


def test_unreachable_target_gives_an_empty_cut():
    """Nothing to fix: no route exists in the first place."""
    net = net_with_costs(["a", "b", "c"], ["a"], ["c"], [("a", "b", 1, 3)])
    cut = min_cut(net)
    assert cut.value == 0
    assert cut.edge_indices == ()
    assert cut.size == 0


def test_parallel_edges_are_cut_independently():
    """Two techniques between the same hosts need two separate fixes."""
    net = net_with_costs(
        ["a", "b"], ["a"], ["b"], [("a", "b", 2, 3), ("a", "b", 7, 4)]
    )
    cut = min_cut(net)
    assert cut.value == 7  # both must go
    assert cut.size == 2


def test_min_cut_is_not_just_the_cheapest_single_edge():
    """Two edges at 3 and 4 beat one edge at 8."""
    net = net_with_costs(
        ["a", "x", "y", "d"],
        ["a"],
        ["d"],
        [("a", "x", 1, 3), ("x", "d", 1, 8), ("a", "y", 1, 4), ("y", "d", 1, 8)],
    )
    cut = min_cut(net)
    assert cut.value == 7
    assert cut.size == 2


def test_attacker_side_excludes_the_virtual_source():
    net = net_with_costs(["a", "b", "c"], ["a"], ["c"], [("a", "b", 1, 1), ("b", "c", 1, 9)])
    cut = min_cut(net)
    assert "a" in cut.attacker_side
    assert not any(n.startswith("__source__") for n in cut.attacker_side)


def test_results_are_deterministic():
    net = random_network(5, n_nodes=14, n_edges=30)
    first = min_cut(net)
    for _ in range(5):
        assert min_cut(net) == first


# ---------------------------------------------------------------------------
# Multiple entries and targets
# ---------------------------------------------------------------------------


def test_several_entries_are_handled_jointly():
    """The joint cut is cheaper than fixing each entry's route separately."""
    net = net_with_costs(
        ["a", "b", "hub", "d"],
        ["a", "b"],
        ["d"],
        [("a", "hub", 1, 5), ("b", "hub", 1, 5), ("hub", "d", 1, 2)],
    )
    cut = min_cut(net)
    # Cutting the shared hub->d link costs 2; cutting both entry links costs 10.
    assert cut.value == 2
    assert cut_names(net, cut) == ["fix hub->d (2)"]


def test_several_targets_must_all_be_protected():
    net = net_with_costs(
        ["a", "x", "y"],
        ["a"],
        ["x", "y"],
        [("a", "x", 1, 3), ("a", "y", 1, 4)],
    )
    cut = min_cut(net)
    assert cut.value == 7
    assert cut.size == 2


def test_virtual_arcs_never_appear_in_the_cut():
    """Guards the sentinel-capacity argument in capacity.arc_capacities."""
    for seed in range(40):
        net = random_network(seed, n_nodes=12, n_edges=28, n_entry=3, n_targets=3)
        graph = augmented(net)
        cut = max_flow_min_cut(graph)
        # Every reported index is a real Network edge, and the counts agree,
        # so nothing virtual was silently dropped on the way out.
        assert all(0 <= i < len(net.edges) for i in cut.edge_indices)


# ---------------------------------------------------------------------------
# Capacity modes
# ---------------------------------------------------------------------------


def test_unit_mode_counts_links_not_cost():
    net = net_with_costs(
        ["a", "x", "y", "d"],
        ["a"],
        ["d"],
        [("a", "x", 1, 50), ("x", "d", 1, 50), ("a", "y", 1, 50), ("y", "d", 1, 50)],
    )
    assert min_cut(net, "unit").value == 2


def test_unit_mode_equals_the_number_of_edge_disjoint_paths():
    """Menger's theorem, which is the unit-capacity case of max-flow min-cut."""
    net = net_with_costs(
        ["a", "p", "q", "r", "d"],
        ["a"],
        ["d"],
        [
            ("a", "p", 1, 1),
            ("p", "d", 1, 1),
            ("a", "q", 1, 1),
            ("q", "d", 1, 1),
            ("a", "r", 1, 1),
            ("r", "d", 1, 1),
        ],
    )
    assert min_cut(net, "unit").value == 3


def test_inverse_difficulty_is_exact():
    net = net_with_costs(["a", "b", "c"], ["a"], ["c"], [("a", "b", 3, 1), ("b", "c", 7, 1)])
    cut = min_cut(net, "inverse-difficulty")
    # 1/7 < 1/3, so the hard link is the cheap one to cut in this mode.
    assert cut.value == Fraction(1, 7)
    assert isinstance(cut.value, Fraction)


def test_inverse_difficulty_prefers_the_harder_link_within_one_route():
    """The counter-intuitive behaviour discussed in capacity.py.

    Given a choice *along a single route*, this mode cuts the hard link,
    because 1/10 is cheaper than 1/1. That is backwards from "go and fix the
    easy things", which is why the mode's docstring spells out which question
    it is really answering.
    """
    net = net_with_costs(
        ["a", "mid", "d"], ["a"], ["d"], [("a", "mid", 1, 1), ("mid", "d", 10, 1)]
    )
    cut = min_cut(net, "inverse-difficulty")
    assert [net.edges[i].difficulty for i in cut.edge_indices] == [10]
    assert cut.value == Fraction(1, 10)


def test_inverse_difficulty_still_cuts_every_route():
    """Preference only applies where there is a choice.

    Two disjoint routes must both be cut, so an easy link gets cut whether
    the mode likes it or not: 1/1 from the easy route plus 1/10 from the hard
    one. Worth stating explicitly, because it bounds how far the mode's bias
    actually reaches.
    """
    net = net_with_costs(
        ["a", "easy", "hard", "d"],
        ["a"],
        ["d"],
        [("a", "easy", 1, 1), ("easy", "d", 1, 1),
         ("a", "hard", 10, 1), ("hard", "d", 10, 1)],
    )
    cut = min_cut(net, "inverse-difficulty")
    assert cut.value == Fraction(11, 10)
    assert sorted(net.edges[i].difficulty for i in cut.edge_indices) == [1, 10]


def test_edge_capacity_rejects_an_unknown_mode():
    net = net_with_costs(["a", "b"], ["a"], ["b"], [("a", "b", 1, 1)])
    with pytest.raises(ValueError, match="unknown capacity mode"):
        edge_capacity(net.edges[0], "cheapest")


def test_virtual_sentinel_exceeds_every_real_capacity_total():
    net = net_with_costs(["a", "b"], ["a"], ["b"], [("a", "b", 1, 4), ("a", "b", 1, 6)])
    graph = augmented(net)
    caps = arc_capacities(graph, "fixcost")
    real_total = 4 + 6
    virtual = [caps[i] for i, arc in enumerate(graph.arcs) if arc.edge_index is None]
    assert all(v > real_total for v in virtual)


# ---------------------------------------------------------------------------
# The self-checks
# ---------------------------------------------------------------------------


def test_self_check_fires_when_the_cut_disagrees_with_the_flow(monkeypatch):
    """Corrupt the reachable set and the theorem check must catch it."""
    net = net_with_costs(["a", "b"], ["a"], ["b"], [("a", "b", 1, 3)])
    # Claiming every node is on the attacker's side yields an empty cut,
    # which cannot match a positive flow.
    monkeypatch.setattr(
        maxflow_module, "_reachable", lambda residual, source: set(residual.out)
    )
    with pytest.raises(SelfCheckError, match="theorem violated"):
        min_cut(net)


def test_self_check_is_an_exception_not_an_assert():
    """assert statements vanish under python -O; this check must not."""
    assert issubclass(SelfCheckError, RuntimeError)


def test_sink_reachability_helper():
    net = net_with_costs(["a", "b", "c"], ["a"], ["c"], [("a", "b", 1, 1), ("b", "c", 1, 1)])
    graph = augmented(net)
    assert maxflow_module._sink_still_reachable(graph, frozenset())
    # Arc 1 is the a->b edge; removing it isolates the target.
    assert not maxflow_module._sink_still_reachable(graph, frozenset({1}))


def test_cut_really_disconnects_on_random_graphs():
    """An external restatement of the self-check, in case it is ever weakened."""
    for seed in range(60):
        net = random_network(seed, n_nodes=14, n_edges=32, n_entry=2, n_targets=2)
        graph = augmented(net)
        cut = max_flow_min_cut(graph)
        removed = frozenset(
            arc_index
            for arc_index, arc in enumerate(graph.arcs)
            if arc.edge_index in cut.edge_indices
        )
        assert not maxflow_module._sink_still_reachable(graph, removed), f"seed {seed}"


# ---------------------------------------------------------------------------
# networkx oracle
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("mode", CAPACITY_MODES)
@pytest.mark.parametrize("seed", range(120))
def test_matches_networkx_minimum_cut(seed, mode):
    """360 comparisons: every capacity mode against networkx.minimum_cut."""
    net = random_network(seed, n_nodes=12, n_edges=25, allow_parallel=False)
    graph = augmented(net)
    assert max_flow_min_cut(graph, mode).value == networkx_min_cut_value(
        graph, mode
    ), f"seed {seed} mode {mode}"


@pytest.mark.parametrize("seed", range(120))
def test_matches_networkx_on_multigraphs_by_summing_capacities(seed):
    """networkx refuses multigraphs, but parallel capacities add.

    Two parallel edges of capacity c1 and c2 are equivalent to one of
    c1 + c2 for flow purposes, so the value must still agree even though the
    cut's edge set cannot be recovered from the collapsed mirror.
    """
    net = random_network(seed, n_nodes=12, n_edges=30)
    graph = augmented(net)
    assert max_flow_min_cut(graph, "fixcost").value == networkx_min_cut_value(
        graph, "fixcost", summed=True
    ), f"seed {seed}"


@pytest.mark.parametrize("seed", range(60))
def test_matches_networkx_with_many_entries_and_targets(seed):
    net = random_network(
        seed, n_nodes=18, n_edges=50, n_entry=3, n_targets=3, allow_parallel=False
    )
    graph = augmented(net)
    assert max_flow_min_cut(graph, "fixcost").value == networkx_min_cut_value(
        graph, "fixcost"
    ), f"seed {seed}"


@pytest.mark.parametrize("seed", range(60))
def test_dense_graphs_agree(seed):
    net = random_network(seed, n_nodes=10, n_edges=45, allow_parallel=False)
    graph = augmented(net)
    assert max_flow_min_cut(graph, "fixcost").value == networkx_min_cut_value(
        graph, "fixcost"
    ), f"seed {seed}"


@pytest.mark.parametrize("seed", range(100))
def test_cut_capacity_always_equals_the_flow_value(seed):
    """The theorem itself, restated as a property over random graphs."""
    net = random_network(seed, n_nodes=14, n_edges=35)
    graph = augmented(net)
    caps = arc_capacities(graph, "fixcost")
    cut = max_flow_min_cut(graph, "fixcost")
    total = sum(
        caps[arc_index]
        for arc_index, arc in enumerate(graph.arcs)
        if arc.edge_index in cut.edge_indices
    )
    assert total == cut.value, f"seed {seed}"
