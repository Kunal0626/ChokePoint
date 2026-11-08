#!/usr/bin/env python3
"""Measure how runtime grows with graph size, and fit the empirical exponent.

Generates docs/BENCHMARKS.md's tables:

    .venv/bin/python scripts/benchmark_sweep.py

Edges are held at five per node across every size so that the sweep varies
one thing. Letting density drift would make the exponent meaningless, since
the bounds depend on E as well as V.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from chokepoint.bench import environment, run_benchmark  # noqa: E402

SIZES = [100, 250, 500, 1000, 2000]
EDGES_PER_NODE = 5
SEED = 1
REPEAT = 5


def fit_exponent(sizes: list[int], times: list[float]) -> float:
    """Least-squares slope of log(time) against log(nodes).

    If runtime behaves like c * n**p then the slope of that line is p. It is
    an empirical exponent over this range of sizes on this machine, not a
    proof of anything -- but it is directly comparable to the theoretical
    bound, which is the point.
    """
    xs = [math.log(n) for n in sizes]
    ys = [math.log(t) for t in times]
    mean_x = sum(xs) / len(xs)
    mean_y = sum(ys) / len(ys)
    numerator = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    denominator = sum((x - mean_x) ** 2 for x in xs)
    return numerator / denominator


def main() -> None:
    env = environment()
    print("Environment")
    for key, value in env.items():
        print(f"  {key:<8}: {value}")
    print(f"  {'repeat':<8}: median of {REPEAT}, after one untimed warm-up")
    print(f"  {'density':<8}: {EDGES_PER_NODE} edges per node at every size")
    print(f"  {'seed':<8}: {SEED}")
    print()

    results = []
    for nodes in SIZES:
        result = run_benchmark(
            nodes=nodes, edges=nodes * EDGES_PER_NODE, seed=SEED, repeat=REPEAT
        )
        results.append(result)
        print(f"  measured {nodes} nodes", file=sys.stderr)

    labels = [t.label for t in results[0].timings]

    print("| nodes | edges | " + " | ".join(labels) + " |")
    print("|---" * (len(labels) + 2) + "|")
    for result in results:
        cells = " | ".join(f"{t.median_ms:.2f} ms" for t in result.timings)
        print(f"| {result.nodes} | {result.edges} | {cells} |")
    print()

    print("| operation | 100 -> 2000 | empirical exponent | theoretical bound |")
    print("|---|---|---|---|")
    bounds = {
        "build augmented graph": "O(V+E)",
        "Dijkstra": "O((V+E) log V)",
        "Edmonds-Karp + min-cut": "O(V*E^2)",
    }
    for index, label in enumerate(labels):
        times = [r.timings[index].median_ms for r in results]
        factor = times[-1] / times[0]
        exponent = fit_exponent(SIZES, times)
        bound = bounds.get(label, "O(k*V*(V+E) log V)")
        print(f"| {label} | x{factor:.0f} | n^{exponent:.2f} | {bound} |")
    print()

    print("| nodes | cheapest cost | hops | min-cut | cut edges | augmentations |")
    print("|---|---|---|---|---|---|")
    for result in results:
        print(
            f"| {result.nodes} | {result.cheapest_cost} | {result.cheapest_hops} "
            f"| {result.min_cut_value} | {result.min_cut_edges} "
            f"| {result.augmentations} |"
        )


if __name__ == "__main__":
    main()
