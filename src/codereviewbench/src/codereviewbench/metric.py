"""Micro-average upstream profile counts; a mean of per-PR F2 is incorrect."""

import argparse
import json
from collections.abc import Sequence
from pathlib import Path


def aggregate(rewards: Sequence[dict | None]) -> dict[str, float]:
    if not rewards or any(r is None for r in rewards):
        raise ValueError("Cannot aggregate incomplete or failed verification")
    output = {}
    for profile in ("strict", "core", "all"):
        tp, fp, fn = (
            sum(r[f"{profile}_{key}"] for r in rewards if r is not None)
            for key in ("tp", "fp", "fn")
        )
        output[f"{profile}_precision"] = tp / (tp + fp) if tp + fp else 0.0
        output[f"{profile}_recall"] = tp / (tp + fn) if tp + fn else 0.0
        output[f"{profile}_f1"] = 2 * tp / (2 * tp + fp + fn) if tp else 0.0
        output[f"{profile}_f2"] = 5 * tp / (5 * tp + fp + 4 * fn) if tp else 0.0
    return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("-i", type=Path, required=True)
    parser.add_argument("-o", type=Path, required=True)
    args = parser.parse_args()
    args.o.write_text(
        json.dumps(
            aggregate([json.loads(line) for line in args.i.read_text().splitlines()])
        )
    )
