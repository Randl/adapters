"""Generate a documented subset from user-supplied licensed ROMs."""

import ast
import hashlib
import io
import json
import shutil
import tarfile
import tempfile
import urllib.request
from pathlib import Path

import yaml

REVISION = "faab53179cb4babdd102f35cb83c24a5f2c29d05"
TEMPLATE = Path(__file__).parent / "task-template"
GAMES = {
    "kirby": "kirby_dream_land.gb",
    "pokemon_crystal": "pokemon_crystal.gbc",
    "super_mario_land": "super_mario_land.gb",
    "zelda": "zelda_links_awakening.gbc",
}


class VideoGameBenchAdapter:
    def __init__(
        self,
        output_dir: Path,
        rom_dir: Path,
        source_dir: Path | None = None,
        limit: int | None = None,
        overwrite: bool = False,
        task_ids: list[str] | None = None,
        oracle_dir: Path | None = None,
    ):
        self.output_dir = Path(output_dir)
        self.rom_dir, self.source_dir, self.oracle_dir = rom_dir, source_dir, oracle_dir
        self.limit, self.overwrite, self.task_ids = limit, overwrite, task_ids
        if limit is not None and limit < 0:
            raise ValueError("--limit must be nonnegative")

    def run(self) -> None:
        selected = sorted(GAMES)
        if self.task_ids is not None:
            requested = {
                x.removeprefix("videogamebench-")
                .removesuffix("-lite")
                .replace("-", "_")
                for x in self.task_ids
            }
            if requested - set(GAMES):
                raise ValueError(
                    "Only the four released Game Boy checkpoint games are supported"
                )
            selected = [game for game in selected if game in requested]
        if self.limit is not None:
            selected = selected[: self.limit]
        selected = [
            g
            for g in selected
            if self.overwrite
            or not (
                self.output_dir / f"videogamebench-{g.replace('_', '-')}-lite"
            ).exists()
        ]
        for game in selected:
            if not (self.rom_dir / GAMES[game]).is_file():
                raise FileNotFoundError(
                    f"Supply the licensed ROM: {self.rom_dir / GAMES[game]}"
                )
        if not selected:
            return
        with tempfile.TemporaryDirectory() as cache:
            source = self.source_dir
            if source is None:
                source = Path(cache)
                url = f"https://api.github.com/repos/alexzhang13/VideoGameBench/tarball/{REVISION}"
                with (
                    urllib.request.urlopen(url, timeout=180) as response,
                    tarfile.open(
                        fileobj=io.BytesIO(response.read()), mode="r:gz"
                    ) as archive,
                ):
                    # Copy only ordinary files needed by this integration.
                    for item in archive.getmembers():
                        name = item.name.partition("/")[2]
                        if item.isfile() and (
                            name.startswith(("configs/", "src/")) or name == "LICENSE"
                        ):
                            path = source / name
                            if not path.resolve().is_relative_to(source.resolve()):
                                raise ValueError("Unsafe upstream archive path")
                            stream = archive.extractfile(item)
                            if stream is not None:
                                path.parent.mkdir(parents=True, exist_ok=True)
                                path.write_bytes(stream.read())
            for game in selected:
                self.generate(game, source)

    def generate(self, game: str, source: Path) -> None:
        task_id = f"videogamebench-{game.replace('_', '-')}-lite"
        target = self.output_dir / task_id
        config_dir = source / "configs" / game
        config = yaml.safe_load((config_dir / "config.yaml").read_text())
        checkpoints = sorted(
            (config_dir / "checkpoints").glob("*.png"), key=lambda p: int(p.stem)
        )
        if not checkpoints:
            raise ValueError(f"No released checkpoints for {game}")
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(
            TEMPLATE, target, ignore=shutil.ignore_patterns("__pycache__", "*.pyc")
        )
        rom = self.rom_dir / GAMES[game]
        for area in ["environment", "tests"]:
            shutil.copyfile(rom, target / area / "game.gb")
            # The game interface has no access to checkpoint images or rubrics.
            for relative in [
                "src/__init__.py",
                "src/utils.py",
                "src/emulators/__init__.py",
                "src/emulators/interface_base.py",
                "src/emulators/gba/__init__.py",
                "src/emulators/gba/interface.py",
            ]:
                path = target / area / "upstream" / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source / relative, path)
        shutil.copytree(config_dir / "checkpoints", target / "tests/checkpoints")
        evaluator = (source / "src/vgbench_evaluator.py").read_text()
        base = next(
            n
            for n in ast.parse(evaluator).body
            if isinstance(n, ast.ClassDef) and n.name == "BaseVGBenchEvaluator"
        )
        checker_source = ast.get_source_segment(evaluator, base)
        if checker_source is None:
            raise ValueError("Cannot extract upstream checkpoint class")
        (target / "tests/checkpoint.py").write_text(
            "from abc import ABC, abstractmethod\nfrom typing import List, Callable, Optional, Dict, Any\n"
            "from src.utils import hash_image, is_same_hash\n" + checker_source + "\n"
        )
        info = {
            "game": game,
            "task_id": task_id,
            "threshold": config.get("threshold", 10),
            "max_steps": 15000,
            "action_frames": 15,
            "upstream_revision": REVISION,
            "rom_sha256": hashlib.sha256(rom.read_bytes()).hexdigest(),
        }
        for area in ["environment", "tests"]:
            (target / area / "game.json").write_text(json.dumps(info, indent=2))
            shutil.copyfile(source / "LICENSE", target / area / "UPSTREAM_LICENSE")
        prompt = (
            (TEMPLATE / "instruction.md")
            .read_text()
            .replace("{game_prompt}", (config_dir / "prompt.txt").read_text())
        )
        (target / "instruction.md").write_text(prompt)
        (target / "task.toml").write_text(
            (TEMPLATE / "task.toml").read_text().replace("{task_id}", task_id)
        )
        if self.oracle_dir is not None:
            shutil.copyfile(
                self.oracle_dir / f"{game}.json", target / "solution/actions.json"
            )
