"""Shared test fixtures: random network generation and the networkx bridge.

networkx appears only here and in the test modules. It is an independent
oracle, never a runtime dependency: the point of the project is that the
algorithms are written by hand, so networkx exists to disagree with them.
"""

from __future__ import annotations

import random
from typing import Any

import networkx as nx

from chokepoint.graph import AugmentedGraph, build_augmented_graph
from chokepoint.loader import parse_network
from chokepoint.model import Network


def network(
    nodes: list[str],
    entry: list[str],
    targets: list[str],
    edges: list[tuple[str, str, int]],
) -> Network:
    """Build a small network from terse tuples, for hand-written test cases."""
    return parse_network(
        {
            "name": "test",
            "nodes": [{"id": n} for n in nodes],
            "entry": entry,
            "targets": targets,
            "edges": [
                {"from": s, "to": t, "difficulty": d, "fix": {"name": f"fix {s}->{t}", "cost": 1}}
                for s, t, d in edges
            ],
        }
    )


def random_network(
    seed: int,
    *,
    n_nodes: int = 12,
    n_edges: int = 25,
    n_entry: int = 1,
    n_targets: int = 1,
    max_difficulty: int = 10,
    max_fix_cost: int = 5,
    allow_parallel: bool = True,
) -> Network:
    """A reproducible random network.

    Deliberately makes no attempt to guarantee the target is reachable: about
    a third of these have no attack path at all, which is exactly the case
    most likely to be handled wrongly. Parallel edges are not de-duplicated,
    for the same reason.
    """
    if n_nodes < n_entry + n_targets:
        raise ValueError("n_nodes must leave room for distinct entry and target nodes")

    rng = random.Random(seed)
    ids = [f"n{i}" for i in range(n_nodes)]
    # Entry and target sets must not overlap; the loader rejects a node that
    # is both, since no set of edge fixes could disconnect it from itself.
    entry = ids[:n_entry]
    targets = ids[-n_targets:]

    edges: list[dict[str, Any]] = []
    used: set[tuple[str, str]] = set()
    attempts = 0
    while len(edges) < n_edges and attempts < n_edges * 20:
        attempts += 1
        source, target = rng.sample(ids, 2)  # sample of 2 cannot be a self-loop
        # allow_parallel=False is for oracle tests against networkx DiGraph,
        # which cannot represent parallel edges and would otherwise silently
        # disagree about how many distinct routes exist.
        if not allow_parallel:
            if (source, target) in used:
                continue
            used.add((source, target))
        edges.append(
            {
                "from": source,
                "to": target,
                "difficulty": rng.randint(1, max_difficulty),
                "technique": "synthetic",
                "fix": {
                    "name": f"fix {source}->{target} #{len(edges)}",
                    "cost": rng.randint(1, max_fix_cost),
                },
            }
        )

    return parse_network(
        {
            "name": f"random-{seed}",
            "nodes": [{"id": i} for i in ids],
            "entry": entry,
            "targets": targets,
            "edges": edges,
        }
    )


def to_networkx(graph: AugmentedGraph) -> nx.MultiDiGraph:
    """Mirror an augmented graph into networkx.

    MultiDiGraph rather than DiGraph: a DiGraph would collapse parallel edges
    and quietly agree with a buggy implementation that did the same.
    """
    mirror = nx.MultiDiGraph()
    mirror.add_nodes_from(graph.adjacency)
    for arc_index, arc in enumerate(graph.arcs):
        mirror.add_edge(
            arc.source, arc.target, key=arc_index, difficulty=graph.difficulty_of(arc_index)
        )
    return mirror


def to_networkx_raw(net: Network) -> nx.MultiDiGraph:
    """Mirror the network's real edges only, with no virtual source or sink.

    Used to check the super-source construction independently: the cheapest
    path through the augmented graph must equal the cheapest over all
    (entry, target) pairs in the raw graph.
    """
    mirror = nx.MultiDiGraph()
    mirror.add_nodes_from(net.node_ids)
    for index, edge in enumerate(net.edges):
        mirror.add_edge(edge.source, edge.target, key=index, difficulty=edge.difficulty)
    return mirror


def networkx_best_pairwise_cost(net: Network) -> int | None:
    """Cheapest entry-to-target cost per networkx, over every pair."""
    mirror = to_networkx_raw(net)
    best: int | None = None
    for source in net.entry:
        lengths = nx.single_source_dijkstra_path_length(mirror, source, weight="difficulty")
        for target in net.targets:
            if target in lengths:
                cost = lengths[target]
                best = cost if best is None else min(best, cost)
    return best


def assert_path_consistent(net: Network, path: Any) -> None:
    """Check an AttackPath against the network it came from.

    Verifying the reported *cost* alone would pass a bug that returned the
    right number with the wrong route, so the route is checked hop by hop.
    """
    edges = [net.edges[i] for i in path.edge_indices]

    assert path.nodes, "path has no nodes"
    assert path.nodes[0] in net.entry, f"{path.nodes[0]!r} is not an entry point"
    assert path.nodes[-1] in net.targets, f"{path.nodes[-1]!r} is not a target"
    assert len(path.nodes) == len(edges) + 1, "node count does not match hop count"

    for position, edge in enumerate(edges):
        assert edge.source == path.nodes[position], f"hop {position} does not start where it should"
        assert edge.target == path.nodes[position + 1], f"hop {position} does not end where it should"

    assert sum(e.difficulty for e in edges) == path.total_difficulty, "reported cost is not the sum of hops"
    # Positive real weights mean a shortest path can never revisit a node.
    assert len(set(path.nodes)) == len(path.nodes), f"path revisits a node: {path.nodes}"


def augmented(net: Network) -> AugmentedGraph:
    return build_augmented_graph(net)


def to_networkx_simple(graph: AugmentedGraph) -> nx.DiGraph:
    """Mirror an augmented graph into a plain DiGraph.

    Only valid when the network has no parallel edges; a DiGraph keeps one
    edge per node pair, so building this from a multigraph would quietly
    discard routes.
    """
    mirror = nx.DiGraph()
    mirror.add_nodes_from(graph.adjacency)
    for arc_index, arc in enumerate(graph.arcs):
        if mirror.has_edge(arc.source, arc.target):
            raise AssertionError(
                f"parallel edge {arc.source}->{arc.target}: use to_networkx instead"
            )
        mirror.add_edge(
            arc.source, arc.target, difficulty=graph.difficulty_of(arc_index)
        )
    return mirror


def networkx_k_shortest_costs(graph: AugmentedGraph, k: int) -> list[int]:
    """Costs of the k shortest simple paths per networkx, cheapest first."""
    mirror = to_networkx_simple(graph)
    costs: list[int] = []
    try:
        for path in nx.shortest_simple_paths(
            mirror, graph.source, graph.sink, weight="difficulty"
        ):
            costs.append(
                sum(mirror[u][v]["difficulty"] for u, v in zip(path, path[1:]))
            )
            if len(costs) == k:
                break
    except nx.NetworkXNoPath:
        return []
    return costs
