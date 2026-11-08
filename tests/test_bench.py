"""Tests for the graph generator and the timing harness.

The generator's two guarantees -- every node reachable, no cycles -- are what
make a timing meaningful, so they are tested rather than trusted. A generator
that occasionally produced an unreachable target would make Dijkstra look
fast for the wrong reason.
"""

from __future__ import annotations

import json
from collections import deque

import pytest

from chokepoint.bench import (
    DEFAULT_REPEAT,
    environment,
    layered_network,
    measure,
    run_benchmark,
)
from chokepoint.cli import main
from chokepoint.dijkstra import cheapest_attack_path


def layer_index(node_id: str) -> int:
    """Nodes are numbered in layer order, so the number orders the layers."""
    return int(node_id[1:])


def reachable_from_entry(network) -> set[str]:
    outgoing: dict[str, list[str]] = {}
    for edge in network.edges:
        outgoing.setdefault(edge.source, []).append(edge.target)
    seen = set(network.entry)
    queue = deque(network.entry)
    while queue:
        node = queue.popleft()
        for neighbour in outgoing.get(node, ()):
            if neighbour not in seen:
                seen.add(neighbour)
                queue.append(neighbour)
    return seen


# ---------------------------------------------------------------------------
# The generator
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("nodes,edges", [(20, 60), (100, 500), (250, 1250)])
def test_generated_graph_has_the_requested_size(nodes, edges):
    network = layered_network(nodes=nodes, edges=edges, seed=1)
    assert len(network.nodes) == nodes
    assert len(network.edges) == edges


@pytest.mark.parametrize("seed", range(10))
def test_every_node_is_reachable(seed):
    """Otherwise a timing may be measuring a graph that fell apart."""
    network = layered_network(nodes=120, edges=600, seed=seed)
    assert reachable_from_entry(network) == set(network.node_ids)


@pytest.mark.parametrize("seed", range(10))
def test_the_target_is_always_reachable(seed):
    # cheapest_attack_path, not analyze: the full analysis would additionally
    # re-run Dijkstra once per distinct fix, which here is once per edge, and
    # none of that is what this test is checking.
    network = layered_network(nodes=120, edges=600, seed=seed)
    assert cheapest_attack_path(network) is not None


@pytest.mark.parametrize("seed", range(10))
def test_edges_only_run_forward(seed):
    """A DAG by construction, so path length follows from the layer count."""
    network = layered_network(nodes=120, edges=600, seed=seed)
    for edge in network.edges:
        assert layer_index(edge.source) < layer_index(edge.target), (
            f"seed {seed}: {edge.source} -> {edge.target} runs backwards"
        )


def test_entry_and_target_layers_are_disjoint():
    network = layered_network(nodes=100, edges=500, seed=1)
    assert not set(network.entry) & set(network.targets)
    assert max(map(layer_index, network.entry)) < min(map(layer_index, network.targets))


def test_the_same_seed_gives_the_same_graph():
    first = layered_network(nodes=80, edges=400, seed=7)
    second = layered_network(nodes=80, edges=400, seed=7)
    assert first.edges == second.edges
    assert first.name == second.name


def test_different_seeds_give_different_graphs():
    first = layered_network(nodes=80, edges=400, seed=1)
    second = layered_network(nodes=80, edges=400, seed=2)
    assert first.edges != second.edges


def test_layers_can_be_set_explicitly():
    network = layered_network(nodes=60, edges=300, seed=1, layers=6)
    # Six layers of ten means the first layer holds exactly ten entry points.
    assert len(network.entry) == 10
    assert len(network.targets) == 10


def test_too_few_edges_is_rejected_with_a_useful_message():
    with pytest.raises(ValueError, match="at least"):
        layered_network(nodes=100, edges=5, seed=1)


def test_a_graph_needs_at_least_two_nodes():
    with pytest.raises(ValueError, match="at least 2 nodes"):
        layered_network(nodes=1, edges=1, seed=1)


def test_parallel_edges_are_allowed_and_counted():
    """Density above one edge per pair must not silently produce fewer edges."""
    network = layered_network(nodes=10, edges=200, seed=1)
    assert len(network.edges) == 200


# ---------------------------------------------------------------------------
# The timing harness
# ---------------------------------------------------------------------------


def test_measure_reports_the_requested_number_of_runs():
    calls = []
    timing = measure("noop", lambda: calls.append(1), repeat=4)
    assert timing.runs == 4
    # Four timed runs plus one untimed warm-up.
    assert len(calls) == 5


def test_measure_orders_min_median_max():
    timing = measure("noop", lambda: sum(range(100)), repeat=5)
    assert timing.min_ms <= timing.median_ms <= timing.max_ms
    assert timing.label == "noop"


def test_environment_records_what_a_number_needs():
    env = environment()
    assert set(env) == {"machine", "os", "python"}
    assert all(value for value in env.values())


def test_run_benchmark_times_every_algorithm():
    result = run_benchmark(nodes=80, edges=400, seed=1, repeat=1)
    labels = [t.label for t in result.timings]
    assert labels == [
        "build augmented graph",
        "Dijkstra",
        "Yen k=3",
        "Edmonds-Karp + min-cut",
    ]
    assert all(t.median_ms >= 0 for t in result.timings)


def test_run_benchmark_reports_a_non_degenerate_graph():
    """The figures that prove the timing measured real work."""
    result = run_benchmark(nodes=200, edges=1000, seed=1, repeat=1)
    assert result.cheapest_cost is not None
    assert result.cheapest_hops >= 2
    assert result.paths_found >= 1
    assert result.min_cut_edges > 0
    assert result.augmentations > 0


def test_benchmark_findings_are_seed_deterministic():
    """Timings vary; what the algorithms find must not."""
    first = run_benchmark(nodes=120, edges=600, seed=3, repeat=1)
    second = run_benchmark(nodes=120, edges=600, seed=3, repeat=1)
    assert (first.cheapest_cost, first.min_cut_value, first.augmentations) == (
        second.cheapest_cost,
        second.min_cut_value,
        second.augmentations,
    )


# ---------------------------------------------------------------------------
# The CLI
# ---------------------------------------------------------------------------


def test_bench_command_runs(capsys):
    assert main(["bench", "--nodes", "80", "--edges", "400", "--repeat", "1"]) == 0
    out = capsys.readouterr().out
    assert "ChokePoint benchmark" in out
    assert "Edmonds-Karp + min-cut" in out
    # The environment must be printed with the numbers, not assumed.
    assert "python" in out
    assert "Theoretical bounds" in out


def test_bench_json(capsys):
    assert main(
        ["bench", "--nodes", "80", "--edges", "400", "--repeat", "1", "--json"]
    ) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["graph"]["nodes"] == 80
    assert payload["graph"]["edges"] == 400
    assert set(payload["environment"]) == {"machine", "os", "python"}
    assert len(payload["timings_ms"]) == 4
    assert payload["found"]["cheapest_attack_cost"] is not None


def test_bench_needs_no_network_file(capsys):
    """bench generates its own graph, so it must not touch the loader."""
    assert main(["bench", "--nodes", "20", "--edges", "60", "--repeat", "1"]) == 0


def test_bench_rejects_an_impossible_graph(capsys):
    assert main(["bench", "--nodes", "100", "--edges", "3", "--repeat", "1"]) == 2
    assert "at least" in capsys.readouterr().err


@pytest.mark.parametrize("flag", ["--nodes", "--edges", "--repeat"])
def test_bench_rejects_non_positive_sizes(flag):
    with pytest.raises(SystemExit) as exc:
        main(["bench", flag, "0"])
    assert exc.value.code == 2


def test_bench_honours_the_capacity_mode(capsys):
    assert main(
        ["bench", "--nodes", "60", "--edges", "300", "--repeat", "1",
         "--capacity", "unit", "--json"]
    ) == 0
    payload = json.loads(capsys.readouterr().out)
    # Under unit capacity the cut value is a count of links.
    assert payload["found"]["min_cut_value"] == payload["found"]["min_cut_edges"]
