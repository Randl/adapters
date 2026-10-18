"""Generate PR review tasks with upstream extraction, deduplication and scoring."""

import io
import json
import re
import shutil
import tarfile
import urllib.request
from pathlib import Path

REVISION = "e616e849755441da38f18bf3adba2c9583b03803"
PACKAGE = Path(__file__).parent
TEMPLATE = PACKAGE / "task-template"
MODULES = [
    "step2_5_dedup_candidates.py",
    "step3_judge_comments.py",
]


class CodeReviewBenchAdapter:
    def __init__(
        self,
        output_dir: Path,
        limit: int | None = None,
        overwrite: bool = False,
        task_ids: list[str] | None = None,
        source_dir: Path | None = None,
    ):
        self.output_dir = Path(output_dir)
        self.limit, self.overwrite, self.task_ids = limit, overwrite, task_ids
        self.source_dir = source_dir
        if limit is not None and limit < 0:
            raise ValueError("--limit must be nonnegative")

    def run(self) -> None:
        records = json.loads((PACKAGE / "prs.json").read_text())
        if self.task_ids is not None:
            requested = {x.removeprefix("codereviewbench-") for x in self.task_ids}
            if requested - {r["id"] for r in records}:
                raise ValueError("Unknown task ID")
            records = [r for r in records if r["id"] in requested]
        if self.limit is not None:
            records = records[: self.limit]
        records = [
            r
            for r in records
            if self.overwrite
            or not (self.output_dir / ("codereviewbench-" + r["id"])).exists()
        ]
        if not records:
            return
        required = ["offline/code_review_benchmark/" + name for name in MODULES]
        required += ["offline/analysis/score_profiles.py", "LICENSE"]
        files = {}
        if self.source_dir is not None:
            required += [
                p.relative_to(self.source_dir).as_posix()
                for p in (self.source_dir / "offline/golden_comments").glob("*.json")
            ]
            files = {name: (self.source_dir / name).read_bytes() for name in required}
        else:
            url = f"https://api.github.com/repos/withmartian/code-review-benchmark/tarball/{REVISION}"
            with (
                urllib.request.urlopen(url, timeout=120) as response,
                tarfile.open(
                    fileobj=io.BytesIO(response.read()), mode="r:gz"
                ) as archive,
            ):
                for item in archive.getmembers():
                    name = item.name.partition("/")[2]
                    if item.isfile() and (
                        name in required
                        or (
                            name.startswith("offline/golden_comments/")
                            and name.endswith(".json")
                        )
                    ):
                        stream = archive.extractfile(item)
                        if stream is not None:
                            files[name] = stream.read()
        golden = {
            r["url"]: r["comments"]
            for name, data in files.items()
            if name.startswith("offline/golden_comments/") and name.endswith(".json")
            for r in json.loads(data)
        }
        for row in records:
            task_id = "codereviewbench-" + row["id"]
            target = self.output_dir / task_id
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(
                TEMPLATE, target, ignore=shutil.ignore_patterns("__pycache__", "*.pyc")
            )
            for name in MODULES:
                (target / "tests" / name).write_bytes(
                    files["offline/code_review_benchmark/" + name]
                )
            (target / "tests/score_profiles.py").write_bytes(
                files["offline/analysis/score_profiles.py"]
            )
            (target / "tests/UPSTREAM_LICENSE").write_bytes(files["LICENSE"])
            problem = dict(row, golden_comments=golden[row["url"]])
            (target / "tests/problem.json").write_text(json.dumps(problem, indent=2))
            (target / "solution/review.json").write_text(
                json.dumps([r["comment"] for r in golden[row["url"]]], indent=2)
            )
            replacements = {
                "{task_id}": task_id,
                "{repo}": row["repo"],
                "{base}": row["base"],
                "{head}": row["head"],
                "{title}": row["title"],
                "{body}": row["body"],
            }
            # Never interpret braces in PR text as format placeholders.
            for filename in ["task.toml", "instruction.md", "environment/Dockerfile"]:
                text = (TEMPLATE / filename).read_text()
                text = re.sub(
                    r"\{(?:task_id|repo|base|head|title|body)\}",
                    lambda match, values=replacements: values[match[0]],
                    text,
                )
                (target / filename).write_text(text)
