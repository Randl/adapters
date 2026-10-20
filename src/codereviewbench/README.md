## CodeReviewBench (offline) → Harbor Adapter

## Overview

Review real pull requests and recover human-curated issues while avoiding false positives.
The adapter covers all 50 offline PRs: 10 each from cal.com, Discourse, Grafana,
Keycloak and Sentry. It retains all 173 golden comments (139 strict / 158 core /
173 all). The online benchmark is excluded.

Upstream: [CodeReviewBench](https://github.com/withmartian/code-review-benchmark),
revision `e616e849755441da38f18bf3adba2c9583b03803`.

## What is CodeReviewBench (offline)?

The benchmark compares code-review candidates with human-curated issues using an
LLM judge. It reports precision, recall, F1 and F2 for strict, core and all category
profiles. The primary metric here is **core micro F2**, obtained by summing TP/FP/FN
across PRs. Averaging per-PR F2 scores is incorrect.

## Adapter Features

- Stable names and all four standard generator flags; full, parity and sanity splits.
- Pinned PR commits, title/body, upstream evaluator and ground truth. SHA-256
  checks reject modified upstream files, including with `--source-dir`.
- Offline, unprivileged agent environment containing only the current tracked
  source tree and the required base-to-head diff; no Git objects or history.
- Separate verifier container; only the submitted JSON crosses into verification.
- Standard Harbor YAML configs for parity and ground-truth oracle experiments.

## Generated Task Structure

```text
codereviewbench/TASK_ID/
├── task.toml
├── instruction.md
├── environment/Dockerfile
├── tests/                   # private upstream evaluator and golden comments
└── solution/                # private ground-truth oracle
```

The adapter is an independent uv project. `parity_experiment.json` is intentionally
absent until real matched runs exist; the structural validator reports this as pending.

## Run Evaluation / Harness

### Running with Datasets Registry

The dataset is not published. After acceptance, use the assigned registry ID with
`harbor run -d ORG/DATASET`. Local paths are used below.

### Using Job Configurations

Install Harbor separately: `uv tool install harbor==0.24.0`. From the repository root:

```bash
harbor run -c src/codereviewbench/codereviewbench-oracle.yaml
harbor run -c src/codereviewbench/codereviewbench-parity.yaml
```

`run_codereviewbench.yaml` also defaults to oracle. Edit the standard YAML fields
`agents[].model_name`, `agents[].kwargs`, `agents[].override_timeout_sec`,
`verifier.override_timeout_sec`, `timeout_multiplier`, `environment`,
`orchestrator.n_concurrent_trials`, `datasets` and `jobs_dir` as needed. Standard
Harbor CLI overrides work, for example `-m MODEL --agent-kwarg max_turns=80`.
For paired experiments, edit the input YAML **before preparation** so both sides
receive identical settings.

### Running Individual Trial

```bash
harbor trial start -p datasets/codereviewbench/TASK_ID -a oracle
harbor trial start -p datasets/codereviewbench/TASK_ID \
  -a terminus-2 -m anthropic/claude-sonnet-5-5 --effort medium
```

## Usage: Create Task Directories

```bash
cd src/codereviewbench
uv sync
uv run codereviewbench --output-dir ../../datasets/codereviewbench
```

Flags: `--output-dir`, `--limit`, `--overwrite`, `--task-ids ID [ID ...]`,
`--source-dir`, `--split full|parity|sanity`, `--judge-model`, `--judge-base-url`,
`--judge-temperature`.
Full and parity both contain all 50 PRs. Sanity selects two PRs per project by
SHA-256 of the stable ID, without consulting outcomes. Unknown IDs and negative
limits are rejected. Existing tasks are skipped unless `--overwrite` is passed.

The default judge is `anthropic/claude-sonnet-4-5-20250929` via
`https://api.withmartian.com/v1`. Export `JUDGE_API_KEY` on the host. Set generation
defaults with `--judge-model` and `--judge-base-url`; the private
verifier's network allowlist is derived from the endpoint. An OpenAI-compatible
endpoint must support upstream's requests. Never put credentials in the YAML or
build context. The solver uses its provider's host-side credential, normally
`ANTHROPIC_API_KEY`.

The verifier configuration uses `JUDGE_API_KEY`, `JUDGE_MODEL` and
`JUDGE_BASE_URL`. Only the upstream integration boundary translates these to
upstream's `MARTIAN_*` names; no Martian-specific credential is required when
using another compatible provider.

The generated experiment launchers honor `JUDGE_MODEL` and `JUDGE_BASE_URL` from
the environment over prepared defaults. The URL is used exactly as supplied.
Each launch creates a fresh directory under the prepared folder's `runs/`, with
matching upstream and Harbor settings and a verifier allowlist for that endpoint.
The resolved model, endpoint and result directory are printed before evaluation.
Credentials remain in the environment; recorded configs contain only their
variable reference.

`JUDGE_TEMPERATURE` overrides the prepared sampling setting on both evaluation
paths. The default is `0`, matching upstream. Use `JUDGE_TEMPERATURE=default` to
omit the request field for models that reject temperature zero; numeric values
from 0 to 2 are also supported. This is an explicit sampling change, recorded in
the run plan and upstream judge config. A shared client wrapper applies it to
deduplication and judging while leaving pinned upstream source, prompts and
scoring unchanged. The endpoint URL is never rewritten.

## Comparison with Original Benchmark (Parity)

The prepared setting is Terminus 2 with **Sonnet 5.5**, medium reasoning, 40 turns
and 1800 seconds, on all 50 PRs with three repetitions per side. These defaults
are configurable in `codereviewbench-parity.yaml` and the preparation flags.
[Sonnet 5.5's official API ID](https://platform.claude.com/docs/en/models/sonnet-5-5/overview)
is `claude-sonnet-5-5` without a date suffix. Its API rejects non-default
`temperature`; the config omits it. Host-side inference lets the task container
remain fully offline.

| Agent | Model | Metric | Number of Runs | Dataset Size | Original Benchmark Performance | Harbor Adapter Performance |
|-------|-------|--------|----------------|--------------|--------------------------------|----------------------------|
| terminus-2@2.0.0 (planned) | anthropic/claude-sonnet-5-5 | core micro F2 | 3 planned per side | 50 | Not measured | Not measured |

The [offline leaderboard](https://codereview.withmartian.com/?mode=offline) lists
review **tools**; its model selector selects the **judge**, not the reviewer model.
Its published Claude Code (CLI) results have core F2 40.1% under Sonnet 4.5 judging
(65 TP, 113 FP, 93 FN), providing a non-trivial scoring regression fixture. This
replay does **not** measure Sonnet 5.5 performance or establish model parity.
The chosen judge is one of upstream's published judge configurations and costs
less than the leaderboard's default Opus judge.

Prepare both experiments, starting in this adapter directory:

```bash
# Obtain the exact upstream snapshot once; it stays on the host.
git clone https://github.com/withmartian/code-review-benchmark /tmp/crb-upstream
git -C /tmp/crb-upstream checkout e616e849755441da38f18bf3adba2c9583b03803

uv run codereviewbench --source-dir /tmp/crb-upstream \
  --output-dir ../../datasets/codereviewbench --overwrite
uv run python -m codereviewbench.experiments prepare \
  --source-dir /tmp/crb-upstream \
  --tasks-dir ../../datasets/codereviewbench \
  --config codereviewbench-parity.yaml \
  --runs 3 --sanity-per-project 2 --harbor-version 0.24.0 \
  --output-dir /tmp/crb-experiments

# Separate experiments; both use the real upstream LLM judge.
bash /tmp/crb-experiments/run-oracle.sh
bash /tmp/crb-experiments/run-parity.sh
```

Preparation makes no API calls and refuses to overwrite an experiment folder.
Launchers print preflight checks and numbered stages. Upstream judge output is
streamed to the terminal and saved to per-stage logs, with a status message
after 30 seconds without output. Failures identify the stage and log location.
`--sanity-per-project 0` omits the pilot. There is no score-based pilot cutoff.
Generated configs and `plan.json` record the resolved settings. The launchers run
sanity on both sides, then full repetition 1 on both, followed by repetitions 2
and 3. Failed/incomplete jobs are rejected; successful runs produce micro scores,
mean ± sample SEM and the required range-overlap check. Result directories are
separate from adapter code. Record actual API costs and response model IDs when
running; no live parity or live oracle acceptance is claimed yet.

This is a shared-agent bridge, analogous to the adapters that add an agent to an
upstream evaluator: both sides use the same prompt, offline snapshot, tools and
Terminus implementation, with **independent inference runs**. On the original
side Harbor only orchestrates inference, with its verifier disabled. The helper
exports individual candidates into upstream's native format and runs the unchanged
`step2_5_dedup_candidates`, `step3_judge_comments` and `score_profiles` code.
It does not reproduce an undocumented proprietary leaderboard agent.

The oracle submits every released golden comment, with no score override. The
original oracle goes through the native dedup/judge pipeline; the Harbor oracle
uses `solution/solve.sh` and the separate verifier. Exact-match test doubles test
all 50 oracle submissions locally, but cannot establish live judge acceptance.

## Notes & Caveats

MIT benchmark code; PR sources retain their project licenses. Image builds need
network access to fetch the exact commits and OS packages. **Agent execution has
no network access**, including no model API exception. The host agent process
calls the solver API; the private verifier can contact only its judge endpoint.
Installed CLI agents that require internet from inside the task container are
incompatible with this policy; use a host-driven agent such as Terminus 2.

Multi-stage builds copy only tracked PR-head files and the review diff into the
final image. There are no Git objects, remotes, refs, reflogs, alternate checkouts
or source-stage layers in that image. Current repository Markdown, tests and
licenses remain because they are legitimate benchmark inputs. The adapter keeps
only its required README and task instruction Markdown; draft PR notes are removed.

Verifier code, ground truth and oracle files are outside the agent build context.
The unprivileged agent cannot change the source files. Its output is data, never
executed by the verifier. Links, FIFOs/devices, invalid JSON, oversized files and
invalid candidate lists are rejected. Missing/invalid submissions become empty
reviews with the actual PR's false negatives. Agent-created reward files do not
influence the separate verifier. No host repository, Docker socket or provider
credentials are intentionally mounted into the agent environment.

**Residual cheating risks:** upstream's LLM judge consumes free-form candidates,
so prompt injection and broad speculative claims remain possible attacks on the
original scoring protocol. Public PRs/golden comments may also have appeared in
model training. Offline isolation does not remove memorization. A claim that all
cheating is impossible would be unsupported. Fixing judge prompts or changing the
scoring rule would change the benchmark and needs an upstream protocol change.

Candidate strings enter after extraction, matching upstream's direct individual
comment path. Raw review summaries require upstream extraction and are outside
this interface. Dedup/judge prompts, confidence handling, excluded-category
handling and micro scoring are unchanged. Failed judging produces no reward;
exhausted upstream dedup retries are treated as infrastructure failure on **both**
sides instead of accepting upstream's singleton fallback. This failure-policy
difference is explicit and applies symmetrically.

## Installation / Prerequisites

Python 3.11+, uv, Docker and external Harbor 0.24.0 with separate-verifier and
network-policy support. Run `uv sync` in this adapter's independent project.
The dev group includes dependencies for running upstream's unchanged CLIs.

```bash
CODEREVIEWBENCH_SOURCE=/tmp/crb-upstream uv run pytest tests
uv run ruff check .
uv run ruff format --check .
uv run ty check
# From the repository root:
python3 scripts/validate_adapter.py codereviewbench
```

The runtime isolation probe can be run in a built image with:

```bash
docker run --rm --network none -i --entrypoint python IMAGE \
  - < src/codereviewbench/audit.py
```

## Troubleshooting

Missing rewards mean verification failed; inspect logs and fix the provider or
container before retrying. Do not interpret infrastructure failures as low scores.
Regenerate tasks after template or judge changes. The structural validator's
missing-parity-results error remains until actual runs are recorded. API credentials
are required for live oracle verification as well as parity.

## Citation

```bibtex
@misc{codereviewbench,
  title={CodeReviewBench (offline)},
  url={https://github.com/withmartian/code-review-benchmark}
}
```

## Authors & Contributions

Prepared by Evgenii Zheltonozhskii with Codex assistance. Benchmark prompts, data,
code and authorship remain credited to upstream authors.

## Acknowledgement

No sponsored inference or paid parity runs were used for this implementation.
