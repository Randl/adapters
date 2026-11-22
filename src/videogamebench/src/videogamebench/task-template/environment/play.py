"""Launch the shared game client with Harbor service and workspace defaults."""

import os
import sys
from pathlib import Path


if __name__ == "__main__":
    client = Path(__file__).with_name("client") / "play.py"
    os.execv(
        sys.executable,
        [
            sys.executable,
            str(client),
            "--url",
            "http://game:8080",
            "--screen",
            "/workspace/screen.png",
            "--check-log",
            "/workspace/visual-checks.jsonl",
            *sys.argv[1:],
        ],
    )
