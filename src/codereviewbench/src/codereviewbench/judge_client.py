"""Explicit request configuration shared by the native and Harbor judges."""

import asyncio
import importlib
import math
import os
import sys
from typing import Any, cast


def parse_temperature(value: str) -> float | None:
    if value == "default":
        return None
    try:
        temperature = float(value)
    except ValueError:
        raise ValueError(
            "JUDGE_TEMPERATURE must be 'default' or a number in [0, 2]"
        ) from None
    if not math.isfinite(temperature) or not 0 <= temperature <= 2:
        raise ValueError("JUDGE_TEMPERATURE must be 'default' or a number in [0, 2]")
    return temperature


def create_client(**kwargs):
    from openai import AsyncOpenAI

    temperature = parse_temperature(os.environ.get("JUDGE_TEMPERATURE", "0"))
    client = AsyncOpenAI(**kwargs)
    original_create = client.chat.completions.create

    async def create(**request):
        if temperature is None:
            request.pop("temperature", None)
        else:
            request["temperature"] = temperature
        return await original_create(**request)

    cast(Any, client.chat.completions).create = create
    return client


def main() -> None:
    """Run a pinned upstream CLI with only its client factory replaced."""
    name = sys.argv.pop(1)
    if name not in {"step2_5_dedup_candidates", "step3_judge_comments"}:
        raise ValueError("Unsupported upstream module")
    module = importlib.import_module(f"code_review_benchmark.{name}")
    cast(Any, module).AsyncOpenAI = create_client
    print(f"Judge temperature: {os.environ.get('JUDGE_TEMPERATURE', '0')}", flush=True)
    asyncio.run(module.main())


if __name__ == "__main__":
    main()
