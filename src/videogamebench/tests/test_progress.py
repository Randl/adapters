import json
from pathlib import Path

import pytest


@pytest.fixture
def session(tmp_path, monkeypatch):
    runtime = Path(__file__).parents[1] / "src/videogamebench/runtime"
    monkeypatch.syspath_prepend(str(runtime))
    from videogamebench.runtime.session import Session

    root = tmp_path / "game"
    root.mkdir()
    (root / "manifest.json").write_text(
        json.dumps(
            {
                "game": "test_game",
                "checkpoint_count": 2,
                "settings": {"record_video": False, "max_steps": 100},
            }
        )
    )
    return Session(root, tmp_path / "state")


def test_private_score_logs_and_throttling(session, capsys):
    session.controller = "manual"
    session.log_progress("started", force=True)
    session.log_progress()  # The immediate periodic update is suppressed.
    session.steps = 15
    session.checkpoint_index = 2
    session.completed = True
    session.log_progress("checkpoint", force=True)
    session.error = "emulator failed"
    session.log_progress("finished", force=True, status="infrastructure_error")
    records = [
        json.loads(line)
        for line in (session.state_dir / "progress.jsonl").read_text().splitlines()
    ]
    assert [r["event"] for r in records] == ["started", "checkpoint", "finished"]
    assert [r["score"] for r in records] == [0, 1, None]
    assert records[1]["steps"] == 15
    assert records[1]["checkpoint_index"] == 2
    assert records[2]["error"] == "emulator failed"
    assert len(capsys.readouterr().out.splitlines()) == 3
    assert not {"score", "checkpoint_index", "completion"} & session.status().keys()


def test_unscored_game_and_disabled_periodic_logs(session):
    session.log_interval_sec = 0
    session.manifest["checkpoint_count"] = 0
    session.log_progress()
    assert not (session.state_dir / "progress.jsonl").exists()
    session.log_progress("finished", force=True, status="stopped")
    result = json.loads((session.state_dir / "progress.jsonl").read_text())
    assert result["score"] is None
    assert result["status"] == "stopped"


def test_replay_progress_preserves_inputs(tmp_path, monkeypatch, capsys):
    import importlib.util
    import io
    import sys

    path = (
        Path(__file__).parents[1]
        / "src/videogamebench/task-template/environment/play.py"
    )
    spec = importlib.util.spec_from_file_location("replay_progress_test", path)
    assert spec is not None and spec.loader is not None
    client = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(client)
    trace = tmp_path / "actions.json"
    trace.write_text(
        json.dumps({"actions": [{"action": None}, {"action": {"UP": True}}]})
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            str(path),
            "--replay",
            str(trace),
            "--screen",
            str(tmp_path / "screen.png"),
            "--progress-interval",
            "0.000001",
        ],
    )
    received = []

    def urlopen(request, timeout):
        if request.full_url.endswith("/action"):
            received.append(json.loads(request.data))
        if request.full_url.endswith("/screen"):
            return io.BytesIO(b"screen")
        return io.BytesIO(
            json.dumps(
                {"steps": len(received), "finished": False, "error": None}
            ).encode()
        )

    monkeypatch.setattr(client.urllib.request, "urlopen", urlopen)
    client.main()
    assert received == [None, {"UP": True}]
    output = capsys.readouterr().err
    assert "Replay 2/2 (100.0%)" in output
    assert "ETA" in output
    assert "separate verifier" in output
