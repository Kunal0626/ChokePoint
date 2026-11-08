"""The matplotlib fallback renderer.

On a machine without Graphviz this is the only picture available, so it is
written to stand on its own rather than to approximate what Graphviz would
have produced. It uses the hand-computed layered layout from visual.py,
because matplotlib has no graph layout of its own.

matplotlib is an optional extra. It is imported inside the render call so
that installing ChokePoint without it still leaves every other command
working, and so that `import chokepoint` costs nothing.
"""

from __future__ import annotations

from pathlib import Path

from .model import Network
from .visual import (
    CUT_COLOUR,
    EDGE_COLOUR,
    PATH_COLOUR,
    RenderUnavailable,
    edge_roles,
    layered_positions,
    node_caption,
    node_columns,
    node_roles,
    title_lines,
)

# Above this, a single page of boxes and arrows is unreadable and drawing it
# just burns seconds. The .dot file is still written, and Graphviz copes with
# far larger graphs, so the useful advice is to render that instead.
MAX_NODES_FOR_PICTURE = 60

# Layout units are columns and rows; these turn them into inches of canvas.
COLUMN_SPACING = 3.2
ROW_SPACING = 1.5


def render_png(
    network: Network,
    image_path: Path,
    *,
    cut_edges: frozenset[int] = frozenset(),
    cheapest_edges: frozenset[int] = frozenset(),
    mode: str = "fixcost",
    cheapest_cost: int | None = None,
    cut_total: int = 0,
) -> Path:
    """Draw the network to a PNG. Raises RenderUnavailable if it cannot."""
    if len(network.nodes) > MAX_NODES_FOR_PICTURE:
        raise RenderUnavailable(
            f"the network has {len(network.nodes)} nodes, more than the "
            f"{MAX_NODES_FOR_PICTURE} this fallback renderer draws legibly. "
            "The .dot file was still written; render that with Graphviz for "
            "a large graph."
        )

    matplotlib, pyplot, patches, lines = _import_matplotlib()

    positions = layered_positions(network)
    roles = node_roles(network)
    edges = edge_roles(network, cut_edges, cheapest_edges)

    columns = {int(x) for x, _ in positions.values()}
    tallest = _tallest_column(positions)
    figure, axes = pyplot.subplots(
        figsize=(
            max(len(columns) * COLUMN_SPACING, 7.0),
            max(tallest * ROW_SPACING + 2.0, 4.0),
        )
    )

    # Bowed edges reach outside the box the nodes occupy, so the points they
    # pass through are collected and fed into the axis limits. Sizing the
    # axes from node positions alone clips long curves and drops their labels
    # on top of the legend.
    curve_extremes = _draw_edges(axes, patches, network, positions, edges)
    _draw_nodes(axes, network, positions, roles)
    _finish(
        pyplot,
        axes,
        lines,
        network,
        positions,
        curve_extremes,
        title_lines(network, mode, cheapest_cost, cut_total, len(cut_edges)),
        any(not role.reachable for role in roles.values()),
    )

    figure.savefig(image_path, dpi=150, bbox_inches="tight")
    pyplot.close(figure)
    return image_path


def _import_matplotlib():
    """Import matplotlib with a headless backend, or explain why we cannot."""
    try:
        import matplotlib
    except ImportError:
        raise RenderUnavailable(
            "matplotlib is not installed, so no fallback image was drawn. "
            "The .dot file was still written. Install it with:  "
            "pip install 'chokepoint[viz]'"
        ) from None

    # Agg before pyplot: this writes files and must never try to open a window.
    matplotlib.use("Agg")
    from matplotlib import patches, pyplot
    from matplotlib import lines as mpl_lines

    return matplotlib, pyplot, patches, mpl_lines


def _tallest_column(positions: dict[str, tuple[float, float]]) -> int:
    counts: dict[float, int] = {}
    for x, _ in positions.values():
        counts[x] = counts.get(x, 0) + 1
    return max(counts.values(), default=1)


def _scaled(position: tuple[float, float]) -> tuple[float, float]:
    x, y = position
    return x * COLUMN_SPACING, y * ROW_SPACING


def _draw_edges(axes, patches, network, positions, edges) -> list[tuple[float, float]]:
    """Arrows first, so the node boxes drawn later hide their endpoints.

    Returns the halfway point of every curve, which is its furthest excursion
    from the straight chord and therefore what the axis limits must allow for.
    """
    curvature = _curvatures(network)
    extremes: list[tuple[float, float]] = []

    for index, edge in enumerate(network.edges):
        role = edges[index]
        start = _scaled(positions[edge.source])
        end = _scaled(positions[edge.target])
        rad = curvature[index]

        # An edge that is both cut and on the cheapest path gets a wide blue
        # halo under the red line, so neither fact hides the other.
        if role.is_both:
            axes.add_patch(
                _arrow(patches, start, end, rad, PATH_COLOUR, role.width + 3.5, 1)
            )
        axes.add_patch(
            _arrow(patches, start, end, rad, role.colour, role.width, 2)
        )
        extremes.append(_label_edge(axes, start, end, rad, str(edge.difficulty), role))

    return extremes


def _arrow(patches, start, end, rad, colour, width, zorder):
    return patches.FancyArrowPatch(
        start,
        end,
        connectionstyle=f"arc3,rad={rad}",
        arrowstyle="-|>",
        mutation_scale=14,
        linewidth=width,
        color=colour,
        # Keep the arrowhead clear of the box it points at.
        shrinkA=34,
        shrinkB=34,
        zorder=zorder,
    )


def _curvatures(network: Network) -> dict[int, float]:
    """Fan apart every edge that shares a pair of endpoints.

    The key is the *unordered* pair, which matters for two different cases
    that both end up drawing one line on top of another:

    *   Parallel edges, two techniques between the same hosts. Hiding one of
        them would hide a whole attack route and the fix that closes it.
    *   Opposite directions, a->b alongside b->a. These are distinct edges
        with distinct fixes, and one may be in the cut while the other is
        not, so a single overlapping line would show one edge's colour and
        silently drop the other's.
    """
    groups: dict[frozenset[str], list[int]] = {}
    for index, edge in enumerate(network.edges):
        groups.setdefault(frozenset((edge.source, edge.target)), []).append(index)

    curvature: dict[int, float] = {}
    for members in groups.values():
        if len(members) == 1:
            # arc3 with rad exactly 0 degenerates; a hair of curve is stable.
            curvature[members[0]] = 0.001
            continue
        # Spread symmetrically: 0, +0.3, -0.3, +0.6, ... Because arc3 bows
        # relative to the direction of travel, a->b and b->a given the same
        # sign land on opposite sides of the page, which is what we want.
        for position, index in enumerate(members):
            step = ((position + 1) // 2) * 0.3
            curvature[index] = (step if position % 2 else -step) or 0.001

    _bow_long_edges(network, curvature)
    return curvature


def _bow_long_edges(network: Network, curvature: dict[int, float]) -> None:
    """Arc edges that skip columns clear of the boxes they pass.

    A straight line from column 1 to column 4 runs behind whatever sits in
    columns 2 and 3, and reads as though it stops there. That is exactly
    backwards for the case this most often applies to: a shortcut edge that
    bypasses an intermediate control is the single most important thing such
    a diagram has to show, and drawing it through that control hides it.

    The bow is pushed away from the vertical middle of the picture, which is
    where the columns are busiest. The sign mapping was established the same
    way as the label offset, by drawing it and looking: for a left-to-right
    edge a positive rad bows downwards.
    """
    columns = node_columns(network)
    positions = layered_positions(network)

    for index, edge in enumerate(network.edges):
        span = abs(columns[edge.target] - columns[edge.source])
        if span < 2 or abs(curvature[index]) > 0.2:
            continue
        start, end = positions[edge.source], positions[edge.target]
        away_from_middle_is_down = (start[1] + end[1]) / 2 <= 0
        rightwards = end[0] > start[0]
        sign = 1 if away_from_middle_is_down == rightwards else -1
        curvature[index] = sign * min(0.09 * span, 0.32)


def _label_edge(axes, start, end, rad, text, role) -> tuple[float, float]:
    midpoint = ((start[0] + end[0]) / 2, (start[1] + end[1]) / 2)
    # Put the label on the curve, not on the straight chord: with several
    # edges between the same two boxes, a label on the chord sits between the
    # curves and cannot be matched to either.
    #
    # For a quadratic Bezier the halfway point is offset from the chord's
    # midpoint by half the control point's offset. The sign below was
    # established by drawing an arc and a candidate point together and
    # looking at them: matplotlib's arc3 bows the opposite way from the
    # (-dy, dx) perpendicular, in both directions of travel.
    dx, dy = end[0] - start[0], end[1] - start[1]
    offset = (dy * rad * 0.5, -dx * rad * 0.5)
    axes.text(
        midpoint[0] + offset[0],
        midpoint[1] + offset[1],
        text,
        fontsize=8,
        ha="center",
        va="center",
        color=role.colour if role.in_cut else "#2c3e50",
        bbox={"boxstyle": "round,pad=0.18", "fc": "white", "ec": "none", "alpha": 0.85},
        zorder=4,
    )
    return (midpoint[0] + offset[0], midpoint[1] + offset[1])


def _draw_nodes(axes, network, positions, roles) -> None:
    for node_id in network.node_ids:
        role = roles[node_id]
        x, y = _scaled(positions[node_id])
        axes.text(
            x,
            y,
            node_caption(network, node_id),
            fontsize=9,
            ha="center",
            va="center",
            zorder=5,
            bbox={
                "boxstyle": "round,pad=0.45",
                "fc": role.fill,
                "ec": role.line,
                "lw": 2.0 if (role.is_entry or role.is_target) else 1.0,
                "ls": "dashed" if not role.reachable else "solid",
            },
        )


def _finish(
    pyplot, axes, lines, network, positions, curve_extremes, title, has_unreachable
) -> None:
    handles = [
        lines.Line2D([], [], color=CUT_COLOUR, lw=3.5, label="in the minimum fix set"),
        lines.Line2D([], [], color=PATH_COLOUR, lw=2.4, label="on the cheapest attack path"),
        lines.Line2D([], [], color=EDGE_COLOUR, lw=0.9, label="other link"),
    ]
    if has_unreachable:
        handles.append(
            lines.Line2D(
                [], [], color="#bdc3c7", lw=1, ls="dashed",
                label="not reachable from any entry point",
            )
        )
    axes.legend(
        handles=handles,
        loc="lower center",
        bbox_to_anchor=(0.5, -0.12),
        ncol=2,
        frameon=False,
        fontsize=8,
    )
    axes.set_title("\n".join(title), fontsize=11, pad=16)

    points = [_scaled(p) for p in positions.values()] + list(curve_extremes)
    xs = [x for x, _ in points]
    ys = [y for _, y in points]
    axes.set_xlim(min(xs) - 1.6, max(xs) + 1.6)
    axes.set_ylim(min(ys) - 0.85, max(ys) + 0.85)
    axes.set_axis_off()
