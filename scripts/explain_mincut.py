#!/usr/bin/env python3
"""Generate the worked example in docs/MAXFLOW_MINCUT.md.

Every number in that document comes from this script, so it can be re-run to
check the prose still matches the code:

    .venv/bin/python scripts/explain_mincut.py

It drives ChokePoint's internals (_Residual, _shortest_augmenting_path) step
by step rather than calling max_flow_min_cut in one go, because the point is
to show the rounds. That means it reaches past the public API on purpose.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tests"))

from chokepoint.capacity import arc_capacities  # noqa: E402
from chokepoint.graph import build_augmented_graph  # noqa: E402
from chokepoint.loader import parse_network  # noqa: E402
from chokepoint.maxflow import (  # noqa: E402
    _Residual,
    _reachable,
    _shortest_augmenting_path,
    max_flow_min_cut,
)

# A 5-node network. Fix costs are the capacities under the default mode.
WORKED_EXAMPLE = {
    "name": "worked-example",
    "nodes": [
        {"id": "s", "label": "Internet", "type": "external"},
        {"id": "a", "label": "Web server", "type": "server"},
        {"id": "b", "label": "Mail server", "type": "server"},
        {"id": "c", "label": "File server", "type": "server"},
        {"id": "t", "label": "Database", "type": "database"},
    ],
    "entry": ["s"],
    "targets": ["t"],
    "edges": [
        {"from": "s", "to": "a", "difficulty": 2, "technique": "unpatched web app",
         "fix": {"name": "Patch web app", "cost": 5}},
        {"from": "s", "to": "b", "difficulty": 3, "technique": "phishing",
         "fix": {"name": "Mail filtering + training", "cost": 5}},
        {"from": "a", "to": "c", "difficulty": 4, "technique": "SMB exposed",
         "fix": {"name": "Firewall SMB from DMZ", "cost": 1}},
        {"from": "a", "to": "t", "difficulty": 6, "technique": "reused DB credentials",
         "fix": {"name": "Rotate DB credentials", "cost": 1}},
        {"from": "b", "to": "c", "difficulty": 5, "technique": "weak SSH password",
         "fix": {"name": "SSH keys only", "cost": 1}},
        {"from": "c", "to": "t", "difficulty": 3, "technique": "database port open",
         "fix": {"name": "Restrict DB to app subnet", "cost": 5}},
    ],
}

# Two cuts of equal value, to make the point that the value is unique but the
# edge set need not be.
TIE_EXAMPLE = {
    "name": "tie",
    "nodes": [{"id": n} for n in ("s", "m", "t")],
    "entry": ["s"],
    "targets": ["t"],
    "edges": [
        {"from": "s", "to": "m", "difficulty": 1, "fix": {"name": "Fix the first hop", "cost": 2}},
        {"from": "m", "to": "t", "difficulty": 1, "fix": {"name": "Fix the second hop", "cost": 2}},
    ],
}


def rule(title: str) -> None:
    print(f"\n{title}\n{'-' * len(title)}")


def arc_label(graph, residual, arc: int) -> str:
    """Render a residual arc as "u->v" plus a marker for backward arcs."""
    tail, head = residual.tail(arc), residual.head[arc]
    pretty = f"{_short(graph, tail)}->{_short(graph, head)}"
    return pretty if arc % 2 == 0 else f"{pretty} (backward)"


def _short(graph, node: str) -> str:
    if node == graph.source:
        return "SRC"
    if node == graph.sink:
        return "SNK"
    return node


def trace(data: dict) -> None:
    """Run Edmonds-Karp one augmentation at a time, narrating each round."""
    net = parse_network(data)
    graph = build_augmented_graph(net)
    capacities = arc_capacities(graph, "fixcost")
    residual = _Residual(graph, capacities)

    rule("Capacities (mode: fixcost)")
    for index, edge in enumerate(net.edges):
        print(f"  {edge.source}->{edge.target}  capacity {edge.fix.cost}   {edge.fix.name}")
    virtual = {capacities[i] for i, arc in enumerate(graph.arcs) if arc.edge_index is None}
    print(f"  virtual super-source/sink arcs: capacity {virtual.pop()} (sum of real + 1)")

    rule("Augmentation rounds (BFS, so always a shortest path)")
    flow = 0
    rounds = 0
    backward_uses = 0
    while (path := _shortest_augmenting_path(residual, graph.source, graph.sink)) is not None:
        rounds += 1
        bottleneck = min(residual.capacity[arc] for arc in path)
        if any(arc % 2 for arc in path):
            backward_uses += 1
        shown = " ".join(arc_label(graph, residual, arc) for arc in path)
        for arc in path:
            residual.capacity[arc] -= bottleneck
            residual.capacity[arc ^ 1] += bottleneck
        flow += bottleneck
        print(f"  round {rounds}: push {bottleneck} along  {shown}")
        print(f"           running flow = {flow}")
    print(f"  no augmenting path remains after {rounds} rounds")
    print(f"  rounds that used a backward residual arc: {backward_uses}")

    rule("Residual capacities when the algorithm stops")
    for index, edge in enumerate(net.edges):
        forward = 2 * next(
            i for i, arc in enumerate(graph.arcs) if arc.edge_index == index
        )
        left = residual.capacity[forward]
        pushed = residual.capacity[forward + 1]
        state = "SATURATED" if left == 0 else f"{left} left"
        print(
            f"  {edge.source}->{edge.target}  capacity {edge.fix.cost}  "
            f"carrying {pushed}  ({state})"
        )

    rule("Reading the cut off the residual graph")
    reachable = _reachable(residual, graph.source)
    print(f"  S = nodes still reachable from the source: "
          f"{sorted(_short(graph, n) for n in reachable)}")
    print(f"  the sink is in S: {graph.sink in reachable}  (it must not be)")
    cut = max_flow_min_cut(graph, "fixcost")
    print(f"  cut edges = original edges from inside S to outside S:")
    total = 0
    for index in cut.edge_indices:
        edge = net.edges[index]
        total += edge.fix.cost
        print(f"    {edge.source}->{edge.target}  cost {edge.fix.cost}   {edge.fix.name}")
    print(f"  total cut capacity = {total}")
    print(f"  max-flow value     = {cut.value}")
    print(f"  theorem holds      = {total == cut.value}")

    try:
        import networkx as nx
        from helpers import networkx_min_cut_value

        theirs = networkx_min_cut_value(graph, "fixcost")
        print(f"  networkx.minimum_cut agrees = {theirs == cut.value} (value {theirs})")
    except ImportError:
        print("  networkx not installed, cross-check skipped")


def show_tie() -> None:
    net = parse_network(TIE_EXAMPLE)
    cut = max_flow_min_cut(build_augmented_graph(net), "fixcost")
    rule("Is the minimum cut unique?")
    print("  s ->(2)-> m ->(2)-> t : both single-edge cuts cost 2.")
    print(f"  value reported     : {cut.value}  (unique)")
    print(f"  edge set reported  : "
          f"{[net.edges[i].fix.name for i in cut.edge_indices]}  (one of two valid answers)")
    print("  The value is always unique; the cut achieving it need not be.")


def measure_backward_usage() -> None:
    """How often BFS actually needs a backward residual arc, measured."""
    from helpers import random_network

    rule("How often is a backward residual arc actually used?")
    graphs = 0
    with_backward = 0
    total_rounds = 0
    backward_rounds = 0
    for seed in range(300):
        net = random_network(seed, n_nodes=20, n_edges=60)
        graph = build_augmented_graph(net)
        residual = _Residual(graph, arc_capacities(graph, "fixcost"))
        graphs += 1
        used_here = 0
        while (p := _shortest_augmenting_path(residual, graph.source, graph.sink)) is not None:
            total_rounds += 1
            if any(arc % 2 for arc in p):
                backward_rounds += 1
                used_here += 1
            bottleneck = min(residual.capacity[arc] for arc in p)
            for arc in p:
                residual.capacity[arc] -= bottleneck
                residual.capacity[arc ^ 1] += bottleneck
        if used_here:
            with_backward += 1
    print(f"  corpus: {graphs} seeded random graphs, 20 nodes / 60 edges")
    print(f"  augmentation rounds in total     : {total_rounds}")
    print(f"  rounds using a backward arc      : {backward_rounds}")
    print(f"  graphs needing at least one      : {with_backward} of {graphs}")


if __name__ == "__main__":
    print("ChokePoint: max-flow min-cut worked example")
    print("=" * 44)
    trace(WORKED_EXAMPLE)
    show_tie()
    measure_backward_usage()
