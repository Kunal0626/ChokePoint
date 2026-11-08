# Measured performance

Every number on this page was produced by a script in this repository and can
be re-run. Nothing here is estimated.

```bash
.venv/bin/python -m chokepoint bench --nodes 1000 --edges 5000 --seed 1
.venv/bin/python scripts/benchmark_sweep.py
```

**Environment for every figure below**

| | |
|---|---|
| Machine | Apple Silicon, `arm64` |
| OS | macOS 26.6.2 |
| Python | CPython 3.14.6 |
| Method | median of 5 runs, after one untimed warm-up |
| Graphs | seeded layered DAGs, 5 edges per node, seed 1 |

These are laptop measurements. No CPU pinning, no thermal control, nothing
else quiesced. They are reproducible on this machine to within a few percent
and are not portable to any other.

---

## 1,000 nodes, 5,000 edges

```
   operation                        median        min        max
   -------------------------------------------------------------
   build augmented graph           1.84 ms    1.83 ms    1.95 ms
   Dijkstra                        1.11 ms    1.05 ms    1.13 ms
   Yen k=3                        22.18 ms   22.13 ms   22.23 ms
   Edmonds-Karp + min-cut        132.56 ms  130.94 ms  133.23 ms

   What the run actually found:
     cheapest attack cost  34 over 20 hops
     distinct paths found  3
     minimum cut           314 across 122 edges
     augmentation rounds   310
```

The second block matters as much as the first. A benchmark on a graph whose
target happens to be unreachable would report a very fast Dijkstra and mean
nothing, so the generator guarantees reachability and the run prints what it
found. A 20-hop cheapest path and a 122-edge cut is real work.

The whole analysis of a 1,000-node network — every algorithm, including the
self-checks — is **under 160 ms**.

## How it scales

Edges held at five per node at every size, so only one thing varies.

| nodes | edges | build graph | Dijkstra | Yen k=3 | Edmonds-Karp + min-cut |
|---|---|---|---|---|---|
| 100 | 500 | 0.18 ms | 0.11 ms | 0.84 ms | 4.19 ms |
| 250 | 1,250 | 0.44 ms | 0.28 ms | 2.52 ms | 14.06 ms |
| 500 | 2,500 | 0.98 ms | 0.55 ms | 6.12 ms | 55.65 ms |
| 1,000 | 5,000 | 1.90 ms | 1.17 ms | 23.81 ms | 137.02 ms |
| 2,000 | 10,000 | 4.04 ms | 2.47 ms | 69.50 ms | 426.94 ms |

Fitting `log(time)` against `log(nodes)` by least squares gives an empirical
exponent, directly comparable to the theoretical bound:

| operation | 100 → 2,000 | empirical | theoretical bound |
|---|---|---|---|
| build augmented graph | ×22 | n^1.04 | O(V + E) |
| Dijkstra | ×22 | **n^1.03** | O((V + E) log V) |
| Yen k=3 | ×83 | n^1.50 | O(k · V · (V + E) log V) |
| Edmonds-Karp + min-cut | ×102 | **n^1.56** | O(V · E²) |

Dijkstra lands at n^1.03 against a bound of O((V+E) log V). With E = 5V that
bound is O(V log V), whose exponent over this range is about 1.1 — so the
measurement sits right on the prediction, and the `log V` factor is too small
to separate from noise across one order of magnitude.

## Why Edmonds-Karp beats its own bound by so much

O(V·E²) with E = 5V is O(V³): an exponent of **3**. The measurement is
**1.56**. That is not a rounding difference, and it is worth explaining
rather than celebrating.

The O(V·E) bound on the *number of augmentations* is a worst case that
requires an adversarial graph. What actually drives the round count is the
max-flow value, because most augmentations push a single unit. Those numbers
were recorded too:

| nodes | cheapest cost | hops | min-cut value | cut edges | augmentations |
|---|---|---|---|---|---|
| 100 | 10 | 5 | 114 | 47 | 102 |
| 250 | 16 | 8 | 146 | 56 | 140 |
| 500 | 21 | 9 | 258 | 84 | 257 |
| 1,000 | 34 | 20 | 314 | 122 | 310 |
| 2,000 | 45 | 31 | 470 | 192 | 470 |

Augmentations track the min-cut value closely (310 against 314 at 1,000
nodes; 470 against 470 at 2,000), and both grow as roughly **n^0.52**. Each
augmentation is one BFS, which is O(V + E) — linear here. So the predicted
exponent is:

```
  augmentations (n^0.52)  ×  BFS (n^1.00)  =  n^1.52
```

against **n^1.56** measured. The model explains the observation.

### The caveat that matters

That n^0.52 is **a property of these generated graphs, not of the
algorithm**. The generator uses about √n layers, so the narrowest layer
boundary holds O(√n) nodes and the minimum cut crossing it is O(√n) edges.
Change the shape — far fewer, far wider layers — and the cut grows faster,
the augmentation count grows with it, and the exponent rises.

So the honest claim is narrow: *on layered graphs of this shape, Edmonds-Karp
runs in about n^1.56, because the augmentation count is governed by the
min-cut value rather than by the O(V·E) worst case.* The O(V·E²) bound is
still the right thing to quote, because it is the only figure that holds
whatever graph arrives.

## What is and is not being timed

**Included.** Graph construction is measured separately rather than folded
into Dijkstra, because it is one-off O(V+E) setup and burying it would
overstate the algorithm. The Edmonds-Karp figure **includes the three
self-checks** — the theorem check, the virtual-arc check, and the fresh BFS
confirming the cut really disconnects — because that is what runs on every
real invocation. Timing a stripped-down version would measure something
nobody executes.

**Excluded.** Reading and validating the JSON file (about 18 ms for a
5,000-edge model), rendering, and report formatting. Those are I/O and
presentation, not the algorithms the project is about.

## Reproducing this

```bash
.venv/bin/python -m chokepoint bench --nodes 1000 --edges 5000 --seed 1
```

```bash
.venv/bin/python scripts/benchmark_sweep.py
```

Both take a seed and are deterministic: the same seed builds the same graph
and finds the same costs, cuts and augmentation counts on any machine. Only
the timings differ.
