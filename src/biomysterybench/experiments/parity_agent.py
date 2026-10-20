"""Native Anthropic-compatible bash agent with explicit settings and no fallback."""

import json
import os
import shlex
from urllib.parse import urlsplit

import httpx
from harbor.agents.base import BaseAgent
from harbor.agents.options import AgentOptions
from pydantic import Field

SYSTEM = (
    "Complete the supplied task in the Linux workspace using the bash tool. "
    "Use the provided files and follow the task's database-access rules. "
    "Write the requested answer and report files before finishing."
)


class ParityOptions(AgentOptions):
    api_base: str
    api_key_env: str = "ANTHROPIC_API_KEY"
    api_version: str = "2023-06-01"
    max_turns: int = Field(gt=0)
    max_tokens: int = Field(gt=0)
    thinking: dict
    effort: str
    request_timeout_sec: float = Field(gt=0)
    tool_timeout_sec: int = Field(gt=0)
    max_tool_output_chars: int = Field(gt=0)


class ParityAgent(BaseAgent):
    options_model = ParityOptions

    @staticmethod
    def name() -> str:
        return "biomysterybench-parity"

    def version(self) -> str:
        return "0.1.0"

    async def setup(self, environment) -> None:
        # No provider credentials, HF cache, remote tools, or SDK inside the sandbox.
        pass

    async def run(self, instruction, environment, context) -> None:
        if not self.model_name:
            raise ValueError("Set model_name in the Harbor job configuration")
        model = self.model_name.removeprefix("anthropic/")
        options = self.options
        assert isinstance(options, ParityOptions)
        base = options.api_base.rstrip("/")
        url = urlsplit(base)
        if (
            url.scheme not in {"http", "https"}
            or not url.hostname
            or url.username
            or url.password
            or url.query
            or url.fragment
        ):
            raise ValueError("api_base must be an HTTP(S) URL without credentials")
        api_key = os.environ[options.api_key_env]
        tools = [
            {
                "name": "bash",
                "description": "Execute a bash command in /workspace and return its output.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "command": {"type": "string"},
                        "timeout_sec": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": options.tool_timeout_sec,
                        },
                    },
                    "required": ["command"],
                    "additionalProperties": False,
                },
            }
        ]
        if self.mcp_servers:
            raise ValueError("Remote/MCP tools are not part of this experiment")
        # A sibling of agent/ is not Harbor's agent-log mount. Keep the canonical
        # transcript on the host so sandbox commands cannot rewrite the audit.
        evidence = self.logs_dir.parent / "trusted-solver"
        evidence.mkdir(exist_ok=False)
        evidence.chmod(0o700)
        context.metadata = {
            "model": model,
            "response_models": [],
            "options": options.model_dump(),
            "trusted_transcript": str(evidence),
        }
        messages = [{"role": "user", "content": instruction}]
        # Endpoint is explicit in the saved job config. No implicit proxy,
        # retries, redirects, fallback middleware, or server-side tools.
        async with httpx.AsyncClient(
            trust_env=False, follow_redirects=False, timeout=options.request_timeout_sec
        ) as client:
            for turn in range(options.max_turns):
                payload = {
                    "model": model,
                    "max_tokens": options.max_tokens,
                    "thinking": options.thinking,
                    "output_config": {"effort": options.effort},
                    "system": SYSTEM,
                    "tools": tools,
                    "messages": messages,
                }
                (evidence / f"{turn:04d}-request.json").write_text(json.dumps(payload))
                response = await client.post(
                    base + "/messages",
                    headers={
                        "x-api-key": api_key,
                        "anthropic-version": options.api_version,
                    },
                    json=payload,
                )
                (evidence / f"{turn:04d}-response.json").write_text(
                    json.dumps(
                        {
                            "status_code": response.status_code,
                            "request_id": response.headers.get("request-id"),
                            "body": response.text,
                        }
                    )
                )
                response.raise_for_status()
                body = response.json()
                if body.get("model") not in context.metadata["response_models"]:
                    context.metadata["response_models"].append(body.get("model"))
                usage = body.get("usage", {})
                context.n_input_tokens = (context.n_input_tokens or 0) + sum(
                    usage.get(k, 0)
                    for k in (
                        "input_tokens",
                        "cache_read_input_tokens",
                        "cache_creation_input_tokens",
                    )
                )
                context.n_output_tokens = (context.n_output_tokens or 0) + usage.get(
                    "output_tokens", 0
                )
                context.n_cache_tokens = (context.n_cache_tokens or 0) + usage.get(
                    "cache_read_input_tokens", 0
                )
                reason = body.get("stop_reason")
                if reason == "refusal":
                    (evidence / "refusal.json").write_text(
                        json.dumps({"turn": turn, "stop_details": body.get("stop_details")})
                    )
                    raise RuntimeError("Solver refused; no retry or model substitution")
                if reason not in {"tool_use", "end_turn"}:
                    raise RuntimeError(f"Incomplete model response: {reason}")
                messages.append({"role": "assistant", "content": body["content"]})
                calls = [b for b in body["content"] if b["type"] == "tool_use"]
                if reason == "end_turn":
                    if calls:
                        raise ValueError("Tool calls in an end_turn response")
                    (evidence / "complete.json").write_text(json.dumps({"turns": turn + 1}))
                    return
                if not calls:
                    raise ValueError("tool_use response without tools")
                results = []
                for call in calls:
                    args = call["input"]
                    timeout = args.get("timeout_sec", options.tool_timeout_sec)
                    if (
                        call["name"] != "bash"
                        or not isinstance(args.get("command"), str)
                        or type(timeout) is not int
                        or not 1 <= timeout <= options.tool_timeout_sec
                    ):
                        raise ValueError("Invalid bash tool invocation")
                    result = await environment.exec(
                        "bash -c " + shlex.quote(args["command"]),
                        cwd="/workspace",
                        timeout_sec=timeout,
                    )
                    output = json.dumps(
                        {
                            "exit_code": result.exit_code,
                            "stdout": result.stdout,
                            "stderr": result.stderr,
                        }
                    )
                    # Preserve full tool output for the host audit, even if the
                    # model-facing observation must be shortened.
                    (evidence / f"{turn:04d}-tool-{len(results):03d}.json").write_text(
                        output
                    )
                    if len(output) > options.max_tool_output_chars:
                        output = (
                            output[: options.max_tool_output_chars]
                            + f"\n[tool output truncated at {options.max_tool_output_chars} characters]"
                        )
                    results.append(
                        {"type": "tool_result", "tool_use_id": call["id"], "content": output}
                    )
                messages.append({"role": "user", "content": results})
        raise RuntimeError("Turn budget exhausted; no continuation on another model")
