"""Turning edges into max-flow capacities.

The min-cut answers "what is the smallest set of fixes?", but *smallest*
needs a unit. That unit is the capacity, and which one you pick changes the
question being asked. Three are offered.

``fixcost`` (default)
    Capacity is the defender's effort to close the link. The min-cut is then
    the cheapest set of fixes that disconnects every entry point from every
    target, which is the question the tool exists to answer.

``unit``
    Every link has capacity 1. The min-cut is the smallest *number* of links
    that must be closed, which by Menger's theorem equals the maximum number
    of edge-disjoint attack paths. Useful when you have no credible cost
    estimates and only want to know how many independent ways in exist.

``inverse-difficulty``
    Capacity is 1/difficulty, so an easy link carries a lot of attacker flow
    and a hard one carries little.

    A note on that last mode, because the name invites a misreading. Min-cut
    selects the set of edges with the *lowest* total capacity. Under
    1/difficulty an easy link (difficulty 1) has capacity 1 and a hard link
    (difficulty 10) has capacity 1/10, so wherever the cut has a *choice
    along a route* it severs the hard link. That is the opposite of "go and
    fix the easy things".

    The bias only reaches as far as the choices available: two disjoint
    routes must both be cut, so an easy link still gets cut when it is the
    only way to sever its route. The mode shifts which edge within a route is
    chosen, not whether a route is cut at all.

    The mode is still coherent, just under a different reading: it treats
    attacker throughput as the thing being maximised and finds where that
    throughput is already most constrained -- the natural bottleneck of the
    network. That is a real question with a real answer. It is simply not
    the same question ``fixcost`` answers, and anyone reading a report
    produced in this mode should know which one they asked.

    If what you want is "prefer cutting the links that are easy to exploit",
    that is capacity proportional to difficulty, which is not implemented.

Exact arithmetic
----------------
``fixcost`` and ``unit`` are integers. ``inverse-difficulty`` uses
``fractions.Fraction``, never float. The min-cut self-checks in maxflow.py
assert that the max-flow value equals the sum of the cut capacities; with
floats that comparison would be a coin flip on any graph where rounding
accumulated, and the checks would either fire spuriously or, worse, pass
while being slightly wrong.
"""

from __future__ import annotations

from fractions import Fraction

from .graph import AugmentedGraph
from .model import Edge

# Capacities are exact: plain ints where possible, Fractions where not.
Capacity = int | Fraction

FIXCOST = "fixcost"
UNIT = "unit"
INVERSE_DIFFICULTY = "inverse-difficulty"
CAPACITY_MODES = (FIXCOST, UNIT, INVERSE_DIFFICULTY)
DEFAULT_CAPACITY_MODE = FIXCOST


def edge_capacity(edge: Edge, mode: str) -> Capacity:
    """Capacity of a single real edge under the chosen mode."""
    if mode == FIXCOST:
        return edge.fix.cost
    if mode == UNIT:
        return 1
    if mode == INVERSE_DIFFICULTY:
        # Difficulty is validated to be >= 1, so this never divides by zero.
        return Fraction(1, edge.difficulty)
    raise ValueError(
        f"unknown capacity mode {mode!r}; choose one of {', '.join(CAPACITY_MODES)}"
    )


def arc_capacities(graph: AugmentedGraph, mode: str) -> tuple[Capacity, ...]:
    """Capacity for every arc of the augmented graph, virtual arcs included.

    Virtual arcs get a capacity larger than every real cut, so that the
    min-cut can never be placed on one. "Disconnect the imaginary source from
    the internet" is a mathematically valid cut and useless advice.

    The sentinel is ``sum(real capacities) + 1`` rather than ``float('inf')``,
    for two reasons. Infinity would drag floats into arithmetic that is
    required to stay exact, and ``inf - x == inf`` would quietly break the
    residual-capacity bookkeeping during augmentation.

    That finite sentinel is provably large enough. Let S be the super-source
    together with every node that is not a target. The sink is outside S, and
    no target is in S, so no virtual arc crosses the boundary: arcs into the
    sink start at targets, and arcs out of the super-source end at entries,
    which are never targets because the loader rejects a node that is both.
    So that cut consists only of real edges and its capacity is at most the
    total of all real capacities, which is strictly below the sentinel. The
    minimum cut is therefore no larger, and any cut containing even one
    virtual arc is strictly worse.
    """
    real: list[Capacity] = [edge_capacity(edge, mode) for edge in graph.network.edges]
    sentinel: Capacity = sum(real) + 1

    return tuple(
        sentinel if arc.edge_index is None else real[arc.edge_index] for arc in graph.arcs
    )
