"""Seeded random graphs and the timing harness behind `chokepoint bench`.

The generated graphs are *layered*, which is both realistic and necessary.
Attack graphs have a direction: the internet on one side, the crown jewels on
the other, and progress in between. A uniformly random digraph has no such
structure, produces paths of two or three hops whatever its size, and would
make the benchmark measure something that looks nothing like the workload.

Two properties are guaranteed by construction, because losing either would
quietly make the numbers meaningless:

*   **Every node is reachable.** Each node outside the first layer is given an
    incoming edge from the previous layer before any random edges are added.
    Without that, a generator can produce a graph whose target is
    unreachable, where Dijkstra returns almost immediately and the timing
    says nothing at all.
*   **No cycles.** Edges only ever run forward, from a layer to a later one.
    Shortest paths and max-flow are both defined on cyclic graphs and
    ChokePoint handles them, but a DAG makes path lengths predictable from
    the layer count, so a slow run can be attributed to size rather than to
    an unlucky shape.
"""

from __future__ import annotations

import platform
import random
import statistics
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from .capacity import Capacity, DEFAULT_CAPACITY_MODE
from .dijkstra import shortest_route
from .graph import build_augmented_graph
from .loader import parse_network
from .maxflow import max_flow_min_cut
from .model import Network
from .yen import DEFAULT_K, k_shortest_routes

DEFAULT_REPEAT = 5
MAX_DIFFICULTY = 10
MAX_FIX_COST = 5
# Most moves are to the next layer; the rest skip ahead, which is what stops
# every shortest path having exactly one hop per layer.
SKIP_PROBABILITY = 0.15
MAX_SKIP = 3


@dataclass(frozen=True)
class Timing:
    """Milliseconds for one operation, over several runs."""

    label: str
    runs: int
    median_ms: float
    min_ms: float
    max_ms: float


@dataclass(frozen=True)
class BenchResult:
    nodes: int
    edges: int
    layers: int
    seed: int
    # What the algorithms actually found, so a reader can tell the work was
    # real and not a graph that fell apart into trivial answers.
    cheapest_cost: int | None
    cheapest_hops: int
    paths_found: int
    min_cut_value: Capacity
    min_cut_edges: int
    augmentations: int
    timings: tuple[Timing, ...] = field(default_factory=tuple)


def layered_network(
    *, nodes: int, edges: int, seed: int, layers: int | None = None
) -> Network:
    """A reproducible layered attack graph.

    ``layers`` defaults to roughly the square root of the node count, which
    keeps layers and layer width growing together as the graph scales.
    """
    if nodes < 2:
        raise ValueError(f"need at least 2 nodes, got {nodes}")
    if layers is None:
        layers = max(2, round(nodes**0.5))
    layers = max(2, min(layers, nodes))

    minimum_edges = nodes - _layer_sizes(nodes, layers)[0]
    if edges < minimum_edges:
        raise ValueError(
            f"{edges} edges is too few for {nodes} nodes in {layers} layers: "
            f"at least {minimum_edges} are needed to reach every node"
        )

    rng = random.Random(seed)
    members = _layer_members(nodes, layers)
    specs: list[dict[str, Any]] = []

    # The spine: give every node outside the first layer a way in.
    for layer in range(1, layers):
        for node_id in members[layer]:
            specs.append(_edge(rng, rng.choice(members[layer - 1]), node_id, len(specs)))

    # Then fill up with random forward edges.
    while len(specs) < edges:
        source_layer = rng.randrange(layers - 1)
        furthest = min(MAX_SKIP, layers - 1 - source_layer)
        jump = (
            rng.randint(2, furthest)
            if furthest >= 2 and rng.random() < SKIP_PROBABILITY
            else 1
        )
        specs.append(
            _edge(
                rng,
                rng.choice(members[source_layer]),
                rng.choice(members[source_layer + jump]),
                len(specs),
            )
        )

    return parse_network(
        {
            "name": f"layered-{nodes}n-{edges}e-seed{seed}",
            "nodes": [{"id": node_id} for layer in members for node_id in layer],
            "entry": list(members[0]),
            "targets": list(members[-1]),
            "edges": specs,
        }
    )


def _layer_sizes(nodes: int, layers: int) -> list[int]:
    sizes = [nodes // layers] * layers
    for index in range(nodes % layers):
        sizes[index] += 1
    return sizes


def _layer_members(nodes: int, layers: int) -> list[list[str]]:
    members: list[list[str]] = []
    start = 0
    for size in _layer_sizes(nodes, layers):
        members.append([f"n{i}" for i in range(start, start + size)])
        start += size
    return members


def _edge(rng: random.Random, source: str, target: str, index: int) -> dict[str, Any]:
    return {
        "from": source,
        "to": target,
        "difficulty": rng.randint(1, MAX_DIFFICULTY),
        "technique": "synthetic",
        # Unique fix names: a benchmark should measure the algorithms, not
        # the de-duplication of shared fixes.
        "fix": {"name": f"fix-{index}", "cost": rng.randint(1, MAX_FIX_COST)},
    }


def measure(
    label: str, operation: Callable[[], Any], repeat: int = DEFAULT_REPEAT
) -> Timing:
    """Time an operation, reporting the median of ``repeat`` runs.

    One untimed warm-up run first. CPython does not JIT, but the first run
    still pays for import-time lazy work and a cold allocator, and including
    it would inflate the figure for the fastest operations most.

    The median rather than the mean, because a single scheduler hiccup on a
    laptop can double one sample and drag a mean with it.
    """
    operation()

    samples: list[float] = []
    for _ in range(repeat):
        started = time.perf_counter()
        operation()
        samples.append((time.perf_counter() - started) * 1000)

    return Timing(
        label=label,
        runs=repeat,
        median_ms=statistics.median(samples),
        min_ms=min(samples),
        max_ms=max(samples),
    )


def run_benchmark(
    *,
    nodes: int,
    edges: int,
    seed: int,
    k: int = DEFAULT_K,
    mode: str = DEFAULT_CAPACITY_MODE,
    repeat: int = DEFAULT_REPEAT,
    layers: int | None = None,
) -> BenchResult:
    """Build one graph and time each algorithm on it."""
    network = layered_network(nodes=nodes, edges=edges, seed=seed, layers=layers)
    graph = build_augmented_graph(network)
    source, sink = graph.source, graph.sink

    # Graph construction is timed separately rather than folded into the
    # algorithms: it is O(V+E) setup that a long-running analysis pays once,
    # and hiding it inside Dijkstra would overstate Dijkstra.
    timings = [
        measure("build augmented graph", lambda: build_augmented_graph(network), repeat),
        measure("Dijkstra", lambda: shortest_route(graph, source, sink), repeat),
        measure(
            f"Yen k={k}", lambda: k_shortest_routes(graph, source, sink, k), repeat
        ),
        # Includes the three self-checks, because that is what the tool does
        # on every real invocation. Timing a stripped-down version would be
        # measuring something nobody runs.
        measure(
            "Edmonds-Karp + min-cut", lambda: max_flow_min_cut(graph, mode), repeat
        ),
    ]

    route = shortest_route(graph, source, sink)
    routes = k_shortest_routes(graph, source, sink, k)
    cut = max_flow_min_cut(graph, mode)

    return BenchResult(
        nodes=nodes,
        edges=len(network.edges),
        layers=max(2, round(nodes**0.5)) if layers is None else layers,
        seed=seed,
        cheapest_cost=None if route is None else route[1],
        cheapest_hops=0 if route is None else len(graph.edge_indices_of(route[0])),
        paths_found=len(routes),
        min_cut_value=cut.value,
        min_cut_edges=cut.size,
        augmentations=cut.augmentations,
        timings=tuple(timings),
    )


def environment() -> dict[str, str]:
    """Machine and tool versions, to be recorded next to every number."""
    release = platform.mac_ver()[0]
    operating_system = (
        f"macOS {release}" if release else f"{platform.system()} {platform.release()}"
    )
    return {
        "machine": platform.machine(),
        "os": operating_system,
        "python": f"{platform.python_implementation()} {platform.python_version()}",
    }
