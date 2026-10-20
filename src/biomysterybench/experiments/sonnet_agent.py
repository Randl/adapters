"""Prepared Harbor 0.24.0 bash agent: direct Sonnet 5, no routing or retries."""

import json
import os
import shlex

import httpx
from harbor.agents.base import BaseAgent

MODEL = "claude-sonnet-5"
ENDPOINT = "https://api.anthropic.com/v1/messages"
SYSTEM = (
    "Complete the supplied task in the Linux workspace using the bash tool. "
    "Use the provided files and follow the task's database-access rules. "
    "Write the requested answer and report files before finishing."
)
TOOLS = [
    {
        "name": "bash",
        "description": "Execute a bash command in /workspace and return its output.",
        "input_schema": {
            "type": "object",
            "properties": {
                "command": {"type": "string"},
                "timeout_sec": {"type": "integer", "minimum": 1, "maximum": 600},
            },
            "required": ["command"],
            "additionalProperties": False,
        },
    }
]

# Executed before the first inference call, after Harbor applies network policy.
# An HF authentication rejection is NOT a successful isolation test.
NETWORK_PROBE = r"""
import json, os, pathlib, subprocess
blocked = [
    "https://huggingface.co/datasets/Anthropic/BioMysteryBench-preview/raw/main/problems.csv",
    "https://huggingface.co/datasets/Anthropic/BioMysteryBench-full/raw/main/problems.csv",
    "https://datasets-server.huggingface.co/",
    "https://cdn-lfs.huggingface.co/",
    "https://cas-bridge.xethub.hf.co/",
    "https://github.com/",
    "https://raw.githubusercontent.com/",
    "https://gist.githubusercontent.com/",
    "https://www.anthropic.com/",
    "https://api.anthropic.com/",
    "https://api.openai.com/",
    "https://www.google.com/",
    "https://1.1.1.1/",
]
def probe(url):
    p = subprocess.run(
        ["curl", "--silent", "--show-error", "--connect-timeout", "3",
         "--max-time", "6", "--output", "/dev/null",
         "--write-out", "%{http_code}", url],
        capture_output=True, text=True, timeout=8,
    )
    return {"url": url, "returncode": p.returncode, "http_code": p.stdout}
positive = probe("https://pypi.org/simple/")
results = [probe(url) for url in blocked]
secrets = [k for k in ["HF_TOKEN", "HUGGING_FACE_HUB_TOKEN",
    "HUGGINGFACE_HUB_TOKEN", "ANTHROPIC_API_KEY", "OPENAI_API_KEY"]
    if os.environ.get(k)]
private = [str(p) for p in [
    pathlib.Path("/tests/problem.json"), pathlib.Path("/solution/answer.txt"),
    pathlib.Path.home()/".cache/huggingface/token",
    pathlib.Path.home()/".huggingface/token",
] if p.exists()]
passed = (positive["returncode"] == 0 and positive["http_code"] == "200"
    and all(r["returncode"] != 0 and r["http_code"] == "000" for r in results)
    and not secrets and not private)
print(json.dumps({"passed": passed, "positive": positive, "blocked": results,
                  "credential_names_present": secrets, "private_paths": private}))
raise SystemExit(0 if passed else 1)
"""


class Sonnet5Agent(BaseAgent):
    @staticmethod
    def name() -> str:
        return "biomysterybench-sonnet5"

    def version(self) -> str:
        return "0.1.0"

    async def setup(self, environment) -> None:
        # No provider credentials, HF cache, remote tools, or SDK inside the sandbox.
        pass

    async def run(self, instruction, environment, context) -> None:
        stop_file = self.logs_dir.parent.parent / "sonnet5.stop"
        if stop_file.exists():
            raise RuntimeError("An earlier trial failed; this job is stopped for review")
        try:
            await self._run_once(instruction, environment, context)
        except BaseException as error:
            # With concurrency=1, no subsequent trial in this job may make
            # inference calls after an error/refusal. Never erase this latch on resume.
            stop_file.write_text(type(error).__name__ + "\n")
            raise

    async def _run_once(self, instruction, environment, context) -> None:
        if self.model_name != f"anthropic/{MODEL}":
            raise ValueError(f"This experiment requires anthropic/{MODEL}")
        if self.mcp_servers:
            raise ValueError("Remote/MCP tools are not part of this experiment")
        # A sibling of agent/ is not Harbor's agent-log mount. Keep the canonical
        # transcript on the host so sandbox commands cannot rewrite the audit.
        evidence = self.logs_dir.parent / "trusted-solver"
        evidence.mkdir(exist_ok=False)
        evidence.chmod(0o700)
        check = await environment.exec(
            "python -c " + shlex.quote(NETWORK_PROBE), timeout_sec=120
        )
        (evidence / "network-check.json").write_text(
            json.dumps(
                {
                    "exit_code": check.exit_code,
                    "stdout": check.stdout,
                    "stderr": check.stderr,
                }
            )
        )
        if check.exit_code != 0:
            raise RuntimeError("Network/private-data preflight failed; no inference sent")
        context.metadata = {
            "model": MODEL,
            "fallback": False,
            "effort": "high",
            "max_turns": 150,
            "max_tokens_per_response": 32768,
            "trusted_transcript": str(evidence),
        }
        messages = [{"role": "user", "content": instruction}]
        # Fixed first-party endpoint; no proxy/env endpoint overrides, SDK retry,
        # fallback middleware, beta fallback headers, or server-side tools.
        async with httpx.AsyncClient(
            trust_env=False, follow_redirects=False, timeout=900
        ) as client:
            for turn in range(150):
                payload = {
                    "model": MODEL,
                    "max_tokens": 32768,
                    "thinking": {"type": "adaptive"},
                    "output_config": {"effort": "high"},
                    "system": SYSTEM,
                    "tools": TOOLS,
                    "messages": messages,
                }
                (evidence / f"{turn:04d}-request.json").write_text(json.dumps(payload))
                response = await client.post(
                    ENDPOINT,
                    headers={
                        "x-api-key": os.environ["ANTHROPIC_API_KEY"],
                        "anthropic-version": "2023-06-01",
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
                iterations = body.get("usage", {}).get("iterations") or []
                if (
                    body.get("model") != MODEL
                    or any(b.get("type") == "fallback" for b in body.get("content", []))
                    or any(i.get("type") == "fallback_message" for i in iterations)
                ):
                    raise RuntimeError("Unexpected model/fallback; invalidate this trial")
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
                    raise RuntimeError("Sonnet 5 refused; no retry or model substitution")
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
                    timeout = args.get("timeout_sec", 600)
                    if (
                        call["name"] != "bash"
                        or not isinstance(args.get("command"), str)
                        or type(timeout) is not int
                        or not 1 <= timeout <= 600
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
                    if len(output) > 100_000:
                        output = (
                            output[:100_000]
                            + "\n[tool output truncated at 100000 characters]"
                        )
                    results.append(
                        {"type": "tool_result", "tool_use_id": call["id"], "content": output}
                    )
                messages.append({"role": "user", "content": results})
        raise RuntimeError("150-turn budget exhausted; no continuation on another model")
