import asyncio
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

import httpx
import openai
import pytest
import yaml

from codereviewbench.adapter import PACKAGE, CodeReviewBenchAdapter, sanity_ids
from codereviewbench.experiments import prepare, run_logged, runtime_config, upstream
from codereviewbench.metric import aggregate


def load_module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def source():
    value = os.environ.get("CODEREVIEWBENCH_SOURCE")
    if not value:
        pytest.skip("Set CODEREVIEWBENCH_SOURCE for upstream integration")
    return Path(value)


@pytest.fixture
def tasks(tmp_path, source):
    output = tmp_path / "tasks"
    CodeReviewBenchAdapter(output, source_dir=source).run()
    return output


@pytest.fixture
def verifier(tasks, monkeypatch):
    test_dir = min(tasks.iterdir()) / "tests"
    monkeypatch.syspath_prepend(str(test_dir))
    return load_module(test_dir / "verify.py", "security_verify")


def test_sources_are_pinned_and_dirty_source_rejected(source, tmp_path):
    hashes = json.loads((PACKAGE / "upstream_hashes.json").read_text())
    for name, expected in hashes.items():
        target = tmp_path / "source" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source / name, target)
        assert hashlib.sha256(target.read_bytes()).hexdigest() == expected
    (tmp_path / "source/offline/analysis/score_profiles.py").write_text("tampered")
    with pytest.raises(ValueError, match="does not match"):
        CodeReviewBenchAdapter(tmp_path / "tasks", source_dir=tmp_path / "source").run()
    assert not (tmp_path / "tasks").exists()


def test_isolation_and_experiment_settings(tasks, source, tmp_path):
    for task in tasks.iterdir():
        config = tomllib.loads((task / "task.toml").read_text())
        assert config["environment"]["network_mode"] == "no-network"
        assert config["verifier"]["environment_mode"] == "separate"
        assert config["verifier"]["allowed_hosts"] == ["api.withmartian.com"]
        assert set(config["verifier"]["env"]) == {
            "JUDGE_API_KEY",
            "JUDGE_MODEL",
            "JUDGE_BASE_URL",
            "JUDGE_TEMPERATURE",
        }
        assert {p.name for p in (task / "environment").iterdir()} == {
            "Dockerfile",
            "docker-compose.yaml",
        }
        compose = yaml.safe_load((task / "environment/docker-compose.yaml").read_text())
        assert compose["services"]["main"]["network_mode"] == "none"
        assert json.loads((task / "solution/review.json").read_text()) == [
            c["comment"]
            for c in json.loads((task / "tests/problem.json").read_text())[
                "golden_comments"
            ]
        ]
    assert len(sanity_ids()) == 10
    output = tmp_path / "experiments"
    prepare(tasks, source, output, PACKAGE.parents[1] / "codereviewbench-parity.yaml")
    for stage in ("sanity", "run1", "run2", "run3"):
        original = yaml.safe_load((output / f"original-{stage}.yaml").read_text())
        harbor = yaml.safe_load((output / f"harbor-{stage}.yaml").read_text())
        for key in ("agents", "datasets", "environment", "orchestrator", "n_attempts"):
            assert original[key] == harbor[key]
        assert original["verifier"]["disable"] is True
    script = (output / "run-parity.sh").read_text()
    assert script.index("harbor-sanity.yaml") < script.index("original-run1.yaml")
    assert script.index("harbor-run1.yaml") < script.index("original-run2.yaml")
    assert "oracle" not in script
    assert "MARTIAN_" not in script
    assert "${JUDGE_API_KEY:?" in script


def test_provider_neutral_settings_reach_upstream(
    verifier, source, tmp_path, monkeypatch
):
    settings = {
        "API_KEY": "test-provider-key",
        "MODEL": "custom/judge",
        "BASE_URL": "https://judge.example/v1",
    }
    for suffix, value in settings.items():
        monkeypatch.setenv(f"JUDGE_{suffix}", value)
        monkeypatch.setenv(f"MARTIAN_{suffix}", "stale-upstream-value")
    verifier.configure_upstream()
    for client in (verifier.DedupLLM(), verifier.LLMJudge()):
        assert client.client.api_key == settings["API_KEY"]
        assert str(client.client.base_url).rstrip("/") == settings["BASE_URL"]
        assert client.model == settings["MODEL"]

    # The original CLI subprocess must receive the same settings, without
    # inheriting any stale provider-specific key from the host.
    monkeypatch.setenv("MARTIAN_API_KEY", "stale-upstream-value")

    def capture_run(*args, **kwargs):
        env = kwargs["env"]
        for suffix, value in settings.items():
            assert env[f"MARTIAN_{suffix}"] == value
        raise RuntimeError("captured upstream invocation")

    monkeypatch.setattr("codereviewbench.experiments.run_logged", capture_run)
    with pytest.raises(RuntimeError, match="captured upstream invocation"):
        upstream(
            source,
            tmp_path / "upstream",
            None,
            True,
            settings["MODEL"],
            settings["BASE_URL"],
        )


@pytest.mark.parametrize("exit_code", [0, 7])
def test_upstream_output_is_visible_and_saved(tmp_path, capsys, exit_code):
    log = tmp_path / "judge.log"
    command = [
        sys.executable,
        "-u",
        "-c",
        f"import sys; print('judge progress'); print('judge stderr', file=sys.stderr); sys.exit({exit_code})",
    ]
    if exit_code:
        with pytest.raises(RuntimeError, match=r"judge failed \(exit 7\); log:"):
            run_logged(command, cwd=tmp_path, env=dict(os.environ), log_path=log)
    else:
        run_logged(command, cwd=tmp_path, env=dict(os.environ), log_path=log)
    output = capsys.readouterr().out
    assert "judge progress" in output and "judge stderr" in output
    assert "judge progress" in log.read_text() and "judge stderr" in log.read_text()
    assert str(log) in output


def test_launcher_reports_preflight_and_stage_failures(tasks, source, tmp_path):
    output = tmp_path / "prepared"
    prepare(tasks, source, output, PACKAGE.parents[1] / "codereviewbench-parity.yaml")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    harbor = bin_dir / "harbor"
    env = dict(
        os.environ,
        PATH=f"{bin_dir}:{os.environ['PATH']}",
        JUDGE_API_KEY="test",
        JUDGE_MODEL="gpt-6-luna",
        JUDGE_BASE_URL="https://api.openai.com/v1",
        JUDGE_TEMPERATURE="default",
    )
    for version, expected in (
        ("wrong", "Expected Harbor 0.24.0; found wrong"),
        ("0.24.0", "original-sanity failed (exit 7"),
    ):
        harbor.write_text(
            f'#!/bin/sh\nif [ "$1" = "--version" ]; then echo {version}; else exit 7; fi\n'
        )
        harbor.chmod(0o755)
        result = subprocess.run(
            ["sh", str(output / "run-parity.sh")],
            check=False,
            env=env,
            capture_output=True,
            text=True,
        )
        assert result.returncode != 0
        assert "Checking credentials" in result.stdout
        assert expected in result.stderr
        assert "Completed." not in result.stdout
        if version == "0.24.0":
            assert "Judge model: gpt-6-luna" in result.stdout
            assert "Judge endpoint: https://api.openai.com/v1" in result.stdout
    run = next((output / "runs").iterdir())
    judge = json.loads((run / "plan.json").read_text())["judge"]
    assert judge["JUDGE_MODEL"] == "gpt-6-luna"
    assert judge["JUDGE_BASE_URL"] == "https://api.openai.com/v1"
    assert judge["JUDGE_TEMPERATURE"] == "default"
    for config_path in run.glob("*.yaml"):
        config = yaml.safe_load(config_path.read_text())
        assert config["verifier"]["env"] == judge
        assert config["datasets"][0]["path"] == str(run / "tasks")
    for task_path in (run / "tasks").glob("*/task.toml"):
        task = tomllib.loads(task_path.read_text())
        assert task["verifier"]["env"] == judge
        assert task["verifier"]["allowed_hosts"] == ["api.openai.com"]
        assert task["environment"]["network_mode"] == "no-network"
    # Defaults in the prepared experiment remain intact for subsequent launches.
    assert (
        json.loads((output / "plan.json").read_text())["judge"]["JUDGE_MODEL"]
        != "gpt-6-luna"
    )


def test_runtime_preserves_exact_url_and_separates_results(tasks, source, tmp_path):
    output = tmp_path / "prepared"
    prepare(tasks, source, output, PACKAGE.parents[1] / "codereviewbench-parity.yaml")
    first = runtime_config(output, source, "custom/model", "https://api.openai.com/")
    second = runtime_config(output, source, "custom/model", "https://api.openai.com/")
    assert first != second
    for run in (first, second):
        judge = json.loads((run / "plan.json").read_text())["judge"]
        assert judge["JUDGE_BASE_URL"] == "https://api.openai.com/"
        assert judge["JUDGE_API_KEY"] == "${JUDGE_API_KEY}"
        task = tomllib.loads(next((run / "tasks").glob("*/task.toml")).read_text())
        assert task["verifier"]["env"] == judge


@pytest.mark.parametrize("temperature", ["0", "default", "1"])
def test_temperature_controls_actual_judge_and_dedup_requests(
    verifier, monkeypatch, temperature
):
    monkeypatch.setenv("JUDGE_API_KEY", "test-key")
    monkeypatch.setenv("JUDGE_MODEL", "custom/judge")
    monkeypatch.setenv("JUDGE_BASE_URL", "https://judge.example/v1")
    monkeypatch.setenv("JUDGE_TEMPERATURE", temperature)
    requests = []
    real_client = openai.AsyncOpenAI

    def handle(request):
        body = json.loads(request.content)
        requests.append(body)
        payload = (
            {"groups": [[0], [1]]}
            if "group duplicate" in body["messages"][0]["content"]
            else {"match": True, "confidence": 1, "reasoning": "test"}
        )
        return httpx.Response(
            200,
            json={
                "id": "test",
                "object": "chat.completion",
                "created": 0,
                "model": body["model"],
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "stop",
                        "message": {
                            "role": "assistant",
                            "content": json.dumps(payload),
                        },
                    }
                ],
            },
        )

    class TestClient(real_client):
        def __init__(self, **kwargs):
            super().__init__(
                **kwargs,
                max_retries=0,
                http_client=httpx.AsyncClient(transport=httpx.MockTransport(handle)),
            )
            # Keep mocked requests independent of SDK platform-detection threads.
            self._platform = "Linux"

    monkeypatch.setattr(openai, "AsyncOpenAI", TestClient)
    monkeypatch.setattr(verifier.step2_5_dedup_candidates, "MAX_RETRIES", 1)
    verifier.configure_upstream()

    async def evaluate():
        dedup, judge = verifier.DedupLLM(), verifier.LLMJudge()
        try:
            assert await dedup.dedup_candidates(["a", "b"], verifier.DEDUP_PROMPT) == [
                [0],
                [1],
            ]
            assert (await judge.match_comment("a", "a"))["match"] is True
        finally:
            await dedup.client.close()
            await judge.client.close()

    asyncio.run(evaluate())
    assert len(requests) == 2
    for request in requests:
        assert request["model"] == "custom/judge"
        if temperature == "default":
            assert "temperature" not in request
        else:
            assert request["temperature"] == float(temperature)


def test_submission_links_devices_fifos_and_limits(verifier, tmp_path):
    target = tmp_path / "review.json"
    target.symlink_to("/etc/passwd")
    with pytest.raises(OSError):
        verifier.load_submission(target)
    target.unlink()
    os.mkfifo(target)
    with pytest.raises(ValueError):
        verifier.load_submission(target)
    target.unlink()
    for content in ("{}", '[""]', '["x", 1]', "[" + '"x",' * 500 + '"x"]'):
        target.write_text(content)
        with pytest.raises(ValueError):
            verifier.load_submission(target)
    target.write_text('["' + "a" * 1_000_001 + '"]')
    with pytest.raises(ValueError):
        verifier.load_submission(target)
    target.write_text('["a concrete issue"]')
    assert verifier.load_submission(target) == ["a concrete issue"]


def test_configurable_parameters_reach_both_sides(tasks, source, tmp_path):
    CodeReviewBenchAdapter(
        tasks,
        source_dir=source,
        overwrite=True,
        judge_model="custom/judge",
        judge_base_url="https://judge.example/v1",
    ).run()
    config = yaml.safe_load(
        (PACKAGE.parents[1] / "codereviewbench-parity.yaml").read_text()
    )
    config["agents"][0]["model_name"] = "custom/solver"
    config["agents"][0]["kwargs"] = {"reasoning_effort": "high", "max_turns": 7}
    config["agents"][0]["override_timeout_sec"] = 123
    config["verifier"]["override_timeout_sec"] = 456
    config["verifier"]["env"] = {"JUDGE_MODEL": "alternate/judge"}
    config["orchestrator"]["n_concurrent_trials"] = 2
    config_path = tmp_path / "custom.yaml"
    config_path.write_text(yaml.safe_dump(config))
    output = tmp_path / "custom-experiment"
    prepare(tasks, source, output, config_path, runs=2, sanity_per_project=1)
    for side in ("original", "harbor"):
        actual = yaml.safe_load((output / f"{side}-sanity.yaml").read_text())
        assert actual["agents"] == config["agents"]
        assert actual["verifier"]["override_timeout_sec"] == 456
        assert actual["orchestrator"]["n_concurrent_trials"] == 2
        assert len(actual["datasets"][0]["task_names"]) == 5
    script = (output / "run-parity.sh").read_text()
    assert "JUDGE_MODEL=alternate/judge" in script
    assert "JUDGE_BASE_URL=https://judge.example/v1" in script
    assert '--judge-model "$JUDGE_MODEL"' in script
    assert '--judge-base-url "$JUDGE_BASE_URL"' in script
    assert "run3" not in script
    assert "--oracle" in (output / "run-oracle.sh").read_text()


def test_ground_truth_all_50_with_deterministic_judge(tasks, verifier):
    """Wiring/ground-truth check only; this is not live oracle acceptance."""

    class IdentityJudge:
        async def match_comment(self, golden, candidate):
            return {"match": golden == candidate, "confidence": 1.0}

    class IdentityDedup:
        async def dedup_candidates(self, candidates, prompt):
            return [[i] for i in range(len(candidates))]

    async def evaluate_all():
        rewards = []
        for task in sorted(tasks.iterdir()):
            problem = json.loads((task / "tests/problem.json").read_text())
            candidates = json.loads((task / "solution/review.json").read_text())
            _, counts = await verifier.evaluate(
                problem, candidates, IdentityJudge(), IdentityDedup()
            )
            rewards.append(counts)
        return rewards

    rewards = asyncio.run(evaluate_all())
    assert len(rewards) == 50
    assert aggregate(rewards)["core_f2"] == 1.0
    assert [sum(r[f"{p}_tp"] for r in rewards) for p in ("strict", "core", "all")] == [
        139,
        158,
        173,
    ]


def test_recorded_leaderboard_scoring_matches_upstream(source):
    """Replay recorded judge decisions, not model inference or measured parity."""
    module = load_module(
        source / "offline/analysis/score_profiles.py", "original_profiles"
    )
    evaluations = json.loads(
        (
            source
            / "offline/results/anthropic_claude-sonnet-4-5-20250929/evaluations.json"
        ).read_text()
    )
    chosen = {
        url: {"claude-code": rows["claude-code"]}
        for url, rows in evaluations.items()
        if "claude-code" in rows
    }
    assert len(chosen) == 50
    rewards = []
    for url, row in chosen.items():
        reward = {}
        for profile in module.PROFILE_CATEGORIES:
            score = module.score_tools({url: row}, {}, profile, 2.0)["claude-code"]
            reward.update({f"{profile}_{k}": score[k] for k in ("tp", "fp", "fn")})
        rewards.append(reward)
    actual = aggregate(rewards)
    for profile in module.PROFILE_CATEGORIES:
        expected = module.score_tools(chosen, {}, profile, 2.0)["claude-code"]
        for metric, original in (
            ("precision", "precision"),
            ("recall", "recall"),
            ("f1", "f1"),
            ("f2", "fbeta"),
        ):
            assert actual[f"{profile}_{metric}"] == pytest.approx(expected[original])
    assert actual["core_f2"] == pytest.approx(325 / 810)
