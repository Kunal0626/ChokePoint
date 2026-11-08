"""Yen's algorithm for the k shortest loopless paths, written by hand.

How it builds on Dijkstra
-------------------------
Dijkstra gives one cheapest path. Yen's gives the next-cheapest ones by
noticing that any path different from the best one must *diverge* from it
somewhere. So for each node along the best path -- call it the spur node --
it asks: what is the cheapest route that follows the best path up to here
and then leaves by a different arc?

Each of those questions is a Dijkstra run on a slightly reduced graph, which
is why Phase 2's ``dijkstra`` takes ``banned_arcs`` and ``banned_nodes``:

*   The arc the known path uses to leave the spur node is banned, which is
    what forces divergence. Every already-accepted path sharing the same root
    contributes its own banned arc, otherwise the same candidate would be
    rediscovered forever.
*   Every node of the root path *except* the spur node is banned, which is
    what makes the result loopless: the new tail physically cannot re-enter
    territory the root already covered.

The cheapest of all those candidates is the second-shortest path. Repeat,
spurring off the newest accepted path each time, and you get the k shortest
in nondecreasing order.

Why the naive approach fails
----------------------------
The obvious shortcut is "delete the best path's edges and run Dijkstra
again". It gives the wrong answer whenever the second-best path *shares* a
prefix with the best one, which is the normal case. On the graph

    a->b 1, b->c 1, c->d 1, b->x 2, x->d 2, a->y 4, y->d 4

the best path is a-b-c-d at 3 and the true second is a-b-x-d at 5, which
reuses a->b. Deleting the best path's edges forbids a->b and reports a-y-d
at 8 instead. Yen's bans one arc at a time precisely to avoid this.

Why loopless, and not k-shortest walks
--------------------------------------
A cheaper implementation lets Dijkstra pop a node more than once and returns
the k shortest *walks*. Those revisit nodes, so on a graph with a->b, b->a
and b->c it happily reports a-b-a-b-c as the second-best route. That is
nonsense as an attack path: an attacker who already controls a host does not
gain anything by compromising it again. Loopless is the only sensible
reading here, and it is what makes the algorithm Yen's rather than a
one-line modification of Dijkstra.

What counts as a distinct path
------------------------------
Paths are compared by their *arc* sequence, not their node sequence. Two
parallel edges between the same hosts -- say a weak SSH password and an
exposed SMB share -- give two routes with identical node lists that are
genuinely different attacks needing different fixes, so both deserve a place
in the top-k. Comparing node sequences would collapse them and hide a fix
the defender needs to know about. Root paths are compared the same way,
which is a small departure from the textbook formulation (it compares nodes)
and is what makes the algorithm correct on multigraphs.

Complexity
----------
Each outer round spurs off a path of up to V nodes, so it performs O(V)
Dijkstra runs, giving O(k * V * (V + E) log V) overall.
"""

from __future__ import annotations

import heapq

from .dijkstra import AttackPath, shortest_route, to_attack_path
from .graph import AugmentedGraph, build_augmented_graph
from .model import Network

DEFAULT_K = 3

# One route: the arcs it uses, and its total difficulty.
Route = tuple[tuple[int, ...], int]


def k_shortest_routes(
    graph: AugmentedGraph, start: str, end: str, k: int = DEFAULT_K
) -> list[Route]:
    """The k cheapest loopless routes from ``start`` to ``end``.

    Returns fewer than k entries when fewer exist, and an empty list when
    ``end`` is unreachable. Results are in nondecreasing order of cost.
    """
    if k < 1:
        raise ValueError(f"k must be at least 1, got {k}")

    first = shortest_route(graph, start, end)
    if first is None:
        return []

    accepted: list[Route] = [first]
    # Candidate routes not yet promoted. Heap entries are (cost, arcs); the
    # arc tuple breaks ties deterministically, so the report is reproducible.
    candidates: list[tuple[int, tuple[int, ...]]] = []
    # Every route ever accepted or queued, so a candidate reachable from
    # several different spur nodes is only considered once.
    seen: set[tuple[int, ...]] = {first[0]}

    while len(accepted) < k:
        previous_arcs, _ = accepted[-1]
        prefix_cost = _prefix_costs(graph, previous_arcs)

        for spur_index in range(len(previous_arcs)):
            root_arcs = previous_arcs[:spur_index]
            spur_node = graph.arcs[previous_arcs[spur_index]].source

            # Force divergence: every accepted route that follows this same
            # root must not be re-derived, so ban the arc each of them takes
            # next.
            banned_arcs = {
                arcs[spur_index]
                for arcs, _ in accepted
                if len(arcs) > spur_index and arcs[:spur_index] == root_arcs
            }
            # Keep it loopless: the tail may not re-enter the root. The root's
            # nodes are exactly the sources of its arcs, which conveniently
            # excludes the spur node itself.
            banned_nodes = {graph.arcs[arc].source for arc in root_arcs}

            spur = shortest_route(
                graph, spur_node, end, banned_arcs=banned_arcs, banned_nodes=banned_nodes
            )
            if spur is None:
                continue

            spur_arcs, spur_cost = spur
            total_arcs = root_arcs + spur_arcs
            if total_arcs in seen:
                continue
            seen.add(total_arcs)
            heapq.heappush(candidates, (prefix_cost[spur_index] + spur_cost, total_arcs))

        # No candidate left means the graph simply has no further loopless
        # route, so k was larger than the number that exist.
        if not candidates:
            break
        cost, arcs = heapq.heappop(candidates)
        accepted.append((arcs, cost))

    return accepted


def k_shortest_attack_paths(network: Network, k: int = DEFAULT_K) -> list[AttackPath]:
    """The k cheapest distinct loopless attack routes, cheapest first."""
    graph = build_augmented_graph(network)
    routes = k_shortest_routes(graph, graph.source, graph.sink, k)
    return [to_attack_path(graph, arcs, cost) for arcs, cost in routes]


def _prefix_costs(graph: AugmentedGraph, arcs: tuple[int, ...]) -> list[int]:
    """Running cost of the first n arcs, for n = 0 .. len(arcs).

    Precomputed because the spur loop needs the root's cost at every index,
    and re-summing it each time would make the round quadratic in path length
    for no reason.
    """
    totals = [0]
    for arc in arcs:
        totals.append(totals[-1] + graph.difficulty_of(arc))
    return totals
