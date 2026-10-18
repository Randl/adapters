import json
import subprocess
import tomllib

import pytest

from decbench.adapter import DecBenchAdapter, function_address
from decbench.metric import aggregate


@pytest.fixture
def dataset(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "sources").mkdir()
    (source / "sources/test.c").write_text("int target(int x) { return x + 1; }\n")
    subprocess.run(
        [
            "gcc",
            "-g",
            "-O0",
            "-c",
            str(source / "sources/test.c"),
            "-o",
            str(source / "target.o"),
        ],
        check=True,
    )
    import hashlib

    checksum = hashlib.sha256((source / "target.o").read_bytes()).hexdigest()
    manifest = {
        "projects": {"example": {"sources": ["sources/test.c"]}},
        "binaries": [
            {
                "project": "example",
                "opt": "O0",
                "binary": "target",
                "binary_path": "target.o",
                "sha256": checksum,
                "functions": ["target"],
            }
        ],
    }
    path = source / "configs/sample-set"
    path.mkdir(parents=True)
    (path / "manifest.json").write_text(json.dumps(manifest))
    (path / "function_results.json").write_text(
        json.dumps(
            {
                "groups": [
                    {
                        "project": "example",
                        "opt_level": "O0",
                        "binary": "target",
                        "functions": [
                            {
                                "function": "target",
                                "values": {
                                    "reference": {
                                        "ged": 0,
                                        "type_match": 1,
                                        "byte_match": 1,
                                    }
                                },
                            }
                        ],
                    }
                ]
            }
        )
    )
    return source


def test_generation_strips_debug_and_keeps_references_private(tmp_path, dataset):
    output = tmp_path / "tasks"
    DecBenchAdapter(output, data_dir=dataset).run()
    task = next(output.iterdir())
    config = tomllib.loads((task / "task.toml").read_text())
    assert config["verifier"]["environment_mode"] == "separate"
    sections = subprocess.check_output(
        ["readelf", "-S", str(task / "environment/target.bin")], text=True
    )
    assert ".debug_info" not in sections and ".symtab" not in sections
    assert (task / "tests/original.bin").read_bytes() == (
        dataset / "target.o"
    ).read_bytes()
    assert not (task / "environment/sources").exists()
    assert function_address(dataset / "target.o", "target") == 0
    before = (task / "task.toml").read_bytes()
    DecBenchAdapter(output, data_dir=dataset, overwrite=True).run()
    assert before == (task / "task.toml").read_bytes()


def test_checksum_and_selection(tmp_path, dataset):
    with pytest.raises(ValueError):
        DecBenchAdapter(
            tmp_path / "tasks", data_dir=dataset, task_ids=["unknown"]
        ).run()
    with pytest.raises(ValueError):
        DecBenchAdapter(tmp_path / "tasks", limit=-1)
    with (dataset / "target.o").open("ab") as stream:
        stream.write(b"tampered")
    with pytest.raises(ValueError, match="checksum"):
        DecBenchAdapter(tmp_path / "tasks", data_dir=dataset).run()


def test_measured_denominators():
    rows = [
        {
            "union": 1,
            "ged_measured": 1,
            "ged_perfect": 1,
            "type_match_measured": 1,
            "type_match_perfect": 0,
            "byte_match_measured": 0,
            "byte_match_perfect": 0,
        },
        {
            "union": 0,
            "ged_measured": 1,
            "ged_perfect": 0,
            "type_match_measured": 1,
            "type_match_perfect": 0,
            "byte_match_measured": 1,
            "byte_match_perfect": 0,
        },
    ]
    assert aggregate(rows) == {"union": 50, "ged": 50, "type_match": 0, "byte_match": 0}
    with pytest.raises(ValueError):
        aggregate([None])


def test_unmeasurable_functions_do_not_enter_union():
    row = {
        "union": 1,
        "ged_measured": 1,
        "ged_perfect": 1,
        "type_match_measured": 0,
        "type_match_perfect": 0,
        "byte_match_measured": 0,
        "byte_match_perfect": 0,
    }
    unmeasurable = dict.fromkeys(row, 0)
    assert aggregate([row, unmeasurable]) == {"union": 100, "ged": 100}
