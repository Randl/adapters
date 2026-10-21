import importlib.util
import io
import json
import sys
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from videogamebench.runtime import recorder


def test_restart_preserves_separate_attempts(tmp_path):
    cache = tmp_path / ".boot-cache"
    cache.mkdir()
    (cache / "initial.state").write_bytes(b"initial state")
    saved = []
    for steps in (25, 0, 12):
        (tmp_path / "actions.json").write_text(json.dumps({"steps": steps}))
        (tmp_path / "gameplay.mp4").write_bytes(bytes([steps]))
        (tmp_path / "logs").mkdir()
        (tmp_path / "logs/game.log").write_text(str(steps))
        saved.append(recorder.archive_attempt(tmp_path))
        assert set(tmp_path.iterdir()) == {tmp_path / "attempts", cache}
        assert (cache / "initial.state").read_bytes() == b"initial state"
    assert len(set(saved)) == 3
    for path, steps in zip(saved, (25, 0, 12), strict=True):
        assert json.loads((path / "actions.json").read_text())["steps"] == steps
        assert (path / "gameplay.mp4").read_bytes() == bytes([steps])
        assert (path / "logs/game.log").read_text() == str(steps)


@pytest.mark.parametrize(
    "enabled,controller,emulator,mode",
    [
        (False, "manual", "gba", "lite"),
        (True, "vgagent", "gba", "lite"),
        (True, "manual", "dos", "lite"),
        (True, "manual", "gba", "realtime"),
    ],
)
@pytest.mark.parametrize("endpoint", ["/restart", "/rewind"])
def test_benchmark_restart_is_rejected(
    monkeypatch, enabled, controller, emulator, mode, endpoint
):
    monkeypatch.setitem(sys.modules, "recorder", recorder)
    monkeypatch.setitem(sys.modules, "session", SimpleNamespace(Session=None))
    path = Path(recorder.__file__).with_name("server.py")
    spec = importlib.util.spec_from_file_location("recorder_test_server", path)
    assert spec is not None and spec.loader is not None
    server = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(server)
    monkeypatch.setattr(
        server, "ARGS", SimpleNamespace(allow_restart=enabled), raising=False
    )
    # There is deliberately no finish method: rejection must not change a run.
    monkeypatch.setattr(
        server,
        "SESSION",
        SimpleNamespace(
            controller=controller,
            manifest={"emulator": emulator},
            settings={"mode": mode},
        ),
        raising=False,
    )
    monkeypatch.setattr(server, "LOCK", threading.Lock(), raising=False)
    handler = server.Handler.__new__(server.Handler)
    handler.path = endpoint
    handler.headers = {"Content-Length": "2"}
    handler.rfile = io.BytesIO(b"{}")
    errors = []
    handler.send_error = lambda code, text: errors.append(code)
    handler.do_POST()
    assert errors == [403]


def test_rewind_keeps_prefix_and_rejects_invalid_counts():
    trace = [{"action": {"START": True}}, {"action": None}, {"action": {"RIGHT": True}}]
    assert recorder.rewind_prefix(trace, 1) == [{"START": True}, None]
    assert recorder.rewind_prefix(trace, 3) == []
    assert len(trace) == 3
    for count in (0, -1, 4, 1.5, True, None):
        with pytest.raises(ValueError):
            recorder.rewind_prefix(trace, count)  # ty: ignore[invalid-argument-type]


def test_snapshots_follow_exact_prefix_and_skip_corruption(tmp_path):
    from videogamebench.runtime.snapshots import SnapshotStore

    actions = [None, {"RIGHT": True}, {"A": True, "RIGHT": True}, None]
    store = SnapshotStore(tmp_path, "identity", "2.6.1", 2)
    store.advance(actions[:2])
    store.save(b"state2", b"screen2", {"checkpoint_index": 1})
    store.advance(actions[2:])
    store.save(b"state4", b"screen4", {"checkpoint_index": 2})
    assert store.nearest(actions)[0]["steps"] == 4
    assert store.nearest(actions[:3])[1] == b"state2"
    assert store.nearest(actions[:2] + [{"LEFT": True}, None])[1] == b"state2"
    assert store.nearest([{"START": True}]) is None
    assert SnapshotStore(tmp_path, "different-rom", "2.6.1").nearest(actions) is None
    assert SnapshotStore(tmp_path, "identity", "other-version").nearest(actions) is None
    (tmp_path / f"{store.digest}.snapshot").write_bytes(b"truncated")
    assert store.nearest(actions)[1] == b"state2"


def test_snapshot_cache_survives_archival(tmp_path):
    cache = tmp_path / ".snapshots"
    cache.mkdir()
    (cache / "sample.snapshot").write_bytes(b"state")
    (tmp_path / "actions.json").write_text("{}")
    archive = recorder.archive_attempt(tmp_path)
    assert (archive / "actions.json").exists()
    assert (cache / "sample.snapshot").read_bytes() == b"state"
