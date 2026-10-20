"""Run the pinned upstream judge and deduplicator in the private verifier."""

import asyncio
import json
import os
import stat
from pathlib import Path

import step2_5_dedup_candidates
import step3_judge_comments
from judge_client import create_client
from score_profiles import PROFILE_CATEGORIES, score_tools
from step2_5_dedup_candidates import DEDUP_PROMPT, DedupLLM
from step3_judge_comments import LLMJudge, evaluate_review


def load_submission(path: Path) -> list[str]:
    # Reject devices, FIFOs and links before opening; never follow agent paths.
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as stream:
        metadata = os.fstat(stream.fileno())
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > 1_000_000:
            raise ValueError("Invalid submission file")
        payload = stream.read(1_000_001)
    if len(payload) > 1_000_000:
        raise ValueError("Oversized submission")
    values = json.loads(payload)
    if not isinstance(values, list) or len(values) > 500:
        raise ValueError("Expected at most 500 review candidates")
    if any(not isinstance(v, str) or not v.strip() for v in values):
        raise ValueError("Candidates must be nonempty strings")
    return values


async def evaluate(
    problem: dict, candidates: list[str], judge=None, dedup=None
) -> tuple[dict, dict]:
    groups = None
    if len(candidates) >= 2:
        groups = await (dedup or DedupLLM()).dedup_candidates(candidates, DEDUP_PROMPT)
        # The original falls back to singletons after exhausted dedup retries.
        # A failed service must remain an infrastructure failure in Harbor.
        if groups is None:
            raise RuntimeError("Upstream deduplication failed; no reward produced")
    if not candidates:
        # Empty or invalid reviews need no model credentials to score zero.
        evaluation = await evaluate_review(None, problem["golden_comments"], [])
    else:
        evaluation = await evaluate_review(
            judge or LLMJudge(), problem["golden_comments"], candidates, groups
        )
    if evaluation.get("errors_count", 0):
        raise RuntimeError("Upstream judge failed; no reward produced")
    rewards = {}
    for profile in PROFILE_CATEGORIES:
        values = score_tools(
            {problem["url"]: {"harbor": evaluation}}, {}, profile, 2.0
        )["harbor"]
        for key in ("tp", "fp", "fn"):
            rewards[f"{profile}_{key}"] = values[key]
    evaluation["dedup_groups"] = groups
    return evaluation, rewards


def configure_upstream() -> None:
    # Public configuration is provider-neutral; preserve the upstream modules.
    for suffix in ("API_KEY", "MODEL", "BASE_URL"):
        os.environ[f"MARTIAN_{suffix}"] = os.environ[f"JUDGE_{suffix}"]
    step2_5_dedup_candidates.AsyncOpenAI = create_client
    step3_judge_comments.AsyncOpenAI = create_client


async def main() -> None:
    configure_upstream()
    problem = json.loads(Path("/tests/problem.json").read_text())
    try:
        candidates = load_submission(Path("/workspace/review.json"))
    except (OSError, UnicodeError, ValueError):
        candidates = []
    evaluation, rewards = await evaluate(problem, candidates)
    evaluation.update(
        task_id=problem["id"],
        judge_model=os.environ["JUDGE_MODEL"],
        judge_temperature=os.environ.get("JUDGE_TEMPERATURE", "0"),
    )
    Path("/logs/verifier/evaluation.json").write_text(json.dumps(evaluation, indent=2))
    Path("/logs/verifier/reward.json").write_text(json.dumps(rewards))
    tp, fp, fn = (rewards[f"core_{key}"] for key in ("tp", "fp", "fn"))
    Path("/logs/verifier/reward.txt").write_text(
        str(5 * tp / (5 * tp + fp + 4 * fn) if tp else 0)
    )


if __name__ == "__main__":
    asyncio.run(main())
