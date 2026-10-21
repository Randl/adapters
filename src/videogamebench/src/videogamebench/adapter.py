"""Generate all twenty public benchmark games using the pinned upstream harness."""

import ast
import hashlib
import io
import json
import secrets
import shutil
import tarfile
import tempfile
import urllib.request
from pathlib import Path

import yaml

from .settings import DEV_GAMES, PARITY_GAMES, REVISION, TEST_GAMES, Settings

TEMPLATE = Path(__file__).parent / "task-template"
RUNTIME = Path(__file__).parent / "runtime"


def read_constants(source: Path):
    tree = ast.parse((source / "src/consts.py").read_text())
    return {
        node.targets[0].id: ast.literal_eval(node.value)
        for node in tree.body
        if isinstance(node, ast.Assign)
        and isinstance(node.targets[0], ast.Name)
        and node.targets[0].id in {"ROM_FILE_MAP", "GAME_URL_MAP"}
    }


def source_digest(source: Path) -> str:
    digest = hashlib.sha256()
    for file in sorted(
        [source / "main.py", *source.glob("src/**/*.py"), *source.glob("configs/**/*")]
    ):
        if file.is_file():
            digest.update(str(file.relative_to(source)).encode())
            digest.update(file.read_bytes())
    return digest.hexdigest()


class VideoGameBenchAdapter:
    def __init__(
        self,
        output_dir: Path,
        rom_dir: Path | None = None,
        source_dir: Path | None = None,
        limit: int | None = None,
        overwrite: bool = False,
        task_ids: list[str] | None = None,
        oracle_dir: Path | None = None,
        split: str = "full",
        settings: Settings | None = None,
        revision: str = REVISION,
        bundle_dir: Path | None = None,
    ):
        self.output_dir = Path(output_dir)
        self.rom_dir, self.source_dir, self.oracle_dir = rom_dir, source_dir, oracle_dir
        self.limit, self.overwrite, self.task_ids = limit, overwrite, task_ids
        self.split, self.settings, self.revision, self.bundle_dir = (
            split,
            settings or Settings(),
            revision,
            bundle_dir,
        )
        if limit is not None and limit < 0:
            raise ValueError("--limit must be nonnegative")
        if split not in {"full", "test", "dev", "parity"}:
            raise ValueError("Unknown split")
        if len(revision) != 40 or any(c not in "0123456789abcdef" for c in revision):
            raise ValueError("Use an immutable 40-character upstream revision")

    def selected_games(self):
        games = {
            "full": TEST_GAMES + DEV_GAMES,
            "test": TEST_GAMES,
            "dev": DEV_GAMES,
            "parity": PARITY_GAMES,
        }[self.split]
        selected = sorted(games)
        if self.task_ids is not None:
            aliases = {
                alias: game
                for game in games
                for alias in (
                    game,
                    game.replace("_", "-"),
                    self.task_id(game),
                    f"videogamebench/{self.task_id(game)}",
                )
            }
            unknown = set(self.task_ids) - aliases.keys()
            if unknown:
                raise ValueError(f"Unknown task IDs in {self.split}: {sorted(unknown)}")
            requested = {aliases[t] for t in self.task_ids}
            selected = [g for g in selected if g in requested]
        return selected if self.limit is None else selected[: self.limit]

    def task_id(self, game):
        return f"videogamebench-{game.replace('_', '-')}-{self.settings.mode}"

    def run(self) -> None:
        selected = [
            g
            for g in self.selected_games()
            if self.overwrite or not (self.output_dir / self.task_id(g)).exists()
        ]
        if not selected:
            return
        with tempfile.TemporaryDirectory() as cache:
            source = self.source_dir or Path(cache)
            if self.source_dir is None:
                url = f"https://api.github.com/repos/alexzhang13/VideoGameBench/tarball/{self.revision}"
                with (
                    urllib.request.urlopen(url, timeout=180) as response,
                    tarfile.open(
                        fileobj=io.BytesIO(response.read()), mode="r:gz"
                    ) as archive,
                ):
                    for item in archive.getmembers():
                        name = item.name.partition("/")[2]
                        if item.isfile() and (
                            name.startswith(("configs/", "src/"))
                            or name in {"main.py", "LICENSE"}
                        ):
                            path = source / name
                            if not path.resolve().is_relative_to(source.resolve()):
                                raise ValueError("Unsafe upstream archive path")
                            stream = archive.extractfile(item)
                            if stream is not None:
                                path.parent.mkdir(parents=True, exist_ok=True)
                                path.write_bytes(stream.read())
            constants = read_constants(source)
            digest = source_digest(source)
            # Check all assets before replacing any existing task.
            for game in selected:
                if game in constants["ROM_FILE_MAP"] and (
                    self.rom_dir is None
                    or not (self.rom_dir / constants["ROM_FILE_MAP"][game]).is_file()
                ):
                    raise FileNotFoundError(
                        f"Supply licensed ROM {constants['ROM_FILE_MAP'][game]} via --rom-dir"
                    )
            for game in selected:
                self.generate(game, source, constants, digest)

    def generate(self, game: str, source: Path, constants: dict, digest: str) -> None:
        target = self.output_dir / self.task_id(game)
        config_dir = source / "configs" / game
        config = yaml.safe_load((config_dir / "config.yaml").read_text())
        checkpoints = sorted(
            (config_dir / "checkpoints").glob("*.png"), key=lambda p: int(p.stem)
        )
        # Stage first so malformed source/assets do not destroy an existing task.
        self.output_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=self.output_dir) as staging:
            task = Path(staging) / self.task_id(game)
            shutil.copytree(
                TEMPLATE, task, ignore=shutil.ignore_patterns("__pycache__", "*.pyc")
            )
            private = task / "environment/game"
            private.mkdir()
            upstream = private / "upstream"
            shutil.copytree(
                source / "src",
                upstream / "src",
                ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
            )
            shutil.copytree(config_dir, upstream / "configs" / game)
            shutil.copyfile(source / "main.py", upstream / "main.py")
            shutil.copyfile(source / "LICENSE", private / "UPSTREAM_LICENSE")
            shutil.copytree(
                RUNTIME,
                private / "runtime",
                ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
            )
            assets = {}
            if config["emulator"] == "gba":
                rom_name = constants["ROM_FILE_MAP"][game]
                rom = self.rom_dir / rom_name
                (upstream / "roms").mkdir()
                shutil.copyfile(rom, upstream / "roms" / rom_name)
                assets[rom_name] = hashlib.sha256(rom.read_bytes()).hexdigest()
            elif self.bundle_dir is not None:
                bundle = self.bundle_dir / f"{game}.jsdos"
                if not bundle.is_file():
                    raise FileNotFoundError(bundle)
                shutil.copyfile(bundle, private / "bundle.jsdos")
                assets[bundle.name] = hashlib.sha256(bundle.read_bytes()).hexdigest()
            manifest = {
                "game": game,
                "task_id": self.task_id(game),
                "emulator": config["emulator"],
                "settings": self.settings.to_dict(),
                "upstream_revision": self.revision,
                "source_sha256": digest,
                "assets": assets,
                "checkpoint_count": len(checkpoints),
                "bundle_local": self.bundle_dir is not None
                and config["emulator"] == "dos",
            }
            identity = hashlib.sha256(
                json.dumps(manifest, sort_keys=True).encode()
            ).hexdigest()
            manifest["identity"] = identity
            for path in (private / "manifest.json", task / "tests/manifest.json"):
                path.write_text(json.dumps(manifest, indent=2) + "\n")
            # Per-generation key; private game/verifier contexts only, never main.
            key = secrets.token_hex(32)
            (private / "result.key").write_text(key)
            (task / "tests/result.key").write_text(key)
            shutil.copyfile(RUNTIME / "evidence.py", task / "tests/evidence.py")
            for path in (
                task / "environment/Dockerfile",
                task / "environment/Dockerfile.game",
                task / "tests/Dockerfile",
            ):
                path.write_text(
                    path.read_text().replace("{base_image}", self.settings.base_image)
                )
            values = {
                **self.settings.to_dict(),
                "task_id": self.task_id(game),
                "revision": self.revision,
                "game_prompt": (config_dir / "prompt.txt").read_text()
                if (config_dir / "prompt.txt").exists()
                else "Play the game and complete its objectives.",
                "emulator": config["emulator"],
            }
            for name in (
                "task.toml",
                "instruction.md",
                "environment/docker-compose.yaml",
            ):
                text = (task / name).read_text()
                for k, v in values.items():
                    text = text.replace("{" + k + "}", str(v))
                (task / name).write_text(text)
            if self.oracle_dir is not None:
                trace = self.oracle_dir / f"{game}.json"
                if trace.exists():
                    shutil.copyfile(trace, task / "solution/actions.json")
            if target.exists():
                shutil.rmtree(target)
            shutil.move(str(task), target)
