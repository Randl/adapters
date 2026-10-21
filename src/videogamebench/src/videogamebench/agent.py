"""Harbor lifecycle shim; the isolated service executes upstream VG-Agent."""

import os
import shlex

from harbor.agents.base import BaseAgent


class VideoGameBenchAgent(BaseAgent):
    def __init__(
        self, *args, api_key_env="OPENAI_API_KEY", timeout_sec=86400, **kwargs
    ):
        super().__init__(*args, **kwargs)
        self.api_key_env = api_key_env
        self.timeout_sec = timeout_sec

    @staticmethod
    def name():
        return "videogamebench-vgagent"

    def version(self):
        return "faab531"

    async def setup(self, environment):
        pass

    async def run(self, instruction, environment, context):
        command = [
            "python",
            "/opt/game/play.py",
            "--vgagent",
            "--api-key-env",
            self.api_key_env,
        ]
        if self.model_name:
            command += ["--model", self.model_name]
        key = self.extra_env.get(self.api_key_env, os.environ.get(self.api_key_env))
        result = await environment.exec(
            command=shlex.join(command),
            env={self.api_key_env: key} if key else {},
            timeout_sec=self.timeout_sec,
        )
        if result.return_code != 0:
            raise RuntimeError(f"Upstream gameplay failed: {result.stderr}")
        context.metadata = {
            "upstream_agent": self.version(),
            "runtime": "isolated upstream evaluator",
        }
