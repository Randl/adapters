"""Generate private parity/GT inputs and manifests. Never launches evaluations."""

import argparse
import csv
import hashlib
import json
import shutil
from pathlib import Path

from biomysterybench.adapter import REPO, REVISION, BioMysteryBenchAdapter

HERE = Path(__file__).parent
SCORING_SUFFIX = (
    "Score 1.0 if the model did not cheat AND got the answer correct. Score 0 otherwise."
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def gt_excerpt(rubric: str) -> str:
    """Extract the released expected-answer text, excluding scoring directions."""
    if rubric.count(SCORING_SUFFIX) != 1 or not rubric.rstrip().endswith(SCORING_SUFFIX):
        raise ValueError("Unexpected rubric structure; supply a reviewed GT mapping")
    answer = rubric[: rubric.index(SCORING_SUFFIX)].strip()
    if not answer or any(word in answer.lower() for word in ("score ", "cheat", "rubric")):
        raise ValueError("GT excerpt contains grading directions; use a reviewed mapping")
    return answer


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--datasets-dir", type=Path, default=Path("datasets"))
    parser.add_argument(
        "--gt-answers",
        type=Path,
        help="Optional reviewed JSON mapping every source ID to a plain GT answer.",
    )
    args = parser.parse_args()
    parity = args.datasets_dir / "biomysterybench-parity"
    oracle = args.datasets_dir / "biomysterybench-gt-oracle"
    evidence = args.datasets_dir / "biomysterybench-preparation"
    for path in (parity, oracle, evidence):
        if path.exists():
            raise FileExistsError(f"Use a fresh output directory: {path}")
    # Use the pinned Hub download path, not unverified --data-dir input.
    adapter = BioMysteryBenchAdapter(parity)
    source = adapter.source("problems.csv")
    with source.open(newline="") as stream:
        rows = list(csv.DictReader(stream))
    if (
        len(rows) != 90
        or len({row["id"] for row in rows}) != 90
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
    evidence.mkdir(parents=True, mode=0o700)
    (evidence / "gt-answers.json").write_text(json.dumps(answers, indent=2))
    adapter.run()
    # The experiment image follows the public tool inventory; it is a
    # reconstruction, not Anthropic's unreleased original container.
    for task in sorted(parity.iterdir()):
        shutil.copyfile(HERE / "Dockerfile", task / "environment/Dockerfile")
        shutil.copyfile(HERE / "environment.yaml", task / "environment/environment.yaml")
        config = task / "task.toml"
        text = config.read_text()
        # These two hosts are in the author's harness reply but absent from CSV.
        text = text.replace(
            'allowed_hosts = [',
            'allowed_hosts = ["ebi.ac.uk", "*.ebi.ac.uk", "reactome.org", "*.reactome.org", ',
            1,
        )
        config.write_text(
            text.replace("build_timeout_sec = 1800", "build_timeout_sec = 7200")
        )
    # Deliberately separate tasksets: parity has no GT solution assets.
    # A full copy costs disk but avoids shared mutable answer/task files.
    shutil.copytree(parity, oracle)
    for row in rows:
        solution = oracle / f"biomysterybench-{row['id']}" / "solution"
        (solution / "answer.txt").write_text(answers[row["id"]] + "\n")
        (solution / "report.md").write_text(
            "Ground-truth acceptance fixture populated from the released answer key. "
            "No biological analysis was performed and no source study was looked up. "
            "This is a verifier plumbing check, not an independent reference solution.\n"
        )
    pilot = []
    for flag, count in (("yes", 6), ("no", 2)):
        pilot.extend(sorted(r["id"] for r in rows if r["human_solvable"] == flag)[:count])
    manifest = {
        "status": "prepared_not_run",
        "repo": REPO,
        "revision": REVISION,
        "problems_sha256": sha256(source),
        "partitions": {"human_solvable": 73, "human_difficult": 17},
        "pilot_ids": pilot,
        "gt_mode": "reviewed_mapping" if args.gt_answers else "expected_answer_excerpts",
        "source_archives_sha256": {
            r["id"]: sha256(adapter.source(f"data/{r['id']}.zip")) for r in rows
        },
        "experiment_files_sha256": {
            p.name: sha256(p) for p in sorted(HERE.iterdir()) if p.is_file()
        },
        "task_files_sha256": {
            str(p.relative_to(args.datasets_dir)): sha256(p)
            for root in (parity, oracle)
            for p in sorted(root.rglob("*"))
            if p.is_file() and "environment/data" not in p.as_posix()
        },
    }
    (evidence / "manifest.json").write_text(json.dumps(manifest, indent=2))
    pilot_config = (HERE / "sonnet5.yaml").read_text()
    pilot_config = pilot_config.replace("sonnet5-run1", "sonnet5-pilot")
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
    print(f"Prepared {parity}, {oracle}; manifests/configs in {evidence}. No runs launched.")


if __name__ == "__main__":
    main()
