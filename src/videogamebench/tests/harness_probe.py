"""Compare upstream and instrumented loops with deterministic I/O doubles.

No emulator gameplay, model parity or oracle success is claimed by this probe.
"""

import asyncio
import io
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

os.environ["LITELLM_LOCAL_MODEL_COST_MAP"] = "True"

from PIL import Image

root, side, output = Path(sys.argv[1]), sys.argv[2], Path(sys.argv[3])
sys.path[:0] = [str(root / "upstream"), str(root / "runtime")]
os.chdir(root / "upstream")
manifest = json.loads((root / "manifest.json").read_text())
from src.emulators.dos.interface import DOSGameInterface
from src.emulators.dos.website_server import DOSGameServer
from src.emulators.gba.interface import GBAInterface
from src.llm.llm_client import LLMClient

requests, actions = [], []
image = Image.new("RGB", (160, 144), "black")
image.paste("white", (10, 5, 40, 20))
buffer = io.BytesIO()
image.save(buffer, format="PNG")
screen = buffer.getvalue()


def gb_observation(self):
    return {"screen": image, "buttons": self.get_available_buttons()}


def gb_step(self, action, frames):
    actions.append(["step", action, frames])
    return gb_observation(self), 0, False, {}


def gb_noop(self, frames):
    # Real-time idle ticks depend on scheduling; test their fixed duration separately.
    if frames != 1:
        actions.append(["noop", frames])
    return gb_observation(self), 0, False, {}


GBAInterface.load_game = lambda *args: True
GBAInterface.close = lambda *args: None
GBAInterface.get_observation = gb_observation
GBAInterface.step = gb_step
GBAInterface.no_op = gb_noop


async def dos_load(self, initial_url):
    self.browser = SimpleNamespace(current_mouse_position=(0, 0))


async def dos_observation(self):
    return screen


async def dos_step(self, action, action_input):
    actions.append(
        [
            action,
            action_input,
            self.lite,
            self.num_screenshots_per_action,
            self.key_press_delay_ms,
        ]
    )
    return "action performed", [screen]


async def dos_close(self):
    pass


DOSGameInterface.load_game = dos_load
DOSGameInterface.get_observation = dos_observation
DOSGameInterface.step = dos_step
DOSGameInterface.close = dos_close
DOSGameServer.start = lambda *args, **kwargs: "http://localhost:8000"
DOSGameServer.stop = lambda *args: None


async def response(self, system_message, messages, image_data=None):
    requests.append(
        {
            "system": system_message,
            "messages": json.loads(json.dumps(messages)),
            "images": [b.hex() for b in image_data]
            if isinstance(image_data, list)
            else None,
            "model": self.model,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }
    )
    await asyncio.sleep(0)
    if manifest["emulator"] == "gba":
        return "```reflection\nkeep moving\n```\n```actions\n['RIGHT', ('A', 'RIGHT')]\n```"
    return json.dumps(
        {
            "thought": "move",
            "action": "press_key",
            "action_input": "ArrowRight",
            "memory": "keep moving",
        }
    )


LLMClient.generate_response = response
result = None
if side == "instrumented":
    from session import Session

    session = Session(root, output.with_suffix(""))
    session.started = True
    session.controller = "vgagent"
    session.run(None, None)
    from src.llm.utils import parse_actions_response

    marker = output.with_suffix(".executed")
    assert (
        parse_actions_response(
            "```actions\n__import__('pathlib').Path("
            + repr(str(marker))
            + ").touch()\n```"
        )
        == []
    )
    assert not marker.exists()
    result = json.loads((session.state_dir / "result.json").read_text())["payload"]
else:
    import main

    sys.argv = [
        "main.py",
        "--game",
        manifest["game"],
        "--headless",
        "--model",
        manifest["settings"]["model"],
        "--max-steps",
        "3",
    ]
    if manifest["settings"]["mode"] == "lite":
        sys.argv.append("--lite")
    args = main.load_game_config(main.parse_args())
    if manifest["emulator"] == "gba":
        from src.run_vgbench_gb import run_gba_emulator

        asyncio.run(run_gba_emulator(args))
    else:
        from src.run_vgbench_dos import run_dos_emulator

        asyncio.run(run_dos_emulator(args))
output.write_text(
    json.dumps({"requests": requests, "actions": actions, "result": result})
)
