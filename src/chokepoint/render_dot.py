"""Emit Graphviz DOT, and render it if the `dot` binary happens to exist.

The .dot file is always written, whether or not Graphviz is installed. It is
plain text, so it diffs cleanly in review, it commits sensibly, and anyone who
does have Graphviz can render it later at any size. The PNG is a convenience
on top of that, not the deliverable.

Nothing here imports a Graphviz Python binding. The file is built by string
concatenation and the binary, if present, is invoked as a subprocess with a
fixed argument list and no shell. That keeps the runtime dependency list empty.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from .model import Network
from .visual import (
    CUT_COLOUR,
    ENTRY_FILL,
    ENTRY_LINE,
    PATH_COLOUR,
    RenderUnavailable,
    TARGET_FILL,
    TARGET_LINE,
    edge_roles,
    node_caption,
    node_roles,
    title_lines,
)

GRAPHVIZ_HINT = (
    "the Graphviz 'dot' binary is not on PATH, so no image was rendered from "
    "the .dot file. On macOS, install Homebrew first (see https://brew.sh) "
    "and then run:  brew install graphviz"
)


def graphviz_binary() -> str | None:
    """Path to `dot`, or None when Graphviz is not installed."""
    return shutil.which("dot")


def _quote(text: str) -> str:
    """Quote a DOT string literal, escaping what DOT treats specially."""
    escaped = text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
    return f'"{escaped}"'


def _attrs(pairs: dict[str, object]) -> str:
    return ", ".join(f"{key}={_quote(str(value))}" for key, value in pairs.items())


def to_dot(
    network: Network,
    *,
    cut_edges: frozenset[int] = frozenset(),
    cheapest_edges: frozenset[int] = frozenset(),
    mode: str = "fixcost",
    cheapest_cost: int | None = None,
    cut_total: int = 0,
) -> str:
    """Build the DOT source for a network, with the cut and path highlighted."""
    roles = node_roles(network)
    edges = edge_roles(network, cut_edges, cheapest_edges)
    # A real newline here; _quote turns it into DOT's \n escape. Joining with
    # a literal backslash-n would survive quoting and print as text.
    caption = "\n".join(
        title_lines(network, mode, cheapest_cost, cut_total, len(cut_edges))
    )

    lines = [
        "digraph chokepoint {",
        "  rankdir=LR;",
        "  labelloc=\"t\";",
        f"  label={_quote(caption)};",
        "  fontname=\"Helvetica\";",
        "  fontsize=13;",
        "  node [fontname=\"Helvetica\", fontsize=10];",
        "  edge [fontname=\"Helvetica\", fontsize=9];",
        "",
    ]

    for node_id in network.node_ids:
        role = roles[node_id]
        if role.is_target:
            shape, style = "doubleoctagon", "filled,bold"
        elif role.is_entry:
            shape, style = "box", "filled,rounded,bold"
        elif not role.reachable:
            shape, style = "box", "filled,rounded,dashed"
        else:
            shape, style = "box", "filled,rounded"
        attributes = {
            "label": node_caption(network, node_id),
            "shape": shape,
            "style": style,
            "fillcolor": role.fill,
            "color": role.line,
            "penwidth": 2 if (role.is_entry or role.is_target) else 1,
        }
        if not role.reachable:
            attributes["tooltip"] = "not reachable from any entry point"
        lines.append(f"  {_quote(node_id)} [{_attrs(attributes)}];")

    lines.append("")
    for index, edge in enumerate(network.edges):
        role = edges[index]
        # A colon-separated colorList makes Graphviz draw parallel splines, so
        # an edge that is both cut and on the cheapest path shows both facts.
        colour = f"{CUT_COLOUR}:{PATH_COLOUR}" if role.is_both else role.colour
        attributes = {
            "label": str(edge.difficulty),
            "color": colour,
            "penwidth": role.width,
            "tooltip": f"{edge.technique} | fix: {edge.fix.name} (cost {edge.fix.cost})",
        }
        if role.in_cut:
            attributes["fontcolor"] = CUT_COLOUR
        lines.append(
            f"  {_quote(edge.source)} -> {_quote(edge.target)} [{_attrs(attributes)}];"
        )

    # Pin entries hard left and targets hard right, so the picture always
    # reads in the same direction regardless of the graph's shape.
    lines.append("")
    lines.append("  { rank=min; " + " ".join(_quote(n) for n in network.entry) + "; }")
    lines.append("  { rank=max; " + " ".join(_quote(n) for n in network.targets) + "; }")
    lines.append("")
    lines.extend(_legend())
    lines.append("}")
    return "\n".join(lines) + "\n"


def _legend() -> list[str]:
    """A dashed cluster explaining the colour and weight encoding."""
    sample_edge = "shape=point, width=0.01, label=\"\", color=\"#ffffff\""
    return [
        "  subgraph cluster_legend {",
        "    label=\"Legend\";",
        "    fontsize=10;",
        "    style=dashed;",
        "    color=\"#bdc3c7\";",
        f"    lg_cut_a [{sample_edge}]; lg_cut_b [{sample_edge}];",
        f"    lg_path_a [{sample_edge}]; lg_path_b [{sample_edge}];",
        f"    lg_both_a [{sample_edge}]; lg_both_b [{sample_edge}];",
        f"    lg_cut_a -> lg_cut_b [label=\" in the minimum fix set\","
        f" color={_quote(CUT_COLOUR)}, penwidth=3.5];",
        f"    lg_path_a -> lg_path_b [label=\" on the cheapest attack path\","
        f" color={_quote(PATH_COLOUR)}, penwidth=2.4];",
        f"    lg_both_a -> lg_both_b [label=\" both\","
        f" color={_quote(CUT_COLOUR + ':' + PATH_COLOUR)}, penwidth=3.5];",
        f"    lg_entry [label=\"entry point\", shape=box,"
        f" style=\"filled,rounded,bold\", fillcolor={_quote(ENTRY_FILL)},"
        f" color={_quote(ENTRY_LINE)}, fontsize=9];",
        f"    lg_target [label=\"target\", shape=doubleoctagon, style=\"filled,bold\","
        f" fillcolor={_quote(TARGET_FILL)}, color={_quote(TARGET_LINE)}, fontsize=9];",
        "  }",
    ]


def write_dot(path: Path, source: str) -> Path:
    path.write_text(source, encoding="utf-8")
    return path


def render_with_graphviz(dot_path: Path, image_path: Path, image_format: str = "png") -> Path:
    """Run `dot` on a .dot file. Raises RenderUnavailable if it cannot."""
    binary = graphviz_binary()
    if binary is None:
        raise RenderUnavailable(GRAPHVIZ_HINT)

    completed = subprocess.run(
        [binary, f"-T{image_format}", str(dot_path), "-o", str(image_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or f"exit code {completed.returncode}"
        raise RenderUnavailable(f"Graphviz failed to render the .dot file: {detail}")
    return image_path
