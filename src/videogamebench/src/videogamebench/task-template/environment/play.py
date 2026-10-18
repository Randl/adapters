"""Advance one emulator action and retain the replay and observation."""

import argparse
import json
import urllib.request
from pathlib import Path

parser = argparse.ArgumentParser(description=__doc__)
action = parser.add_mutually_exclusive_group()
action.add_argument(
    "--buttons",
    nargs="+",
    choices=["A", "B", "START", "SELECT", "UP", "DOWN", "LEFT", "RIGHT"],
)
action.add_argument("--no-op", action="store_true")
args = parser.parse_args()
if args.buttons or args.no_op:
    value = {key: True for key in args.buttons} if args.buttons else None
    request = urllib.request.Request(
        "http://game:8080", data=json.dumps(value).encode()
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        Path("/workspace/actions.json").write_bytes(response.read())
with urllib.request.urlopen("http://game:8080", timeout=30) as response:
    Path("/workspace/screen.png").write_bytes(response.read())
print("/workspace/screen.png")
