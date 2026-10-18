"""Public visual control service; scores are computed by independent replay."""

import io
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from src.emulators.gba.interface import GBAInterface

GAME = GBAInterface(render=False)
if not GAME.load_game("/opt/game/game.gb"):
    raise RuntimeError("Could not load the supplied ROM")
CONFIG = json.loads(Path("/opt/game/game.json").read_text())
LOCK = threading.Lock()
ACTIONS = []


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        with LOCK:
            screen = io.BytesIO()
            GAME.get_screen().save(screen, format="PNG")
            data = screen.getvalue()
        self.send_response(200)
        self.send_header("Content-Type", "image/png")
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 1024:
                raise ValueError("Invalid request size")
            action = json.loads(self.rfile.read(length))
            if action is not None and (
                not isinstance(action, dict)
                or any(
                    k not in GAME.BUTTON_MAP or type(v) is not bool
                    for k, v in action.items()
                )
            ):
                raise ValueError("Invalid button action")
            with LOCK:
                if len(ACTIONS) >= CONFIG["max_steps"]:
                    raise ValueError("Action budget exhausted")
                if action is None:
                    GAME.no_op(CONFIG["action_frames"])
                else:
                    GAME.step(action, CONFIG["action_frames"])
                ACTIONS.append(action)
                data = json.dumps(ACTIONS).encode()
        except (ValueError, json.JSONDecodeError):
            self.send_error(400, "Invalid action or exhausted budget")
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(data)


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", 8080), Handler).serve_forever()
