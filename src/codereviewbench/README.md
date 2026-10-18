## CodeReviewBench (offline) → Harbor Adapter

## Overview

Review real pull requests and recover human-curated issues while avoiding false positives.

50 tasks = 10 PRs each from cal.com, Discourse, Grafana, Keycloak and Sentry. All 173 golden comments are retained. Strict/core/all profiles include 139/158/173 issues. The online benchmark is excluded.

Source: [CodeReviewBench (offline)](https://github.com/withmartian/code-review-benchmark), revision e616e849755441da38f18bf3adba2c9583b03803. Licensing details are in Notes.

## What is CodeReviewBench (offline)?

Review real pull requests and recover human-curated issues while avoiding false positives. Core micro F2; strict/core/all precision, recall, F1 and F2 are retained.

## Adapter Features

- Stable IDs, selection, limits and overwriting.
- Pinned sources and self-contained generated tasks.
- Separate private verifier and explicit failure behavior.
- Retained verifier evidence and reproduction configuration.

## Generated Task Structure

~~~text
codereviewbench/TASK_ID/
├── task.toml
├── instruction.md
├── environment/   # public inputs and agent build context
├── tests/         # private verifier and references
└── solution/      # oracle launcher and available references
~~~

The independent project at src/codereviewbench/ contains pyproject.toml, uv.lock, metadata,
run_codereviewbench.yaml, and src/codereviewbench/ with adapter.py, main.py and task-template/.
parity_experiment.json will be added only after real coordinated runs.

## Run Evaluation / Harness

### Running with Datasets Registry

This dataset is unpublished. After registry acceptance, use the assigned registry
ID with harbor run -d ORG/DATASET. Current verification uses local paths.

### Using Job Configurations

Install Harbor separately with uv tool install harbor==0.24.0. From this branch's
repository root, after generation:

~~~bash
harbor run -c src/codereviewbench/run_codereviewbench.yaml
harbor run -c src/codereviewbench/run_codereviewbench.yaml -a codex -m MODEL
harbor job resume -p /path/to/job
~~~

Oracle is the default. This configuration does not assert oracle success; read
Notes for the required reference assets.

### Running Individual Trial

~~~bash
harbor trial start -p datasets/codereviewbench/TASK_ID -a oracle
harbor trial start -p datasets/codereviewbench/TASK_ID -a codex -m MODEL
~~~

## Usage: Create Task Directories

~~~bash
cd src/codereviewbench
uv sync
uv run codereviewbench --output-dir ../../datasets/codereviewbench
~~~

Standard flags: --output-dir, --limit, --overwrite, --task-ids ID [ID ...].
Unknown IDs and negative limits are rejected. Existing tasks are skipped without
--overwrite. Default output is datasets/codereviewbench relative to invocation directory;
use ../../datasets/codereviewbench from the project to match the repo-root run config.

## Comparison with Original Benchmark (Parity)

No measured model parity is claimed. No placeholder parity JSON is committed;
the structural validator will report that required file as pending.

| Agent | Model | Metric | Number of Runs | Dataset Size | Original Benchmark Performance | Harbor Adapter Performance |
|-------|-------|--------|----------------|--------------|--------------------------------|----------------------------|
| Pending | Pending | See text | 0 | 50 | Not measured | Not measured |

Scenario 1: use the same pinned CLI agent, checkout, title/body, diff and candidate JSON contract on both sides. On the original side, save candidates.json, run step2_5_dedup_candidates and step3_judge_comments with its dedup file, then analysis/score_profiles.py --profile core --beta 2.0. Raw-summary evaluation is a different interface and must be labeled separately.

Harbor-side compatibility command, which alone does not establish parity:

```bash
harbor run -c src/codereviewbench/run_codereviewbench.yaml -a codex -m MODEL
```

Agree on solver/model versions, judge routing, prompts/tools, subset, images,
Harbor revision, limits, at least three repetitions and expected cost before paid
runs. Run 5–10 tasks on both sides, one full matched repetition, then agreed
repeats. Preserve raw runs, report mean ± sample SEM, and require overlapping
score ranges. Oracle and deterministic tests are separate evidence.

## Notes & Caveats

MIT benchmark code; PR sources retain their project licenses. Export MARTIAN_API_KEY for verification. Image builds fetch exact PR commits and can require several GB. --source-dir accepts the pinned upstream checkout.

prs.json pins all original PR base/head SHAs and title/body. Images check out the head and materialize the complete base-to-head diff. Golden comments and judge code exist only in verifier assets. Remotes are removed, and the agent network is restricted to model APIs.

The output is an array of individual candidate strings, entering the upstream pipeline after extraction. The raw-summary extraction model is not applied again to already separated candidates. Pinned upstream deduplication, matching, category exclusions and scoring are reused unchanged. Dedup and matching use the original openai/gpt-4o-mini default through Martian. This is an upstream alias, not a dated judge snapshot; record the routed model before parity.

Dedup or judge service failures leave no reward. Upstream's exhausted-dedup fallback is intentionally treated as infrastructure failure instead of silently changing the candidate set. Invalid/missing reviews become empty candidates and retain the real PR identity. Evidence retains matches, confidence and dedup groups.

Each PR emits strict/core/all TP/FP/FN counts. metric.py computes micro scores from summed counts, matching analysis/score_profiles.py. Averaging PR F2 rewards is incorrect. Matched excluded categories are neither rewarded nor penalized. The oracle uses released golden comments; live judge acceptance is not established.

Review lessons checked against [adapters PR 9](https://github.com/harbor-framework/adapters/pull/9),
[Harbor PR 3104](https://github.com/harbor-framework/harbor/pull/3104) and
[Harbor PR 2974](https://github.com/harbor-framework/harbor/pull/2974): preserve
failure identity, executable acceptance rules and diagnostic evidence; keep
credentials private; distinguish model parity from synthetic and oracle checks.
No push, public post, upload or registry write has occurred.

## Installation / Prerequisites

Python 3.11+, uv, Docker, and external Harbor 0.24.0 with separate verifier support.
Run uv sync inside this adapter's independent project. Source-access, assets,
credential and platform requirements are listed in Notes.

Local validation from this independent project:

```bash
CODEREVIEWBENCH_SOURCE=/path/to/pinned/upstream uv run pytest tests
uv run ruff check .
uv run ruff format --check .
uv run ty check
```

The upstream source environment variables enable integration cases without network
requests. Type checks cover generator code and ordinary tests; generated runtime
modules are checked in their own containers or evaluator environment.

## Troubleshooting

Missing rewards after verifier errors indicate infrastructure failure; inspect
logs and fix the provider/install before retrying. Invalid submissions receive
zero. Regenerate with --overwrite after template changes. An oracle missing its
reference needs a real validated solution. Keep restricted generated data local.

## Citation

~~~bibtex
@misc{codereviewbench,
  title={CodeReviewBench (offline)},
  url={https://github.com/withmartian/code-review-benchmark}
}
~~~

## Authors & Contributions

Prepared locally by Evgenii Zheltonozhskii with Codex assistance. Benchmark
prompts, data, code and authorship remain credited to upstream authors.

## Acknowledgement

No sponsored inference or paid parity runs were used for this implementation.
