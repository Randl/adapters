"""Prepare matched experiments and run the unchanged upstream evaluation CLI."""

import argparse
import copy
import importlib.util
import json
import math
import os
import shlex
import statistics
import subprocess
import sys
import tempfile
import time
import tomllib
from pathlib import Path
from urllib.parse import urlsplit

import yaml

from .adapter import (
    PACKAGE,
    REVISION,
    CodeReviewBenchAdapter,
    sanity_ids,
    validate_source,
)
from .judge_client import parse_temperature
from .metric import aggregate

JUDGE = "anthropic/claude-sonnet-4-5-20250929"
TOOL = "harbor-terminus"


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n")


def source_files(source: Path) -> dict[str, bytes]:
    hashes = json.loads((PACKAGE / "upstream_hashes.json").read_text())
    files = {name: (source / name).read_bytes() for name in hashes}
    validate_source(files)
    return files


def prepare(
    tasks: Path,
    source: Path,
    output: Path,
    config: Path,
    runs: int = 3,
    sanity_per_project: int = 2,
    harbor_version: str = "0.24.0",
) -> None:
    """Write reviewable configs and sequential launchers; make no model calls."""
    source_files(source)
    records = json.loads((PACKAGE / "prs.json").read_text())
    expected = {"codereviewbench-" + r["id"] for r in records}
    if {p.name for p in tasks.iterdir() if (p / "task.toml").exists()} != expected:
        raise ValueError("Prepare requires the full generated 50-task dataset")
    if runs < 2 or not 0 <= sanity_per_project <= 10:
        raise ValueError("Use >=2 runs and 0..10 sanity tasks per project")
    base = yaml.safe_load(config.read_text())
    if len(base["agents"]) != 1 or base.get("n_attempts", 1) != 1:
        raise ValueError("Prepare one agent with one attempt per paired repetition")
    judges = [
        tomllib.loads((tasks / name / "task.toml").read_text())["verifier"]["env"]
        for name in sorted(expected)
    ]
    if any(j != judges[0] for j in judges):
        raise ValueError("All tasks must have identical judge configuration")
    judge = {**judges[0], **base.get("verifier", {}).get("env", {})}
    judge_model = judge["JUDGE_MODEL"]
    judge_base_url = judge["JUDGE_BASE_URL"]
    if (
        urlsplit(judge_base_url).hostname
        != urlsplit(judges[0]["JUDGE_BASE_URL"]).hostname
    ):
        raise ValueError(
            "Regenerate tasks with --judge-base-url to change the network allowlist"
        )
    if judge["JUDGE_API_KEY"] != "${JUDGE_API_KEY}":
        raise ValueError(
            "Export JUDGE_API_KEY on the host; do not embed credentials in configs"
        )
    output.mkdir(parents=True, exist_ok=False)
    base["jobs_dir"] = str(output / "jobs")
    stages = (["sanity"] if sanity_per_project else []) + [
        f"run{i}" for i in range(1, runs + 1)
    ]
    for stage in [*stages, "oracle"]:
        dataset = {"path": str(tasks)}
        if stage == "sanity":
            dataset["task_names"] = [
                "codereviewbench-" + x for x in sanity_ids(sanity_per_project)
            ]
        for side in ("original", "harbor"):
            if stage == "oracle" and side == "original":
                continue  # Upstream oracle uses released comments directly.
            job_config: dict = dict(
                copy.deepcopy(base), datasets=[dataset], job_name=f"{side}-{stage}"
            )
            if stage == "oracle":
                job_config["agents"] = [{"name": "oracle"}]
            if side == "original":
                job_config.setdefault("verifier", {})["disable"] = True
                job_config["metrics"] = []
            else:
                job_config["metrics"] = [
                    {
                        "type": "uv-script",
                        "kwargs": {"script_path": str(PACKAGE / "metric.py")},
                    }
                ]
            (output / f"{side}-{stage}.yaml").write_text(
                yaml.safe_dump(job_config, sort_keys=False)
            )
    write_launchers(
        output,
        stages,
        source,
        judge_model,
        judge_base_url,
        harbor_version,
        judge.get("JUDGE_TEMPERATURE", "0"),
    )
    write_json(
        output / "plan.json",
        {
            "status": "prepared; not measured",
            "upstream_revision": REVISION,
            "harbor_version": harbor_version,
            "agent_config": base["agents"][0],
            "judge": judge,
            "task_ids": sorted(expected),
            "sanity_ids": sanity_ids(sanity_per_project),
            "metric": "core micro F2",
            "runs_per_side": runs,
            "scope": "Independent inference per side; shared offline task inputs and "
            "configured agent. Original side runs unchanged upstream CLIs. "
            "This does not reproduce the leaderboard's proprietary tools.",
        },
    )


def write_launchers(
    output: Path,
    stages: list[str],
    source: Path,
    judge_model: str,
    judge_base_url: str,
    harbor_version: str,
    judge_temperature: str = "0",
) -> None:
    """Refresh launch scripts without touching configs or existing results."""
    q = shlex.quote
    python = q(sys.executable)
    common = (
        f"{python} -m codereviewbench.experiments upstream "
        f'--source-dir {q(str(source))} --judge-model "$JUDGE_MODEL" '
        '--judge-base-url "$JUDGE_BASE_URL" --judge-temperature "$JUDGE_TEMPERATURE"'
    )
    header = [
        "#!/bin/bash",
        'if [ -z "${BASH_VERSION:-}" ]; then exec bash "$0" "$@"; fi',
        "set -Eeuo pipefail",
        "current_step=preflight",
        'trap \'status=$?; printf "ERROR: %s failed (exit %s, line %s)\\n" "$current_step" "$status" "$LINENO" >&2; exit "$status"\' ERR',
        f"printf '%s\\n' {q('CodeReviewBench experiments — prepared config: ' + str(output))}",
        "printf '%s\\n' 'Checking credentials and Harbor version…'",
        'run_step() { current_step="$1"; shift; printf "\\n==> %s\\n" "$current_step"; "$@"; printf "<== Finished: %s\\n" "$current_step"; }',
        ': "${JUDGE_API_KEY:?Set the judge API key on the host}"',
        'actual_version="$(harbor --version)"',
        (
            f'if [ "$actual_version" != {q(harbor_version)} ]; then '
            f'printf "ERROR: Expected Harbor %s; found %s\\n" {q(harbor_version)} '
            '"$actual_version" >&2; exit 1; fi'
        ),
        f'if [ "${{JUDGE_MODEL+x}}" != x ]; then JUDGE_MODEL={q(judge_model)}; fi',
        f'if [ "${{JUDGE_BASE_URL+x}}" != x ]; then JUDGE_BASE_URL={q(judge_base_url)}; fi',
        f'if [ "${{JUDGE_TEMPERATURE+x}}" != x ]; then JUDGE_TEMPERATURE={q(judge_temperature)}; fi',
        "export JUDGE_MODEL JUDGE_BASE_URL JUDGE_TEMPERATURE",
        'printf "Judge temperature: %s\\n" "$JUDGE_TEMPERATURE"',
        'printf "Judge model: %s\\nJudge endpoint: %s\\n" "$JUDGE_MODEL" "$JUDGE_BASE_URL"',
        'printf "%s\\n" "Preparing isolated run settings…"',
        (
            f'RUN_DIR="$({python} -m codereviewbench.experiments runtime-config '
            f"--output-dir {q(str(output))} --source-dir {q(str(source))} "
            '--judge-model "$JUDGE_MODEL" --judge-base-url "$JUDGE_BASE_URL" '
            '--judge-temperature "$JUDGE_TEMPERATURE")"'
        ),
        'printf "Results: %s\\n" "$RUN_DIR"',
    ]
    parity = header.copy()
    for stage in stages:
        for side in ("original", "harbor"):
            parity.append(f'harbor run -y -c "$RUN_DIR/{side}-{stage}.yaml"')
            if side == "original":
                parity.append(
                    f'{common} --job "$RUN_DIR/jobs/original-{stage}"'
                    f' --output-dir "$RUN_DIR/original-{stage}"'
                )
        if stage == "sanity":
            parity.append(
                f"{python} -m codereviewbench.experiments summarize "
                '--output-dir "$RUN_DIR" --sanity'
            )
    parity.append(
        f'{python} -m codereviewbench.experiments summarize --output-dir "$RUN_DIR"'
    )
    oracle = header + [
        f'{common} --oracle --output-dir "$RUN_DIR/original-oracle"',
        'harbor run -y -c "$RUN_DIR/harbor-oracle.yaml"',
        (
            f"{python} -m codereviewbench.experiments summarize "
            '--output-dir "$RUN_DIR" --oracle'
        ),
    ]
    for name, commands in (("run-parity.sh", parity), ("run-oracle.sh", oracle)):
        path = output / name
        labeled = commands[: len(header)]
        for index, command in enumerate(commands[len(header) :], 1):
            label = f"{name.removesuffix('.sh')}: step {index}/{len(commands) - len(header)}"
            if "harbor run" in command:
                label += " — " + Path(shlex.split(command)[-1]).stem
            elif " upstream " in command:
                label += " — upstream deduplication and judging"
            else:
                label += " — summarize scores"
            labeled.append(f"run_step {q(label)} {command}")
        labeled.append('printf "Completed. Results: %s\\n" "$RUN_DIR"')
        temporary = path.with_suffix(".sh.tmp")
        temporary.write_text("\n".join(labeled) + "\n")
        temporary.chmod(0o755)
        temporary.replace(path)


def runtime_config(
    prepared: Path,
    source: Path,
    judge_model: str,
    judge_base_url: str,
    judge_temperature: str = "0",
) -> Path:
    """Resolve a launch into fresh configs and tasks shared by both evaluators."""
    if not judge_model.strip():
        raise ValueError("JUDGE_MODEL must not be empty")
    # Validate configuration/source before creating a run or making any API calls.
    source_files(source)
    adapter = CodeReviewBenchAdapter(
        prepared,
        source_dir=source,
        judge_model=judge_model,
        judge_base_url=judge_base_url,
        judge_temperature=judge_temperature,
    )
    plan = json.loads((prepared / "plan.json").read_text())
    configs = {p.name: yaml.safe_load(p.read_text()) for p in prepared.glob("*.yaml")}
    if not configs:
        raise ValueError("No prepared Harbor configs found")
    runs = prepared / "runs"
    runs.mkdir(exist_ok=True)
    output = Path(tempfile.mkdtemp(prefix="run-", dir=runs))
    adapter.output_dir = output / "tasks"
    adapter.run()
    judge = {
        "JUDGE_API_KEY": "${JUDGE_API_KEY}",
        "JUDGE_MODEL": judge_model,
        "JUDGE_BASE_URL": judge_base_url,
        "JUDGE_TEMPERATURE": judge_temperature,
    }
    for name, config in configs.items():
        config["jobs_dir"] = str(output / "jobs")
        for dataset in config["datasets"]:
            dataset["path"] = str(adapter.output_dir)
        config.setdefault("verifier", {}).setdefault("env", {}).update(judge)
        (output / name).write_text(yaml.safe_dump(config, sort_keys=False))
    plan["judge"] = judge
    plan["prepared_config"] = str(prepared)
    write_json(output / "plan.json", plan)
    return output


def trials(job: Path) -> list[tuple[Path, dict]]:
    results = [
        (p.parent, json.loads(p.read_text())) for p in sorted(job.glob("*/result.json"))
    ]
    if not results:
        raise ValueError(f"No trials in {job}")
    for path, result in results:
        if result.get("exception_info"):
            raise ValueError(f"Infrastructure/agent failure: {path}")
    return results


def run_logged(command: list[str], *, cwd: Path, env: dict, log_path: Path) -> None:
    """Keep the full log while displaying output and liveness during API waits."""
    print(f"Starting {log_path.stem}; log: {log_path}", flush=True)
    started = last_progress = time.monotonic()
    with (
        log_path.open("w") as log,
        log_path.open() as reader,
        subprocess.Popen(
            command, cwd=cwd, env=env, stdout=log, stderr=subprocess.STDOUT
        ) as process,
    ):
        try:
            while True:
                finished = process.poll() is not None
                chunk = reader.read()
                if chunk:
                    print(chunk, end="", flush=True)
                    last_progress = time.monotonic()
                if finished:
                    break
                if time.monotonic() - last_progress >= 30:
                    print(
                        f"[{log_path.stem}] Still running "
                        f"({int(time.monotonic() - started)}s elapsed)…",
                        flush=True,
                    )
                    last_progress = time.monotonic()
                time.sleep(0.25)
        except BaseException:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
            raise
        if process.returncode:
            raise RuntimeError(
                f"{log_path.stem} failed (exit {process.returncode}); log: {log_path}"
            )
    print(f"Finished {log_path.stem} in {time.monotonic() - started:.1f}s", flush=True)


def upstream(
    source: Path,
    output: Path,
    job: Path | None,
    oracle: bool,
    judge_model: str = JUDGE,
    judge_base_url: str = "https://api.withmartian.com/v1",
    judge_temperature: str = "0",
) -> None:
    parse_temperature(judge_temperature)
    files = source_files(source)
    output.mkdir(parents=True, exist_ok=False)
    for name, data in files.items():
        if name.startswith("offline/"):
            path = output / name.removeprefix("offline/")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
    golden = {
        r["url"]: r
        for name, data in files.items()
        if name.startswith("offline/golden_comments/")
        for r in json.loads(data)
    }
    manifest = json.loads((PACKAGE / "prs.json").read_text())
    by_name = {"codereviewbench-" + r["id"]: r for r in manifest}
    submissions = {}
    if oracle:
        submissions = {
            r["url"]: [c["comment"] for c in r["comments"]] for r in golden.values()
        }
    else:
        if job is None:
            raise ValueError("--job is required without --oracle")
        for path, result in trials(job):
            name = result["task_name"].split("/")[-1]
            url = by_name[name]["url"]
            if url in submissions:
                raise ValueError(f"Duplicate trial: {name}")
            artifact = path / "artifacts/workspace/review.json"
            try:
                if artifact.is_symlink() or artifact.stat().st_size > 1_000_000:
                    raise ValueError("Invalid artifact")
                values = json.loads(artifact.read_text())
                if (
                    not isinstance(values, list)
                    or len(values) > 500
                    or artifact.stat().st_size > 1_000_000
                    or any(not isinstance(x, str) or not x.strip() for x in values)
                ):
                    values = []
            except (OSError, ValueError, UnicodeError):
                values = []
            submissions[url] = values
        job_config = json.loads((job / "config.json").read_text())
        expected = job_config["datasets"][0].get("task_names") or list(by_name)
        expected_count = min(
            job_config["datasets"][0].get("n_tasks") or 50, len(expected)
        )
        if len(submissions) != expected_count:
            raise ValueError("Incomplete original inference run")
    model_dir = output / "results" / judge_model.replace("/", "_")
    write_json(
        output / "results/benchmark_data.json",
        {
            url: {
                "golden_comments": golden[url]["comments"],
                "reviews": [{"tool": TOOL, "review_comments": []}],
            }
            for url in submissions
        },
    )
    write_json(
        model_dir / "candidates.json",
        {
            url: {TOOL: [{"text": x, "source": "inline"} for x in values]}
            for url, values in submissions.items()
        },
    )
    # Translate only at the boundary; the pinned upstream modules stay unchanged.
    env = dict(
        os.environ,
        MARTIAN_API_KEY=os.environ.get("JUDGE_API_KEY", ""),
        MARTIAN_MODEL=judge_model,
        MARTIAN_BASE_URL=judge_base_url,
        JUDGE_TEMPERATURE=judge_temperature,
    )
    write_json(
        output / "judge-config.json",
        {
            "model": judge_model,
            "base_url": judge_base_url,
            "temperature": judge_temperature,
        },
    )
    for module in ("step2_5_dedup_candidates", "step3_judge_comments"):
        run_logged(
            [
                sys.executable,
                "-u",
                "-m",
                "codereviewbench.judge_client",
                module,
                "--tool",
                TOOL,
            ],
            cwd=output,
            env=env,
            log_path=output / f"{module}.log",
        )
    # Native dedup falls back to singletons. Reject degraded runs symmetrically.
    log = (output / "step2_5_dedup_candidates.log").read_text()
    if "Fallbacks : 0 " not in log and "Nothing to process." not in log:
        raise RuntimeError("Upstream dedup fallback; discard this repetition")
    evaluations = json.loads((model_dir / "evaluations.json").read_text())
    if set(evaluations) != set(submissions) or any(
        TOOL not in rows
        or rows[TOOL].get("errors_count", 0)
        or rows[TOOL].get("skipped")
        for rows in evaluations.values()
    ):
        raise RuntimeError("Incomplete/failed upstream evaluation")
    spec = importlib.util.spec_from_file_location(
        "original_score_profiles", output / "analysis/score_profiles.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    scores = {
        profile: module.score_tools(evaluations, {}, profile, 2.0)[TOOL]
        for profile in ("strict", "core", "all")
    }
    write_json(output / "scores.json", scores)
    if oracle and any(scores[p]["fbeta"] != 1 for p in scores):
        raise RuntimeError(
            "Ground-truth oracle did not score 100%; inspect judge evidence"
        )


def harbor_score(job: Path, expected: int) -> float:
    rows = trials(job)
    if len(rows) != expected or len({r["task_name"] for _, r in rows}) != expected:
        raise ValueError("Incomplete/duplicate Harbor trials")
    return aggregate(
        [json.loads((path / "verifier/reward.json").read_text()) for path, _ in rows]
    )["core_f2"]


def summarize_oracle(output: Path) -> None:
    original = json.loads((output / "original-oracle/scores.json").read_text())
    job = output / "jobs/harbor-oracle"
    harbor_score(job, 50)  # Reject failed, incomplete or duplicate trials first.
    harbor = aggregate(
        [
            json.loads((path / "verifier/reward.json").read_text())
            for path, _ in trials(job)
        ]
    )
    accepted = all(
        original[p]["fbeta"] == 1.0 and harbor[f"{p}_f2"] == 1.0
        for p in ("strict", "core", "all")
    )
    write_json(
        output / "oracle-summary.json",
        {
            "original": original,
            "harbor": harbor,
            "all_profiles_pass": accepted,
        },
    )
    if not accepted:
        raise ValueError("Ground-truth oracle is not 100% on both sides")


def summarize(output: Path, sanity: bool) -> None:
    plan = json.loads((output / "plan.json").read_text())
    stages = (
        ["sanity"]
        if sanity
        else [f"run{i}" for i in range(1, plan["runs_per_side"] + 1)]
    )
    original = [
        json.loads((output / f"original-{s}/scores.json").read_text())["core"]["fbeta"]
        for s in stages
    ]
    harbor = [
        harbor_score(
            output / f"jobs/harbor-{s}", len(plan["sanity_ids"]) if sanity else 50
        )
        for s in stages
    ]
    result = {"original_runs": original, "harbor_runs": harbor}
    if sanity:
        write_json(output / "sanity-summary.json", result)
    else:
        for name, values in (("original", original), ("harbor", harbor)):
            result[name] = (
                f"{statistics.mean(values):.6f} ± "
                f"{statistics.stdev(values) / math.sqrt(len(values)):.6f}"
            )
        result["ranges_overlap"] = max(original) >= min(harbor) and max(harbor) >= min(
            original
        )
        write_json(output / "parity-summary.json", result)
        if not result["ranges_overlap"]:
            raise ValueError(
                "Parity ranges do not overlap; investigate before publishing"
            )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action", choices=["prepare", "runtime-config", "upstream", "summarize"]
    )
    parser.add_argument("--source-dir", type=Path)
    parser.add_argument("--tasks-dir", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--job", type=Path)
    parser.add_argument("--oracle", action="store_true")
    parser.add_argument("--sanity", action="store_true")
    parser.add_argument("--config", type=Path, help="Standard Harbor parity YAML")
    parser.add_argument(
        "--runs", type=int, default=3, help="Matched repetitions per side"
    )
    parser.add_argument(
        "--sanity-per-project", type=int, default=2, help="0 disables sanity runs"
    )
    parser.add_argument("--harbor-version", default="0.24.0")
    parser.add_argument("--judge-model", default=JUDGE)
    parser.add_argument("--judge-base-url", default="https://api.withmartian.com/v1")
    parser.add_argument(
        "--judge-temperature", default="0", help="0..2 or default to omit"
    )
    args = parser.parse_args()
    output = args.output_dir.resolve()
    if args.action == "prepare":
        if args.source_dir is None or args.tasks_dir is None or args.config is None:
            parser.error("prepare requires --source-dir, --tasks-dir and --config")
        prepare(
            args.tasks_dir.resolve(),
            args.source_dir.resolve(),
            output,
            args.config.resolve(),
            args.runs,
            args.sanity_per_project,
            args.harbor_version,
        )
    elif args.action == "runtime-config":
        if args.source_dir is None:
            parser.error("runtime-config requires --source-dir")
        print(
            runtime_config(
                output,
                args.source_dir.resolve(),
                args.judge_model,
                args.judge_base_url,
                args.judge_temperature,
            )
        )
    elif args.action == "upstream":
        if args.source_dir is None:
            parser.error("upstream requires --source-dir")
        upstream(
            args.source_dir.resolve(),
            output,
            args.job,
            args.oracle,
            args.judge_model,
            args.judge_base_url,
            args.judge_temperature,
        )
    else:
        if args.oracle:
            summarize_oracle(output)
        else:
            summarize(output, args.sanity)


if __name__ == "__main__":
    main()
