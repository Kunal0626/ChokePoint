"""Assembling the three report sections, and the what-if analysis.

This module turns the raw algorithm output into the thing a defender can act
on. Three decisions in here are worth defending.

Applying a fix removes every edge that names it
-----------------------------------------------
Fix names are deliberately not unique (see model.Fix). One real action --
"enforce MFA on the VPN" -- can close several modelled links, and applying it
should close all of them. So ``apply_fix`` matches by name, not by edge.

Paths are resolved to hops immediately, not kept as edge indices
----------------------------------------------------------------
The what-if analysis derives modified copies of the network, and edge indices
into the original are meaningless in a copy that has had edges removed. Every
path is therefore flattened into self-contained ``Hop`` records at the point
it is produced, so no index can outlive the network it referred to.

The min-cut's capacity and its real-world price can differ
----------------------------------------------------------
Max-flow minimises the sum of *edge* capacities. If two edges in the cut share
a fix name, that fix's cost is counted twice in the capacity but paid once in
reality. ``FixSet`` reports both numbers and the report points at the gap when
there is one.

The uncomfortable consequence, stated plainly because it would be dishonest to
hide it: when fixes are shared, the cut that minimises the capacity is not
necessarily the one that minimises the real bill. ChokePoint reports a cut
that is provably optimal for the capacity objective, and tells you its true
de-duplicated price. Optimising the de-duplicated price directly is a
different and harder problem -- it is no longer a min-cut, because the cost of
cutting one edge now depends on which others you cut -- and it is listed under
future work rather than quietly approximated.
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass, replace

from .capacity import Capacity, DEFAULT_CAPACITY_MODE
from .dijkstra import AttackPath, cheapest_attack_path
from .maxflow import min_cut
from .model import Network
from .yen import DEFAULT_K, k_shortest_attack_paths


class UnknownFixError(ValueError):
    """The named fix does not appear anywhere in the network."""


@dataclass(frozen=True)
class Hop:
    """One step of an attack path, carrying everything the report needs."""

    source: str
    source_label: str
    target: str
    target_label: str
    difficulty: int
    technique: str
    fix_name: str
    fix_cost: int


@dataclass(frozen=True)
class PathView:
    """An attack path flattened into self-contained hops."""

    hops: tuple[Hop, ...]
    total_difficulty: int

    @property
    def nodes(self) -> tuple[str, ...]:
        if not self.hops:
            return ()
        return (self.hops[0].source,) + tuple(hop.target for hop in self.hops)

    @property
    def labels(self) -> tuple[str, ...]:
        """Human-readable node names, for reports that name hosts not ids."""
        if not self.hops:
            return ()
        return (self.hops[0].source_label,) + tuple(
            hop.target_label for hop in self.hops
        )

    @property
    def fix_names(self) -> frozenset[str]:
        return frozenset(hop.fix_name for hop in self.hops)


@dataclass(frozen=True)
class FixEntry:
    """A distinct fix, and the edges it would close."""

    name: str
    cost: int
    edge_count: int


@dataclass(frozen=True)
class FixSet:
    """The min-cut, expressed as fixes rather than edges."""

    mode: str
    entries: tuple[FixEntry, ...]
    # What max-flow minimised: the sum of per-edge capacities.
    cut_capacity: Capacity
    # What it would actually cost, counting each distinct fix once.
    deduplicated_cost: int
    edge_count: int

    @property
    def counts_a_fix_more_than_once(self) -> bool:
        """True when a shared fix makes the capacity overstate the real bill."""
        return self.edge_count > len(self.entries)


@dataclass(frozen=True)
class FixImpact:
    """What applying one fix on its own would achieve."""

    name: str
    cost: int
    edges_removed: int
    # None means the target became unreachable: an unbounded improvement.
    new_cheapest: int | None
    delta: int | None
    top_paths_hit: int

    @property
    def disconnects(self) -> bool:
        return self.new_cheapest is None


@dataclass(frozen=True)
class Analysis:
    """Everything the analyze report needs."""

    network_name: str
    k: int
    mode: str
    baseline_cheapest: int | None
    paths: tuple[PathView, ...]
    fix_set: FixSet
    fix_impacts: tuple[FixImpact, ...]

    @property
    def reachable(self) -> bool:
        return self.baseline_cheapest is not None


@dataclass(frozen=True)
class WhatIf:
    """The result of applying one named fix."""

    network_name: str
    k: int
    mode: str
    applied: FixEntry
    baseline_cheapest: int | None
    new_cheapest: int | None
    delta: int | None
    original_paths_surviving: int
    original_path_count: int
    paths: tuple[PathView, ...]

    @property
    def disconnects(self) -> bool:
        return self.new_cheapest is None


# ---------------------------------------------------------------------------
# Fixes
# ---------------------------------------------------------------------------


def distinct_fixes(network: Network) -> dict[str, FixEntry]:
    """Every distinct fix in the network, keyed by name.

    A fix named on several edges appears once, with the edge count. Costs are
    taken from the first edge that names it; a model that gives the same fix
    two different costs is a modelling error the loader cannot catch, so the
    first value wins deterministically rather than silently averaging.
    """
    found: dict[str, FixEntry] = {}
    for edge in network.edges:
        existing = found.get(edge.fix.name)
        if existing is None:
            found[edge.fix.name] = FixEntry(
                name=edge.fix.name, cost=edge.fix.cost, edge_count=1
            )
        else:
            found[edge.fix.name] = replace(existing, edge_count=existing.edge_count + 1)
    return found


def apply_fix(network: Network, fix_name: str) -> Network:
    """A copy of the network with every edge naming this fix removed.

    Raises UnknownFixError, with suggestions, when nothing names it: a typo in
    a fix name should not silently analyse an unchanged network and report
    that the fix achieved nothing.
    """
    known = distinct_fixes(network)
    if fix_name not in known:
        raise UnknownFixError(_unknown_fix_message(fix_name, sorted(known)))
    return replace(
        network, edges=tuple(e for e in network.edges if e.fix.name != fix_name)
    )


def _unknown_fix_message(fix_name: str, known: list[str]) -> str:
    message = f"no fix named {fix_name!r} in this network"
    suggestions = difflib.get_close_matches(fix_name, known, n=3, cutoff=0.5)
    if suggestions:
        message += "; did you mean " + " or ".join(repr(s) for s in suggestions) + "?"
    elif known:
        shown = ", ".join(repr(name) for name in known[:8])
        if len(known) > 8:
            shown += f", ... ({len(known)} total)"
        message += f"; available fixes: {shown}"
    return message


# ---------------------------------------------------------------------------
# Views
# ---------------------------------------------------------------------------


def to_path_view(network: Network, path: AttackPath) -> PathView:
    """Flatten an AttackPath into hops that do not depend on edge indices."""
    hops = []
    for edge_index in path.edge_indices:
        edge = network.edges[edge_index]
        hops.append(
            Hop(
                source=edge.source,
                source_label=network.label_of(edge.source),
                target=edge.target,
                target_label=network.label_of(edge.target),
                difficulty=edge.difficulty,
                technique=edge.technique,
                fix_name=edge.fix.name,
                fix_cost=edge.fix.cost,
            )
        )
    return PathView(hops=tuple(hops), total_difficulty=path.total_difficulty)


def _path_views(network: Network, k: int) -> tuple[PathView, ...]:
    return tuple(
        to_path_view(network, path) for path in k_shortest_attack_paths(network, k)
    )


def _cheapest_cost(network: Network) -> int | None:
    path = cheapest_attack_path(network)
    return None if path is None else path.total_difficulty


# ---------------------------------------------------------------------------
# The three report sections
# ---------------------------------------------------------------------------


def build_fix_set(network: Network, mode: str) -> FixSet:
    """Section 2: the min-cut, expressed as a set of distinct fixes."""
    cut = min_cut(network, mode)
    counts: dict[str, int] = {}
    costs: dict[str, int] = {}
    for edge_index in cut.edge_indices:
        edge = network.edges[edge_index]
        counts[edge.fix.name] = counts.get(edge.fix.name, 0) + 1
        costs.setdefault(edge.fix.name, edge.fix.cost)

    entries = tuple(
        FixEntry(name=name, cost=costs[name], edge_count=counts[name])
        # Most expensive first, then by name for determinism: a defender reads
        # the top of this list to see where the budget actually goes.
        for name in sorted(counts, key=lambda n: (-costs[n], n))
    )
    return FixSet(
        mode=mode,
        entries=entries,
        cut_capacity=cut.value,
        deduplicated_cost=sum(entry.cost for entry in entries),
        edge_count=len(cut.edge_indices),
    )


def rank_fixes(
    network: Network,
    baseline_cheapest: int | None,
    baseline_paths: tuple[PathView, ...],
) -> tuple[FixImpact, ...]:
    """Section 3: every fix, ranked by what it achieves on its own.

    Two measures, because neither alone is enough. How much the fix raises the
    attacker's cheapest cost says whether it slows them down; how many of the
    top-k paths it appears on says how much of the attack surface it touches.
    A fix can score zero on the first and still be essential -- see
    docs/MINCUT_VS_GREEDY.md.
    """
    impacts: list[FixImpact] = []
    for entry in distinct_fixes(network).values():
        reduced = apply_fix(network, entry.name)
        new_cheapest = _cheapest_cost(reduced)
        delta = (
            None
            if new_cheapest is None or baseline_cheapest is None
            else new_cheapest - baseline_cheapest
        )
        impacts.append(
            FixImpact(
                name=entry.name,
                cost=entry.cost,
                edges_removed=entry.edge_count,
                new_cheapest=new_cheapest,
                delta=delta,
                top_paths_hit=sum(
                    1 for path in baseline_paths if entry.name in path.fix_names
                ),
            )
        )
    return tuple(sorted(impacts, key=_impact_rank))


def _impact_rank(impact: FixImpact) -> tuple:
    """Disconnecting fixes first, then the biggest slowdown, then reach.

    Cost breaks ties ascending, so that among equally effective fixes the
    cheap one is recommended. The name is the final tiebreak purely so the
    ordering is reproducible.
    """
    return (
        0 if impact.disconnects else 1,
        -(impact.delta or 0),
        -impact.top_paths_hit,
        impact.cost,
        impact.name,
    )


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------


def analyze(
    network: Network, k: int = DEFAULT_K, mode: str = DEFAULT_CAPACITY_MODE
) -> Analysis:
    """Run all three report sections."""
    paths = _path_views(network, k)
    baseline = paths[0].total_difficulty if paths else None
    return Analysis(
        network_name=network.name,
        k=k,
        mode=mode,
        baseline_cheapest=baseline,
        paths=paths,
        fix_set=build_fix_set(network, mode),
        fix_impacts=rank_fixes(network, baseline, paths),
    )


def whatif(
    network: Network,
    fix_name: str,
    k: int = DEFAULT_K,
    mode: str = DEFAULT_CAPACITY_MODE,
) -> WhatIf:
    """Apply one fix and report what the attacker has left."""
    known = distinct_fixes(network)
    if fix_name not in known:
        raise UnknownFixError(_unknown_fix_message(fix_name, sorted(known)))

    baseline_paths = _path_views(network, k)
    baseline = baseline_paths[0].total_difficulty if baseline_paths else None

    reduced = apply_fix(network, fix_name)
    new_paths = _path_views(reduced, k)
    new_cheapest = new_paths[0].total_difficulty if new_paths else None

    # A surviving path is one of the original top-k that does not use the
    # applied fix, which is cheaper and clearer than re-deriving identity
    # across two different networks.
    surviving = sum(1 for path in baseline_paths if fix_name not in path.fix_names)

    return WhatIf(
        network_name=network.name,
        k=k,
        mode=mode,
        applied=known[fix_name],
        baseline_cheapest=baseline,
        new_cheapest=new_cheapest,
        delta=None if new_cheapest is None or baseline is None else new_cheapest - baseline,
        original_paths_surviving=surviving,
        original_path_count=len(baseline_paths),
        paths=new_paths,
    )
