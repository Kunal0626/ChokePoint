"""Rendering an Analysis as text or as JSON.

Numbers in JSON
---------------
Capacities are exact: integers under ``fixcost`` and ``unit``, Fractions under
``inverse-difficulty``. JSON has no Fraction, and emitting 0.14285714285714285
would throw away the exactness the rest of the pipeline works to preserve. So
an integer capacity is emitted as a JSON number and a fractional one as the
string ``"1/7"``. The ``capacity_mode`` field tells a consumer which to
expect, and the rule is stated in the output itself under ``_format``.
"""

from __future__ import annotations

from fractions import Fraction
from typing import Any

from .capacity import Capacity
from .recommend import Analysis, FixImpact, PathView, WhatIf

WIDTH = 74


def _capacity(value: Capacity) -> Any:
    """Exact JSON encoding: int stays a number, Fraction becomes "n/d"."""
    if isinstance(value, Fraction):
        return str(value) if value.denominator != 1 else value.numerator
    return value


def _capacity_text(value: Capacity) -> str:
    return str(value)


def _heading(title: str, trailing: str = "") -> str:
    if trailing:
        pad = WIDTH - len(title) - len(trailing)
        line = title + " " * max(pad, 1) + trailing
    else:
        line = title
    return f"{line}\n{'-' * WIDTH}"


def _node_text(path: PathView, index: int) -> str:
    """Label a node, avoiding "a (a)" when the label is just the id."""
    hop = path.hops[index] if index < len(path.hops) else path.hops[-1]
    node_id, label = (
        (hop.source, hop.source_label)
        if index < len(path.hops)
        else (hop.target, hop.target_label)
    )
    return label if label == node_id else f"{label} [{node_id}]"


def _arrow_path(path: PathView) -> str:
    """Compact route summary, using labels so it reads like the detail view."""
    return " -> ".join(path.labels)


# ---------------------------------------------------------------------------
# Text report
# ---------------------------------------------------------------------------


def text_report(analysis: Analysis) -> str:
    out: list[str] = []
    out.append("=" * WIDTH)
    out.append(f" ChokePoint: {analysis.network_name}")
    out.append(f" capacity mode: {analysis.mode}     top-k requested: {analysis.k}")
    out.append("=" * WIDTH)
    out.append("")

    out.extend(_section_paths(analysis))
    out.append("")
    out.extend(_section_fix_set(analysis))
    out.append("")
    out.extend(_section_ranking(analysis))
    return "\n".join(out)


def _section_paths(analysis: Analysis) -> list[str]:
    if not analysis.reachable:
        return [
            _heading("1. ATTACK PATHS"),
            "",
            "   No attack path exists: no target is reachable from any entry",
            "   point. Nothing needs fixing to keep it that way.",
        ]

    out = [
        _heading("1. ATTACK PATHS", f"cheapest: {analysis.baseline_cheapest}"),
        "",
        "   Cheapest route, hop by hop:",
        "",
    ]
    cheapest = analysis.paths[0]
    out.append(f"      {_node_text(cheapest, 0)}")
    for position, hop in enumerate(cheapest.hops):
        out.append(f"        |  difficulty {hop.difficulty}   {hop.technique}")
        out.append(f"        |  fix: {hop.fix_name} (cost {hop.fix_cost})")
        out.append(f"        v")
        marker = "   <-- TARGET" if position == len(cheapest.hops) - 1 else ""
        out.append(f"      {_node_text(cheapest, position + 1)}{marker}")

    out.append("")
    out.append(f"   Top {analysis.k} distinct loopless paths:")
    out.append("")
    for number, path in enumerate(analysis.paths, 1):
        out.append(
            f"      #{number}  difficulty {path.total_difficulty:>3}   {_arrow_path(path)}"
        )
    if len(analysis.paths) < analysis.k:
        plural = "" if len(analysis.paths) == 1 else "s"
        out.append(
            f"      (only {len(analysis.paths)} distinct loopless path{plural} exist)"
        )
    return out


def _section_fix_set(analysis: Analysis) -> list[str]:
    fix_set = analysis.fix_set
    out = [
        _heading(
            f"2. MINIMUM FIX SET (min-cut)",
            f"total cost: {fix_set.deduplicated_cost}",
        ),
        "",
    ]
    if not fix_set.entries:
        out.append("   Nothing to cut: no target is reachable.")
        return out

    out.append("   Applying all of these cuts every route to every target.")
    out.append("   No cheaper set of fixes achieves that.")
    out.append("")
    for entry in fix_set.entries:
        shared = (
            f"   (closes {entry.edge_count} links)" if entry.edge_count > 1 else ""
        )
        out.append(f"      {'cost':<5}{entry.cost:>3}   {entry.name}{shared}")
    out.append(f"      {'-' * 8}")
    out.append(f"      {'total':<5}{fix_set.deduplicated_cost:>3}")

    if fix_set.counts_a_fix_more_than_once:
        out.append("")
        out.append(
            f"   Note: the cut spans {fix_set.edge_count} edges but only "
            f"{len(fix_set.entries)} distinct fixes."
        )
        out.append(
            f"   Max-flow minimised the per-edge total "
            f"({_capacity_text(fix_set.cut_capacity)}); the real bill is"
        )
        out.append(
            f"   {fix_set.deduplicated_cost}, because a shared fix is paid once. "
            "See docs/MINCUT_VS_GREEDY.md."
        )
    return out


def _section_ranking(analysis: Analysis) -> list[str]:
    out = [_heading("3. SINGLE-FIX RANKING"), ""]
    if not analysis.reachable:
        out.append("   Skipped: with no attack path there is nothing to rank.")
        return out

    out.append("   Each fix applied alone. Ranked by how much it raises the")
    out.append(f"   attacker's cheapest cost, then by reach across the top {analysis.k}.")
    out.append("")
    out.append(f"      {'fix':<26}{'cost':>5}{'after':>7}{'raises':>8}{'paths':>8}")
    out.append(f"      {'-' * 54}")
    total = len(analysis.paths)
    for impact in analysis.fix_impacts:
        out.append(f"      {_impact_row(impact, total)}")
    out.append("")
    out.append("   A fix that raises the cost by +0 is not useless: it may be")
    out.append("   needed in the cut because another route is equally cheap.")
    return out


def _impact_row(impact: FixImpact, total_paths: int) -> str:
    name = impact.name if len(impact.name) <= 25 else impact.name[:22] + "..."
    if impact.disconnects:
        after, raises = "CUT", "all"
    else:
        after = str(impact.new_cheapest)
        raises = f"+{impact.delta}"
    reach = f"{impact.top_paths_hit}/{total_paths}"
    return f"{name:<26}{impact.cost:>5}{after:>7}{raises:>8}{reach:>8}"


def text_whatif(result: WhatIf) -> str:
    out = ["=" * WIDTH]
    out.append(f" ChokePoint what-if: {result.network_name}")
    out.append(f" applied fix: {result.applied.name} (cost {result.applied.cost})")
    out.append("=" * WIDTH)
    out.append("")
    if result.applied.edge_count > 1:
        out.append(
            f"   This fix closes {result.applied.edge_count} links, all of which "
            "were removed."
        )
        out.append("")

    if result.baseline_cheapest is None:
        out.append("   No attack path existed before the fix either.")
        return "\n".join(out)

    out.append(f"   Cheapest attack cost before : {result.baseline_cheapest}")
    if result.disconnects:
        out.append("   Cheapest attack cost after  : no route remains")
        out.append("")
        out.append("   This fix alone disconnects every target.")
    else:
        out.append(f"   Cheapest attack cost after  : {result.new_cheapest}")
        out.append(f"   Raised the attacker's cost by : +{result.delta}")
    out.append("")
    out.append(
        f"   Of the original top {result.k} paths, "
        f"{result.original_paths_surviving} of {result.original_path_count} "
        "did not use this fix."
    )

    if result.paths:
        out.append("")
        out.append(f"   Remaining cheapest routes:")
        out.append("")
        for number, path in enumerate(result.paths, 1):
            out.append(
                f"      #{number}  difficulty {path.total_difficulty:>3}   "
                f"{_arrow_path(path)}"
            )
    return "\n".join(out)


# ---------------------------------------------------------------------------
# JSON report
# ---------------------------------------------------------------------------

_FORMAT_NOTE = (
    "Capacities are exact. Integer capacities are JSON numbers; fractional "
    "ones (capacity_mode=inverse-difficulty) are strings like '1/7'."
)


def _path_json(path: PathView) -> dict[str, Any]:
    return {
        "total_difficulty": path.total_difficulty,
        "nodes": list(path.nodes),
        "hops": [
            {
                "from": hop.source,
                "to": hop.target,
                "difficulty": hop.difficulty,
                "technique": hop.technique,
                "fix": {"name": hop.fix_name, "cost": hop.fix_cost},
            }
            for hop in path.hops
        ],
    }


def json_report(analysis: Analysis) -> dict[str, Any]:
    fix_set = analysis.fix_set
    return {
        "_format": _FORMAT_NOTE,
        "network": analysis.network_name,
        "capacity_mode": analysis.mode,
        "k": analysis.k,
        "target_reachable": analysis.reachable,
        "cheapest_attack_cost": analysis.baseline_cheapest,
        "attack_paths": [_path_json(p) for p in analysis.paths],
        "minimum_fix_set": {
            "fixes": [
                {"name": e.name, "cost": e.cost, "edges_closed": e.edge_count}
                for e in fix_set.entries
            ],
            "total_cost": fix_set.deduplicated_cost,
            "cut_capacity": _capacity(fix_set.cut_capacity),
            "edges_cut": fix_set.edge_count,
            "shares_a_fix_across_edges": fix_set.counts_a_fix_more_than_once,
        },
        "single_fix_ranking": [
            {
                "name": i.name,
                "cost": i.cost,
                "edges_removed": i.edges_removed,
                "cheapest_after": i.new_cheapest,
                "raises_cheapest_by": i.delta,
                "disconnects": i.disconnects,
                "top_paths_hit": i.top_paths_hit,
            }
            for i in analysis.fix_impacts
        ],
    }


def json_whatif(result: WhatIf) -> dict[str, Any]:
    return {
        "_format": _FORMAT_NOTE,
        "network": result.network_name,
        "capacity_mode": result.mode,
        "k": result.k,
        "applied_fix": {
            "name": result.applied.name,
            "cost": result.applied.cost,
            "edges_closed": result.applied.edge_count,
        },
        "cheapest_before": result.baseline_cheapest,
        "cheapest_after": result.new_cheapest,
        "raises_cheapest_by": result.delta,
        "disconnects": result.disconnects,
        "original_paths_surviving": result.original_paths_surviving,
        "original_path_count": result.original_path_count,
        "remaining_paths": [_path_json(p) for p in result.paths],
    }
