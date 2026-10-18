"""Report rubric accuracy separately for the released human-solvability partitions."""

import argparse
import json
from collections.abc import Sequence
from pathlib import Path


def aggregate(rewards: Sequence[dict | None]) -> dict[str, float]:
    if not rewards or any(row is None for row in rewards):
        raise ValueError("Cannot aggregate incomplete verification")
    result = {}
    for name, flag in (("human_solvable_accuracy", 1), ("human_difficult_accuracy", 0)):
        rows = [
            row for row in rewards if row is not None and row["human_solvable"] == flag
        ]
        if rows:
            result[name] = sum(row["correct"] for row in rows) / len(rows)
    return result


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
