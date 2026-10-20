import csv
import importlib.util
import json
import sys
import tomllib
from pathlib import Path
from zipfile import ZipFile

import pytest


@pytest.fixture
def prepare():
    path = Path(__file__).parents[1] / "experiments/prepare.py"
    spec = importlib.util.spec_from_file_location("bio_prepare", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_resume_interrupted_preparation_uses_source_and_is_idempotent(
    prepare, tmp_path, monkeypatch
):
    source = tmp_path / "source"
    (source / "data").mkdir(parents=True)
    with (source / "problems.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(
            stream,
            ["id", "question", "answer_rubric", "allowed_domains", "human_solvable"],
        )
        writer.writeheader()
        for index in range(90):
            name = f"hb{index:03d}"
            writer.writerow(
                {
                    "id": name,
                    "question": "Identify the tissue.",
                    "answer_rubric": "Liver. " + prepare.SCORING_SUFFIX,
                    "allowed_domains": "ncbi.nlm.nih.gov",
                    "human_solvable": "yes" if index < 73 else "no",
                }
            )
            with ZipFile(source / f"data/{name}.zip", "w") as archive:
                archive.writestr("reads.txt", f"input {index}")
    monkeypatch.setattr(
        prepare.BioMysteryBenchAdapter, "source", lambda self, name: source / name
    )
    output = tmp_path / "datasets"
    data = tmp_path / "shared-inputs"
    argv = ["prepare.py", "--datasets-dir", str(output), "--data-dir", str(data)]
    monkeypatch.setattr(sys, "argv", argv)
    extract = ZipFile.extractall
    calls = 0

    def interrupted(archive, path):
        nonlocal calls
        calls += 1
        extract(archive, path)
        if calls == 2:
            raise OSError("interrupted extraction")

    with monkeypatch.context() as patch:
        patch.setattr(ZipFile, "extractall", interrupted)
        with pytest.raises(OSError, match="interrupted"):
            prepare.main()
    parity = output / "biomysterybench-parity"
    evidence = output / "biomysterybench-preparation"
    assert (data / "hb000/reads.txt").read_text() == "input 0"
    assert not (data / "hb001").exists()
    assert json.loads((evidence / "manifest.json").read_text())["status"] == "preparing"
    with pytest.raises(FileExistsError, match="--resume"):
        prepare.main()

    monkeypatch.setattr(sys, "argv", [*argv, "--resume"])
    prepare.main()
    oracle = output / "biomysterybench-gt-oracle"
    task = parity / "biomysterybench-hb000"
    config = tomllib.loads((task / "task.toml").read_text())
    assert config["environment"]["allowed_hosts"].count("reactome.org") == 1
    assert not (task / "solution/answer.txt").exists()
    assert (oracle / task.name / "solution/answer.txt").read_text() == "Liver.\n"
    assert len(list(parity.iterdir())) == len(list(oracle.iterdir())) == 90
    for root in (parity, oracle):
        environment = root / task.name / "environment"
        assert not (environment / "data").exists()
        compose = json.loads((environment / "docker-compose.yaml").read_text())
        mount = compose["services"]["main"]["volumes"]
        assert mount == [
            {
                "type": "bind",
                "source": str(data / "hb000"),
                "target": "/workspace/data",
                "read_only": True,
                "bind": {"create_host_path": False},
            }
        ]
        assert "COPY data" not in (environment / "Dockerfile").read_text()
    assert not (task / "solution/report.md").exists()
    assert config["verifier"]["environment_mode"] == "separate"
    manifest = (evidence / "manifest.json").read_text()
    assert json.loads(manifest)["status"] == "prepared_not_run"

    # Rebuild small metadata only; never request ZIPs or rewrite shared inputs.
    def cached_inputs_only(self, name):
        assert name == "problems.csv", "Existing data must not fetch any archive"
        return source / name

    monkeypatch.setattr(prepare.BioMysteryBenchAdapter, "source", cached_inputs_only)
    input_stat = (data / "hb000/reads.txt").stat()
    (oracle / task.name / "stale.txt").write_text("stale")
    prepare.main()
    assert (data / "hb000/reads.txt").stat().st_ino == input_stat.st_ino
    assert (data / "hb000/reads.txt").stat().st_mtime_ns == input_stat.st_mtime_ns
    assert not (oracle / task.name / "stale.txt").exists()
    assert (evidence / "manifest.json").read_text() == manifest
    assert (task / "task.toml").read_text().count('"reactome.org"') == 1


@pytest.mark.parametrize("failure", ["copy", "publish"])
def test_oracle_rebuild_failure_preserves_previous_task(
    prepare, tmp_path, monkeypatch, failure
):
    target = tmp_path / "oracle/task"
    target.mkdir(parents=True)
    (target / "marker").write_text("previous fixture")
    if failure == "copy":

        def fail_copy(*args, **kwargs):
            raise OSError("interrupted copy")

        monkeypatch.setattr(prepare.shutil, "copytree", fail_copy)
    else:
        rename = Path.rename

        def fail_publish(path, destination):
            if path.name == "task" and path != target and destination == target:
                raise OSError("interrupted publish")
            return rename(path, destination)

        monkeypatch.setattr(Path, "rename", fail_publish)
    with pytest.raises(OSError, match="interrupted"):
        prepare.prepare_task(
            prepare.BioMysteryBenchAdapter(tmp_path / "unused"),
            {
                "id": "hb001",
                "question": "Identify the tissue.",
                "answer_rubric": "Liver.",
                "human_solvable": "yes",
                "allowed_domains": "ncbi.nlm.nih.gov",
            },
            target,
            tmp_path / "inputs/hb001",
            "Liver.",
        )
    assert (target / "marker").read_text() == "previous fixture"
    assert not (target / "solution/answer.txt").exists()


def test_supplied_data_reused_without_downloading(prepare, tmp_path):
    data = tmp_path / "provided"
    (data / "hb001").mkdir(parents=True)
    (data / "hb001/input.txt").write_text("input")

    class NoDownloads:
        def source(self, name):
            pytest.fail(f"Unexpected download: {name}")

    assert prepare.prepare_input(NoDownloads(), "hb001", data) == data / "hb001"


def test_input_symlink_cannot_expose_private_files(prepare, tmp_path):
    data = tmp_path / "provided"
    (data / "hb001").mkdir(parents=True)
    (data / "hb001/link").symlink_to(tmp_path / "private-answers")
    with pytest.raises(ValueError, match="Unsupported input"):
        prepare.prepare_input(None, "hb001", data)
