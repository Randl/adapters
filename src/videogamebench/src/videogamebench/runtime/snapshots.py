"""Content-addressed snapshots of human Game Boy Lite action boundaries."""

import hashlib
import io
import json
import zipfile
from pathlib import Path


def extend(digest, action):
    encoded = json.dumps(action, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(bytes.fromhex(digest) + encoded).hexdigest()


class SnapshotStore:
    def __init__(self, directory, identity, emulator_version, interval=100):
        self.directory = Path(directory)
        self.interval = interval
        self.initial = hashlib.sha256(
            json.dumps([1, identity, emulator_version]).encode()
        ).hexdigest()
        self.digest = self.initial
        self.steps = 0

    def advance(self, actions):
        for action in actions:
            self.digest = extend(self.digest, action)
            self.steps += 1

    def save(self, state, screen, progress):
        metadata = {**progress, "steps": self.steps, "prefix": self.digest}
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("metadata.json", json.dumps(metadata))
            archive.writestr("emulator.state", state)
            archive.writestr("screen.png", screen)
        payload = buffer.getvalue()
        self.directory.mkdir(parents=True, exist_ok=True)
        target = self.directory / f"{self.digest}.snapshot"
        temporary = target.with_suffix(".tmp")
        temporary.write_bytes(hashlib.sha256(payload).digest() + payload)
        temporary.replace(target)

    def nearest(self, actions):
        digest = self.initial
        candidates = []
        for step, action in enumerate(actions, 1):
            digest = extend(digest, action)
            path = self.directory / f"{digest}.snapshot"
            if path.exists():
                candidates.append((step, digest, path))
        for step, digest, path in reversed(candidates):
            try:
                encoded = path.read_bytes()
                if hashlib.sha256(encoded[32:]).digest() != encoded[:32]:
                    continue
                with zipfile.ZipFile(io.BytesIO(encoded[32:])) as archive:
                    metadata = json.loads(archive.read("metadata.json"))
                    if metadata["steps"] != step or metadata["prefix"] != digest:
                        continue
                    return (
                        metadata,
                        archive.read("emulator.state"),
                        archive.read("screen.png"),
                    )
            except (OSError, ValueError, KeyError, zipfile.BadZipFile):
                continue
        return None
