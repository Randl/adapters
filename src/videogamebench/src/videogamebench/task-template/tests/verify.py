"""Grade authenticated live evidence, never agent-supplied screenshots or scores."""

import json
from pathlib import Path

from evidence import verify


def main():
    config = json.loads(Path("/tests/manifest.json").read_text())
    envelope = json.loads(Path("/state/result.json").read_text())
    result = verify(envelope, Path("/tests/result.key").read_text(), config["identity"])
    Path("/logs/verifier/result.json").write_text(json.dumps(result, indent=2))
    if result["status"] == "infrastructure_error":
        raise RuntimeError(result["error"])
    if not result["checkpoint_count"]:
        raise RuntimeError(
            "Upstream releases no checkpoints for this game: trajectory collected, completion unscored"
        )
    if result["status"] not in {"completed", "stopped", "not_started"}:
        raise ValueError("Invalid session status")
    Path("/logs/verifier/reward.txt").write_text(str(result["completion"]))
    print(
        f"Final-checkpoint score: {result['completion']} | "
        f"checkpoint index: {result['checkpoint_index']}/{result['checkpoint_count']} | "
        f"actions: {result['steps']} | status: {result['status']}",
        flush=True,
    )


if __name__ == "__main__":
    main()
