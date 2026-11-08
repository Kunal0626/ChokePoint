"""Tests for Yen's k-shortest-loopless-paths.

Two of these are load-bearing and worth reading before the rest:

*   ``test_second_best_path_may_share_a_prefix`` is the case that separates
    Yen's from the naive "delete the best path and re-run Dijkstra".
*   ``test_loops_are_not_offered_as_a_second_path`` is the case that separates
    loopless paths from k-shortest walks.
"""

from __future__ import annotations

import pytest

from chokepoint.dijkstra import cheapest_attack_path
from chokepoint.yen import k_shortest_attack_paths, k_shortest_routes
from helpers import (
    assert_path_consistent,
    augmented,
    network,
    networkx_k_shortest_costs,
    random_network,
)


def costs(paths) -> list[int]:
    return [p.total_difficulty for p in paths]


# The graph from the module docstring: the second-best route reuses a->b.
SHARED_PREFIX = (
    ["a", "b", "c", "d", "x", "y"],
    ["a"],
    ["d"],
    [
        ("a", "b", 1),
        ("b", "c", 1),
        ("c", "d", 1),
        ("b", "x", 2),
        ("x", "d", 2),
        ("a", "y", 4),
        ("y", "d", 4),
    ],
)


# ---------------------------------------------------------------------------
# Core behaviour
# ---------------------------------------------------------------------------


def test_k_of_one_is_just_dijkstra():
    net = network(*SHARED_PREFIX)
    paths = k_shortest_attack_paths(net, k=1)
    assert len(paths) == 1
    assert paths[0] == cheapest_attack_path(net)


def test_second_best_path_may_share_a_prefix():
    """The whole point of Yen's.

    Deleting every edge of the best path would forbid a->b and report the
    edge-disjoint a-y-d at 8. The true second-best is a-b-x-d at 5.
    """
    paths = k_shortest_attack_paths(network(*SHARED_PREFIX), k=3)
    assert costs(paths) == [3, 5, 8]
    assert paths[0].nodes == ("a", "b", "c", "d")
    assert paths[1].nodes == ("a", "b", "x", "d")
    assert paths[2].nodes == ("a", "y", "d")


def test_loops_are_not_offered_as_a_second_path():
    """a-b-a-b-c is a cheap second *walk* and a nonsense attack path.

    An attacker who already controls b gains nothing by compromising it
    again, so the only loopless route here is a-b-c and k=3 must return one
    path rather than padding the list with walks.
    """
    net = network(["a", "b", "c"], ["a"], ["c"], [("a", "b", 1), ("b", "a", 1), ("b", "c", 1)])
    paths = k_shortest_attack_paths(net, k=3)
    assert len(paths) == 1
    assert paths[0].nodes == ("a", "b", "c")


def test_returns_fewer_than_k_when_fewer_exist():
    net = network(["a", "b"], ["a"], ["b"], [("a", "b", 2)])
    assert len(k_shortest_attack_paths(net, k=10)) == 1


def test_unreachable_target_returns_no_paths():
    net = network(["a", "b", "c"], ["a"], ["c"], [("a", "b", 1)])
    assert k_shortest_attack_paths(net, k=3) == []


@pytest.mark.parametrize("k", [0, -1, -99])
def test_k_below_one_is_rejected(k):
    net = network(*SHARED_PREFIX)
    with pytest.raises(ValueError, match="k must be at least 1"):
        k_shortest_attack_paths(net, k=k)


def test_costs_are_nondecreasing():
    net = network(
        ["a", "b", "c", "d"],
        ["a"],
        ["d"],
        [("a", "b", 1), ("b", "d", 1), ("a", "c", 2), ("c", "d", 2), ("a", "d", 9)],
    )
    assert costs(k_shortest_attack_paths(net, k=3)) == [2, 4, 9]


def test_every_path_is_internally_consistent():
    net = network(*SHARED_PREFIX)
    for path in k_shortest_attack_paths(net, k=3):
        assert_path_consistent(net, path)


def test_results_are_deterministic():
    net = network(*SHARED_PREFIX)
    first = k_shortest_attack_paths(net, k=3)
    for _ in range(5):
        assert k_shortest_attack_paths(net, k=3) == first


# ---------------------------------------------------------------------------
# Parallel edges: distinct techniques, distinct fixes, distinct paths
# ---------------------------------------------------------------------------


def test_parallel_edges_give_two_distinct_paths():
    """Same hosts, two techniques, two fixes -- so two routes worth reporting.

    Comparing paths by node sequence would collapse these into one and hide a
    fix the defender needs.
    """
    net = network(["a", "b"], ["a"], ["b"], [("a", "b", 2), ("a", "b", 5)])
    paths = k_shortest_attack_paths(net, k=3)
    assert costs(paths) == [2, 5]
    assert paths[0].nodes == paths[1].nodes == ("a", "b")
    assert paths[0].edge_indices == (0,)
    assert paths[1].edge_indices == (1,)


def test_parallel_edges_mid_route():
    net = network(
        ["a", "b", "c"],
        ["a"],
        ["c"],
        [("a", "b", 1), ("b", "c", 2), ("b", "c", 3), ("b", "c", 4)],
    )
    paths = k_shortest_attack_paths(net, k=4)
    assert costs(paths) == [3, 4, 5]
    assert len({p.edge_indices for p in paths}) == 3


# ---------------------------------------------------------------------------
# Multiple entries and targets
# ---------------------------------------------------------------------------


def test_paths_from_different_entry_points():
    net = network(
        ["a", "b", "t"], ["a", "b"], ["t"], [("a", "t", 2), ("b", "t", 5)]
    )
    paths = k_shortest_attack_paths(net, k=3)
    assert costs(paths) == [2, 5]
    assert paths[0].nodes == ("a", "t")
    assert paths[1].nodes == ("b", "t")


def test_paths_to_different_targets():
    net = network(
        ["a", "x", "y"], ["a"], ["x", "y"], [("a", "x", 3), ("a", "y", 6)]
    )
    assert costs(k_shortest_attack_paths(net, k=3)) == [3, 6]


# ---------------------------------------------------------------------------
# networkx oracle on graphs with no parallel edges
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("seed", range(200))
def test_matches_networkx_cost_sequence(seed):
    """A mix that includes many graphs with fewer than k paths, and some with none."""
    net = random_network(seed, n_nodes=12, n_edges=25, allow_parallel=False)
    graph = augmented(net)
    ours = [cost for _, cost in k_shortest_routes(graph, graph.source, graph.sink, 5)]
    theirs = networkx_k_shortest_costs(graph, 5)
    assert ours == theirs, f"seed {seed}"


@pytest.mark.parametrize("seed", range(120))
def test_matches_networkx_on_denser_graphs(seed):
    net = random_network(seed, n_nodes=16, n_edges=60, allow_parallel=False)
    graph = augmented(net)
    ours = [cost for _, cost in k_shortest_routes(graph, graph.source, graph.sink, 8)]
    assert ours == networkx_k_shortest_costs(graph, 8), f"seed {seed}"


@pytest.mark.parametrize("seed", range(60))
def test_matches_networkx_with_several_entries_and_targets(seed):
    net = random_network(
        seed, n_nodes=18, n_edges=55, n_entry=3, n_targets=2, allow_parallel=False
    )
    graph = augmented(net)
    ours = [cost for _, cost in k_shortest_routes(graph, graph.source, graph.sink, 6)]
    assert ours == networkx_k_shortest_costs(graph, 6), f"seed {seed}"


# ---------------------------------------------------------------------------
# Property sweep, including graphs with parallel edges that networkx
# cannot represent in a DiGraph
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("seed", range(200))
def test_properties_hold_on_random_multigraphs(seed):
    net = random_network(seed, n_nodes=14, n_edges=40)
    paths = k_shortest_attack_paths(net, k=5)

    assert costs(paths) == sorted(costs(paths)), f"seed {seed}: not nondecreasing"
    assert len({p.edge_indices for p in paths}) == len(paths), f"seed {seed}: duplicate path"

    for path in paths:
        # assert_path_consistent also checks looplessness and that the
        # reported total equals the sum of the hops.
        assert_path_consistent(net, path)

    cheapest = cheapest_attack_path(net)
    if cheapest is None:
        assert paths == []
    else:
        assert paths[0].total_difficulty == cheapest.total_difficulty, f"seed {seed}"


@pytest.mark.parametrize("seed", range(80))
def test_asking_for_more_never_changes_the_earlier_answers(seed):
    """The k shortest must be a prefix of the k+n shortest."""
    net = random_network(seed, n_nodes=14, n_edges=40)
    few = k_shortest_attack_paths(net, k=3)
    many = k_shortest_attack_paths(net, k=7)
    assert costs(many)[: len(few)] == costs(few), f"seed {seed}"
