"""Explicit, paid post-run transcript regrade. Writes separate audit evidence."""

import argparse
import hashlib
import json
import os
from pathlib import Path

import httpx

from biomysterybench.judge import JudgeConfig


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trial", type=Path, required=True)
    parser.add_argument("--task", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--judge-model", help="Defaults to required JUDGE_MODEL")
    parser.add_argument("--judge-base-url", help="Defaults to OPENAI_BASE_URL or OpenAI")
    args = parser.parse_args()
    judge = JudgeConfig.from_env(args.judge_model, args.judge_base_url)
    if args.output.exists():
        raise FileExistsError("Do not overwrite earlier judge evidence")
    trace = args.trial / "trusted-solver"
    if not (trace / "complete.json").is_file():
        raise ValueError("No completed trusted transcript; classify the failure first")
    problem = json.loads((args.task / "tests/problem.json").read_text())
    config = json.loads((args.trial / "config.json").read_text())
    # Prevent accidentally grading an answer against another task's key.
    if Path(config["task"]["path"]).resolve() != args.task.resolve():
        raise ValueError("Trial and task paths do not match")
    events = []
    for response_path in sorted(trace.glob("*-response.json")):
        turn = int(response_path.name.split("-")[0])
        envelope = json.loads(response_path.read_text())
        body = json.loads(envelope["body"])
        events.append(
            {
                "turn": turn,
                "assistant": body["content"],
                "tool_outputs": [
                    json.loads(p.read_text())
                    for p in sorted(trace.glob(f"{turn:04d}-tool-*.json"))
                ],
            }
        )
    # Artifact paths mirror /workspace/... under the trial's artifacts directory.
    artifacts = args.trial / "artifacts/workspace"
    answer_path = artifacts / "answer.txt"
    report_path = artifacts / "report.md"
    data = {
        "question": problem["question"],
        "answer_rubric": problem["answer_rubric"],
        "answer": answer_path.read_text() if answer_path.is_file() else "",
        "report": report_path.read_text() if report_path.is_file() else "",
        "host_recorded_transcript": events,
    }
    prompt = (Path(__file__).parent / "judge_prompt.txt").read_text()
    payload = {
        **judge.completion_options(),
        "messages": [
            {"role": "system", "content": prompt},
            {"role": "user", "content": json.dumps(data)},
        ],
    }
    # No context truncation, retries, proxy routing, or judge-model fallback.
    args.output.mkdir(parents=True, mode=0o700)
    (args.output / "request.json").write_text(json.dumps(payload))
    with httpx.Client(
        trust_env=False, follow_redirects=False, timeout=judge.timeout
    ) as client:
        response = client.post(
            judge.base_url + "/chat/completions",
            headers={"Authorization": "Bearer " + os.environ["OPENAI_API_KEY"]},
            json=payload,
        )
    (args.output / "response.json").write_text(response.text)
    response.raise_for_status()
    raw = response.json()
    judge.validate_response(raw)
    result = json.loads(raw["choices"][0]["message"]["content"])
    status = result.get("cheating_status")
    correct, score = result.get("answer_correct"), result.get("score")
    if type(correct) is not bool or status not in {"clear", "violation", "uncertain"}:
        raise ValueError("Invalid judge decision")
    expected = None if status == "uncertain" else int(correct and status == "clear")
    if (score is not None and type(score) is not int) or score != expected:
        raise ValueError("Inconsistent judge score")
    result.update(
        source_id=problem["id"],
        judge_model=judge.model,
        judge_response_model=raw["model"],
        judge_base_url=judge.base_url,
        judge_temperature=judge.temperature,
        prompt_sha256=hashlib.sha256(prompt.encode()).hexdigest(),
        status="needs_human_review" if score is None else "audited",
    )
    (args.output / "result.json").write_text(json.dumps(result, indent=2))
    # Intentionally never replaces Harbor's verifier reward or original result.


if __name__ == "__main__":
    main()
