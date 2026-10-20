"""Generate BioMysteryBench Harbor tasks."""

import argparse
from pathlib import Path

from .adapter import BioMysteryBenchAdapter
from .judge import DEFAULT_BASE_URL


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir", type=Path, default=Path("datasets/biomysterybench")
    )
    parser.add_argument("--limit", type=int)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--task-ids", nargs="+")
    parser.add_argument(
        "--judge-base-url",
        default=DEFAULT_BASE_URL,
        help="OpenAI-compatible base URL; permits its host only in the private verifier",
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        help="Pinned HF snapshot with problems.csv and data/*.zip",
    )
    parser.add_argument(
        "--oracle-dir", type=Path, help="Independently solved <problem-id>.txt answers"
    )
    parser.add_argument(
        "--split", choices=["full", "human-solvable", "human-difficult"], default="full"
    )
    BioMysteryBenchAdapter(**vars(parser.parse_args())).run()


if __name__ == "__main__":
    main()
