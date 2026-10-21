"""Preserve human attempts without mixing their traces or videos."""

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4


def archive_attempt(state_dir: Path) -> Path:
    name = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:8]
    archive = state_dir / "attempts" / name
    archive.mkdir(parents=True)
    for item in state_dir.iterdir():
        if item.name not in {"attempts", ".boot-cache", ".snapshots"}:
            item.rename(archive / item.name)
    return archive


def rewind_prefix(trace: list, actions: int) -> list:
    if type(actions) is not int or not 1 <= actions <= len(trace):
        raise ValueError(f"Rewind actions must be between 1 and {len(trace)}")
    return [item["action"] for item in trace[:-actions]]
