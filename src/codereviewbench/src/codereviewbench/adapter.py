"""Generate PR review tasks with upstream extraction, deduplication and scoring."""

import hashlib
import io
import json
import re
import shutil
import tarfile
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

from .judge_client import parse_temperature

REVISION = "e616e849755441da38f18bf3adba2c9583b03803"
PACKAGE = Path(__file__).parent
TEMPLATE = PACKAGE / "task-template"
MODULES = [
    "step2_5_dedup_candidates.py",
    "step3_judge_comments.py",
]


def validate_source(files: dict[str, bytes]) -> None:
    """Reject partial, modified or mismatched upstream inputs before writing tasks."""
    hashes = json.loads((PACKAGE / "upstream_hashes.json").read_text())
    for name, expected in hashes.items():
        if name not in files or hashlib.sha256(files[name]).hexdigest() != expected:
            raise ValueError(f"Upstream content does not match {REVISION}: {name}")


def sanity_ids(per_project: int = 2) -> list[str]:
    """Two PRs per project, selected by ID hash without consulting scores."""
    records = json.loads((PACKAGE / "prs.json").read_text())

    def project(row):
        return next(
            p
            for p in ("cal", "discourse", "grafana", "keycloak", "sentry")
            if p in row["repo"]
        )

    return [
        row["id"]
        for repo in sorted({project(r) for r in records})
        for row in sorted(
            (r for r in records if project(r) == repo),
            key=lambda r: hashlib.sha256(r["id"].encode()).hexdigest(),
        )[:per_project]
    ]


class CodeReviewBenchAdapter:
    def __init__(
        self,
        output_dir: Path,
        limit: int | None = None,
        overwrite: bool = False,
        task_ids: list[str] | None = None,
        source_dir: Path | None = None,
        split: str = "full",
        judge_model: str = "anthropic/claude-sonnet-4-5-20250929",
        judge_base_url: str = "https://api.withmartian.com/v1",
        judge_temperature: str = "0",
    ):
        self.output_dir = Path(output_dir)
        self.limit, self.overwrite, self.task_ids = limit, overwrite, task_ids
        self.source_dir = source_dir
        self.split = split
        self.judge_model, self.judge_base_url = judge_model, judge_base_url
        parse_temperature(judge_temperature)
        self.judge_temperature = judge_temperature
        url = urlsplit(judge_base_url)
        if url.scheme != "https" or not url.hostname or url.username or url.password:
            raise ValueError(
                "Judge endpoint must be HTTPS without embedded credentials"
            )
        if split not in {"full", "parity", "sanity"}:
            raise ValueError("Unknown split")
        if limit is not None and limit < 0:
            raise ValueError("--limit must be nonnegative")

    def run(self) -> None:
        records = json.loads((PACKAGE / "prs.json").read_text())
        if self.split == "sanity":
            ids = sanity_ids()
            records = [r for r in records if r["id"] in ids]
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
        required = list(json.loads((PACKAGE / "upstream_hashes.json").read_text()))
        files = {}
        if self.source_dir is not None:
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
                    if item.isfile() and name in required:
                        stream = archive.extractfile(item)
                        if stream is not None:
                            files[name] = stream.read()
        validate_source(files)
        golden = {
            r["url"]: r["comments"]
            for name, data in files.items()
            if name.startswith("offline/golden_comments/") and name.endswith(".json")
            for r in json.loads(data)
        }
        for row in records:
            task_id = "codereviewbench-" + row["id"]
            target = self.output_dir / task_id
            if target.is_symlink():
                raise ValueError(f"Refusing symlink output: {target}")
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(
                TEMPLATE, target, ignore=shutil.ignore_patterns("__pycache__", "*.pyc")
            )
            for name in MODULES:
                (target / "tests" / name).write_bytes(
                    files["offline/code_review_benchmark/" + name]
                )
            shutil.copyfile(
                PACKAGE / "judge_client.py", target / "tests/judge_client.py"
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
                "{judge_model}": json.dumps(self.judge_model),
                "{judge_base_url}": json.dumps(self.judge_base_url),
                "{judge_temperature}": json.dumps(self.judge_temperature),
                "{judge_host}": json.dumps(urlsplit(self.judge_base_url).hostname),
            }
            # Never interpret braces in PR text as format placeholders.
            for filename in ["task.toml", "instruction.md", "environment/Dockerfile"]:
                text = (TEMPLATE / filename).read_text()
                text = re.sub(
                    "|".join(re.escape(key) for key in replacements),
                    lambda match, values=replacements: values[match[0]],
                    text,
                )
                (target / filename).write_text(text)
