"""Prepare matched runs, execute direct upstream controls, and collect real scores."""

import argparse
import json
import math
import shlex
import statistics
import subprocess
import sys
from pathlib import Path

import yaml

from .runtime.evidence import verify
from .settings import DEV_GAMES, PARITY_GAMES, TEST_GAMES


def prepare(dataset, output, runs, kind, concurrency, compatibility_model):
    if runs < 1 or concurrency < 1:
        raise ValueError("Runs and concurrency must be positive")
    tasks = sorted(p.parent for p in dataset.glob("*/task.toml"))
    if not tasks:
        raise ValueError("Generate a dataset first")
    manifests = [json.loads((t / "tests/manifest.json").read_text()) for t in tasks]
    settings = manifests[0]["settings"]
    if any(m["settings"] != settings for m in manifests):
        raise ValueError("Mixed settings in dataset")
    games = {m["game"] for m in manifests}
    expected = set(PARITY_GAMES if kind == "parity" else TEST_GAMES + DEV_GAMES)
    if games != expected:
        raise ValueError(
            f"{kind} expects exactly {sorted(expected)}; generate --split {'parity' if kind == 'parity' else 'full'}"
        )
    output.mkdir(parents=True, exist_ok=True)
    config = {
        "datasets": [{"path": str(dataset)}],
        "agents": [
            {
                "import_path": "videogamebench.agent:VideoGameBenchAgent",
                "model_name": settings["model"],
                "kwargs": {
                    "api_key_env": settings["api_key_env"],
                    "timeout_sec": settings["agent_timeout_sec"],
                },
            }
        ],
        "environment": {"type": "docker", "delete": True},
        "n_concurrent_trials": concurrency,
        "n_attempts": 1,
    }
    commands = []
    ledger = []
    for run in range(1, runs + 1):
        run_config = {
            **config,
            "jobs_dir": str(output / "harbor"),
            "job_name": f"run-{run}",
        }
        path = output / f"harbor-run{run}.yaml"
        path.write_text(yaml.safe_dump(run_config, sort_keys=False))
        commands.append(
            shlex.join(
                [sys.executable, "-m", "harbor.cli.main", "run", "-c", str(path)]
            )
        )
        if kind == "parity":
            commands.append(
                shlex.join(
                    [
                        sys.executable,
                        "-m",
                        "videogamebench.experiment",
                        "original",
                        "--dataset",
                        str(dataset),
                        "--output",
                        str(output / "original" / f"run-{run}"),
                    ]
                )
            )
        for m in manifests:
            for side in (
                ["original", "harbor"] if kind == "parity" else ["oracle-candidate"]
            ):
                ledger.append(
                    {
                        "run": run,
                        "side": side,
                        "task_id": m["task_id"],
                        "identity": m["identity"],
                        "status": "prepared",
                    }
                )
    oracle = {
        **config,
        "agents": [{"name": "oracle"}],
        "jobs_dir": str(output / "oracle-validation"),
        "job_name": "fresh-replay",
    }
    (output / "harbor-oracle.yaml").write_text(yaml.safe_dump(oracle, sort_keys=False))
    compatibility = {
        **config,
        "agents": [{"name": "codex", "model_name": compatibility_model}],
        "jobs_dir": str(output / "compatibility"),
        "job_name": "codex",
    }
    (output / "harbor-compatibility.yaml").write_text(
        yaml.safe_dump(compatibility, sort_keys=False)
    )
    (output / "run.sh").write_text(
        "#!/bin/bash\nset -euo pipefail\n" + "\n".join(commands) + "\n"
    )
    plan = {
        "kind": kind,
        "dataset": str(dataset),
        "runs_per_side": runs,
        "task_count": len(tasks),
        "settings": settings,
        "metric": "final_checkpoint_completion",
        "aggregate": "arithmetic mean of task completion per repetition",
        "acceptance": "overlapping raw run-score ranges; report mean and sample SEM",
        "budget_usd_nominal": runs
        * len(tasks)
        * settings["max_cost"]
        * (2 if kind == "parity" else 1),
        "budget_note": "Upstream checks cost before each call and can overshoot by one request; infrastructure failures produce no score",
        "manifests": manifests,
        "attempts": ledger,
    }
    (output / "plan.json").write_text(json.dumps(plan, indent=2) + "\n")


def original(dataset, output):
    output.mkdir(parents=True, exist_ok=True)
    for task in sorted(dataset.glob("*/task.toml")):
        root = task.parent
        manifest = json.loads((root / "tests/manifest.json").read_text())
        tag = f"videogamebench-control:{manifest['identity'][:16]}"
        subprocess.run(
            [
                "docker",
                "build",
                "-f",
                str(root / "environment/Dockerfile.game"),
                "-t",
                tag,
                str(root / "environment"),
            ],
            check=True,
        )
        destination = output / root.name
        if (destination / "result.json").exists():
            raise FileExistsError(f"Preserve the prior attempt: {destination}")
        destination.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                "--init",
                f"--shm-size={manifest['settings']['game_shm_mb']}m",
                "--cpus",
                str(manifest["settings"]["cpus"]),
                "--memory",
                f"{manifest['settings']['memory_mb']}m",
                "-e",
                manifest["settings"]["api_key_env"],
                "-v",
                f"{destination}:/state",
                tag,
                "xvfb-run",
                "-a",
                "python",
                "/opt/game/runtime/original.py",
            ],
            check=True,
            timeout=manifest["settings"]["agent_timeout_sec"],
        )


def summarize(plan_path, output):
    plan = json.loads(plan_path.read_text())
    root = plan_path.parent
    expected = {m["task_id"]: m["identity"] for m in plan["manifests"]}
    report = {"kind": plan["kind"], "metric": plan["metric"], "sides": {}}
    for side in ("original", "harbor"):
        scores = []
        for run in range(1, plan["runs_per_side"] + 1):
            found = {}
            for file in (root / side / f"run-{run}").rglob("result.json"):
                data = json.loads(file.read_text())
                if "signature" not in data:
                    continue
                record = data["payload"]
                task_id = record.get("task_id")
                if task_id not in expected or record["identity"] != expected[task_id]:
                    raise ValueError(f"Mismatched identity: {file}")
                key = (Path(plan["dataset"]) / task_id / "tests/result.key").read_text()
                verify(data, key, expected[task_id])
                if record["model"] != plan["settings"]["model"]:
                    raise ValueError(f"Model mismatch: {file}")
                if record["status"] != "completed" or record["checkpoint_count"] == 0:
                    raise ValueError(f"Incomplete or unscored run: {file}")
                if task_id in found and found[task_id] != record:
                    raise ValueError(f"Conflicting duplicate result: {file}")
                found[task_id] = record
            if found.keys() != expected.keys():
                raise ValueError(
                    f"Missing tasks for {side} run {run}: {expected.keys() - found.keys()}"
                )
            scores.append(statistics.mean(r["completion"] for r in found.values()))
        report["sides"][side] = {
            "runs": scores,
            "mean": statistics.mean(scores),
            "sample_sem": statistics.stdev(scores) / math.sqrt(len(scores))
            if len(scores) > 1
            else None,
        }
    a, b = (report["sides"][side]["runs"] for side in ("original", "harbor"))
    report["ranges_overlap"] = max(min(a), min(b)) <= min(max(a), max(b))
    output.write_text(json.dumps(report, indent=2) + "\n")


def export_oracles(job, output):
    output.mkdir(parents=True, exist_ok=True)
    count = 0
    for file in sorted(job.rglob("actions.json")):
        result_path = file.with_name("result.json")
        if not result_path.exists():
            continue
        record = json.loads(result_path.read_text()).get("payload", {})
        if record.get("completion") != 1 or record.get("status") != "completed":
            continue
        trace = json.loads(file.read_text())
        target = output / f"{trace['game']}.json"
        if not target.exists():
            target.write_text(json.dumps(trace, indent=2))
            count += 1
    print(
        f"Exported {count} candidates; run fresh oracle verification before calling them validated."
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("prepare")
    p.add_argument("--dataset", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--runs", type=int, default=3)
    p.add_argument("--kind", choices=["parity", "oracle"], default="parity")
    p.add_argument("--concurrency", type=int, default=1)
    p.add_argument("--compatibility-model", default="openai/gpt-5")
    p = sub.add_parser("original")
    p.add_argument("--dataset", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p = sub.add_parser("summarize")
    p.add_argument("--plan", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p = sub.add_parser("export-oracles")
    p.add_argument("--job", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    for key in ("dataset", "output", "plan", "job"):
        if hasattr(args, key):
            setattr(args, key, getattr(args, key).resolve())
    if args.command == "prepare":
        prepare(
            args.dataset,
            args.output,
            args.runs,
            args.kind,
            args.concurrency,
            args.compatibility_model,
        )
    elif args.command == "original":
        original(args.dataset, args.output)
    elif args.command == "summarize":
        summarize(args.plan, args.output)
    else:
        export_oracles(args.job, args.output)


if __name__ == "__main__":
    main()
