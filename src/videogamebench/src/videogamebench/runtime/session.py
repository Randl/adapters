"""Observe upstream execution without replacing its prompts, agents or game loop."""

import asyncio
import io
import json
import math
import os
import queue
import random
import sys
import threading
import time
from pathlib import Path

from evidence import sign
from video import ObservationVideo


class StopEpisode(BaseException):
    pass


class InfrastructureFailure(BaseException):
    pass


class Session:
    def __init__(self, root: Path, state_dir: Path):
        self.root, self.state_dir = root, state_dir
        self.manifest = json.loads((root / "manifest.json").read_text())
        self.settings = self.manifest["settings"]
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.condition = threading.Condition()
        self.actions = queue.Queue()
        self.started = False
        self.finished = False
        self.waiting = False
        self.screen = None
        self.steps = 0
        self.completed = False
        self.checkpoint_index = 0
        self.error = None
        self.trace = []
        self.controller = None
        self.agent = None
        self.game = None
        self.boot_cache_dir = None
        self.snapshots = None
        self.evaluator = None
        self.log_interval_sec = float(
            os.environ.get("VIDEOGAMEBENCH_LOG_INTERVAL_SEC", "10")
        )
        if not math.isfinite(self.log_interval_sec) or self.log_interval_sec < 0:
            raise ValueError(
                "VIDEOGAMEBENCH_LOG_INTERVAL_SEC must be finite and nonnegative"
            )
        self.last_progress_at = 0.0
        self.progress_started_at = time.monotonic()
        self.progress_start_steps = 0
        self.video = (
            ObservationVideo(state_dir, self.settings["video_fps"])
            if self.settings["record_video"]
            else None
        )

    def log_progress(self, event="progress", *, force=False, status=None):
        """Private run evidence; never expose checkpoint progress via the action API."""
        now = time.monotonic()
        if not force and (
            self.log_interval_sec == 0
            or now - self.last_progress_at < self.log_interval_sec
        ):
            return
        elapsed = max(0, now - self.progress_started_at)
        checkpoints = self.manifest["checkpoint_count"]
        record = {
            "event": event,
            "game": self.manifest["game"],
            "controller": self.controller,
            "steps": self.steps,
            "step_budget": self.settings["max_steps"],
            "elapsed_sec": round(elapsed, 3),
            "actions_per_sec": round(
                (self.steps - self.progress_start_steps) / elapsed, 3
            )
            if elapsed
            else 0,
            "checkpoint_index": self.checkpoint_index,
            "checkpoint_count": checkpoints,
            "score": int(self.completed) if checkpoints and not self.error else None,
            "metric": "final_checkpoint_completion",
            "cost_usd": self.agent.llm_client.get_total_cost() if self.agent else 0,
            "status": status or ("finished" if self.finished else "running"),
            "error": self.error,
            "video_error": self.video.error if self.video else None,
        }
        with (self.state_dir / "progress.jsonl").open("a") as output:
            output.write(json.dumps(record) + "\n")
        print("[videogamebench] " + json.dumps(record), flush=True)
        self.last_progress_at = now

    def publish(self, screen):
        if not isinstance(screen, bytes):
            buffer = io.BytesIO()
            screen.save(buffer, format="PNG")
            screen = buffer.getvalue()
        if self.video is not None:
            self.video.update(screen)
        with self.condition:
            self.screen = screen
            self.condition.notify_all()

    def start(self, controller="manual", api_key=None, model=None):
        with self.condition:
            if self.started:
                raise ValueError("A session can only start once")
            if controller not in {"manual", "vgagent"}:
                raise ValueError("Unknown controller")
            self.started = True
            self.controller = controller
        threading.Thread(target=self.run, args=(api_key, model), daemon=True).start()

    def status(self):
        return {
            "started": self.started,
            "finished": self.finished,
            "waiting": self.waiting,
            "steps": self.steps,
            "error": self.error,
        }

    def set_playback_speed(self, speed):
        """Human Lite replay only; frame counts and inputs remain unchanged."""
        if (
            self.controller != "manual"
            or self.manifest["emulator"] != "gba"
            or self.settings["mode"] != "lite"
            or self.game is None
            or not self.waiting
        ):
            raise ValueError(
                "Playback speed requires an idle manual Game Boy Lite session"
            )
        self.game.pyboy.set_emulation_speed(speed)

    def capture_snapshot(self):
        if self.snapshots is None:
            return
        self.snapshots.advance(
            item["action"] for item in self.trace[self.snapshots.steps : self.steps]
        )
        if not self.steps or self.steps % self.snapshots.interval:
            return
        state = io.BytesIO()
        self.game.pyboy.save_state(state)
        evaluator = self.evaluator
        self.snapshots.save(
            state.getvalue(),
            self.screen,
            {
                "completed": self.completed,
                "checkpoint_index": self.checkpoint_index,
                "current_checkpoint_idx": evaluator.current_checkpoint_idx,
                "completed_checkpoints": [
                    i
                    for i, checkpoint in enumerate(evaluator.checkpoints or [])
                    if checkpoint in evaluator.completed_checkpoints
                ],
                "agent_checkpoint": self.agent.current_checkpoint,
            },
        )

    def restore_snapshot(self, actions):
        if self.snapshots is None:
            return 0
        snapshot = self.snapshots.nearest(actions)
        if snapshot is None:
            return 0
        metadata, state, screen = snapshot
        # The upstream loop is blocked waiting for an action at this boundary.
        self.game.pyboy.load_state(io.BytesIO(state))
        self.steps = metadata["steps"]
        self.trace = [
            {"action": action, "restored_from_snapshot": True}
            for action in actions[: self.steps]
        ]
        self.completed = metadata["completed"]
        self.checkpoint_index = metadata["checkpoint_index"]
        self.evaluator.current_checkpoint_idx = metadata["current_checkpoint_idx"]
        self.evaluator.completed_checkpoints = {
            self.evaluator.checkpoints[i] for i in metadata["completed_checkpoints"]
        }
        self.agent.current_checkpoint = metadata["agent_checkpoint"]
        self.snapshots.advance(actions[: self.steps])
        # Retain the exact captured image even if load_state does not render.
        from PIL import Image

        self.agent.store_observation(
            {
                "screen": Image.open(io.BytesIO(screen)).copy(),
                "buttons": self.game.get_available_buttons(),
            }
        )
        self.progress_started_at = time.monotonic()
        self.progress_start_steps = self.steps
        self.log_progress("snapshot_restored", force=True)
        return self.steps

    async def next_action(self):
        self.capture_snapshot()
        # A snapshot skips iterations of the live loop, but never grants an
        # additional action budget to the restored human attempt.
        if self.snapshots is not None and self.steps >= self.settings["max_steps"]:
            raise StopEpisode()
        with self.condition:
            self.waiting = True
            self.condition.notify_all()
        action = await asyncio.to_thread(self.actions.get)
        with self.condition:
            self.waiting = False
        if action == "__finish__":
            raise StopEpisode()
        self.trace.append(
            {"action": action, "elapsed_sec": time.monotonic() - self.started_at}
        )
        return action

    def submit(self, action):
        if self.controller != "manual" or not self.waiting or self.finished:
            raise ValueError("Session is not waiting for a manual action")
        if self.manifest["emulator"] == "gba":
            from src.emulators.gba.interface import GBAInterface

            if action is not None and (
                not isinstance(action, dict)
                or any(
                    k not in GBAInterface.BUTTON_MAP or type(v) is not bool
                    for k, v in action.items()
                )
            ):
                raise ValueError("Expected button booleans or null")
        elif (
            not isinstance(action, dict)
            or set(action) != {"action", "action_input"}
            or action["action"]
            not in {
                None,
                "click",
                "move",
                "move_mouse",
                "move_mouse_left",
                "move_mouse_right",
                "move_mouse_up",
                "move_mouse_down",
                "drag",
                "scroll_down",
                "scroll_up",
                "write",
                "press_key",
                "hold_key",
            }
            or not isinstance(action["action_input"], str)
        ):
            raise ValueError("Expected DOS action and string action_input")
        with self.condition:
            self.waiting = False
            self.actions.put(action)

    def wait_ready(self, timeout=900):
        with self.condition:
            if not self.condition.wait_for(
                lambda: self.finished or self.waiting, timeout
            ):
                raise TimeoutError("Game startup/action timed out")
        if self.error:
            raise RuntimeError(self.error)

    def finish(self):
        if not self.started:
            self.save("not_started")
            self.finished = True
        elif not self.finished:
            self.actions.put("__finish__")
            # A model session must finish its full configured run.
            with self.condition:
                if not self.condition.wait_for(lambda: self.finished, 120):
                    raise TimeoutError("Session has not finished")

    def save(self, status):
        payload = {
            "identity": self.manifest["identity"],
            "task_id": self.manifest["task_id"],
            "status": status,
            "completion": int(self.completed),
            "checkpoint_index": self.checkpoint_index,
            "checkpoint_count": self.manifest["checkpoint_count"],
            "steps": self.steps,
            "controller": self.controller,
            "error": self.error,
            "video_error": self.video.error if self.video else None,
            "model": self.effective_model if self.started else None,
            "cost": self.agent.llm_client.get_total_cost() if self.agent else 0,
        }
        key = (self.root / "result.key").read_text()
        temporary = self.state_dir / "result.tmp"
        temporary.write_text(json.dumps(sign(payload, key), indent=2))
        temporary.replace(self.state_dir / "result.json")
        (self.state_dir / "actions.json").write_text(
            json.dumps(
                {
                    "identity": self.manifest["identity"],
                    "game": self.manifest["game"],
                    "mode": self.settings["mode"],
                    "actions": self.trace,
                },
                indent=2,
            )
        )

    def install_observers(self):
        import ast

        from src.emulators.dos.interface import DOSGameInterface
        from src.emulators.dos.website_server import DOSGameServer
        from src.emulators.gba.interface import GBAInterface
        from src.llm import utils as action_utils
        from src.llm import vgagent
        from src.llm.llm_client import LLMClient
        from src.vgbench_evaluator import BaseVGBenchEvaluator

        # The upstream action parser uses eval on model text. Literal actions have
        # identical meaning, but arbitrary Python must not execute in the scorer.
        action_utils.eval = ast.literal_eval
        if self.settings["api_base"]:
            import litellm

            litellm.api_base = self.settings["api_base"]
        session = self
        original_load = GBAInterface.load_game

        def load_game(game, *args, **kwargs):
            if session.boot_cache_dir is not None and session.controller == "manual":
                from boot_cache import load_game as cached_load

                started = time.monotonic()
                loaded, hit = cached_load(
                    game,
                    original_load,
                    args[0],
                    session.boot_cache_dir,
                    session.manifest["identity"],
                    *args[1:],
                    **kwargs,
                )
                (session.state_dir / "boot.json").write_text(
                    json.dumps(
                        {"cache_hit": hit, "load_seconds": time.monotonic() - started}
                    )
                )
            else:
                loaded = original_load(game, *args, **kwargs)
            session.game = game
            return loaded

        GBAInterface.load_game = load_game
        original_init = vgagent.VideoGameBenchAgent.__init__

        def agent_init(agent, *args, **kwargs):
            kwargs["log_dir"] = session.state_dir / "logs"
            kwargs["log_dir"].mkdir(exist_ok=True)
            original_init(agent, *args, **kwargs)
            agent.llm_client.max_cost = session.settings["max_cost"]
            session.agent = agent

        vgagent.VideoGameBenchAgent.__init__ = agent_init

        original_evaluator_init = BaseVGBenchEvaluator.__init__

        def evaluator_init(evaluator, *args, **kwargs):
            original_evaluator_init(evaluator, *args, **kwargs)
            session.evaluator = evaluator

        BaseVGBenchEvaluator.__init__ = evaluator_init
        original_check = BaseVGBenchEvaluator._check_checkpoint_progress

        def check(evaluator, obs, agent):
            previous = session.checkpoint_index
            finished = original_check(evaluator, obs, agent)
            session.completed |= finished
            session.checkpoint_index = evaluator.current_checkpoint_idx or 0
            changed = session.checkpoint_index != previous
            session.log_progress("checkpoint" if changed else "progress", force=changed)
            return finished

        BaseVGBenchEvaluator._check_checkpoint_progress = check

        gb_observe = vgagent.GameBoyVGAgent.store_observation

        def observe_gb(agent, observation, *args, **kwargs):
            session.publish(observation["screen"])
            return gb_observe(agent, observation, *args, **kwargs)

        vgagent.GameBoyVGAgent.store_observation = observe_gb
        dos_observe = vgagent.WebBrowsingVGAgent.store_observation

        async def observe_dos(agent, frames):
            if frames:
                session.publish(frames[-1])
            return await dos_observe(agent, frames)

        vgagent.WebBrowsingVGAgent.store_observation = observe_dos

        for cls in (vgagent.GameBoyVGAgent, vgagent.WebBrowsingVGAgent):
            original = cls.get_action

            def wrap_get_action(original, is_gb):
                async def get_action(agent, *args, **kwargs):
                    if session.controller == "manual":
                        action = await session.next_action()
                        return (
                            [action]
                            if is_gb
                            else (action["action"], action["action_input"])
                        )
                    session.waiting = True
                    try:
                        return await original(agent, *args, **kwargs)
                    finally:
                        session.waiting = False

                return get_action

            cls.get_action = wrap_get_action(original, cls is vgagent.GameBoyVGAgent)

        for name in ("step", "no_op"):
            original = getattr(GBAInterface, name)

            def wrap_step(original, name):
                def step(game, *args, **kwargs):
                    result = original(game, *args, **kwargs)
                    # The first realtime idle tick precedes scheduling get_action.
                    # Inspect the upstream loop's task rather than a racing flag.
                    pending = sys._getframe(1).f_locals.get("action_task")
                    idle = (
                        name == "no_op" and pending is not None and not pending.done()
                    )
                    if not idle:
                        session.steps += 1
                    session.publish(result[0]["screen"])
                    if session.controller == "vgagent" and not idle:
                        action = args[0] if name == "step" else None
                        session.trace.append(
                            {
                                "action": action,
                                "elapsed_sec": time.monotonic() - session.started_at,
                            }
                        )
                    return result

                return step

            setattr(GBAInterface, name, wrap_step(original, name))
        original_dos_step = DOSGameInterface.step

        async def step_dos(game, action, action_input, *args, **kwargs):
            result = await original_dos_step(
                game, action, action_input, *args, **kwargs
            )
            session.steps += 1
            if session.controller == "vgagent":
                session.trace.append(
                    {
                        "action": {
                            "action": action,
                            "action_input": action_input or "",
                        },
                        "elapsed_sec": time.monotonic() - session.started_at,
                    }
                )
            return result

        DOSGameInterface.step = step_dos

        original_response = LLMClient.generate_response

        async def response(client, *args, **kwargs):
            text = await original_response(client, *args, **kwargs)
            if text.startswith("Error:"):
                # Preserve model parsing; do not turn provider outages into scores.
                raise InfrastructureFailure(
                    "Upstream model client failed; inspect private model logs"
                )
            return text

        LLMClient.generate_response = response

        # Upstream's SimpleHTTPRequestHandler otherwise serves checkpoint files
        # and arbitrary working-directory files to peers on the container network.
        original_handler = DOSGameServer._create_request_handler

        def handler(server, game_url, custom_html=None, lite_mode=False):
            if session.manifest["bundle_local"]:
                game_url = f"http://localhost:{session.settings['port']}/bundle.jsdos"
                if custom_html:
                    from src.consts import GAME_URL_MAP

                    remote = GAME_URL_MAP[session.manifest["game"]]
                    if remote not in custom_html:
                        raise ValueError(
                            "Custom HTML does not contain the configured bundle URL"
                        )
                    custom_html = custom_html.replace(remote, game_url)
            base = original_handler(server, game_url, custom_html, lite_mode)

            class RestrictedHandler(base):
                def do_GET(self):
                    if (
                        self.path == "/bundle.jsdos"
                        and session.manifest["bundle_local"]
                    ):
                        self.send_response(200)
                        self.send_header("Content-Type", "application/octet-stream")
                        self.end_headers()
                        with (session.root / "bundle.jsdos").open("rb") as bundle:
                            import shutil

                            shutil.copyfileobj(bundle, self.wfile)
                    elif self.path in {"/", "/index.html", "/dosbox.conf"}:
                        super().do_GET()
                    else:
                        self.send_error(404)

            return RestrictedHandler

        DOSGameServer._create_request_handler = handler

    def run(self, api_key, model):
        self.started_at = time.monotonic()
        self.effective_model = model or self.settings["model"]
        os.chdir(self.root / "upstream")
        sys.path.insert(0, str(self.root / "upstream"))
        try:
            self.progress_started_at = self.started_at
            self.log_progress("started", force=True)
            if self.settings["seed"] is not None:
                random.seed(self.settings["seed"])
                import numpy as np

                np.random.seed(self.settings["seed"])
            import main as upstream_main

            argv = [
                "main.py",
                "--game",
                self.manifest["game"],
                "--headless",
                "--model",
                self.effective_model,
            ]
            for name in (
                "max_steps",
                "action_frames",
                "skip_frames",
                "step_delay",
                "threshold",
                "temperature",
                "max_tokens",
                "history_tokens",
                "max_context_size",
                "num_screenshots_per_action",
                "api_base",
                "port",
            ):
                value = self.settings[name]
                if value is not None:
                    argv.extend(["--" + name.replace("_", "-"), str(value)])
            if self.settings["mode"] == "lite":
                argv.append("--lite")
            sys.argv = argv
            args = upstream_main.load_game_config(upstream_main.parse_args())
            args.api_key = api_key
            (self.state_dir / "effective-settings.json").write_text(
                json.dumps(
                    {
                        "argv": argv,
                        "settings": self.settings,
                        "threshold": args.threshold,
                        "checkpoint_count": len(args.checkpoints or []),
                    },
                    indent=2,
                )
            )
            self.install_observers()
            if args.emulator == "gba":
                from src.run_vgbench_gb import run_gba_emulator

                asyncio.run(run_gba_emulator(args))
            else:
                from src.run_vgbench_dos import run_dos_emulator

                asyncio.run(run_dos_emulator(args))
            if self.steps != self.settings["max_steps"]:
                raise InfrastructureFailure(
                    "Upstream loop exited before the configured step budget"
                )
            status = "completed"
        except StopEpisode:
            status = "stopped"
        except BaseException as exc:  # noqa: BLE001 -- isolate and record all worker failures
            import traceback

            traceback.print_exc()
            self.error = f"{type(exc).__name__}: {exc}"
            status = "infrastructure_error"
        finally:
            if self.video is not None:
                self.video.close()
            self.save(status)
            self.log_progress("finished", force=True, status=status)
            with self.condition:
                self.finished = True
                self.waiting = False
                self.condition.notify_all()
