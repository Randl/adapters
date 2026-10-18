"""Adapt the frozen sample-set without exposing DWARF, source CFGs or sources."""

import hashlib
import json
import math
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from elftools.elf.elffile import ELFFile
from huggingface_hub import hf_hub_download

REPO = "noelo-lab/decbench-dataset"
REVISION = "815eb96f130b6d2ef7fa600e04669bf20139bf27"
UPSTREAM = "ae070b885b4e005ed37510a2c3445af6284dc2b9"
TEMPLATE = Path(__file__).parent / "task-template"


def function_address(binary: Path, name: str) -> int:
    if binary.read_bytes()[:2] == b"MZ":
        # GNU objcopy exposes PE DWARF as ELF without changing its stored PCs.
        header = subprocess.check_output(["objdump", "-f", str(binary)], text=True)
        target = "elf64-x86-64" if "pei-x86-64" in header else "elf32-i386"
        with tempfile.TemporaryDirectory() as directory:
            dwarf_elf = Path(directory) / "dwarf.elf"
            subprocess.run(
                ["objcopy", "-O", target, str(binary), str(dwarf_elf)], check=True
            )
            return function_address(dwarf_elf, name)
    with binary.open("rb") as stream:
        elf = ELFFile(stream)
        # Match a real defining DIE, rather than an imported declaration.
        dwarf = elf.get_dwarf_info()
        matches = set()
        for unit in dwarf.iter_CUs():
            for die in unit.iter_DIEs():
                if (
                    die.tag != "DW_TAG_subprogram"
                    or "DW_AT_low_pc" not in die.attributes
                ):
                    continue
                origin = die
                while "DW_AT_abstract_origin" in origin.attributes:
                    origin = origin.get_DIE_from_attribute("DW_AT_abstract_origin")
                attr = origin.attributes.get("DW_AT_name")
                if attr and attr.value.decode(errors="replace") == name:
                    matches.add(die.attributes["DW_AT_low_pc"].value)
        if not matches:
            raise ValueError(f"No DWARF definition for {name}")
        # Upstream name_to_addr resolves ambiguous definitions to the lowest PC.
        return min(matches)


class DecBenchAdapter:
    def __init__(
        self,
        output_dir: Path,
        limit: int | None = None,
        overwrite: bool = False,
        task_ids: list[str] | None = None,
        data_dir: Path | None = None,
        oracle_dir: Path | None = None,
    ):
        self.output_dir = Path(output_dir)
        self.limit, self.overwrite, self.task_ids = limit, overwrite, task_ids
        self.data_dir, self.oracle_dir = data_dir, oracle_dir
        if limit is not None and limit < 0:
            raise ValueError("--limit must be nonnegative")

    def source(self, name: str) -> Path:
        if self.data_dir is not None:
            return self.data_dir / name
        return Path(hf_hub_download(REPO, name, repo_type="dataset", revision=REVISION))

    def run(self) -> None:
        manifest = json.loads(
            self.source("configs/sample-set/manifest.json").read_text()
        )
        scores = json.loads(
            self.source("configs/sample-set/function_results.json").read_text()
        )
        eligibility = {
            (g["project"], g["opt_level"], g["binary"], f["function"]): {
                metric: any(
                    metric in values and math.isfinite(values[metric])
                    for values in f["values"].values()
                )
                for metric in ("ged", "type_match", "byte_match")
            }
            for g in scores["groups"]
            for f in g["functions"]
        }
        records = []
        for binary in manifest["binaries"]:
            for function in binary["functions"]:
                key = "-".join(
                    [binary["project"], binary["opt"], binary["binary"], function]
                )
                slug = re.sub(r"[^a-z0-9-]+", "-", key.lower()).strip("-")
                # Preserve distinct upstream names that sanitize to the same slug.
                task_id = (
                    "decbench-"
                    + slug[:100]
                    + "-"
                    + hashlib.sha256(key.encode()).hexdigest()[:10]
                )
                records.append((task_id, binary, function))
        records.sort(key=lambda x: x[0])
        if len({r[0] for r in records}) != len(records):
            raise ValueError("Duplicate generated task IDs")
        if self.task_ids is not None:
            requested = set(self.task_ids)
            if requested - {r[0] for r in records}:
                raise ValueError("Unknown task ID")
            records = [r for r in records if r[0] in requested]
        if self.limit is not None:
            records = records[: self.limit]
        for task_id, binary, function in records:
            target = self.output_dir / task_id
            if target.exists() and not self.overwrite:
                continue
            original = self.source(binary["binary_path"])
            if hashlib.sha256(original.read_bytes()).hexdigest() != binary["sha256"]:
                raise ValueError(f"Binary checksum mismatch: {binary['binary_path']}")
            address = function_address(original, function)
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(
                TEMPLATE, target, ignore=shutil.ignore_patterns("__pycache__", "*.pyc")
            )
            shutil.copyfile(original, target / "tests/original.bin")
            with original.open("rb") as stream:
                machine = (
                    ELFFile(stream)["e_machine"]
                    if stream.read(4) == b"\x7fELF"
                    else "PE"
                )
            stripper = "arm-none-eabi-objcopy" if machine == "EM_ARM" else "objcopy"
            subprocess.run(
                [
                    stripper,
                    "--strip-all",
                    str(original),
                    str(target / "environment/target.bin"),
                ],
                check=True,
            )
            for source in manifest["projects"][binary["project"]]["sources"]:
                destination = target / "tests/sources" / Path(source).name
                destination.parent.mkdir(exist_ok=True)
                shutil.copyfile(self.source(source), destination)
            (target / "environment/target.bin").chmod(0o444)
            info = {
                "task_id": task_id,
                "function": function,
                "address": address,
                "project": binary["project"],
                "opt": binary["opt"],
                "binary": binary["binary"],
                "measurable": eligibility[
                    (binary["project"], binary["opt"], binary["binary"], function)
                ],
                "dataset_revision": REVISION,
                "upstream_revision": UPSTREAM,
            }
            (target / "tests/problem.json").write_text(json.dumps(info, indent=2))
            prompt = (TEMPLATE / "instruction.md").read_text()
            prompt = prompt.replace("{function}", function).replace(
                "{address}", hex(address)
            )
            (target / "instruction.md").write_text(prompt)
            config = (TEMPLATE / "task.toml").read_text().replace("{task_id}", task_id)
            (target / "task.toml").write_text(config)
            if self.oracle_dir is not None:
                shutil.copyfile(
                    self.oracle_dir / f"{task_id}.c", target / "solution/decompiled.c"
                )
