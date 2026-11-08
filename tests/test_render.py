"""Tests for the layout, the DOT emitter, and the matplotlib fallback."""

from __future__ import annotations

import subprocess
import sys

import pytest

from chokepoint.loader import parse_network
from chokepoint.recommend import analyze
from chokepoint.render_dot import (
    GRAPHVIZ_HINT,
    graphviz_binary,
    render_with_graphviz,
    to_dot,
    write_dot,
)
from chokepoint.render_mpl import MAX_NODES_FOR_PICTURE, _curvatures, render_png
from chokepoint.visual import (
    CUT_COLOUR,
    EDGE_COLOUR,
    PATH_COLOUR,
    EdgeRole,
    RenderUnavailable,
    layered_positions,
    node_columns,
    node_roles,
)
from helpers import random_network

DIAMOND = {
    "name": "diamond",
    "nodes": [
        {"id": "s", "label": "Internet", "type": "external"},
        {"id": "a", "label": "Web server", "type": "server"},
        {"id": "b", "label": "Mail server", "type": "server"},
        {"id": "t", "label": "Database", "type": "database"},
        {"id": "orphan", "label": "Old printer", "type": "host"},
    ],
    "entry": ["s"],
    "targets": ["t"],
    "edges": [
        {"from": "s", "to": "a", "difficulty": 1, "technique": "unpatched web app",
         "fix": {"name": "Patch web app", "cost": 5}},
        {"from": "a", "to": "t", "difficulty": 1, "technique": "reused creds",
         "fix": {"name": "Rotate creds", "cost": 1}},
        {"from": "s", "to": "b", "difficulty": 5, "technique": "phishing",
         "fix": {"name": "Mail filtering", "cost": 1}},
        {"from": "b", "to": "t", "difficulty": 5, "technique": "SMB exposed",
         "fix": {"name": "Firewall SMB", "cost": 1}},
    ],
}


def diamond():
    return parse_network(DIAMOND)


def highlighted(network):
    """The arguments both renderers take, derived from a real analysis."""
    result = analyze(network, k=3)
    return {
        "cut_edges": frozenset(result.fix_set.edge_indices),
        "cheapest_edges": frozenset(result.cheapest_edge_indices),
        "mode": result.mode,
        "cheapest_cost": result.baseline_cheapest,
        "cut_total": result.fix_set.deduplicated_cost,
    }


# ---------------------------------------------------------------------------
# Layout
# ---------------------------------------------------------------------------


def test_entries_are_leftmost_and_targets_rightmost():
    columns = node_columns(diamond())
    assert columns["s"] == 0
    assert columns["a"] == columns["b"] == 1
    assert columns["t"] == 2
    # Unreachable nodes are parked past the targets rather than dropped.
    assert columns["orphan"] == 3


def test_a_shallow_target_is_still_drawn_rightmost():
    """Without pinning, a target two hops in would land mid-picture."""
    net = parse_network(
        {
            "name": "t",
            "nodes": [{"id": n} for n in ("s", "t", "x", "y", "z")],
            "entry": ["s"],
            "targets": ["t"],
            "edges": [
                {"from": "s", "to": "t", "difficulty": 1},
                {"from": "s", "to": "x", "difficulty": 1},
                {"from": "x", "to": "y", "difficulty": 1},
                {"from": "y", "to": "z", "difficulty": 1},
            ],
        }
    )
    columns = node_columns(net)
    assert columns["z"] == 3
    assert columns["t"] == 4, "the target must sit past every reachable non-target"


def test_positions_are_deterministic():
    net = diamond()
    assert layered_positions(net) == layered_positions(net)


def test_a_column_is_centred_vertically():
    positions = layered_positions(diamond())
    assert positions["a"][1] == -positions["b"][1]


def test_barycentre_ordering_beats_id_ordering():
    """A node should sit near whatever points at it, not in id order.

    The ids are chosen so the two orderings disagree. Column 1 has no signal
    to go on, so it falls back to id order: 'aaa' above 'bbb'. Column 1 then
    gives column 2 a signal, and 'zzz' (child of 'aaa') must be placed above
    'mmm' (child of 'bbb') even though 'mmm' sorts first. Ordering column 2
    by id instead puts each child opposite its parent and crosses both edges.
    """
    net = parse_network(
        {
            "name": "t",
            "nodes": [{"id": n} for n in ("s", "aaa", "bbb", "zzz", "mmm", "t")],
            "entry": ["s"],
            "targets": ["t"],
            "edges": [
                {"from": "s", "to": "aaa", "difficulty": 1},
                {"from": "s", "to": "bbb", "difficulty": 1},
                {"from": "aaa", "to": "zzz", "difficulty": 1},
                {"from": "bbb", "to": "mmm", "difficulty": 1},
                {"from": "zzz", "to": "t", "difficulty": 1},
                {"from": "mmm", "to": "t", "difficulty": 1},
            ],
        }
    )
    positions = layered_positions(net)
    assert positions["aaa"][1] > positions["bbb"][1], "column 1 falls back to id order"
    assert positions["zzz"][1] > positions["mmm"][1], (
        "column 2 must follow its predecessors, not the alphabet"
    )


def test_node_roles_identify_entries_targets_and_orphans():
    roles = node_roles(diamond())
    assert roles["s"].is_entry and not roles["s"].is_target
    assert roles["t"].is_target
    assert roles["a"].reachable
    assert not roles["orphan"].reachable
    # Every role must resolve to a colour, with no two categories identical.
    assert len({roles[n].fill for n in ("s", "t", "a", "orphan")}) == 4


def test_edge_role_encodes_cut_above_path():
    assert EdgeRole(in_cut=True, on_cheapest=False).colour == CUT_COLOUR
    assert EdgeRole(in_cut=False, on_cheapest=True).colour == PATH_COLOUR
    assert EdgeRole(in_cut=False, on_cheapest=False).colour == EDGE_COLOUR
    both = EdgeRole(in_cut=True, on_cheapest=True)
    assert both.is_both and both.colour == CUT_COLOUR
    assert both.width > EdgeRole(in_cut=False, on_cheapest=True).width


# ---------------------------------------------------------------------------
# DOT
# ---------------------------------------------------------------------------


def test_dot_contains_every_node_and_edge():
    source = to_dot(diamond(), **highlighted(diamond()))
    for node_id in ("s", "a", "b", "t", "orphan"):
        assert f'"{node_id}"' in source
    assert '"s" -> "a"' in source
    assert '"b" -> "t"' in source


def test_dot_marks_the_cut_red_and_thick():
    net = diamond()
    source = to_dot(net, **highlighted(net))
    cut_line = next(
        line for line in source.splitlines() if '"s" -> "b"' in line
    )  # Mail filtering is in the cut
    assert CUT_COLOUR in cut_line
    assert "penwidth=\"3.5\"" in cut_line


def test_dot_draws_a_both_edge_with_two_colours():
    """An edge on the cheapest path and in the cut must show both facts."""
    net = diamond()
    source = to_dot(net, **highlighted(net))
    line = next(l for l in source.splitlines() if '"a" -> "t"' in l)
    assert f"{CUT_COLOUR}:{PATH_COLOUR}" in line


def test_dot_labels_edges_with_difficulty():
    source = to_dot(diamond(), **highlighted(diamond()))
    line = next(l for l in source.splitlines() if '"b" -> "t"' in l)
    assert 'label="5"' in line


def test_dot_pins_entries_and_targets():
    source = to_dot(diamond(), **highlighted(diamond()))
    assert '{ rank=min; "s"; }' in source
    assert '{ rank=max; "t"; }' in source


def test_dot_marks_unreachable_nodes():
    source = to_dot(diamond(), **highlighted(diamond()))
    line = next(l for l in source.splitlines() if l.strip().startswith('"orphan"'))
    assert "dashed" in line
    assert "not reachable" in line


def test_dot_has_a_legend():
    source = to_dot(diamond(), **highlighted(diamond()))
    assert "cluster_legend" in source
    assert "in the minimum fix set" in source
    assert "on the cheapest attack path" in source


def test_dot_title_uses_a_real_newline_escape():
    """\\n must reach Graphviz as an escape, not as literal backslash-n."""
    source = to_dot(diamond(), **highlighted(diamond()))
    title = next(l for l in source.splitlines() if l.strip().startswith("label="))
    assert "\\n" in title
    assert "\\\\n" not in title


def test_dot_escapes_awkward_identifiers():
    net = parse_network(
        {
            "name": 'quote " and backslash \\ network',
            "nodes": [{"id": 'we"ird'}, {"id": "back\\slash"}],
            "entry": ['we"ird'],
            "targets": ["back\\slash"],
            "edges": [{"from": 'we"ird', "to": "back\\slash", "difficulty": 2}],
        }
    )
    source = to_dot(net)
    assert '"we\\"ird"' in source
    assert '"back\\\\slash"' in source
    # Every quote in the file must be either a delimiter or escaped, so the
    # count of unescaped quotes stays even on every line.
    for line in source.splitlines():
        unescaped = len(line.replace('\\"', "")) - len(
            line.replace('\\"', "").replace('"', "")
        )
        assert unescaped % 2 == 0, line


def test_dot_handles_an_unreachable_target():
    net = parse_network(
        {
            "name": "safe",
            "nodes": [{"id": "a"}, {"id": "b"}, {"id": "c"}],
            "entry": ["a"],
            "targets": ["c"],
            "edges": [{"from": "a", "to": "b", "difficulty": 2}],
        }
    )
    source = to_dot(net, **highlighted(net))
    assert "no target is reachable" in source


def test_write_dot_round_trips(tmp_path):
    path = write_dot(tmp_path / "n.dot", to_dot(diamond()))
    assert path.read_text(encoding="utf-8").startswith("digraph chokepoint {")


@pytest.mark.parametrize("seed", range(25))
def test_dot_generation_never_crashes(seed):
    net = random_network(seed, n_nodes=12, n_edges=28, n_entry=2, n_targets=2)
    assert to_dot(net, **highlighted(net)).endswith("}\n")


# ---------------------------------------------------------------------------
# Invoking Graphviz
# ---------------------------------------------------------------------------


def test_graphviz_binary_is_a_path_or_none():
    found = graphviz_binary()
    assert found is None or isinstance(found, str)


def test_missing_graphviz_explains_how_to_install_it(tmp_path, monkeypatch):
    monkeypatch.setattr("chokepoint.render_dot.shutil.which", lambda _: None)
    with pytest.raises(RenderUnavailable) as exc:
        render_with_graphviz(tmp_path / "n.dot", tmp_path / "n.png")
    assert "brew install graphviz" in str(exc.value)
    assert GRAPHVIZ_HINT in str(exc.value)


def test_graphviz_failure_is_reported(tmp_path, monkeypatch):
    monkeypatch.setattr("chokepoint.render_dot.shutil.which", lambda _: "/usr/bin/dot")

    def failing(*args, **kwargs):
        return subprocess.CompletedProcess(args, 1, "", "syntax error in line 3")

    monkeypatch.setattr("chokepoint.render_dot.subprocess.run", failing)
    with pytest.raises(RenderUnavailable, match="syntax error in line 3"):
        render_with_graphviz(tmp_path / "n.dot", tmp_path / "n.png")


def test_graphviz_success_returns_the_image_path(tmp_path, monkeypatch):
    monkeypatch.setattr("chokepoint.render_dot.shutil.which", lambda _: "/usr/bin/dot")
    recorded = {}

    def succeeding(command, **kwargs):
        recorded["command"] = command
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr("chokepoint.render_dot.subprocess.run", succeeding)
    image = tmp_path / "n.png"
    assert render_with_graphviz(tmp_path / "n.dot", image) == image
    # A fixed argument list and no shell.
    assert recorded["command"][0] == "/usr/bin/dot"
    assert "-Tpng" in recorded["command"]


# ---------------------------------------------------------------------------
# The matplotlib fallback
# ---------------------------------------------------------------------------


def test_render_png_writes_a_real_png(tmp_path):
    net = diamond()
    path = render_png(net, tmp_path / "n.png", **highlighted(net))
    data = path.read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    assert len(data) > 5_000, "suspiciously small image"


def test_render_png_handles_an_unreachable_target(tmp_path):
    net = parse_network(
        {
            "name": "safe",
            "nodes": [{"id": "a"}, {"id": "b"}, {"id": "c"}],
            "entry": ["a"],
            "targets": ["c"],
            "edges": [{"from": "a", "to": "b", "difficulty": 2}],
        }
    )
    assert render_png(net, tmp_path / "n.png", **highlighted(net)).exists()


def test_render_png_refuses_a_graph_too_big_to_read(tmp_path):
    net = random_network(1, n_nodes=MAX_NODES_FOR_PICTURE + 5, n_edges=120)
    with pytest.raises(RenderUnavailable) as exc:
        render_png(net, tmp_path / "n.png")
    message = str(exc.value)
    assert "dot file was still written" in message
    assert "Graphviz" in message


def test_missing_matplotlib_is_explained(tmp_path, monkeypatch):
    """matplotlib is an optional extra, so its absence must not be a crash."""
    monkeypatch.setitem(sys.modules, "matplotlib", None)
    with pytest.raises(RenderUnavailable) as exc:
        render_png(diamond(), tmp_path / "n.png")
    assert "matplotlib is not installed" in str(exc.value)
    assert "chokepoint[viz]" in str(exc.value)


def test_parallel_edges_get_different_curvatures():
    """Otherwise one attack route is drawn exactly on top of another."""
    net = parse_network(
        {
            "name": "t",
            "nodes": [{"id": "a"}, {"id": "b"}],
            "entry": ["a"],
            "targets": ["b"],
            "edges": [
                {"from": "a", "to": "b", "difficulty": 2},
                {"from": "a", "to": "b", "difficulty": 5},
                {"from": "a", "to": "b", "difficulty": 7},
            ],
        }
    )
    rads = set(_curvatures(net).values())
    assert len(rads) == 3


def test_opposite_directions_get_different_curvatures():
    """a->b and b->a are distinct edges with distinct fixes."""
    net = parse_network(
        {
            "name": "t",
            "nodes": [{"id": "a"}, {"id": "b"}],
            "entry": ["a"],
            "targets": ["b"],
            "edges": [
                {"from": "a", "to": "b", "difficulty": 2},
                {"from": "b", "to": "a", "difficulty": 5},
            ],
        }
    )
    rads = list(_curvatures(net).values())
    assert rads[0] != rads[1]


def test_a_lone_edge_is_drawn_straight():
    net = parse_network(
        {
            "name": "t",
            "nodes": [{"id": "a"}, {"id": "b"}],
            "entry": ["a"],
            "targets": ["b"],
            "edges": [{"from": "a", "to": "b", "difficulty": 2}],
        }
    )
    assert abs(next(iter(_curvatures(net).values()))) < 0.01


@pytest.mark.parametrize("seed", range(12))
def test_rendering_never_crashes_on_random_graphs(seed, tmp_path):
    net = random_network(seed, n_nodes=10, n_edges=24, n_entry=2, n_targets=2)
    assert render_png(net, tmp_path / f"{seed}.png", **highlighted(net)).exists()
