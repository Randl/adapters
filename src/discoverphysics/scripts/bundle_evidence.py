"""Bundle a completed oracle job and its exact tasks without provider credentials.

Run with `uv run --extra harbor python scripts/bundle_evidence.py` from the adapter directory. Existing output
directories are rejected to avoid mixing evidence from different exports.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path
from typing import Any

from harbor.publisher.packager import Packager

ADAPTER_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = ADAPTER_DIR.parents[1]
SECRET_KEY = re.compile(
    r"api[_-]?key|(?:^|_)token$|authorization|password|secret", re.IGNORECASE
)
TOKEN = re.compile(r"\b(?:sk-[A-Za-z0-9_-]{16,}|hf_[A-Za-z0-9]{20,})\b")


def secret_values(value: Any) -> set[str]:
    values: set[str] = set()
    if isinstance(value, dict):
        for key, item in value.items():
            if SECRET_KEY.search(key) and isinstance(item, str) and item:
                values.add(item)
            values.update(secret_values(item))
    elif isinstance(value, list):
        for item in value:
            values.update(secret_values(item))
    return values


def redact(text: str, secrets: set[str]) -> str:
    for value in sorted(secrets, key=len, reverse=True):
        text = text.replace(value, "[REDACTED]")
    return TOKEN.sub("[REDACTED]", text).replace(str(REPO_ROOT), "<HARBOR_ROOT>")


def bundle(job_dir: Path, tasks_dir: Path, output_dir: Path) -> None:
    job_dir, tasks_dir, output_dir = (
        path.resolve() for path in (job_dir, tasks_dir, output_dir)
    )
    trials = sorted(job_dir.glob("*/result.json"))
    if not trials:
        raise ValueError("No completed trial results found")
    if output_dir.exists():
        raise FileExistsError(output_dir)

    # Collect secret values from every JSON document, including nested configs
    # in trial results and lockfiles, then scrub their occurrences from logs too.
    secrets: set[str] = set()
    for path in job_dir.rglob("*.json"):
        secrets.update(secret_values(json.loads(path.read_text())))
    secrets.discard("")
    records = []
    rows = []
    for path in trials:
        trial = json.loads(path.read_text())
        lock = json.loads((path.parent / "lock.json").read_text())
        task_name = Path(trial["task_id"]["path"]).name
        task_dir = tasks_dir / task_name
        digest, files = Packager.compute_content_hash(task_dir)
        if f"sha256:{digest}" != lock["task"]["digest"]:
            raise ValueError(
                f"Task snapshot does not match recorded digest: {task_name}"
            )
        for source in files:
            target = output_dir / "tasks" / task_name / source.relative_to(task_dir)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        metadata = tomllib.loads((task_dir / "task.toml").read_text())["metadata"]
        reward = json.loads((path.parent / "verifier/reward.json").read_text())
        records.append(reward)
        rows.append(
            {
                "task": task_name,
                "trial": path.parent.name,
                "reward": reward["reward"],
                "normalized_mse": reward.get("normalized_mse"),
                "explanation_score": reward.get("explanation_score"),
                "task_digest": f"sha256:{digest}",
                "upstream_commit": metadata["upstream_commit"],
            }
        )

    for source in sorted(job_dir.rglob("*")):
        if not source.is_file() or source.suffix not in {
            ".json",
            ".jsonl",
            ".log",
            ".txt",
        }:
            continue
        text = source.read_text()
        if source.suffix == ".json":
            # JSON escaping can hide a credential's raw spelling.
            def scrub(value: Any) -> Any:
                if isinstance(value, dict):
                    return {
                        key: "[REDACTED]"
                        if SECRET_KEY.search(key) and item
                        else scrub(item)
                        for key, item in value.items()
                    }
                if isinstance(value, list):
                    return [scrub(item) for item in value]
                return redact(value, secrets) if isinstance(value, str) else value

            text = json.dumps(scrub(json.loads(text)), indent=2) + "\n"
        else:
            text = redact(text, secrets)
        target = output_dir / "job" / source.relative_to(job_dir)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)

    with (output_dir / "per-task-results.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    (output_dir / "rewards.jsonl").write_text(
        "".join(json.dumps(record) + "\n" for record in records)
    )
    shutil.copy2(
        ADAPTER_DIR / "src/discoverphysics/metric.py", output_dir / "metric.py"
    )
    subprocess.run(
        [
            sys.executable,
            str(output_dir / "metric.py"),
            "-i",
            str(output_dir / "rewards.jsonl"),
            "-o",
            str(output_dir / "recomputed-metrics.json"),
        ],
        check=True,
    )
    provenance = {
        "job_name": job_dir.name,
        "trial_count": len(rows),
        "task_digests_verified": True,
        "upstream_commits": sorted({row["upstream_commit"] for row in rows}),
        "harbor_commit_at_run": None,
        "adapter_commit_at_export": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, text=True
        ).strip(),
        "notes": [
            "The original run did not record its Harbor Git revision; no revision is inferred from timestamps.",
            "Bundled tasks match recorded lock digests; ignored Python caches are omitted.",
            "Provider credentials are redacted in job files; task files are copied unchanged.",
            "job/result.json preserves historical metrics; recomputed-metrics.json uses the bundled metric.py.",
            "This is oracle evidence, not an agent parity or standard CLI-agent compatibility result.",
        ],
    }
    (output_dir / "provenance.json").write_text(json.dumps(provenance, indent=2) + "\n")
    for path in (output_dir / "tasks").rglob("*"):
        if path.is_file() and TOKEN.search(path.read_text()):
            raise ValueError(f"Credential-like value in task snapshot: {path.name}")
    checksums = {
        str(path.relative_to(output_dir)): Packager.compute_file_hash(path)
        for path in sorted(output_dir.rglob("*"))
        if path.is_file()
    }
    (output_dir / "sha256.json").write_text(json.dumps(checksums, indent=2) + "\n")
    print(f"Bundled {len(rows)} trials; all task digests verified: {output_dir}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--job-dir", type=Path, required=True)
    parser.add_argument("--tasks-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    bundle(args.job_dir, args.tasks_dir, args.output_dir)
