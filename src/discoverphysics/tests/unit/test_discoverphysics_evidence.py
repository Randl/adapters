from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest
from harbor.publisher.packager import Packager

SCRIPT = Path(__file__).resolve().parents[2] / "scripts/bundle_evidence.py"
SPEC = importlib.util.spec_from_file_location("discoverphysics_evidence", SCRIPT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("Could not load evidence bundler")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


@pytest.mark.parametrize("tamper", [False, True])
def test_evidence_redacts_credentials_and_verifies_task_identity(tmp_path, tamper):
    tasks = tmp_path / "tasks"
    task = tasks / "circle__seed-0"
    task.mkdir(parents=True)
    (task / "task.toml").write_text('[metadata]\nupstream_commit = "pinned"\n')
    (task / "instruction.md").write_text("Discover a law.")
    digest, _ = Packager.compute_content_hash(task)
    job = tmp_path / "job"
    trial = job / "circle__seed-0__trial"
    (trial / "verifier").mkdir(parents=True)
    secret = 'test-credential-with-"quote\\and-backslash'
    config = {"verifier": {"env": {"ANTHROPIC_API_KEY": secret}}}
    (job / "config.json").write_text(json.dumps(config))
    (trial / "result.json").write_text(
        json.dumps(
            {
                "task_id": {"path": str(task)},
                "config": config,
                "message": secret,
            }
        )
    )
    (trial / "lock.json").write_text(
        json.dumps({"task": {"digest": f"sha256:{digest}"}})
    )
    (trial / "trial.log").write_text(f"provider error: {secret}")
    (trial / "verifier/reward.json").write_text(
        json.dumps(
            {
                "reward": 1,
                "world_index": 0,
                "seed": 0,
                "seed_pool_size": 2,
            }
        )
    )
    output = tmp_path / "bundle"
    if tamper:
        (task / "instruction.md").write_text("Changed after the run.")
        with pytest.raises(ValueError, match="does not match recorded digest"):
            MODULE.bundle(job, tasks, output)
        return

    MODULE.bundle(job, tasks, output)
    exported = json.loads(
        (output / "job/circle__seed-0__trial/result.json").read_text()
    )
    assert exported["config"]["verifier"]["env"]["ANTHROPIC_API_KEY"] == "[REDACTED]"
    assert exported["message"] == "[REDACTED]"
    assert (
        output / "job/circle__seed-0__trial/trial.log"
    ).read_text() == "provider error: [REDACTED]"
    assert Packager.compute_content_hash(output / "tasks/circle__seed-0")[0] == digest
    assert (
        json.loads((output / "recomputed-metrics.json").read_text())["trial_pass_rate"]
        == 1
    )
    checksums = json.loads((output / "sha256.json").read_text())
    assert all(
        Packager.compute_file_hash(output / path) == value
        for path, value in checksums.items()
    )
