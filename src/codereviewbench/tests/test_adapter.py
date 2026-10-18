import asyncio
import importlib.util
import json
import os
import tomllib
from pathlib import Path

import pytest

from codereviewbench.adapter import PACKAGE, CodeReviewBenchAdapter
from codereviewbench.metric import aggregate


@pytest.fixture
def upstream():
    value = os.environ.get("CODEREVIEWBENCH_SOURCE")
    if not value:
        pytest.skip("Set CODEREVIEWBENCH_SOURCE to the pinned upstream checkout")
    return Path(value)


@pytest.fixture
def generated(tmp_path, upstream):
    output = tmp_path / "tasks"
    CodeReviewBenchAdapter(output, source_dir=upstream).run()
    return output


def test_full_generation_determinism_and_isolation(generated, upstream):
    tasks = sorted(generated.iterdir())
    assert len(tasks) == 50
    names = [
        tomllib.loads((p / "task.toml").read_text())["task"]["name"] for p in tasks
    ]
    assert len(set(names)) == 50
    first = tasks[0]
    before = {
        str(p.relative_to(first)): p.read_bytes()
        for p in first.rglob("*")
        if p.is_file()
    }
    CodeReviewBenchAdapter(
        generated, source_dir=upstream, limit=1, overwrite=True
    ).run()
    assert before == {
        str(p.relative_to(first)): p.read_bytes()
        for p in first.rglob("*")
        if p.is_file()
    }
    assert not any(p.name == "problem.json" for p in (first / "environment").rglob("*"))
    assert (first / "tests/step3_judge_comments.py").read_bytes() == (
        upstream / "offline/code_review_benchmark/step3_judge_comments.py"
    ).read_bytes()


def test_manifest_and_unknown_ids(tmp_path):
    manifest = json.loads((PACKAGE / "prs.json").read_text())
    assert len(manifest) == len({r["id"] for r in manifest}) == 50
    assert all(len(r["base"]) == len(r["head"]) == 40 for r in manifest)
    with pytest.raises(ValueError):
        CodeReviewBenchAdapter(tmp_path, task_ids=["unknown"]).run()
    with pytest.raises(ValueError):
        CodeReviewBenchAdapter(tmp_path, limit=-1)


def verifier(generated, monkeypatch):
    task = min(generated.iterdir())
    monkeypatch.syspath_prepend(str(task / "tests"))
    spec = importlib.util.spec_from_file_location(
        "review_verify", task / "tests/verify.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_upstream_matching_profiles_dedup_and_failure(generated, monkeypatch):
    module = verifier(generated, monkeypatch)
    problem = {
        "url": "PR",
        "golden_comments": [
            {"comment": "bug", "category": "bug"},
            {"comment": "style", "category": "style"},
        ],
    }

    class Judge:
        async def match_comment(self, golden, candidate):
            return {"match": golden in candidate, "confidence": 0.9}

    class Dedup:
        async def dedup_candidates(self, candidates, prompt):
            return [[0, 1], [2], [3]]

    evaluation, rewards = asyncio.run(
        module.evaluate(
            problem, ["bug", "duplicate", "style", "noise"], Judge(), Dedup()
        )
    )
    assert rewards == {
        "strict_tp": 1,
        "strict_fp": 1,
        "strict_fn": 0,
        "core_tp": 1,
        "core_fp": 1,
        "core_fn": 0,
        "all_tp": 2,
        "all_fp": 1,
        "all_fn": 0,
    }
    assert evaluation["dedup_groups"] == [[0, 1], [2], [3]]

    class Broken:
        async def match_comment(self, golden, candidate):
            return {"error": "provider unavailable"}

    with pytest.raises(RuntimeError):
        asyncio.run(module.evaluate(problem, ["bug"], Broken()))
    _, empty = asyncio.run(module.evaluate(problem, []))
    assert empty["core_fn"] == 1 and empty["core_tp"] == 0


def test_micro_metric():
    rows = [
        {
            f"{profile}_{key}": value
            for profile in ("strict", "core", "all")
            for key, value in zip(("tp", "fp", "fn"), counts)
        }
        for counts in [(1, 0, 0), (0, 0, 9)]
    ]
    result = aggregate(rows)
    assert result["core_recall"] == 0.1
    assert result["core_f2"] == 5 / 41
    with pytest.raises(ValueError):
        aggregate([rows[0], None])
