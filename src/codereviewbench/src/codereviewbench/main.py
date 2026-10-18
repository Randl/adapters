"""Generate the 50 offline CodeReviewBench tasks."""

import argparse
from pathlib import Path

from .adapter import CodeReviewBenchAdapter


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir", type=Path, default=Path("datasets/codereviewbench")
    )
    parser.add_argument("--limit", type=int)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--task-ids", nargs="+")
    parser.add_argument(
        "--source-dir", type=Path, help="Local checkout of the pinned upstream revision"
    )
    CodeReviewBenchAdapter(**vars(parser.parse_args())).run()


if __name__ == "__main__":
    main()
