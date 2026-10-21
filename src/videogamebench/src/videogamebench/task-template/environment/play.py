"""Visual game client for CLI agents, replay candidates and the VG-Agent shim."""

import argparse
import json
import math
import os
import sys
import time
import urllib.request
from pathlib import Path


def request(url, path, value=None, timeout=900):
    body = json.dumps(value).encode() if value is not None else None
    with urllib.request.urlopen(
        urllib.request.Request(url + path, data=body), timeout=timeout
    ) as response:
        return response.read()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://game:8080")
    parser.add_argument("--timeout", type=float, default=900)
    parser.add_argument("--poll-interval", type=float, default=2)
    parser.add_argument(
        "--progress-interval",
        type=float,
        default=10,
        help="Seconds between replay progress messages; 0 disables periodic messages",
    )
    parser.add_argument("--screen", type=Path, default=Path("/workspace/screen.png"))
    commands = parser.add_mutually_exclusive_group()
    commands.add_argument("--buttons", nargs="+")
    commands.add_argument("--no-op", action="store_true")
    commands.add_argument(
        "--action", help='DOS JSON: {"action":"press_key","action_input":"ArrowRight"}'
    )
    commands.add_argument("--replay", type=Path)
    commands.add_argument("--finish", action="store_true")
    commands.add_argument("--vgagent", action="store_true")
    parser.add_argument("--model")
    parser.add_argument("--api-key-env", default="OPENAI_API_KEY")
    args = parser.parse_args()
    if not math.isfinite(args.progress_interval) or args.progress_interval < 0:
        parser.error("--progress-interval must be finite and nonnegative")

    def call(path, value=None):
        return request(args.url, path, value, args.timeout)

    if args.finish:
        call("/finish", {})
        return
    if args.vgagent:
        call(
            "/start",
            {
                "controller": "vgagent",
                "api_key": os.environ.get(args.api_key_env),
                "model": args.model,
            },
        )
        while True:
            status = json.loads(call("/status"))
            if status["finished"]:
                if status["error"]:
                    raise RuntimeError(status["error"])
                return
            time.sleep(args.poll_interval)
    args.screen.parent.mkdir(parents=True, exist_ok=True)
    args.screen.write_bytes(call("/screen"))
    if args.replay:
        trace = json.loads(args.replay.read_text())
        # A trace is a candidate policy: each action is executed and scored anew.
        actions = trace["actions"] if isinstance(trace, dict) else trace
        started = last_progress = time.monotonic()
        total = len(actions)
        print(
            f"Replaying {total} actions from a fresh game…", file=sys.stderr, flush=True
        )
        for index, item in enumerate(actions, 1):
            action = item["action"] if isinstance(trace, dict) else item
            # JSON null is an action, so send it explicitly (GET has no body).
            with urllib.request.urlopen(
                urllib.request.Request(
                    args.url + "/action", data=json.dumps(action).encode()
                ),
                timeout=args.timeout,
            ) as response:
                status = json.load(response)
            now = time.monotonic()
            if (
                args.progress_interval and now - last_progress >= args.progress_interval
            ) or index == total:
                elapsed = now - started
                rate = index / elapsed if elapsed else 0
                remaining = (total - index) / rate if rate else 0
                print(
                    f"Replay {index}/{total} ({index / total:.1%}) | "
                    f"{rate:.2f} actions/s | elapsed {elapsed / 60:.1f} min | "
                    f"ETA {remaining / 60:.1f} min",
                    file=sys.stderr,
                    flush=True,
                )
                last_progress = now
            if status.get("error"):
                raise RuntimeError(status["error"])
            if status["finished"]:
                break
        call("/finish", {})
        print(
            "Replay finished. The separate verifier will report the score.",
            file=sys.stderr,
            flush=True,
        )
    elif args.buttons or args.no_op or args.action:
        value = (
            json.loads(args.action)
            if args.action
            else ({key: True for key in args.buttons} if args.buttons else None)
        )
        with urllib.request.urlopen(
            urllib.request.Request(
                args.url + "/action", data=json.dumps(value).encode()
            ),
            timeout=args.timeout,
        ) as response:
            response.read()
    args.screen.write_bytes(call("/screen"))
    print(args.screen)


if __name__ == "__main__":
    main()
