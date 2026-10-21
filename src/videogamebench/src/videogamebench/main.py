"""Generate public VideoGameBench tasks; settings YAML controls all run parameters."""

import argparse
from pathlib import Path

import yaml

from .adapter import VideoGameBenchAdapter
from .settings import REVISION, Settings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir", type=Path, default=Path("datasets/videogamebench")
    )
    parser.add_argument("--rom-dir", type=Path)
    parser.add_argument(
        "--bundle-dir",
        type=Path,
        help="Optional licensed <game>.jsdos bundles; otherwise upstream URLs",
    )
    parser.add_argument("--source-dir", type=Path)
    parser.add_argument("--revision", default=REVISION)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--task-ids", nargs="+")
    parser.add_argument(
        "--split", choices=["full", "test", "dev", "parity"], default="full"
    )
    parser.add_argument(
        "--oracle-dir", type=Path, help="Candidate <game>.json action traces"
    )
    parser.add_argument("--settings", type=Path, help="YAML mapping of Settings fields")
    parser.add_argument(
        "--set",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help="Override any setting using YAML scalar syntax",
    )
    args = vars(parser.parse_args())
    file = args.pop("settings")
    values = yaml.safe_load(file.read_text()) if file else {}
    for override in args.pop("set"):
        key, separator, value = override.partition("=")
        if not separator:
            parser.error("--set expects KEY=VALUE")
        values[key] = yaml.safe_load(value)
    args["settings"] = Settings.from_dict(values)
    VideoGameBenchAdapter(**args).run()


if __name__ == "__main__":
    main()
