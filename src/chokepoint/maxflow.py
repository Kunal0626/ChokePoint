"""Edmonds-Karp max-flow and min-cut extraction, written by hand.

Why the min-cut is the right answer to "what is the smallest set of fixes?"
--------------------------------------------------------------------------
A set of fixes works if and only if removing those edges leaves no path from
any entry point to any target -- in other words, if and only if it is a *cut*
separating source from sink. So "the cheapest set of fixes that works" is
literally "the minimum-capacity cut", once capacity is defined as the cost of
applying the fix.

The max-flow min-cut theorem says the value of the maximum flow equals the
capacity of the minimum cut. That is what makes the problem tractable:
enumerating cuts is exponential, but max-flow is polynomial, so we compute
the easy quantity and read the cut off the residual graph at the end.

Why Edmonds-Karp rather than plain Ford-Fulkerson
-------------------------------------------------
Ford-Fulkerson says "find any augmenting path, saturate it, repeat". It is
correct but says nothing about which path to pick, and the choice decides
whether it terminates at all.

With integer capacities each augmentation pushes at least 1 unit, so it halts
in at most |max-flow| rounds -- but that is a bound on the *flow value*, not
on the input size. The textbook pathological graph has two parallel routes of
capacity 1000000 joined by a middle edge of capacity 1; a bad path choice
alternates across the middle edge and takes 2000000 rounds on a graph with 4
nodes. With irrational capacities Ford-Fulkerson need not terminate at all.

Edmonds-Karp is Ford-Fulkerson with one rule added: always pick a *shortest*
augmenting path, found by BFS rather than DFS. That makes the number of
augmentations O(V*E) regardless of the capacity values, for O(V*E^2) overall.
The bound is independent of the numbers in the input, which is what turns it
from "usually fine" into a guarantee. This matters here because
``--capacity inverse-difficulty`` produces fractional capacities, exactly the
case where the capacity-dependent bound tells you nothing useful.

What residual edges are and why they exist
------------------------------------------
Pushing f units along an edge of capacity c leaves c - f units of forward
room, and adds a *backward* residual edge of capacity f. That backward edge
is not a real link in the network. It exists so a later augmentation can
cancel part of an earlier, regretted routing decision: sending flow backwards
along it means "re-route f units of what I previously pushed here".

Without that ability the algorithm would be a greedy heuristic and would get
stuck. Consider s->a and b->t of capacity 1 each, a->b of capacity 1, plus
s->b and a->t of capacity 1. Routing s->a->b->t first saturates the middle
edge and appears to block both remaining routes; the backward residual on
a->b is what lets a second augmentation push s->b->(undo a->b)->a->t, giving
a total of 2. Residual edges are how a polynomial algorithm avoids needing to
be clever about the order it picks paths in.

Extracting the cut
------------------
When no augmenting path remains, let S be the set of nodes still reachable
from the source in the residual graph. The sink is not in S, by definition of
"no augmenting path". The cut is every original edge running from inside S to
outside S. Each such edge must be fully saturated -- otherwise it would have
residual room and its endpoint would have been in S -- which is why the cut's
capacity equals the flow.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

from .capacity import DEFAULT_CAPACITY_MODE, Capacity, arc_capacities
from .graph import AugmentedGraph, build_augmented_graph
from .model import Network


class SelfCheckError(RuntimeError):
    """A computed min-cut failed its own verification.

    Deliberately an exception rather than an ``assert``: assertions vanish
    under ``python -O``, and a tool whose output is a security recommendation
    should not be able to silently stop checking itself.
    """


@dataclass(frozen=True)
class MinCut:
    """A verified minimum cut: the cheapest set of fixes that disconnects."""

    mode: str
    # Equal to both the max-flow value and the total capacity of the cut.
    value: Capacity
    # Indices into Network.edges, in the order the edges appear in the file.
    edge_indices: tuple[int, ...]
    # Nodes on the attacker's side of the cut. The virtual super-source is
    # always in this set by construction and is omitted as noise.
    attacker_side: frozenset[str] = field(compare=False)
    # BFS augmentation rounds used, reported by the benchmark in Phase 8.
    augmentations: int = field(compare=False, default=0)

    @property
    def size(self) -> int:
        return len(self.edge_indices)


class _Residual:
    """Residual graph with paired forward and backward arcs.

    Residual arc 2i is the forward residual of augmented-graph arc i and
    2i+1 is its reverse. Pairing them adjacently means the partner of arc j
    is ``j ^ 1``, so no lookup table is needed, and the tail of arc j is just
    the head of its partner.

    One residual pair per *arc*, not per node pair, is what makes parallel
    edges work: two links between the same hosts keep separate capacities and
    can be cut independently.
    """

    __slots__ = ("head", "capacity", "origin", "out")

    def __init__(self, graph: AugmentedGraph, capacities: tuple[Capacity, ...]) -> None:
        self.head: list[str] = []
        self.capacity: list[Capacity] = []
        # The augmented-graph arc each residual arc came from, for both members
        # of the pair, so the cut can be reported in terms of real edges.
        self.origin: list[int] = []
        self.out: dict[str, list[int]] = {node: [] for node in graph.adjacency}

        for arc_index, arc in enumerate(graph.arcs):
            forward = len(self.head)
            self.head.append(arc.target)
            self.capacity.append(capacities[arc_index])
            self.origin.append(arc_index)
            self.out[arc.source].append(forward)

            self.head.append(arc.source)
            self.capacity.append(0)  # a backward residual starts empty
            self.origin.append(arc_index)
            self.out[arc.target].append(forward + 1)

    def tail(self, arc: int) -> str:
        return self.head[arc ^ 1]

    @property
    def forward_arcs(self) -> range:
        """Even indices: the residual arcs that correspond to real direction."""
        return range(0, len(self.head), 2)


def max_flow_min_cut(
    graph: AugmentedGraph, mode: str = DEFAULT_CAPACITY_MODE
) -> MinCut:
    """Compute the max-flow, read off the min-cut, and verify both."""
    capacities = arc_capacities(graph, mode)
    residual = _Residual(graph, capacities)

    flow: Capacity = 0
    augmentations = 0
    while (path := _shortest_augmenting_path(residual, graph.source, graph.sink)) is not None:
        # The bottleneck is the most we can push without exceeding any
        # residual capacity on the path.
        bottleneck = min(residual.capacity[arc] for arc in path)
        for arc in path:
            residual.capacity[arc] -= bottleneck
            # Create or extend the backward residual, so this decision can be
            # partially undone later.
            residual.capacity[arc ^ 1] += bottleneck
        flow += bottleneck
        augmentations += 1

    attacker_side = _reachable(residual, graph.source)
    cut_arcs = tuple(
        residual.origin[arc]
        for arc in residual.forward_arcs
        if residual.tail(arc) in attacker_side and residual.head[arc] not in attacker_side
    )

    _verify(graph, capacities, flow, cut_arcs)

    return MinCut(
        mode=mode,
        value=flow,
        edge_indices=tuple(
            index
            for index in (graph.arcs[arc].edge_index for arc in cut_arcs)
            if index is not None
        ),
        attacker_side=frozenset(attacker_side - {graph.source}),
        augmentations=augmentations,
    )


def min_cut(network: Network, mode: str = DEFAULT_CAPACITY_MODE) -> MinCut:
    """The cheapest set of fixes that cuts every route to every target."""
    return max_flow_min_cut(build_augmented_graph(network), mode)


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _shortest_augmenting_path(
    residual: _Residual, source: str, sink: str
) -> list[int] | None:
    """BFS for an augmenting path, returned as residual arc indices.

    BFS rather than DFS is the entire difference between Edmonds-Karp and
    plain Ford-Fulkerson, and the reason the round count is bounded by the
    graph's size instead of by the magnitude of its capacities.
    """
    parent: dict[str, int] = {}
    seen = {source}
    queue = deque([source])

    while queue:
        node = queue.popleft()
        for arc in residual.out[node]:
            if residual.capacity[arc] <= 0:
                continue
            next_node = residual.head[arc]
            if next_node in seen:
                continue
            seen.add(next_node)
            parent[next_node] = arc
            if next_node == sink:
                return _walk_back(residual, parent, source, sink)
            queue.append(next_node)

    return None


def _walk_back(
    residual: _Residual, parent: dict[str, int], source: str, sink: str
) -> list[int]:
    path: list[int] = []
    node = sink
    while node != source:
        arc = parent[node]
        path.append(arc)
        node = residual.tail(arc)
    path.reverse()
    return path


def _reachable(residual: _Residual, source: str) -> set[str]:
    """Nodes reachable from the source using residual capacity only."""
    seen = {source}
    queue = deque([source])
    while queue:
        node = queue.popleft()
        for arc in residual.out[node]:
            if residual.capacity[arc] > 0 and residual.head[arc] not in seen:
                seen.add(residual.head[arc])
                queue.append(residual.head[arc])
    return seen


def _verify(
    graph: AugmentedGraph,
    capacities: tuple[Capacity, ...],
    flow: Capacity,
    cut_arcs: tuple[int, ...],
) -> None:
    """Check the cut against the flow, and against reality.

    These run on every invocation, not only in tests. A test suite can only
    vouch for the graphs it was written against; this vouches for the graph
    actually in front of the user.
    """
    total = sum(capacities[arc] for arc in cut_arcs)
    if total != flow:
        raise SelfCheckError(
            "max-flow min-cut theorem violated: max-flow is "
            f"{flow} but the extracted cut has capacity {total}. "
            "This is a bug in ChokePoint, not in your network model."
        )

    virtual = [arc for arc in cut_arcs if graph.arcs[arc].edge_index is None]
    if virtual:
        raise SelfCheckError(
            f"{len(virtual)} virtual arc(s) appeared in the cut. The sentinel "
            "capacity for virtual arcs is meant to make this impossible, so "
            "this is a bug in ChokePoint, not in your network model."
        )

    if _sink_still_reachable(graph, frozenset(cut_arcs)):
        raise SelfCheckError(
            "the extracted cut does not actually disconnect the target: a "
            "route survives after removing every cut edge. This is a bug in "
            "ChokePoint, not in your network model."
        )


def _sink_still_reachable(graph: AugmentedGraph, removed: frozenset[int]) -> bool:
    """Plain BFS on the original graph with the cut edges deleted.

    Deliberately independent of the residual machinery: a check that reused
    the residual graph would share any bug that produced the bad cut.
    """
    seen = {graph.source}
    queue = deque([graph.source])
    while queue:
        node = queue.popleft()
        for arc_index in graph.adjacency[node]:
            if arc_index in removed:
                continue
            target = graph.arcs[arc_index].target
            if target == graph.sink:
                return True
            if target not in seen:
                seen.add(target)
                queue.append(target)
    return False
