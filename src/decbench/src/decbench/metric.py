"""Report upstream perfect percentages with per-metric measured denominators."""

import argparse
import json
from collections.abc import Sequence
from pathlib import Path


def aggregate(rewards: Sequence[dict | None]) -> dict[str, float]:
    if not rewards or any(r is None for r in rewards):
        raise ValueError("Cannot aggregate incomplete verification")
    rows = [r for r in rewards if r is not None]
    measured_rows = [
        r
        for r in rows
        if any(r[f"{name}_measured"] for name in ("ged", "type_match", "byte_match"))
    ]
    result = (
        {"union": 100 * sum(r["union"] for r in measured_rows) / len(measured_rows)}
        if measured_rows
        else {}
    )
    for name in ("ged", "type_match", "byte_match"):
        denominator = sum(r[f"{name}_measured"] for r in rows)
        if denominator:
            result[name] = 100 * sum(r[f"{name}_perfect"] for r in rows) / denominator
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
