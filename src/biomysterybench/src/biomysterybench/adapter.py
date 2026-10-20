"""Generate self-contained tasks from the pinned, gated BioMysteryBench release."""

import csv
import json
import re
import shutil
import stat
from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import ZipFile

from huggingface_hub import hf_hub_download

from .judge import DEFAULT_BASE_URL, endpoint_host

REPO = "Anthropic/BioMysteryBench-full"
REVISION = "b5a889c4757214ec9a6ade876b734f920a7799db"
TEMPLATE = Path(__file__).parent / "task-template"
RELEASED_DOMAINS = frozenset(
    {
        "conda.anaconda.org",
        "repo.anaconda.com",
        "ncbi.nlm.nih.gov",
        "ftp.ncbi.nlm.nih.gov",
        "ensembl.org",
        "ftp.ensembl.org",
        "hgdownload.soe.ucsc.edu",
        "uniprot.org",
        "bioconductor.org",
        "pypi.org",
        "bioconda.github.io",
        "cran.r-project.org",
        "cran.rstudio.com",
        "ftp.ebi.ac.uk",
    }
)


def allowed_hosts(value: str) -> list[str]:
    """Accept only the pinned release's database/package domains."""
    domains = {x.strip() for x in value.split(",") if x.strip()}
    if not domains or domains - RELEASED_DOMAINS:
        raise ValueError(f"Unexpected source domains: {sorted(domains)}")
    return sorted(domains | {"*." + x for x in domains} | {"files.pythonhosted.org"})


class BioMysteryBenchAdapter:
    def __init__(
        self,
        output_dir: Path,
        limit: int | None = None,
        overwrite: bool = False,
        task_ids: list[str] | None = None,
        data_dir: Path | None = None,
        oracle_dir: Path | None = None,
        split: str = "full",
        judge_base_url: str = DEFAULT_BASE_URL,
    ):
        self.output_dir = Path(output_dir)
        self.limit, self.overwrite, self.task_ids = limit, overwrite, task_ids
        self.data_dir, self.oracle_dir, self.split = data_dir, oracle_dir, split
        self.judge_base_url = judge_base_url.rstrip("/")
        self.judge_host = endpoint_host(self.judge_base_url)
        if limit is not None and limit < 0:
            raise ValueError("--limit must be nonnegative")

    def source(self, name: str) -> Path:
        if self.data_dir is not None:
            return self.data_dir / name
        return Path(hf_hub_download(REPO, name, repo_type="dataset", revision=REVISION))

    def run(self) -> None:
        with self.source("problems.csv").open(newline="") as stream:
            rows = sorted(csv.DictReader(stream), key=lambda row: row["id"])
        ids = [row["id"] for row in rows]
        if len(ids) != len(set(ids)) or any(
            not re.fullmatch(r"[a-z0-9]+", x) for x in ids
        ):
            raise ValueError("Duplicate or unsafe problem IDs")
        if self.split != "full":
            flag = "yes" if self.split == "human-solvable" else "no"
            rows = [r for r in rows if r["human_solvable"] == flag]
        if self.task_ids is not None:
            requested = {s.removeprefix("biomysterybench-") for s in self.task_ids}
            missing = requested - {r["id"] for r in rows}
            if missing:
                raise ValueError(f"Unknown task IDs in split: {sorted(missing)}")
            rows = [r for r in rows if r["id"] in requested]
        if self.limit is not None:
            rows = rows[: self.limit]
        for row in rows:
            task_id = "biomysterybench-" + row["id"]
            target = self.output_dir / task_id
            if target.exists() and not self.overwrite:
                continue
            # Validate all archive entries before extracting any file.
            with ZipFile(self.source(f"data/{row['id']}.zip")) as archive:
                for entry in archive.infolist():
                    path = Path(entry.filename)
                    if (
                        path.is_absolute()
                        or ".." in path.parts
                        or stat.S_ISLNK(entry.external_attr >> 16)
                    ):
                        raise ValueError(f"Unsafe archive member: {entry.filename}")
                # Stage beside the output directory so extraction/copy failures
                # cannot leave a partially generated task or destroy an old one.
                self.output_dir.parent.mkdir(parents=True, exist_ok=True)
                with TemporaryDirectory(
                    prefix=f".{task_id}-", dir=self.output_dir.parent
                ) as directory:
                    staging = Path(directory) / "task"
                    shutil.copytree(
                        TEMPLATE,
                        staging,
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
                    )
                    archive.extractall(staging / "environment/data")
                    self._write_task(staging, task_id, row)
                    self.output_dir.mkdir(parents=True, exist_ok=True)
                    backup = Path(directory) / "previous"
                    if target.exists():
                        target.rename(backup)
                    try:
                        staging.rename(target)
                    except BaseException:
                        if backup.exists():
                            backup.rename(target)
                        raise

    def _write_task(self, target: Path, task_id: str, row: dict[str, str]) -> None:
        (target / "instruction.md").write_text(
            (TEMPLATE / "instruction.md")
            .read_text()
            .replace("{question}", row["question"])
        )
        hosts = allowed_hosts(row["allowed_domains"])
        config = (TEMPLATE / "task.toml").read_text().replace("{task_id}", task_id)
        config = config.replace("{allowed_hosts}", json.dumps(hosts))
        config = config.replace("{source_id}", row["id"])
        config = config.replace("{human_solvable}", row["human_solvable"])
        config = config.replace("{judge_base_url}", json.dumps(self.judge_base_url))
        config = config.replace("{judge_allowed_hosts}", json.dumps([self.judge_host]))
        (target / "task.toml").write_text(config)
        shutil.copyfile(Path(__file__).with_name("judge.py"), target / "tests/judge.py")
        (target / "tests/problem.json").write_text(json.dumps(row, indent=2))
        if self.oracle_dir is not None:
            shutil.copyfile(
                self.oracle_dir / f"{row['id']}.txt", target / "solution/answer.txt"
            )
            shutil.copyfile(
                self.oracle_dir / f"{row['id']}.md", target / "solution/report.md"
            )
