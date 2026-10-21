"""One isolated upstream session per task, with optional human recorder controls."""

import argparse
import hashlib
import io
import json
import os
import shutil
import sys
import tempfile
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from recorder import archive_attempt, rewind_prefix
from session import Session

LOCK = threading.Lock()
INSTANCE = uuid.uuid4().hex
SCRIPT = str(Path(__file__).resolve())
RESTORING = False
RESTORE_PROGRESS = 0
RESTORE_ERROR = None
SNAPSHOT_STEP = 0


def status():
    return {
        **SESSION.status(),
        "restoring": RESTORING,
        "restore_progress": RESTORE_PROGRESS,
        "restore_error": RESTORE_ERROR,
        "snapshot_step": SNAPSHOT_STEP,
    }


def restore(plan):
    global RESTORING, RESTORE_PROGRESS, RESTORE_ERROR, SNAPSHOT_STEP
    from PIL import Image

    started = time.monotonic()
    try:
        if plan["identity"] != SESSION.manifest["identity"]:
            raise ValueError("Rewind settings do not match this task")
        SESSION.start()
        SESSION.wait_ready()
        SNAPSHOT_STEP = SESSION.restore_snapshot(plan["actions"])
        RESTORE_PROGRESS = SNAPSHOT_STEP
        SESSION.set_playback_speed(plan["speed"])
        with (SESSION.state_dir / "restored-screen-hashes.jsonl").open("w") as output:
            for index, action in enumerate(
                plan["actions"][SNAPSHOT_STEP:], SNAPSHOT_STEP + 1
            ):
                SESSION.submit(action)
                SESSION.wait_ready()
                if SESSION.finished:
                    raise RuntimeError("Session ended during rewind")
                with Image.open(io.BytesIO(SESSION.screen)) as image:
                    digest = hashlib.sha256(image.convert("RGB").tobytes()).hexdigest()
                output.write(json.dumps({"step": index, "pixel_sha256": digest}) + "\n")
                RESTORE_PROGRESS = index
        SESSION.set_playback_speed(1)
        # Persist the reconstructed prefix immediately, even before more play.
        SESSION.save("recording")
        (SESSION.state_dir / "restore-metrics.json").write_text(
            json.dumps(
                {
                    "snapshot_step": SNAPSHOT_STEP,
                    "target_step": SESSION.steps,
                    "replayed_actions": SESSION.steps - SNAPSHOT_STEP,
                    "restore_seconds": time.monotonic() - started,
                },
                indent=2,
            )
        )
    except Exception as exc:  # noqa: BLE001 -- surface worker failures to the recorder UI
        RESTORE_ERROR = str(exc)
    finally:
        RESTORING = False


def restart():
    """A new interpreter avoids retaining upstream monkeypatches or emulator state."""
    os.chdir(ARGS.root)
    if WORKSPACE is not None:
        WORKSPACE.cleanup()
    os.execv(sys.executable, [sys.executable, SCRIPT, *SERVER_ARGS])


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def send(self, data, content_type="application/json"):
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == "/":
            self.send(
                Path(__file__).with_name("player.html").read_bytes(),
                "text/html; charset=utf-8",
            )
        elif self.path == "/controls":
            self.send(
                json.dumps(
                    {
                        "game": SESSION.manifest["game"],
                        "emulator": SESSION.manifest["emulator"],
                        "mode": SESSION.settings["mode"],
                        "action_frames": SESSION.settings["action_frames"],
                        "allow_restart": ARGS.allow_restart,
                        "instance": INSTANCE,
                        "restart_timeout_sec": ARGS.restart_timeout_sec,
                        "replay_speed": ARGS.replay_speed,
                        "snapshot_interval": ARGS.snapshot_interval,
                    }
                ).encode()
            )
        elif self.path in {"/health", "/status"}:
            self.send(json.dumps(status()).encode())
        elif self.path == "/screen":
            try:
                with LOCK:
                    if RESTORING:
                        raise ValueError("Reconstructing the recorded game")
                    if not SESSION.started:
                        SESSION.start()
                    if SESSION.controller == "manual":
                        SESSION.wait_ready()
                    if SESSION.screen is None:
                        raise ValueError("No screen yet")
                    self.send(
                        SESSION.screen,
                        "image/png"
                        if SESSION.manifest["emulator"] == "gba"
                        else "image/jpeg",
                    )
            except (OSError, RuntimeError, ValueError) as exc:
                self.send_error(503, str(exc))
        else:
            self.send_error(404)

    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 65536:
                raise ValueError("Invalid request size")
            data = json.loads(self.rfile.read(length))
            with LOCK:
                if RESTORING:
                    self.send_error(409, "Wait for rewind to finish")
                    return
                if self.path in {"/restart", "/rewind"}:
                    if (
                        not ARGS.allow_restart
                        or SESSION.controller not in {None, "manual"}
                        or SESSION.manifest["emulator"] != "gba"
                        or SESSION.settings["mode"] != "lite"
                    ):
                        self.send_error(
                            403,
                            "Restart is only enabled for a human Game Boy Lite recorder",
                        )
                        return
                    plan = None
                    if self.path == "/rewind":
                        if not isinstance(data, dict) or data.keys() - {
                            "actions",
                            "speed",
                        }:
                            raise ValueError(
                                "Expected rewind actions and optional speed"
                            )
                        prefix = rewind_prefix(SESSION.trace, data.get("actions"))
                        speed = data.get("speed", ARGS.replay_speed)
                        if type(speed) is not int or speed < 0:
                            raise ValueError(
                                "Replay speed must be a nonnegative integer; 0 is unlimited"
                            )
                        plan = {
                            "actions": prefix,
                            "speed": speed,
                            "identity": SESSION.manifest["identity"],
                        }
                    SESSION.finish()
                    saved = archive_attempt(SESSION.state_dir)
                    if plan is not None:
                        plan["source_attempt"] = saved.name
                        (SESSION.state_dir / "restore-plan.json").write_text(
                            json.dumps(plan)
                        )
                    self.send(json.dumps({"saved_attempt": saved.name}).encode())
                    self.wfile.flush()
                    restart()
                    return
                elif self.path == "/start":
                    if not isinstance(data, dict) or data.keys() - {
                        "controller",
                        "api_key",
                        "model",
                    }:
                        raise ValueError("Invalid start request")
                    SESSION.start(**data)
                elif self.path == "/action":
                    SESSION.submit(data)
                    SESSION.wait_ready()
                elif self.path == "/finish":
                    SESSION.finish()
                else:
                    self.send_error(404)
                    return
            self.send(json.dumps(status()).encode())
        except (ValueError, TypeError) as exc:
            self.send_error(400, str(exc))
        except (OSError, RuntimeError) as exc:
            self.send_error(503, str(exc))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("/opt/game"))
    parser.add_argument("--state-dir", type=Path, default=Path("/state"))
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--allow-restart", action="store_true")
    parser.add_argument(
        "--boot-cache",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Reuse the exact post-boot emulator state in the human recorder",
    )
    parser.add_argument(
        "--snapshot-interval",
        type=int,
        default=100,
        help="Cache a human Game Boy Lite state every N actions; 0 disables snapshots",
    )
    parser.add_argument("--restart-timeout-sec", type=float, default=60)
    parser.add_argument(
        "--replay-speed",
        type=int,
        default=0,
        help="Rewind playback multiplier; 0 removes the speed limit",
    )
    SERVER_ARGS = sys.argv[1:]  # Upstream replaces sys.argv while a game runs.
    ARGS = parser.parse_args()
    if ARGS.replay_speed < 0 or ARGS.restart_timeout_sec <= 0:
        parser.error("Replay speed must be nonnegative and restart timeout positive")
    if ARGS.snapshot_interval < 0:
        parser.error("Snapshot interval must be nonnegative")
    ARGS.root, ARGS.state_dir = ARGS.root.resolve(), ARGS.state_dir.resolve()
    WORKSPACE = (
        tempfile.TemporaryDirectory(prefix="vgbench-recorder-")
        if ARGS.allow_restart
        else None
    )
    game_root = ARGS.root
    if WORKSPACE is not None:
        # PyBoy may persist battery RAM beside a ROM. Every human attempt gets
        # its own copy, leaving the generated task's initial assets untouched.
        game_root = Path(WORKSPACE.name) / "game"
        shutil.copytree(ARGS.root, game_root)
    SESSION = Session(game_root, ARGS.state_dir)
    if ARGS.allow_restart and ARGS.boot_cache:
        SESSION.boot_cache_dir = ARGS.state_dir / ".boot-cache"
    if (
        ARGS.allow_restart
        and ARGS.snapshot_interval
        and SESSION.manifest["emulator"] == "gba"
        and SESSION.settings["mode"] == "lite"
    ):
        from importlib.metadata import version

        from snapshots import SnapshotStore

        SESSION.snapshots = SnapshotStore(
            ARGS.state_dir / ".snapshots",
            SESSION.manifest["identity"],
            version("pyboy"),
            ARGS.snapshot_interval,
        )
    plan_file = ARGS.state_dir / "restore-plan.json"
    if ARGS.allow_restart and plan_file.exists():
        plan = json.loads(plan_file.read_text())
        plan_file.rename(ARGS.state_dir / "restoration.json")
        RESTORING = True
        threading.Thread(target=restore, args=(plan,), daemon=True).start()
    ThreadingHTTPServer((ARGS.host, ARGS.port), Handler).serve_forever()
