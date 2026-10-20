"""Prepare local Docker tasks backed by shared input data. Never runs evaluations."""

import argparse
import csv
import hashlib
import json
import re
import shutil
import stat
from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import ZipFile

from huggingface_hub.utils import tqdm

from biomysterybench.adapter import REPO, REVISION, TEMPLATE, BioMysteryBenchAdapter
from biomysterybench.judge import DEFAULT_BASE_URL

HERE = Path(__file__).parent
SCORING_SUFFIX = "Score 1.0 if the model did not cheat AND got the answer correct. Score 0 otherwise."


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def gt_excerpt(rubric: str) -> str:
    """Extract the released expected-answer text, excluding scoring directions."""
    if rubric.count(SCORING_SUFFIX) != 1 or not rubric.rstrip().endswith(
        SCORING_SUFFIX
    ):
        raise ValueError("Unexpected rubric structure; supply a reviewed GT mapping")
    answer = rubric[: rubric.index(SCORING_SUFFIX)].strip()
    if not answer or any(
        word in answer.lower() for word in ("score ", "cheat", "rubric")
    ):
        raise ValueError(
            "GT excerpt contains grading directions; use a reviewed mapping"
        )
    return answer


def validate_input_directory(path: Path) -> None:
    """Only this directory is mounted; reject links to data outside it."""
    if path.is_symlink() or not path.is_dir():
        raise ValueError(f"Not a regular input directory: {path}")
    found_file = False
    for child in path.rglob("*"):
        if child.is_symlink() or not (child.is_file() or child.is_dir()):
            raise ValueError(f"Unsupported input file: {child}")
        found_file |= child.is_file()
    if not found_file:
        raise ValueError(
            f"Empty input directory: {path}; remove it to allow extraction"
        )


def prepare_input(
    adapter: BioMysteryBenchAdapter, source_id: str, data_dir: Path
) -> Path:
    """Reuse supplied inputs; extract missing inputs once from the pinned HF cache."""
    target = data_dir / source_id
    if target.exists() or target.is_symlink():
        validate_input_directory(target)
        return target
    data_dir.mkdir(parents=True, exist_ok=True)
    archive_path = adapter.source(f"data/{source_id}.zip")
    with ZipFile(archive_path) as archive:
        for entry in archive.infolist():
            path = Path(entry.filename)
            if (
                path.is_absolute()
                or ".." in path.parts
                or stat.S_ISLNK(entry.external_attr >> 16)
            ):
                raise ValueError(f"Unsafe archive member: {entry.filename}")
        with TemporaryDirectory(prefix=f".{source_id}-", dir=data_dir) as directory:
            staging = Path(directory) / "data"
            archive.extractall(staging)
            validate_input_directory(staging)
            staging.rename(target)
    return target


def publish_task(staging: Path, target: Path) -> None:
    """Replace only a complete generated task, restoring the old task on failure."""
    backup = staging.parent / "previous"
    if target.exists():
        target.rename(backup)
    try:
        staging.rename(target)
    except BaseException:
        if backup.exists():
            backup.rename(target)
        raise


def prepare_task(
    adapter: BioMysteryBenchAdapter,
    row: dict,
    target: Path,
    input_dir: Path,
    answer: str | None = None,
) -> None:
    """Generate small task metadata with a read-only bind mount, never a data copy."""
    target.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix=f".{target.name}-", dir=target.parent) as directory:
        staging = Path(directory) / "task"
        shutil.copytree(
            TEMPLATE, staging, ignore=shutil.ignore_patterns("__pycache__", "*.pyc")
        )
        adapter._write_task(staging, target.name, row)
        environment = staging / "environment"
        shutil.copyfile(HERE / "Dockerfile", environment / "Dockerfile")
        shutil.copyfile(HERE / "environment.yaml", environment / "environment.yaml")
        # JSON is valid YAML. Escape Compose interpolation in host paths.
        compose = {
            "services": {
                "main": {
                    "volumes": [
                        {
                            "type": "bind",
                            "source": str(input_dir.resolve()).replace("$", "$$"),
                            "target": "/workspace/data",
                            "read_only": True,
                            "bind": {"create_host_path": False},
                        }
                    ]
                }
            }
        }
        (environment / "docker-compose.yaml").write_text(json.dumps(compose, indent=2))
        (environment / ".dockerignore").write_text("data/\ndocker-compose.yaml\n")
        config = staging / "task.toml"
        text = config.read_text().replace(
            "allowed_hosts = [",
            'allowed_hosts = ["ebi.ac.uk", "*.ebi.ac.uk", "reactome.org", "*.reactome.org", ',
            1,
        )
        config.write_text(
            text.replace("build_timeout_sec = 1800", "build_timeout_sec = 7200")
        )
        instruction = staging / "instruction.md"
        instruction.write_text(
            instruction.read_text()
            + "\nInput files in `/workspace/data` are read-only. "
            "Write derived files elsewhere under `/workspace`.\n"
        )
        if answer is not None:
            (staging / "solution/answer.txt").write_text(answer + "\n")
            (staging / "solution/report.md").write_text(
                "Ground-truth acceptance fixture populated from the released answer key. "
                "No biological analysis was performed and no source study was looked up. "
                "This is a verifier plumbing check, not an independent reference solution.\n"
            )
        publish_task(staging, target)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--datasets-dir", type=Path, default=Path("datasets"))
    parser.add_argument(
        "--data-dir",
        type=Path,
        help="Shared extracted inputs: <path>/<source-id>/; reuse existing directories, extract missing ones",
    )
    parser.add_argument("--judge-base-url", default=DEFAULT_BASE_URL)
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Rebuild existing task metadata; reuse shared inputs",
    )
    parser.add_argument(
        "--gt-answers",
        type=Path,
        help="Reviewed JSON mapping every source ID to a plain GT answer",
    )
    args = parser.parse_args()
    parity = args.datasets_dir / "biomysterybench-parity"
    oracle = args.datasets_dir / "biomysterybench-gt-oracle"
    evidence = args.datasets_dir / "biomysterybench-preparation"
    data_dir = (args.data_dir or args.datasets_dir / "biomysterybench-data").resolve()
    for root in (parity, oracle, evidence):
        if data_dir.is_relative_to(root.resolve()):
            raise ValueError(
                "--data-dir must be outside generated tasksets and preparation metadata"
            )
        if root.is_symlink() or (root.exists() and not root.is_dir()):
            raise ValueError(f"Not a regular output directory: {root}")
        if root.exists() and not args.resume:
            raise FileExistsError(f"Use --resume to rebuild task metadata: {root}")
    adapter = BioMysteryBenchAdapter(parity, judge_base_url=args.judge_base_url)
    source = adapter.source("problems.csv")
    with source.open(newline="") as stream:
        rows = list(csv.DictReader(stream))
    if (
        len(rows) != 90
        or len({row["id"] for row in rows}) != 90
        or any(not re.fullmatch(r"[a-z0-9]+", row["id"]) for row in rows)
        or sum(row["human_solvable"] == "yes" for row in rows) != 73
        or sum(row["human_solvable"] == "no" for row in rows) != 17
    ):
        raise ValueError("Expected the v11 90-problem, 73/17 release")
    if args.gt_answers:
        answers = json.loads(args.gt_answers.read_text())
        if set(answers) != {r["id"] for r in rows} or any(
            not isinstance(a, str) or not a.strip() for a in answers.values()
        ):
            raise ValueError("GT mapping must contain a nonempty answer for all 90 IDs")
    else:
        answers = {row["id"]: gt_excerpt(row["answer_rubric"]) for row in rows}
    task_names = {"biomysterybench-" + row["id"] for row in rows}
    for root in (parity, oracle):
        if root.exists():
            for task in root.iterdir():
                if (
                    task.is_symlink()
                    or not task.is_dir()
                    or task.name not in task_names
                ):
                    raise ValueError(f"Unexpected generated task: {task}")
    evidence.mkdir(parents=True, mode=0o700, exist_ok=True)
    (evidence / "manifest.json").write_text(
        json.dumps(
            {"status": "preparing", "repo": REPO, "revision": REVISION}, indent=2
        )
    )
    (evidence / "gt-answers.json").write_text(json.dumps(answers, indent=2))
    inputs = {}
    with tqdm(
        rows, desc="Preparing shared inputs", unit="task", dynamic_ncols=True
    ) as progress:
        for row in progress:
            progress.set_postfix_str(row["id"])
            inputs[row["id"]] = prepare_input(adapter, row["id"], data_dir)
    for root, label in (
        (parity, "Preparing parity tasks"),
        (oracle, "Preparing GT fixtures"),
    ):
        with tqdm(rows, desc=label, unit="task", dynamic_ncols=True) as progress:
            for row in progress:
                progress.set_postfix_str(row["id"])
                prepare_task(
                    adapter,
                    row,
                    root / ("biomysterybench-" + row["id"]),
                    inputs[row["id"]],
                    answers[row["id"]] if root == oracle else None,
                )
    pilot = []
    for flag, count in (("yes", 6), ("no", 2)):
        pilot.extend(
            sorted(r["id"] for r in rows if r["human_solvable"] == flag)[:count]
        )
    manifest = {
        "status": "prepared_not_run",
        "repo": REPO,
        "revision": REVISION,
        "problems_sha256": sha256(source),
        "data_dir": str(data_dir),
        "input_data": {source_id: str(path) for source_id, path in inputs.items()},
        "input_validation": "Existing directories reused without content verification; new ZIPs checked during extraction",
        "partitions": {"human_solvable": 73, "human_difficult": 17},
        "pilot_ids": pilot,
        "gt_mode": "reviewed_mapping"
        if args.gt_answers
        else "expected_answer_excerpts",
        "experiment_files_sha256": {
            p.name: sha256(p) for p in sorted(HERE.iterdir()) if p.is_file()
        },
        "task_files_sha256": {
            str(p.relative_to(args.datasets_dir)): sha256(p)
            for root in (parity, oracle)
            for p in sorted(root.rglob("*"))
            if p.is_file()
        },
    }
    pilot_config = (
        (HERE / "sonnet5.yaml").read_text().replace("sonnet5-run1", "sonnet5-pilot")
    )
    pilot_config = pilot_config.replace(
        "  - path: datasets/biomysterybench-parity",
        "  - path: "
        + json.dumps(str(parity.resolve()))
        + "\n    task_names: "
        + json.dumps(["biomysterybench-" + x for x in pilot]),
    )
    (evidence / "pilot.yaml").write_text(pilot_config)
    for source_name, target in (("sonnet5.yaml", parity), ("gt-oracle.yaml", oracle)):
        config = (HERE / source_name).read_text()
        default_path = (
            "datasets/biomysterybench-parity"
            if source_name == "sonnet5.yaml"
            else "datasets/biomysterybench-gt-oracle"
        )
        (evidence / source_name).write_text(
            config.replace(default_path, json.dumps(str(target.resolve())))
        )
    (evidence / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print(f"Prepared {parity}, {oracle}; shared inputs: {data_dir}. No runs launched.")


if __name__ == "__main__":
    main()
