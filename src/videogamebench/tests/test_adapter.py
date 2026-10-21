import importlib.util
import json
import os
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest
import yaml

from videogamebench.adapter import VideoGameBenchAdapter, read_constants
from videogamebench.experiment import prepare, summarize
from videogamebench.settings import DEV_GAMES, TEST_GAMES, Settings


@pytest.fixture(scope="module")
def source():
    path = os.environ.get("VIDEOGAMEBENCH_SOURCE")
    if not path:
        pytest.skip("Set VIDEOGAMEBENCH_SOURCE to the pinned upstream checkout")
    return Path(path)


@pytest.fixture(scope="module")
def generated(tmp_path_factory, source):
    root = tmp_path_factory.mktemp("videogamebench")
    roms = root / "roms"
    roms.mkdir()
    for name in read_constants(source)["ROM_FILE_MAP"].values():
        (roms / name).write_bytes(b"generation fixture, not a licensed game")
    output = root / "tasks"
    VideoGameBenchAdapter(output, rom_dir=roms, source_dir=source).run()
    return output, roms


def test_all_games_and_harbor_schema(generated):
    from harbor.models.task.config import TaskConfig

    output, _ = generated
    tasks = sorted(output.iterdir())
    assert len(tasks) == 20
    scored = 0
    for task in tasks:
        config = TaskConfig.model_validate_toml((task / "task.toml").read_text())
        assert config.verifier.environment_mode == "separate"
        assert config.verifier.collect[0].service == "game"
        assert not isinstance(config.artifacts[0], str)
        assert config.artifacts[0].service == "game"
        manifest = json.loads((task / "tests/manifest.json").read_text())
        scored += bool(manifest["checkpoint_count"])
        assert (task / "environment/game/upstream/main.py").is_file()
        assert (
            "game"
            not in (task / "environment/Dockerfile")
            .read_text()
            .split("COPY")[1]
            .splitlines()[0]
            .split()[0]
        )
        assert not (task / "environment/checkpoints").exists()
        assert (task / "tests/result.key").read_text() == (
            task / "environment/game/result.key"
        ).read_text()
    assert scored == 8


def test_filter_overwrite_and_parameters(tmp_path, generated, source):
    _, roms = generated
    output = tmp_path / "tasks"
    settings = Settings(mode="realtime", max_steps=42, threshold=3, action_frames=7)
    adapter = VideoGameBenchAdapter(
        output, roms, source, task_ids=["doom2", "zelda"], settings=settings
    )
    adapter.run()
    task = output / "videogamebench-doom2-realtime"
    manifest = json.loads((task / "tests/manifest.json").read_text())
    assert manifest["settings"]["threshold"] == 3
    assert manifest["settings"]["max_steps"] == 42
    before = (task / "tests/result.key").read_text()
    adapter.run()
    assert (task / "tests/result.key").read_text() == before
    adapter.overwrite = True
    adapter.run()
    assert (task / "tests/result.key").read_text() != before
    assert (
        json.loads((task / "tests/manifest.json").read_text())["identity"]
        == manifest["identity"]
    )
    with pytest.raises(ValueError):
        VideoGameBenchAdapter(output, task_ids=["missing"]).run()
    with pytest.raises(FileNotFoundError):
        VideoGameBenchAdapter(
            tmp_path / "missing", source_dir=source, task_ids=["kirby"]
        ).run()
    assert len(VideoGameBenchAdapter(output, split="parity").selected_games()) == 7
    assert len(VideoGameBenchAdapter(output, split="dev").selected_games()) == 13
    assert VideoGameBenchAdapter(output, limit=0).selected_games() == []


@pytest.mark.parametrize(
    "kwargs",
    [
        {"max_steps": 0},
        {"temperature": float("nan")},
        {"mode": "fake"},
        {"max_context_size": -1},
        {"threshold": -1},
        {"typo": 1},
    ],
)
def test_settings_validation(kwargs):
    with pytest.raises(ValueError):
        Settings.from_dict(kwargs)


def test_evidence_rejects_tampering_and_wrong_task():
    path = Path(__file__).parents[1] / "src/videogamebench/runtime/evidence.py"
    spec = importlib.util.spec_from_file_location("evidence_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    payload = {"identity": "one", "completion": 0}
    signed = module.sign(payload, "secret")
    assert module.verify(signed, "secret", "one") == payload
    with pytest.raises(ValueError):
        module.verify(signed, "secret", "two")
    signed["payload"]["completion"] = 1
    with pytest.raises(ValueError):
        module.verify(signed, "secret", "one")


def test_prepare_jobs_and_missing_results(tmp_path, generated, source):
    from harbor.models.job.config import JobConfig

    _, roms = generated
    dataset = tmp_path / "parity"
    VideoGameBenchAdapter(dataset, roms, source, split="parity").run()
    output = tmp_path / "experiment"
    prepare(dataset, output, 3, "parity", 1, "openai/gpt-5")
    for path in output.glob("*.yaml"):
        JobConfig.model_validate(yaml.safe_load(path.read_text()))
    plan = json.loads((output / "plan.json").read_text())
    assert len(plan["attempts"]) == 42
    assert plan["budget_usd_nominal"] == 1260
    with pytest.raises(ValueError, match="Missing tasks"):
        summarize(output / "plan.json", output / "summary.json")


@pytest.mark.parametrize("game", ["kirby", "doom2"])
@pytest.mark.parametrize("mode", ["lite", "realtime"])
def test_upstream_loop_and_prompt_equivalence(tmp_path, generated, source, game, mode):
    _, roms = generated
    dataset = tmp_path / "probe"
    VideoGameBenchAdapter(
        dataset,
        roms,
        source,
        task_ids=[game],
        settings=Settings(mode=mode, max_steps=3),
    ).run()
    root = next(dataset.iterdir()) / "environment/game"
    outputs = []
    for side in ("baseline", "instrumented"):
        output = tmp_path / f"{side}.json"
        subprocess.run(
            [
                sys.executable,
                str(Path(__file__).with_name("harness_probe.py")),
                str(root),
                side,
                str(output),
            ],
            check=True,
            timeout=90,
            capture_output=True,
        )
        outputs.append(json.loads(output.read_text()))
    assert outputs[0]["requests"] == outputs[1]["requests"]
    assert outputs[0]["actions"] == outputs[1]["actions"]
    assert outputs[1]["result"]["status"] == "completed"
    assert outputs[1]["result"]["steps"] == 3


def test_readme_and_metadata_counts():
    root = Path(__file__).parents[1]
    data = json.loads((root / "adapter_metadata.json").read_text())[0]
    assert sum(x["size"] for x in data["original_benchmark"]) == len(
        TEST_GAMES + DEV_GAMES
    )
    assert (
        tomllib.loads((root / "pyproject.toml").read_text())["project"]["name"]
        == "harbor-videogamebench-adapter"
    )


def test_summary_statistics_and_signature(tmp_path, generated, source):
    from videogamebench.runtime.evidence import sign

    _, roms = generated
    dataset = tmp_path / "dataset"
    VideoGameBenchAdapter(dataset, roms, source, split="parity").run()
    output = tmp_path / "runs"
    prepare(dataset, output, 3, "parity", 1, "openai/gpt-5")
    tasks = sorted(dataset.iterdir())
    for side in ("original", "harbor"):
        for run in range(1, 4):
            for index, task in enumerate(tasks):
                manifest = json.loads((task / "tests/manifest.json").read_text())
                payload = {
                    "task_id": task.name,
                    "identity": manifest["identity"],
                    "model": manifest["settings"]["model"],
                    "status": "completed",
                    "checkpoint_count": manifest["checkpoint_count"],
                    "completion": int(index < run),
                }
                path = output / side / f"run-{run}" / task.name / "result.json"
                path.parent.mkdir(parents=True)
                path.write_text(
                    json.dumps(sign(payload, (task / "tests/result.key").read_text()))
                )
    summary = output / "summary.json"
    summarize(output / "plan.json", summary)
    result = json.loads(summary.read_text())
    assert result["ranges_overlap"]
    assert result["sides"]["original"]["mean"] == pytest.approx(2 / 7)
    assert result["sides"]["original"]["sample_sem"] == pytest.approx(1 / (7 * 3**0.5))
    # Never include a forged completion in the experiment aggregate.
    path = next((output / "original").rglob("result.json"))
    record = json.loads(path.read_text())
    record["payload"]["completion"] = 99
    path.write_text(json.dumps(record))
    with pytest.raises(ValueError, match="Untrusted"):
        summarize(output / "plan.json", summary)


def test_video_without_display(tmp_path, monkeypatch):
    import io
    import time

    import cv2
    from PIL import Image

    from videogamebench.runtime.video import ObservationVideo

    monkeypatch.delenv("DISPLAY", raising=False)
    recorder = ObservationVideo(tmp_path, fps=20)
    buffer = io.BytesIO()
    Image.new("RGB", (160, 144), "red").save(buffer, format="PNG")
    recorder.update(buffer.getvalue())
    time.sleep(0.15)
    recorder.close()
    assert recorder.error is None
    capture = cv2.VideoCapture(str(tmp_path / "gameplay.mp4"))
    ok, frame = capture.read()
    capture.release()
    assert ok and frame.shape == (144, 160, 3)
    assert (tmp_path / "video-timestamps.jsonl").read_text().strip()
