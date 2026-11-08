#!/usr/bin/env python3
"""Generate the examples in docs/MINCUT_VS_GREEDY.md.

Every number in that document comes from here:

    .venv/bin/python scripts/explain_ranking.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from chokepoint.loader import parse_network  # noqa: E402
from chokepoint.recommend import analyze  # noqa: E402

# A hub that both cheap routes pass through, plus a slow bypass. Hardening the
# hub is one expensive fix with a large effect; the cheap fixes downstream each
# have no effect alone but together they disconnect everything.
HUB = {
    "name": "hub-and-bypass",
    "nodes": [
        {"id": "s", "label": "Internet"},
        {"id": "hub", "label": "Jump host"},
        {"id": "a", "label": "App server"},
        {"id": "b", "label": "Build server"},
        {"id": "c", "label": "Contractor VPN"},
        {"id": "t", "label": "Database"},
    ],
    "entry": ["s"],
    "targets": ["t"],
    "edges": [
        {"from": "s", "to": "hub", "difficulty": 1, "technique": "stolen SSH key",
         "fix": {"name": "Harden jump host", "cost": 20}},
        {"from": "hub", "to": "a", "difficulty": 1, "technique": "unpatched app",
         "fix": {"name": "Patch app server", "cost": 1}},
        {"from": "a", "to": "t", "difficulty": 1, "technique": "reused DB password",
         "fix": {"name": "Rotate app DB password", "cost": 1}},
        {"from": "hub", "to": "b", "difficulty": 1, "technique": "exposed CI agent",
         "fix": {"name": "Lock down CI agent", "cost": 1}},
        {"from": "b", "to": "t", "difficulty": 1, "technique": "CI deploy credentials",
         "fix": {"name": "Scope CI credentials", "cost": 1}},
        {"from": "s", "to": "c", "difficulty": 9, "technique": "phishing a contractor",
         "fix": {"name": "MFA on contractor VPN", "cost": 1}},
        {"from": "c", "to": "t", "difficulty": 9, "technique": "flat network",
         "fix": {"name": "Segment contractor VLAN", "cost": 1}},
    ],
}

# Two identical disjoint routes: every single fix scores zero.
TWINS = {
    "name": "twin-routes",
    "nodes": [{"id": n} for n in ("s", "a", "b", "t")],
    "entry": ["s"],
    "targets": ["t"],
    "edges": [
        {"from": "s", "to": "a", "difficulty": 1, "fix": {"name": "Fix route A entry", "cost": 2}},
        {"from": "a", "to": "t", "difficulty": 1, "fix": {"name": "Fix route A exit", "cost": 2}},
        {"from": "s", "to": "b", "difficulty": 1, "fix": {"name": "Fix route B entry", "cost": 2}},
        {"from": "b", "to": "t", "difficulty": 1, "fix": {"name": "Fix route B exit", "cost": 2}},
    ],
}


def show(data: dict, k: int) -> None:
    net = parse_network(data)
    result = analyze(net, k=k)
    cut_names = {e.name for e in result.fix_set.entries}

    print(f"\n### {result.network_name}")
    print(f"\nbaseline cheapest attack cost: {result.baseline_cheapest}")
    print(f"top-{k} paths:")
    for number, path in enumerate(result.paths, 1):
        print(f"  #{number}  difficulty {path.total_difficulty:>3}   "
              f"{' -> '.join(path.labels)}")

    print(f"\nminimum fix set (total cost {result.fix_set.deduplicated_cost}):")
    for entry in result.fix_set.entries:
        print(f"  cost {entry.cost:>3}   {entry.name}")

    print("\nsingle-fix ranking:")
    print(f"  {'fix':<26}{'cost':>5}{'after':>7}{'raises':>8}{'paths':>7}  in cut?")
    print(f"  {'-' * 62}")
    for impact in result.fix_impacts:
        after = "CUT" if impact.disconnects else str(impact.new_cheapest)
        raises = "all" if impact.disconnects else f"+{impact.delta}"
        mark = "yes" if impact.name in cut_names else "no"
        print(f"  {impact.name:<26}{impact.cost:>5}{after:>7}{raises:>8}"
              f"{impact.top_paths_hit:>4}/{len(result.paths)}  {mark}")

    best = result.fix_impacts[0]
    print(f"\nbest single fix by effect : {best.name!r} "
          f"(cost {best.cost}, raises by "
          f"{'all' if best.disconnects else '+' + str(best.delta)})")
    print(f"is it in the minimum cut? : {'yes' if best.name in cut_names else 'NO'}")
    print(f"cut members with +0 effect: "
          f"{sum(1 for i in result.fix_impacts if i.name in cut_names and i.delta == 0)}"
          f" of {len(cut_names)}")


if __name__ == "__main__":
    print("ChokePoint: minimum cut versus best single fix")
    print("=" * 46)
    show(HUB, k=3)
    show(TWINS, k=4)
