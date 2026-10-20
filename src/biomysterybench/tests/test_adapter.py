import csv
import importlib.util
import json
import stat
import subprocess
import sys
import tomllib
from pathlib import Path
from types import SimpleNamespace
from zipfile import ZipFile, ZipInfo

import pytest

from biomysterybench.adapter import TEMPLATE, BioMysteryBenchAdapter


def source(tmp_path):
    data = tmp_path / "source"
    (data / "data").mkdir(parents=True)
    with (data / "problems.csv").open("w", newline="") as f:
        writer = csv.DictWriter(
            f, ["id", "question", "answer_rubric", "allowed_domains", "human_solvable"]
        )
        writer.writeheader()
        for name, human in [("hb001", "yes"), ("hb002", "no")]:
            writer.writerow(
                {
                    "id": name,
                    "question": "Identify the tissue.",
                    "answer_rubric": "PRIVATE_EXPECTED_ANSWER",
                    "allowed_domains": "ncbi.nlm.nih.gov",
                    "human_solvable": human,
                }
            )
            with ZipFile(data / f"data/{name}.zip", "w") as archive:
                archive.writestr("reads.txt", "public input")
    return data


def test_generate_filter_and_isolation(tmp_path):
    data, output = source(tmp_path), tmp_path / "tasks"
    BioMysteryBenchAdapter(output, data_dir=data, split="human-solvable").run()
    task = output / "biomysterybench-hb001"
    config = tomllib.loads((task / "task.toml").read_text())
    assert config["task"]["name"] == "anthropic/biomysterybench-hb001"
    assert config["verifier"]["environment_mode"] == "separate"
    assert config["environment"]["network_mode"] == "allowlist"
    assert config["verifier"]["environment"]["allowed_hosts"] == ["api.openai.com"]
    assert not {
        "api.openai.com",
        "api.anthropic.com",
        "huggingface.co",
        "github.com",
    } & set(config["environment"]["allowed_hosts"])
    assert "PRIVATE_EXPECTED_ANSWER" not in (task / "instruction.md").read_text()
    assert all(
        "PRIVATE_EXPECTED_ANSWER" not in p.read_text()
        for p in (task / "environment").rglob("*")
        if p.is_file()
    )
    before = {
        str(p.relative_to(task)): p.read_bytes() for p in task.rglob("*") if p.is_file()
    }
    BioMysteryBenchAdapter(
        output, data_dir=data, task_ids=["hb001"], overwrite=True
    ).run()
    assert before == {
        str(p.relative_to(task)): p.read_bytes() for p in task.rglob("*") if p.is_file()
    }
    (task / "marker").touch()
    BioMysteryBenchAdapter(output, data_dir=data, limit=1).run()
    assert (task / "marker").exists()


@pytest.mark.parametrize(
    "domain", ["huggingface.co", "*.org", "github.com", "ncbi.nlm.nih.gov.evil.test"]
)
def test_source_cannot_expand_network_access(domain):
    from biomysterybench.adapter import allowed_hosts

    with pytest.raises(ValueError, match="Unexpected source domains"):
        allowed_hosts(domain)


@pytest.mark.parametrize("member", ["../escape", "/absolute", "link"])
def test_reject_unsafe_archive(tmp_path, member):
    data = source(tmp_path)
    with ZipFile(data / "data/hb001.zip", "w") as archive:
        info = ZipInfo(member)
        if member == "link":
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
        archive.writestr(info, "unsafe")
    output = tmp_path / "tasks"
    with pytest.raises(ValueError):
        BioMysteryBenchAdapter(output, data_dir=data, limit=1).run()
    assert not output.exists()


def test_unknown_ids_and_limits(tmp_path):
    data = source(tmp_path)
    with pytest.raises(ValueError):
        BioMysteryBenchAdapter(
            tmp_path / "out", data_dir=data, task_ids=["missing"]
        ).run()
    with pytest.raises(ValueError):
        BioMysteryBenchAdapter(tmp_path / "out", limit=-1)
    BioMysteryBenchAdapter(tmp_path / "out", data_dir=data, limit=0).run()
    assert not (tmp_path / "out").exists()


@pytest.mark.parametrize("overwrite", [False, True])
def test_missing_oracle_report_preserves_destination_and_allows_retry(
    tmp_path, overwrite
):
    data, output = source(tmp_path), tmp_path / "tasks"
    task = output / "biomysterybench-hb001"
    before = {}
    if overwrite:
        BioMysteryBenchAdapter(output, data_dir=data, limit=1).run()
        before = {
            p.relative_to(task): p.read_bytes() for p in task.rglob("*") if p.is_file()
        }
    oracle = tmp_path / "oracle"
    oracle.mkdir()
    (oracle / "hb001.txt").write_text("independent answer")
    adapter = BioMysteryBenchAdapter(
        output, data_dir=data, oracle_dir=oracle, limit=1, overwrite=overwrite
    )
    with pytest.raises(FileNotFoundError):
        adapter.run()
    if overwrite:
        assert before == {
            p.relative_to(task): p.read_bytes() for p in task.rglob("*") if p.is_file()
        }
    else:
        assert not task.exists()
    (oracle / "hb001.md").write_text("independent analysis")
    adapter.run()
    assert (task / "solution/answer.txt").read_text() == "independent answer"
    assert (task / "solution/report.md").read_text() == "independent analysis"


@pytest.mark.parametrize("failure", [OSError, KeyboardInterrupt])
def test_interrupted_extraction_does_not_publish_partial_task(
    tmp_path, monkeypatch, failure
):
    data, output = source(tmp_path), tmp_path / "tasks"
    extract = ZipFile.extractall

    def interrupted_extract(archive, path):
        extract(archive, path)
        raise failure("interrupted extraction")

    adapter = BioMysteryBenchAdapter(output, data_dir=data, limit=1)
    with monkeypatch.context() as patch:
        patch.setattr(ZipFile, "extractall", interrupted_extract)
        with pytest.raises(failure):
            adapter.run()
    assert not (output / "biomysterybench-hb001").exists()
    adapter.run()
    assert (output / "biomysterybench-hb001/environment/data/reads.txt").exists()


def test_failed_publish_restores_existing_task(tmp_path, monkeypatch):
    data, output = source(tmp_path), tmp_path / "tasks"
    adapter = BioMysteryBenchAdapter(output, data_dir=data, limit=1)
    adapter.run()
    task = output / "biomysterybench-hb001"
    (task / "marker").write_text("old task")
    rename = Path.rename

    def failed_publish(path, destination):
        if path.name == "task" and destination == task:
            raise OSError("failed to publish")
        return rename(path, destination)

    with monkeypatch.context() as patch:
        patch.setattr(Path, "rename", failed_publish)
        adapter.overwrite = True
        with pytest.raises(OSError, match="failed to publish"):
            adapter.run()
    assert (task / "marker").read_text() == "old task"
    assert (task / "environment/data/reads.txt").exists()
    adapter.run()
    assert not (task / "marker").exists()


def test_judge_failures_are_not_scores():
    spec = importlib.util.spec_from_file_location(
        "bio_verify", TEMPLATE / "tests/verify.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    def client(content):
        response = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
        )
        return SimpleNamespace(
            chat=SimpleNamespace(
                completions=SimpleNamespace(create=lambda **kwargs: response)
            )
        )

    problem = {"question": "Q", "answer_rubric": "A"}
    assert module.grade(problem, "A", "analysis", client('{"score": 1}'))["score"] == 1
    for value in ['{"score": true}', '{"score": 0.5}', "invalid"]:
        with pytest.raises(ValueError):
            module.grade(problem, "A", "analysis", client(value))

    class Broken:
        def create(self, **kwargs):
            raise TimeoutError("provider down")

    with pytest.raises(TimeoutError):
        module.grade(
            problem,
            "A",
            "analysis",
            SimpleNamespace(chat=SimpleNamespace(completions=Broken())),
        )


def test_partition_metrics():
    from biomysterybench.metric import aggregate

    rows = [
        {"correct": 1, "human_solvable": 1},
        {"correct": 0, "human_solvable": 1},
        {"correct": 0, "human_solvable": 0},
    ]
    assert aggregate(rows) == {
        "n_verified": 3,
        "n_missing": 0,
        "human_solvable_accuracy": 0.5,
        "human_difficult_accuracy": 0,
    }
    assert aggregate(rows[:2]) == {
        "n_verified": 2,
        "n_missing": 0,
        "human_solvable_accuracy": 0.5,
    }


@pytest.mark.parametrize(
    ("rewards", "expected"),
    [
        ([], {"n_verified": 0, "n_missing": 0}),
        ([None], {"n_verified": 0, "n_missing": 1}),
        (
            [{"correct": 1, "human_solvable": 1}, None],
            {"n_verified": 1, "n_missing": 1},
        ),
    ],
)
def test_metric_cli_handles_incomplete_runs(tmp_path, rewards, expected):
    source = tmp_path / "rewards.jsonl"
    output = tmp_path / "metrics.json"
    source.write_text("".join(json.dumps(row) + "\n" for row in rewards))
    subprocess.run(
        [
            sys.executable,
            str(TEMPLATE.parent / "metric.py"),
            "-i",
            str(source),
            "-o",
            str(output),
        ],
        check=True,
    )
    assert json.loads(output.read_text()) == expected
