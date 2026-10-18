import importlib.util
import json
import os
import tomllib
from pathlib import Path

import pytest
from PIL import Image

from videogamebench.adapter import GAMES, VideoGameBenchAdapter


@pytest.fixture
def generated(tmp_path, monkeypatch):
    source = os.environ.get("VIDEOGAMEBENCH_SOURCE")
    if not source:
        pytest.skip("Set VIDEOGAMEBENCH_SOURCE to the pinned upstream checkout")
    roms = tmp_path / "roms"
    roms.mkdir()
    for name in GAMES.values():
        (roms / name).write_bytes(
            b"synthetic generation fixture, not an executable ROM"
        )
    output = tmp_path / "tasks"
    VideoGameBenchAdapter(output, rom_dir=roms, source_dir=Path(source)).run()
    return output


def test_generation_scope_and_sidecar(generated):
    tasks = sorted(generated.iterdir())
    assert len(tasks) == 4
    for task in tasks:
        config = tomllib.loads((task / "task.toml").read_text())
        assert config["verifier"]["environment_mode"] == "separate"
        dockerfile = (task / "environment/Dockerfile").read_text()
        assert "game.gb" not in dockerfile and "upstream" not in dockerfile
        assert (task / "environment/Dockerfile.game").exists()
        assert not (task / "environment/checkpoints").exists()
        compile((task / "tests/checkpoint.py").read_text(), "checkpoint.py", "exec")


def test_checkpoint_behavior_and_replay(generated, monkeypatch):
    task = next(generated.glob("*kirby*"))
    monkeypatch.syspath_prepend(str(task / "tests/upstream"))
    monkeypatch.syspath_prepend(str(task / "tests"))
    spec = importlib.util.spec_from_file_location("vg_verify", task / "tests/verify.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    from imagehash import average_hash as hash_image

    black = Image.new("RGB", (160, 144), "black")
    white = Image.new("RGB", (160, 144), "white")
    white.paste("black", (0, 0, 80, 144))
    checker = module.ReplayEvaluator(
        checkpoints=[hash_image(black), hash_image(white)], threshold=1
    )
    progress = module.Progress()
    # Preserve upstream's acceptance of jumping straight to the last checkpoint.
    assert checker._check_checkpoint_progress(white, progress)
    assert progress.index == 2
    assert not checker._check_checkpoint_progress(black, progress)
    events = []

    class Game:
        def no_op(self, frames):
            events.append(("noop", frames))
            return {"screen": white}, 0, False, {}

        def step(self, action, frames):
            events.append((action, frames))
            return {"screen": white}, 0, False, {}

    checker = module.ReplayEvaluator(checkpoints=[hash_image(white)], threshold=1)
    assert module.replay([None, {"A": True}], Game(), checker, module.Progress(), 15)
    assert events == [("noop", 15), ({"A": True}, 15)]
    path = task / "bad.json"
    for value in [[{"INVALID": True}], [{"A": 1}], "not a list"]:
        path.write_text(json.dumps(value))
        with pytest.raises(ValueError):
            module.load_actions(path, 15000)


def test_missing_assets_and_unknown_ids(tmp_path):
    with pytest.raises(FileNotFoundError):
        VideoGameBenchAdapter(tmp_path / "out", rom_dir=tmp_path).run()
    with pytest.raises(ValueError):
        VideoGameBenchAdapter(
            tmp_path / "out", rom_dir=tmp_path, task_ids=["doom2"]
        ).run()
    with pytest.raises(ValueError):
        VideoGameBenchAdapter(tmp_path / "out", rom_dir=tmp_path, limit=-1)
