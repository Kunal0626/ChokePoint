"""Tests for the command-line interface, including its exit codes."""

from __future__ import annotations

import json

import pytest

from chokepoint.cli import main

DEMO = {
    "name": "demo",
    "nodes": [
        {"id": "internet", "label": "Internet", "type": "external"},
        {"id": "web", "label": "Web server", "type": "server"},
        {"id": "db", "label": "Production database", "type": "database"},
    ],
    "entry": ["internet"],
    "targets": ["db"],
    "edges": [
        {"from": "internet", "to": "web", "difficulty": 1, "technique": "unpatched web app",
         "fix": {"name": "Patch web app", "cost": 5}},
        {"from": "web", "to": "db", "difficulty": 2, "technique": "reused DB credentials",
         "fix": {"name": "Rotate DB credentials", "cost": 1}},
    ],
}


@pytest.fixture
def model(tmp_path):
    path = tmp_path / "net.json"
    path.write_text(json.dumps(DEMO), encoding="utf-8")
    return str(path)


# ---------------------------------------------------------------------------
# analyze
# ---------------------------------------------------------------------------


def test_analyze_succeeds(model, capsys):
    assert main(["analyze", model]) == 0
    out = capsys.readouterr().out
    assert "ChokePoint: demo" in out
    assert "1. ATTACK PATHS" in out


def test_analyze_json_is_valid_and_on_stdout(model, capsys):
    assert main(["analyze", model, "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["network"] == "demo"
    assert payload["cheapest_attack_cost"] == 3


def test_analyze_honours_k(model, capsys):
    assert main(["analyze", model, "--k", "1", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["k"] == 1


@pytest.mark.parametrize("mode", ["fixcost", "unit", "inverse-difficulty"])
def test_analyze_accepts_every_capacity_mode(model, capsys, mode):
    assert main(["analyze", model, "--capacity", mode, "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["capacity_mode"] == mode


def test_out_writes_both_renderings(model, tmp_path, capsys):
    out_dir = tmp_path / "artifacts"
    assert main(["analyze", model, "--out", str(out_dir)]) == 0
    assert (out_dir / "report.txt").exists()
    assert (out_dir / "report.json").exists()
    payload = json.loads((out_dir / "report.json").read_text(encoding="utf-8"))
    assert payload["network"] == "demo"


def test_out_creates_missing_directories(model, tmp_path):
    nested = tmp_path / "a" / "b" / "c"
    assert main(["analyze", model, "--out", str(nested)]) == 0
    assert (nested / "report.txt").exists()


def test_out_keeps_stdout_pure_json(model, tmp_path, capsys):
    """So `--json --out DIR | jq` still works."""
    assert main(["analyze", model, "--json", "--out", str(tmp_path / "o")]) == 0
    captured = capsys.readouterr()
    json.loads(captured.out)  # must not raise
    assert "wrote" in captured.err


# ---------------------------------------------------------------------------
# whatif
# ---------------------------------------------------------------------------


def test_whatif_succeeds(model, capsys):
    assert main(["whatif", model, "--apply", "Rotate DB credentials"]) == 0
    out = capsys.readouterr().out
    assert "ChokePoint what-if: demo" in out
    assert "no route remains" in out


def test_whatif_json(model, capsys):
    assert main(["whatif", model, "--apply", "Patch web app", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["applied_fix"]["name"] == "Patch web app"
    assert payload["disconnects"] is True


def test_whatif_requires_apply(model):
    with pytest.raises(SystemExit) as exc:
        main(["whatif", model])
    assert exc.value.code == 2


# ---------------------------------------------------------------------------
# Error handling and exit codes
# ---------------------------------------------------------------------------


def test_unknown_fix_exits_2_with_a_suggestion(model, capsys):
    assert main(["whatif", model, "--apply", "Patch web ap"]) == 2
    assert "did you mean 'Patch web app'" in capsys.readouterr().err


def test_missing_file_exits_2(tmp_path, capsys):
    assert main(["analyze", str(tmp_path / "nope.json")]) == 2
    assert "not found" in capsys.readouterr().err


def test_malformed_json_exits_2(tmp_path, capsys):
    path = tmp_path / "bad.json"
    path.write_text("{not json", encoding="utf-8")
    assert main(["analyze", str(path)]) == 2
    assert "not valid JSON" in capsys.readouterr().err


def test_invalid_model_exits_2_and_lists_problems(tmp_path, capsys):
    broken = dict(DEMO)
    broken["edges"] = [{"from": "internet", "to": "ghost", "difficulty": 0}]
    path = tmp_path / "broken.json"
    path.write_text(json.dumps(broken), encoding="utf-8")
    assert main(["analyze", str(path)]) == 2
    err = capsys.readouterr().err
    assert "unknown node id 'ghost'" in err
    assert "from 1 to 10" in err


def test_directory_instead_of_file_exits_2(tmp_path, capsys):
    assert main(["analyze", str(tmp_path)]) == 2
    assert "is a directory" in capsys.readouterr().err


@pytest.mark.parametrize("k", ["0", "-1", "abc"])
def test_bad_k_is_rejected_by_the_parser(model, k):
    with pytest.raises(SystemExit) as exc:
        main(["analyze", model, "--k", k])
    assert exc.value.code == 2


def test_unknown_capacity_mode_is_rejected_by_the_parser(model):
    with pytest.raises(SystemExit) as exc:
        main(["analyze", model, "--capacity", "cheapest"])
    assert exc.value.code == 2


def test_no_subcommand_is_rejected():
    with pytest.raises(SystemExit) as exc:
        main([])
    assert exc.value.code == 2


def test_version_flag(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    assert "chokepoint" in capsys.readouterr().out


def test_self_check_failure_exits_3(model, capsys, monkeypatch):
    """Exit 3 is reserved for "this tool cannot verify its own output"."""
    import chokepoint.maxflow as maxflow_module

    monkeypatch.setattr(
        maxflow_module, "_reachable", lambda residual, source: set(residual.out)
    )
    assert main(["analyze", model]) == 3
    err = capsys.readouterr().err
    assert "self-check failed" in err
    assert "bug in ChokePoint" in err
