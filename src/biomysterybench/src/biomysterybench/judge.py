"""Shared, explicit OpenAI-compatible judge configuration."""

import math
import os
from dataclasses import dataclass
from urllib.parse import urlsplit

DEFAULT_BASE_URL = "https://api.openai.com/v1"


def endpoint_host(base_url: str) -> str:
    url = urlsplit(base_url)
    if (
        url.scheme not in {"http", "https"}
        or not url.hostname
        or url.username
        or url.password
        or url.query
        or url.fragment
    ):
        raise ValueError("Judge base URL must be an absolute HTTP(S) URL without credentials")
    return url.hostname


@dataclass(frozen=True)
class JudgeConfig:
    model: str
    base_url: str
    temperature: float | None
    timeout: float

    @classmethod
    def from_env(
        cls, model: str | None = None, base_url: str | None = None
    ) -> "JudgeConfig":
        model = (model or os.environ.get("JUDGE_MODEL", "")).strip()
        if not model:
            raise ValueError("Set JUDGE_MODEL explicitly; no official judge is known")
        base_url = (
            base_url or os.environ.get("OPENAI_BASE_URL") or DEFAULT_BASE_URL
        ).rstrip("/")
        endpoint_host(base_url)
        raw_temperature = os.environ.get("JUDGE_TEMPERATURE", "")
        temperature = float(raw_temperature) if raw_temperature else None
        if temperature is not None and (
            not math.isfinite(temperature) or not 0 <= temperature <= 2
        ):
            raise ValueError("JUDGE_TEMPERATURE must be between 0 and 2")
        timeout = float(os.environ.get("JUDGE_TIMEOUT_SEC", "120"))
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("JUDGE_TIMEOUT_SEC must be positive")
        return cls(
            model=model,
            base_url=base_url,
            temperature=temperature,
            timeout=timeout,
        )

    def completion_options(self) -> dict:
        options: dict = {"model": self.model, "response_format": {"type": "json_object"}}
        if self.temperature is not None:
            options["temperature"] = self.temperature
        return options

    def validate_response(self, response: dict) -> None:
        choices = response.get("choices", [])
        if (
            len(choices) != 1
            or choices[0].get("finish_reason") != "stop"
            or choices[0].get("message", {}).get("refusal")
        ):
            raise ValueError("Incomplete or refused judge response")
