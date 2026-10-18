"""Generate four VideoGameBench Game Boy Lite tasks with licensed ROMs."""

import argparse
from pathlib import Path

from .adapter import VideoGameBenchAdapter


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir", type=Path, default=Path("datasets/videogamebench")
    )
    parser.add_argument("--rom-dir", type=Path, required=True)
    parser.add_argument("--source-dir", type=Path)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--task-ids", nargs="+")
    parser.add_argument(
        "--oracle-dir", type=Path, help="Successful <game>.json action replays"
    )
    VideoGameBenchAdapter(**vars(parser.parse_args())).run()


if __name__ == "__main__":
    main()
