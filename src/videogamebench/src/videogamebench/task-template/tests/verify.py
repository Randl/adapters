"""Replay validated actions against real emulator screens and upstream checkpoints."""

import json
from pathlib import Path

from checkpoint import BaseVGBenchEvaluator
from PIL import Image
from src.emulators.gba.interface import GBAInterface
from src.utils import hash_image


class ReplayEvaluator(BaseVGBenchEvaluator):
    async def run_episode(self, agent):
        raise NotImplementedError(
            "Independent replay uses the upstream checkpoint checker"
        )


class Progress:
    def __init__(self):
        self.index = 0

    def update_checkpoint(self, index):
        self.index = index


def load_actions(path: Path, max_steps: int) -> list:
    if path.is_symlink() or path.stat().st_size > 4_000_000:
        raise ValueError("Invalid replay file")
    actions = json.loads(path.read_text())
    if not isinstance(actions, list) or len(actions) > max_steps:
        raise ValueError("Invalid replay length")
    for action in actions:
        if action is not None and (
            not isinstance(action, dict)
            or any(
                key not in GBAInterface.BUTTON_MAP or type(value) is not bool
                for key, value in action.items()
            )
        ):
            raise ValueError("Invalid replay action")
    return actions


def replay(actions: list, game, evaluator, progress, frames: int) -> bool:
    finished = False
    for action in actions:
        obs, _, _, _ = (
            game.no_op(frames) if action is None else game.step(action, frames)
        )
        finished |= evaluator._check_checkpoint_progress(obs["screen"], progress)
    return finished


def main() -> None:
    config = json.loads(Path("/tests/game.json").read_text())
    try:
        actions = load_actions(Path("/workspace/actions.json"), config["max_steps"])
    except (OSError, UnicodeError, ValueError):
        actions = []
    progress = Progress()
    if actions:
        checkpoints = sorted(
            Path("/tests/checkpoints").glob("*.png"), key=lambda p: int(p.stem)
        )
        hashes = [hash_image(Image.open(p)) for p in checkpoints]
        evaluator = ReplayEvaluator(checkpoints=hashes, threshold=config["threshold"])
        game = GBAInterface(render=False)
        if not game.load_game("/opt/game/game.gb"):
            raise RuntimeError("ROM could not be loaded; no reward produced")
        try:
            finished = replay(
                actions, game, evaluator, progress, config["action_frames"]
            )
        finally:
            game.close()
    else:
        finished = False
    result = {
        "task_id": config["task_id"],
        "completion": int(finished),
        "checkpoint_index": progress.index,
        "actions": len(actions),
        "rom_sha256": config["rom_sha256"],
        "mode": "lite",
    }
    Path("/logs/verifier/replay.json").write_text(json.dumps(result, indent=2))
    Path("/logs/verifier/reward.txt").write_text(str(int(finished)))


if __name__ == "__main__":
    main()
