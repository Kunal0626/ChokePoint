"""Shared layout and styling for both renderers.

The DOT output and the matplotlib fallback must encode the same information
the same way, or the two pictures of one network would disagree. Everything
that decides *what a thing looks like* lives here, so the renderers only
decide *how to draw it*.

The layered layout
------------------
matplotlib has no graph layout algorithm, so positions are computed by hand.
Attack graphs have a natural reading direction -- entry points on the left,
crown jewels on the right -- so nodes are placed in columns by their hop
distance from the nearest entry point, with two adjustments:

*   Targets are pinned to their own column on the far right, past every other
    reachable node. Without this a target that happens to sit two hops from
    the internet would be drawn in the middle of the picture, which reads as
    "not very important" when it is the whole point of the diagram.
*   Nodes with no path from any entry point are parked in a further column and
    greyed out, rather than being dropped. They are usually a modelling
    mistake -- a host someone forgot to connect -- and silently hiding them
    would hide the mistake.

Edges may run backwards or within a column; that is allowed and is drawn as a
curve. Forcing a strictly layered graph would mean inventing dummy nodes,
which is a lot of machinery for a picture that is already a fallback.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass

from .model import Network


class RenderUnavailable(RuntimeError):
    """A picture could not be produced, with a reason fit to show a user."""


# Colours are chosen to stay distinguishable in greyscale by also differing in
# weight: cut edges are the thickest, cheapest-path edges next, the rest hairline.
CUT_COLOUR = "#c0392b"  # red
PATH_COLOUR = "#2980b9"  # blue
EDGE_COLOUR = "#7f8c8d"  # grey
ENTRY_FILL = "#d5f5e3"
ENTRY_LINE = "#1e8449"
TARGET_FILL = "#fadbd8"
TARGET_LINE = "#c0392b"
NODE_FILL = "#ecf0f1"
NODE_LINE = "#34495e"
GHOST_FILL = "#f7f7f7"
GHOST_LINE = "#bdc3c7"

CUT_WIDTH = 3.5
PATH_WIDTH = 2.4
EDGE_WIDTH = 0.9


@dataclass(frozen=True)
class EdgeRole:
    """How one edge should be drawn."""

    in_cut: bool
    on_cheapest: bool

    @property
    def colour(self) -> str:
        if self.in_cut:
            return CUT_COLOUR
        if self.on_cheapest:
            return PATH_COLOUR
        return EDGE_COLOUR

    @property
    def width(self) -> float:
        if self.in_cut:
            return CUT_WIDTH
        if self.on_cheapest:
            return PATH_WIDTH
        return EDGE_WIDTH

    @property
    def is_both(self) -> bool:
        """An edge can be on the cheapest path *and* in the cut.

        That is the common case, not an edge case: the cut has to sever every
        route, including the cheapest one. Both renderers draw such an edge
        red with a blue halo, so neither fact is hidden by the other.
        """
        return self.in_cut and self.on_cheapest


@dataclass(frozen=True)
class NodeRole:
    """How one node should be drawn."""

    is_entry: bool
    is_target: bool
    reachable: bool

    @property
    def fill(self) -> str:
        if not self.reachable:
            return GHOST_FILL
        if self.is_entry:
            return ENTRY_FILL
        if self.is_target:
            return TARGET_FILL
        return NODE_FILL

    @property
    def line(self) -> str:
        if not self.reachable:
            return GHOST_LINE
        if self.is_entry:
            return ENTRY_LINE
        if self.is_target:
            return TARGET_LINE
        return NODE_LINE


def edge_roles(
    network: Network,
    cut_edges: frozenset[int],
    cheapest_edges: frozenset[int],
) -> tuple[EdgeRole, ...]:
    return tuple(
        EdgeRole(in_cut=index in cut_edges, on_cheapest=index in cheapest_edges)
        for index in range(len(network.edges))
    )


def node_roles(network: Network) -> dict[str, NodeRole]:
    reachable = _hop_depths(network)
    return {
        node_id: NodeRole(
            is_entry=node_id in network.entry,
            is_target=node_id in network.targets,
            reachable=node_id in reachable,
        )
        for node_id in network.node_ids
    }


def _hop_depths(network: Network) -> dict[str, int]:
    """Unweighted BFS distance from the nearest entry point.

    Hop count rather than difficulty: this decides *where a box is drawn*, and
    a layout driven by weights would put a node a long way right merely
    because its exploit is hard, which is not what the x-axis means.
    """
    outgoing: dict[str, list[str]] = {}
    for edge in network.edges:
        outgoing.setdefault(edge.source, []).append(edge.target)

    depth = {entry: 0 for entry in network.entry}
    queue = deque(network.entry)
    while queue:
        node = queue.popleft()
        for neighbour in outgoing.get(node, ()):
            if neighbour not in depth:
                depth[neighbour] = depth[node] + 1
                queue.append(neighbour)
    return depth


def node_columns(network: Network) -> dict[str, int]:
    """Assign every node to a column, left to right."""
    depth = _hop_depths(network)

    # The rightmost column is reserved for targets, so it sits past the
    # deepest *non*-target node rather than past everything.
    non_target = [d for node, d in depth.items() if node not in network.targets]
    target_column = (max(non_target) if non_target else 0) + 1
    ghost_column = target_column + 1

    columns: dict[str, int] = {}
    for node_id in network.node_ids:
        if node_id in network.targets:
            columns[node_id] = target_column
        elif node_id in depth:
            columns[node_id] = depth[node_id]
        else:
            columns[node_id] = ghost_column
    return columns


def layered_positions(network: Network) -> dict[str, tuple[float, float]]:
    """(x, y) for every node: x is the column, y orders within the column.

    Within a column, nodes are ordered by the average height of the nodes
    that point at them -- the barycentre heuristic, the standard first pass
    of layered graph drawing. Ordering alphabetically instead is simpler but
    scatters each node's predecessors up and down the previous column, so the
    edges cross far more than they need to and the picture stops being
    readable at about a dozen nodes.

    One left-to-right sweep is enough here. Repeating it, or sweeping back
    and forth, keeps improving real layouts, but this is the fallback
    renderer for graphs small enough to read; Graphviz does the proper job.
    """
    columns = node_columns(network)
    grouped: dict[int, list[str]] = {}
    # Seeded in id order so that, absent any other signal, the result is
    # reproducible run to run.
    for node_id in sorted(network.node_ids, key=lambda n: (columns[n], n)):
        grouped.setdefault(columns[node_id], []).append(node_id)

    incoming: dict[str, list[str]] = {}
    for edge in network.edges:
        incoming.setdefault(edge.target, []).append(edge.source)

    positions: dict[str, tuple[float, float]] = {}
    first_column = min(grouped)
    for column in sorted(grouped):
        members = grouped[column]
        if column != first_column:
            members = sorted(members, key=lambda n: _barycentre(n, incoming, positions))
        middle = (len(members) - 1) / 2
        for index, node_id in enumerate(members):
            positions[node_id] = (float(column), middle - index)
    return positions


def _barycentre(
    node_id: str,
    incoming: dict[str, list[str]],
    placed: dict[str, tuple[float, float]],
) -> tuple[float, str]:
    """Sort key: pull a node towards the average height of its predecessors.

    Negated because y decreases as the index within a column increases, so
    the highest average must sort first. Nodes whose predecessors are not yet
    placed fall to the bottom of the column, with the id breaking ties.
    """
    heights = [placed[p][1] for p in incoming.get(node_id, ()) if p in placed]
    if not heights:
        return (float("inf"), node_id)
    return (-sum(heights) / len(heights), node_id)


def node_caption(network: Network, node_id: str) -> str:
    """Two lines: the label, then the type when it adds anything."""
    node = network.node(node_id)
    if node.label == node_id:
        return f"{node_id}\n({node.type})"
    return f"{node.label}\n[{node_id}]"


def title_lines(
    network: Network,
    mode: str,
    cheapest: int | None,
    cut_total: int,
    cut_size: int,
) -> list[str]:
    """The caption both renderers put above the picture."""
    if cheapest is None:
        second = "no target is reachable from any entry point"
    else:
        plural = "fix" if cut_size == 1 else "fixes"
        second = (
            f"cheapest attack cost {cheapest}  |  "
            f"minimum fix set: {cut_size} {plural}, total cost {cut_total}"
        )
    return [f"ChokePoint: {network.name}  (capacity mode: {mode})", second]
