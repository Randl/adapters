import io
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import imagehash
import pytest
from PIL import Image

from videogamebench.checkpoints import crop_box, generate, hash_ambiguities, safe_name


def test_invalid_plan_does_not_write_images(tmp_path):
    for value in ("../game", "game/name", "", "/absolute"):
        with pytest.raises(ValueError):
            safe_name(value)
    for crop in ((0, 0, 0, 1), (-0.1, 0, 1, 1), (0, 0, float("nan"), 1)):
        with pytest.raises(ValueError):
            crop_box(crop, (160, 144))
    assert crop_box((0.25, 0, 0.75, 1), (640, 360)) == (160, 0, 480, 360)


def test_extract_compare_and_detect_ambiguous_final(tmp_path, monkeypatch):
    frame = Image.new("RGB", (16, 8), "black")
    frame.paste("white", (0, 0, 4, 8))
    encoded = io.BytesIO()
    frame.save(encoded, format="PNG")
    reference = tmp_path / "upstream/configs/game/checkpoints/1.png"
    reference.parent.mkdir(parents=True)
    frame.crop((0, 0, 8, 8)).save(reference)
    videos = tmp_path / "videos"
    videos.mkdir()
    (videos / "video.video.mp4").write_bytes(b"fixture")
    monkeypatch.setattr(
        "videogamebench.checkpoints.subprocess.run",
        lambda command, **kwargs: SimpleNamespace(stdout=encoded.getvalue()),
    )
    entries: list[dict[str, Any]] = [
        {
            "profile": "expanded",
            "game": "game",
            "id": str(index),
            "video": "video",
            "timestamp_sec": index,
            "crop": [0, 0, 0.5, 1],
            "label": "milestone",
            "final": index == 2,
            "upstream_id": 1,
        }
        for index in (1, 2)
    ]
    plan = {
        "upstream_revision": "fixture",
        "videos": {"video": {}},
        "checkpoints": entries,
    }
    output = tmp_path / "output"
    report = generate(plan, videos, tmp_path / "upstream", output, "decoder")
    assert all(entry["comparison"]["distance"] == 0 for entry in report["checkpoints"])
    assert report["hash_ambiguities"][0]["includes_final"]
    assert report["hash_ambiguities"][0]["distance"] == 0
    with Image.open(output / "expanded/game/1.png") as image:
        assert image.size == (8, 8)
        assert (
            str(imagehash.average_hash(image))
            == report["checkpoints"][0]["average_hash"]
        )
    with pytest.raises(FileExistsError):
        generate(plan, videos, tmp_path / "upstream", output, "decoder")
    plan["videos"]["video"]["sha256"] = "not-the-video-digest"
    with pytest.raises(ValueError, match="Video content changed"):
        generate(plan, videos, tmp_path / "upstream", tmp_path / "changed", "decoder")
    assert not (tmp_path / "changed").exists()
    plan["videos"]["video"].pop("sha256")
    entries[0]["upstream_sha256"] = "not-the-reference-digest"
    with pytest.raises(ValueError, match="Published reference content changed"):
        generate(plan, videos, tmp_path / "upstream", tmp_path / "changed", "decoder")
    assert not (tmp_path / "changed").exists()


def test_hash_ambiguities_respect_game_profile_and_threshold():
    base = {
        "profile": "expanded",
        "game": "game",
        "id": "1",
        "average_hash": "0000000000000000",
    }
    entries: list[dict[str, Any]] = [
        base,
        {
            **base,
            "id": "2",
            "average_hash": "00000000000001ff",
            "threshold": 8,
            "final": True,
        },
    ]
    assert hash_ambiguities(entries) == []
    entries[1]["threshold"] = 9
    assert hash_ambiguities(entries)[0]["distance"] == 9
    entries[1]["profile"] = "reconstructed-upstream"
    assert hash_ambiguities(entries) == []


def test_curated_plan_coverage_and_provenance():
    directory = Path(__file__).resolve().parents[1] / "checkpoints"
    plan = json.loads((directory / "plan.json").read_text())
    sources = json.loads((directory / "sources.json").read_text())
    expanded = [e for e in plan["checkpoints"] if e["profile"] == "expanded"]
    assert {e["game"] for e in expanded} == set(sources["games"])
    assert sum(e["definition"] == "paper" for e in expanded) == 166
    for game in sources["games"]:
        entries = [e for e in expanded if e["game"] == game]
        assert sum(e["final"] for e in entries) == 1
        assert entries[-1]["final"]
        times = [e["walkthrough_elapsed_sec"] for e in entries]
        assert times == sorted(times), game
        if sources["games"][game]["split"] == "dev":
            assert len(entries) > 1
    for entry in plan["checkpoints"]:
        video = plan["videos"][entry["video"]]
        assert len(video["sha256"]) == 64
        assert 0 <= entry["timestamp_sec"] <= video["duration"]
        assert entry["emulator_validation"] == "pending"
        if "upstream_id" in entry:
            assert len(entry["upstream_sha256"]) == 64
