import csv
import importlib.util
import stat
import tomllib
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
        "human_solvable_accuracy": 0.5,
        "human_difficult_accuracy": 0,
    }
    assert aggregate(rows[:2]) == {"human_solvable_accuracy": 0.5}
    with pytest.raises(ValueError):
        aggregate([None])
