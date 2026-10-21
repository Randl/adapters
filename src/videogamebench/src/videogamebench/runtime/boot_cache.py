"""Cache the exact upstream post-boot state for the human Game Boy recorder."""

import hashlib
import io
import json
from importlib.metadata import version
from pathlib import Path


def load_game(game, original_load, rom_path, cache_dir, identity, *args, **kwargs):
    from src.emulators.gba.interface import PyBoy

    key = hashlib.sha256(
        json.dumps(
            {"identity": identity, "pyboy": version("pyboy")}, sort_keys=True
        ).encode()
    ).hexdigest()
    cache = Path(cache_dir) / f"{key}.state"
    if cache.exists():
        try:
            encoded = cache.read_bytes()
            digest, payload = encoded[:32], encoded[32:]
            if hashlib.sha256(payload).digest() != digest:
                raise ValueError("Incomplete boot cache")
            game.pyboy = PyBoy(rom_path, window="SDL2" if game.render else "headless")
            game.pyboy.load_state(io.BytesIO(payload))
            game.pyboy.set_emulation_speed(1)
            return True, True
        except Exception:  # noqa: BLE001 -- invalid caches fall back to an ordinary upstream boot
            if game.pyboy is not None:
                game.pyboy.stop(save=False)
                game.pyboy = None
    loaded = original_load(game, rom_path, *args, **kwargs)
    if loaded:
        state = io.BytesIO()
        game.pyboy.save_state(state)
        payload = state.getvalue()
        cache.parent.mkdir(parents=True, exist_ok=True)
        temporary = cache.with_suffix(".tmp")
        temporary.write_bytes(hashlib.sha256(payload).digest() + payload)
        temporary.replace(cache)
    return loaded, False
