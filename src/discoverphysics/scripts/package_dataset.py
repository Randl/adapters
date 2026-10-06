"""Create a publishable manifest for an already generated 22-task suite.

Run with `uv run --extra harbor python scripts/package_dataset.py` from the adapter directory.
"""

from __future__ import annotations

import argparse
import shutil
import tomllib
from pathlib import Path

from harbor.models.dataset.manifest import (
    DatasetFileRef,
    DatasetInfo,
    DatasetManifest,
    DatasetTaskRef,
)
from harbor.models.task.config import Author
from harbor.publisher.packager import Packager

ADAPTER_DIR = Path(__file__).resolve().parents[1]


def package_dataset(dataset_dir: Path) -> DatasetManifest:
    tasks = sorted(dataset_dir.glob("*/task.toml"))
    worlds: dict[str, set[int]] = {}
    refs = []
    revisions = set()
    for path in tasks:
        config = tomllib.loads(path.read_text())
        metadata = config["metadata"]
        worlds.setdefault(metadata["world"], set()).add(metadata["seed"])
        revisions.add(metadata["upstream_commit"])
        digest, _ = Packager.compute_content_hash(path.parent)
        refs.append(
            DatasetTaskRef(name=config["task"]["name"], digest=f"sha256:{digest}")
        )
    if (
        len(tasks) != 22
        or len(worlds) != 11
        or any(seeds != {0, 1} for seeds in worlds.values())
    ):
        raise ValueError("Publication requires all 11 N-body worlds at seeds 0 and 1")
    if len(revisions) != 1 or "wave" in worlds:
        raise ValueError(
            "Tasks must share one upstream revision and exclude field-only wave"
        )
    metric = dataset_dir / "metric.py"
    shutil.copyfile(ADAPTER_DIR / "src/discoverphysics/metric.py", metric)
    manifest = DatasetManifest(
        dataset=DatasetInfo(
            name="discoverphysics/discoverphysics",
            description=(
                "DiscoverPhysics: 11 public N-body worlds at seeds 0 and 1 (22 tasks). "
                "The field-only wave world lacks pinned batch normalization metadata "
                "and is excluded, as are the unreleased force_geography and "
                "running_coupling worlds. Upstream revision: "
                f"{next(iter(revisions))}. "
                "Adapter: https://github.com/harbor-framework/adapters/tree/main/src/discoverphysics. "
                "Oracle validation is separate from ongoing agent parity."
            ),
            authors=[
                Author(
                    name="Evgenii Zheltonozhskii",
                    email="zheltonozhskiy@gmail.com",
                )
            ],
            keywords=["scientific-discovery", "physics", "experimentation"],
        ),
        tasks=refs,
        files=[
            DatasetFileRef(
                path="metric.py",
                digest=f"sha256:{Packager.compute_file_hash(metric)}",
            )
        ],
    )
    (dataset_dir / "dataset.toml").write_text(manifest.to_toml())
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset_dir", type=Path)
    args = parser.parse_args()
    manifest = package_dataset(args.dataset_dir)
    print(f"Packaged {len(manifest.tasks)} tasks: {manifest.dataset.name}")
