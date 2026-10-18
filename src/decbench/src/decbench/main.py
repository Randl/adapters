"""Generate tasks from DecBench's frozen 250-function sample-set."""

import argparse
from pathlib import Path

from .adapter import DecBenchAdapter


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=Path("datasets/decbench"))
    parser.add_argument("--limit", type=int)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--task-ids", nargs="+")
    parser.add_argument("--data-dir", type=Path, help="Pinned HF snapshot root")
    parser.add_argument(
        "--oracle-dir", type=Path, help="Independently reconstructed <task-id>.c files"
    )
    DecBenchAdapter(**vars(parser.parse_args())).run()


if __name__ == "__main__":
    main()
