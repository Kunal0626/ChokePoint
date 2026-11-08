"""Command-line interface.

Exit codes, so the tool is usable from a script:

    0   analysis completed
    2   the input or the request was wrong (bad JSON, invalid model,
        unknown fix name, missing file)
    3   an internal self-check failed, which is a bug in ChokePoint

Exit code 3 is kept distinct from 2 on purpose. A 2 means "your model needs
fixing"; a 3 means "this tool computed something it could not verify and you
should not trust the output". Collapsing them would let a real bug look like
a user error.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from . import __version__
from .bench import DEFAULT_REPEAT, environment, run_benchmark
from .capacity import CAPACITY_MODES, DEFAULT_CAPACITY_MODE
from .loader import load_network
from .maxflow import SelfCheckError
from .model import Network
from .recommend import Analysis, analyze, whatif
from .render_dot import render_with_graphviz, to_dot, write_dot
from .render_mpl import render_png
from .report import (
    json_bench,
    json_report,
    json_whatif,
    text_bench,
    text_report,
    text_whatif,
)
from .visual import RenderUnavailable
from .yen import DEFAULT_K

PROGRAM = "chokepoint"


def _positive_int(raw: str) -> int:
    try:
        value = int(raw)
    except ValueError:
        raise argparse.ArgumentTypeError(f"expected a whole number, got {raw!r}") from None
    if value < 1:
        raise argparse.ArgumentTypeError(f"must be at least 1, got {value}")
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=PROGRAM,
        description="Attack-path and patch-priority analyzer for network graphs.",
    )
    parser.add_argument("--version", action="version", version=f"{PROGRAM} {__version__}")
    subcommands = parser.add_subparsers(dest="command", required=True)

    def add_common(sub: argparse.ArgumentParser) -> None:
        sub.add_argument("network", help="path to the network model JSON file")
        sub.add_argument(
            "--k",
            type=_positive_int,
            default=DEFAULT_K,
            metavar="N",
            help=f"how many distinct attack paths to report (default {DEFAULT_K})",
        )
        sub.add_argument(
            "--capacity",
            choices=CAPACITY_MODES,
            default=DEFAULT_CAPACITY_MODE,
            help=(
                "what the min-cut minimises: fixcost = cheapest adequate set of "
                "fixes (default); unit = fewest links; inverse-difficulty = "
                "where attacker throughput is most constrained"
            ),
        )
        sub.add_argument(
            "--json", action="store_true", help="emit machine-readable JSON instead of text"
        )

    analyze_cmd = subcommands.add_parser(
        "analyze", help="report attack paths, the minimum fix set, and fix rankings"
    )
    add_common(analyze_cmd)
    analyze_cmd.add_argument(
        "--out",
        metavar="DIR",
        help="also write report.txt and report.json into this directory",
    )

    whatif_cmd = subcommands.add_parser(
        "whatif", help="apply one fix and report what the attacker has left"
    )
    add_common(whatif_cmd)
    whatif_cmd.add_argument(
        "--apply",
        required=True,
        metavar="FIX",
        help="name of the fix to apply, exactly as it appears in the model",
    )

    bench_cmd = subcommands.add_parser(
        "bench", help="time the algorithms on a generated layered graph"
    )
    bench_cmd.add_argument(
        "--nodes", type=_positive_int, default=1000, metavar="N", help="default 1000"
    )
    bench_cmd.add_argument(
        "--edges", type=_positive_int, default=5000, metavar="N", help="default 5000"
    )
    bench_cmd.add_argument(
        "--seed", type=int, default=1, help="graph generator seed (default 1)"
    )
    bench_cmd.add_argument(
        "--repeat",
        type=_positive_int,
        default=DEFAULT_REPEAT,
        metavar="N",
        help=f"timed runs per operation (default {DEFAULT_REPEAT})",
    )
    bench_cmd.add_argument(
        "--layers", type=_positive_int, default=None, metavar="N",
        help="default is about the square root of the node count",
    )
    bench_cmd.add_argument("--k", type=_positive_int, default=DEFAULT_K, metavar="N")
    bench_cmd.add_argument(
        "--capacity", choices=CAPACITY_MODES, default=DEFAULT_CAPACITY_MODE
    )
    bench_cmd.add_argument("--json", action="store_true")

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    # bench generates its own graph, so it never touches the loader.
    if args.command == "bench":
        return _run_bench(args)

    try:
        network = load_network(args.network)
        analysis: Analysis | None = None
        if args.command == "analyze":
            analysis = analyze(network, k=args.k, mode=args.capacity)
            text, payload = text_report(analysis), json_report(analysis)
        elif args.command == "whatif":
            outcome = whatif(network, args.apply, k=args.k, mode=args.capacity)
            text, payload = text_whatif(outcome), json_whatif(outcome)
        else:
            raise AssertionError(f"unhandled command {args.command!r}")
    except (FileNotFoundError, IsADirectoryError, ValueError) as exc:
        # Every user-facing input problem lands here: missing file, malformed
        # JSON, a model that fails validation, an unknown fix name.
        print(f"{PROGRAM}: {exc}", file=sys.stderr)
        return 2
    except SelfCheckError as exc:
        print(f"{PROGRAM}: internal self-check failed, so the result is", file=sys.stderr)
        print("not trustworthy. This is a bug in ChokePoint.", file=sys.stderr)
        print(f"\n{exc}", file=sys.stderr)
        return 3

    rendered = json.dumps(payload, indent=2) if args.json else text
    print(rendered)

    if getattr(args, "out", None) and analysis is not None:
        _write_artifacts(Path(args.out), text, payload, network, analysis)

    return 0


def _run_bench(args: argparse.Namespace) -> int:
    try:
        result = run_benchmark(
            nodes=args.nodes,
            edges=args.edges,
            seed=args.seed,
            k=args.k,
            mode=args.capacity,
            repeat=args.repeat,
            layers=args.layers,
        )
    except ValueError as exc:
        print(f"{PROGRAM}: {exc}", file=sys.stderr)
        return 2

    env = environment()
    payload = json_bench(result, env)
    print(json.dumps(payload, indent=2) if args.json else text_bench(result, env))
    return 0


def _note(message: str) -> None:
    """Progress and diagnostics go to stderr.

    Keeping stdout to the report alone is what lets `--json --out DIR` be
    piped into another tool without the notes corrupting the stream.
    """
    print(f"{PROGRAM}: {message}", file=sys.stderr)


def _write_artifacts(
    directory: Path, text: str, payload: dict, network: Network, analysis: Analysis
) -> None:
    """Write the two reports, the .dot file, and a picture if one is possible."""
    directory.mkdir(parents=True, exist_ok=True)

    report_txt = directory / "report.txt"
    report_json = directory / "report.json"
    report_txt.write_text(text + "\n", encoding="utf-8")
    report_json.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    _note(f"wrote {report_txt}")
    _note(f"wrote {report_json}")

    highlights = {
        "cut_edges": frozenset(analysis.fix_set.edge_indices),
        "cheapest_edges": frozenset(analysis.cheapest_edge_indices),
        "mode": analysis.mode,
        "cheapest_cost": analysis.baseline_cheapest,
        "cut_total": analysis.fix_set.deduplicated_cost,
    }

    # The .dot file is the real deliverable and is always written: it is text,
    # it reviews and commits cleanly, and anyone with Graphviz can render it
    # later at any size. The image is a convenience on top.
    dot_path = write_dot(directory / "network.dot", to_dot(network, **highlights))
    _note(f"wrote {dot_path}")

    image_path = directory / "network.png"
    try:
        render_with_graphviz(dot_path, image_path)
    except RenderUnavailable as graphviz_problem:
        try:
            render_png(network, image_path, **highlights)
        except RenderUnavailable as fallback_problem:
            _note(f"no image written: {fallback_problem}")
        else:
            _note(f"wrote {image_path} (matplotlib fallback)")
        _note(f"note: {graphviz_problem}")
    else:
        _note(f"wrote {image_path} (rendered by Graphviz)")
