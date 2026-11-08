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
from .capacity import CAPACITY_MODES, DEFAULT_CAPACITY_MODE
from .loader import load_network
from .maxflow import SelfCheckError
from .recommend import analyze, whatif
from .report import json_report, json_whatif, text_report, text_whatif
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

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        network = load_network(args.network)
        if args.command == "analyze":
            result = analyze(network, k=args.k, mode=args.capacity)
            text, payload = text_report(result), json_report(result)
        else:
            outcome = whatif(network, args.apply, k=args.k, mode=args.capacity)
            text, payload = text_whatif(outcome), json_whatif(outcome)
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

    if getattr(args, "out", None):
        _write_artifacts(Path(args.out), text, payload)

    return 0


def _write_artifacts(directory: Path, text: str, payload: dict) -> None:
    """Write both renderings side by side.

    Notes go to stderr so that `--json --out DIR` still produces clean JSON on
    stdout for a pipeline to consume.
    """
    directory.mkdir(parents=True, exist_ok=True)
    report_txt = directory / "report.txt"
    report_json = directory / "report.json"
    report_txt.write_text(text + "\n", encoding="utf-8")
    report_json.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"{PROGRAM}: wrote {report_txt}", file=sys.stderr)
    print(f"{PROGRAM}: wrote {report_json}", file=sys.stderr)
