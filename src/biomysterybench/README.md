## BioMysteryBench → Harbor Adapter

## Overview

Analyze anonymized biological datasets to identify tissues, organisms, variants and perturbations.

90 tasks = 73 human-solvable + 17 human-difficult problems in the revised v11 full set. No problems are excluded. The original 99-problem paper results use an earlier answer key.

Source: [BioMysteryBench](https://huggingface.co/datasets/Anthropic/BioMysteryBench-full), revision b5a889c4757214ec9a6ade876b734f920a7799db. Licensing details are in Notes.

## What is BioMysteryBench?

Analyze anonymized biological datasets to identify tissues, organisms, variants and perturbations. Binary rubric acceptance, reported separately for the 73/17 partitions.

## Adapter Features

- Stable IDs, selection, limits and overwriting.
- Pinned sources and self-contained generated tasks.
- Separate private verifier and explicit failure behavior.
- Retained verifier evidence and reproduction configuration.
- Prepared Sonnet 5 reproduction and separate GT fixture experiment (not run).

## Generated Task Structure

~~~text
biomysterybench/TASK_ID/
├── task.toml
├── instruction.md
├── environment/   # public inputs and agent build context
├── tests/         # private verifier and references
└── solution/      # oracle launcher and available references
~~~

The independent project at src/biomysterybench/ contains pyproject.toml, uv.lock, metadata,
run_biomysterybench.yaml, and src/biomysterybench/ with adapter.py, main.py and task-template/.
parity_experiment.json will be added only after real coordinated runs.

## Run Evaluation / Harness

### Running with Datasets Registry

This dataset is unpublished. After registry acceptance, use the assigned registry
ID with harbor run -d ORG/DATASET. Current verification uses local paths.

### Using Job Configurations

Install Harbor separately with uv tool install harbor==0.24.0. From this branch's
repository root, after generation:

~~~bash
harbor run -c src/biomysterybench/run_biomysterybench.yaml
harbor job resume -p /path/to/job
~~~

Oracle is the default. This configuration does not assert oracle success; read
Notes for the required reference assets.

### Prepared Sonnet 5 and GT experiments

The setup in `experiments/` is prepared but unexecuted. From the repository root:

```bash
uv run --project src/biomysterybench \
  python src/biomysterybench/experiments/prepare.py
```

Preparation downloads the pinned release and creates separate parity and GT
tasksets under `datasets/`, plus hashes and configs in
`datasets/biomysterybench-preparation/`. It never launches evaluations and refuses
existing destinations. GT fixtures contain expected-answer excerpts with scoring
directions removed; `--gt-answers /private/answers.json` accepts a reviewed mapping
of all 90 source IDs to plain answers. GT acceptance tests verifier plumbing,
not independent biological analysis. Keep these answer-bearing outputs private.

The image recipe follows the author's published tool inventory with Python 3.11,
R 4.3 and conda. Its packages have not been resolved or built. Before collecting
scores, build it, freeze the image digest and package list across all tasks/runs,
and record the Harbor version and source commit. The experiment adds EBI and
Reactome from the author reply to the CSV's scientific-domain allowlist.

Future run commands, after image and fixture review:

```bash
export PYTHONPATH="$PWD/src/biomysterybench/experiments"
# Host credentials: ANTHROPIC_API_KEY for solver, OPENAI_API_KEY for judge.
# Set JUDGE_MODEL to the chosen judge's pinned model ID before running.
harbor run -c datasets/biomysterybench-preparation/gt-oracle.yaml
harbor run -c datasets/biomysterybench-preparation/pilot.yaml
# Only after reviewing the fixed eight-task pilot:
harbor run -c datasets/biomysterybench-preparation/sonnet5.yaml
```

The solver calls `claude-sonnet-5` directly from the host with native bash tools,
adaptive thinking at high effort, with no configured model substitution or
automatic retries. Requested and returned model IDs are recorded for review.
Local budgets are 150 turns, 32,768 output tokens per response,
two hours per task and at most 600 seconds per command. These are explicit
reconstruction choices, not recovered Anthropic evaluation settings.
The generic `parity_agent:ParityAgent` reads `model_name` and validated `kwargs`
from `experiments/sonnet5.yaml`: API base URL, thinking,
effort, token/turn budgets, request/command timeouts and output truncation.
The API key environment-variable name and Anthropic API version are also
configurable. The prepared config pins the first-party endpoint and Sonnet 5;
changing models or providers requires a separately identified experiment.

Harbor enforces the sandbox's scientific-domain allowlist. HF, GitHub and model
API hosts are excluded; credentials and references stay outside the tested
sandbox. There is no per-trial network probe. Do not add host mounts, provider
credentials, remote tools or extra allowed hosts. The network policy cannot rule
out every mirror on an allowed scientific domain.

Raw responses and tool outputs are stored in the host-only `trusted-solver/`
trial directory. Errors and structured refusals fail the affected trial.
Natural-language refusals still require transcript review. Review the
first full run before creating separately named run2/run3 configs.

Audit every completed attempt with the separate, paid transcript judge:

```bash
uv run --project src/biomysterybench \
  python src/biomysterybench/experiments/audit.py \
  --trial jobs/JOB/TRIAL \
  --task datasets/biomysterybench-parity/biomysterybench-ID \
  --output jobs/JOB/TRIAL/transcript-audit
```

The fixed `experiments/judge_prompt.txt` separates correctness from prohibited
source lookup, permits memory and ordinary reference-database use, and requires
concrete evidence. Uncertain audits need human adjudication. Audits preserve the
original verifier reward. Report audited and provisional scores distinctly;
include refusals as failures in fixed denominators, and treat infrastructure
failures as incomplete runs rather than reporting survivor-only accuracy.

### Judge configuration

There is no known official Anthropic judge model or prompt for this release.
`JUDGE_MODEL` is required, with no default or fallback. The earlier GPT-4.1 pin
was a local choice without benchmark-specific support and has been removed.
Freeze the selected judge and its settings across GT, pilot, full runs and audit.

The verifier and transcript audit share configuration and response validation:

| Setting | Behavior |
|---|---|
| `JUDGE_MODEL` | Required OpenAI-compatible model ID, preferably a pinned snapshot. |
| `JUDGE_TEMPERATURE` | Optional; omitted by default because some reasoning models reject temperature overrides. |
| `JUDGE_TIMEOUT_SEC` | Request timeout, default 120 seconds; keep below the Harbor verifier timeout. |
| `OPENAI_API_KEY` | Credential for the chosen judge provider; stays outside the solver sandbox. |
| `--judge-base-url` | Generation/preparation option, default `https://api.openai.com/v1`. Records `OPENAI_BASE_URL` and its host in the private verifier's allowlist. |

For a custom provider, pass `--judge-base-url` to `biomysterybench` or
`experiments/prepare.py` before generation. Use the same URL for
`experiments/audit.py --judge-base-url` (or its `OPENAI_BASE_URL` environment
variable). The audit also accepts `--judge-model`. Changing the verifier endpoint
requires regenerating tasks so the recorded URL and network policy agree.
Neither path configures model substitution. Returned model IDs are recorded,
including provider-resolved aliases. Errors/refusals produce no judge score.

This follows existing adapters' use of environment-configured judges, although
names and defaults differ: HLE uses `JUDGE_MODEL`/`OPENAI_BASE_URL` (o3-mini in its
task template, GPT-5 in its parity config); BixBench uses `MODEL_NAME=gpt-4o`;
FinanceAgent configures `MODEL_NAME=openai/gpt-5-2025-08-07`, while its verifier
fallback default is GPT-5.2. These are examples, not an agreed judge standard or
evidence about Anthropic's grader.

### Running Individual Trial

~~~bash
harbor trial start -p datasets/biomysterybench/TASK_ID -a oracle
~~~

## Usage: Create Task Directories

~~~bash
cd src/biomysterybench
uv sync
uv run biomysterybench --output-dir ../../datasets/biomysterybench --limit 1
~~~

Standard flags: --output-dir, --limit, --overwrite, --task-ids ID [ID ...].
Unknown IDs and negative limits are rejected. Existing tasks are skipped without
--overwrite. Default output is datasets/biomysterybench relative to invocation directory;
use ../../datasets/biomysterybench from the project to match the repo-root run config.

## Comparison with Original Benchmark (Parity)

No measured model parity is claimed. No placeholder parity JSON is committed;
the structural validator will report that required file as pending.

| Agent | Model | Metric | Number of Runs | Dataset Size | Original Benchmark Performance | Harbor Adapter Performance |
|-------|-------|--------|----------------|--------------|--------------------------------|----------------------------|
| Pending | Pending | See text | 0 | 90 | Not measured | Not measured |

No official executable original harness was found. Native Anthropic parity cannot currently be asserted. Coordinate an explicitly labeled reconstructed-harness comparison, fixing the dataset, solver, model, judge, prompts, allowlist, images, budgets and attempt order. Repeated-attempt pass@5 is not the mean of five trial rewards.

The prepared reproduction target is Sonnet 5's **87.5% human-solvable / 34.1%
human-difficult** in the [July 24 Opus 5 system card](https://www.anthropic.com/claude-opus-5-system-card),
§8.17.1. Its removal counts match v11, but it does not specify a dataset commit.
There are no measurements from the prepared setup and no claimed successful
reproduction. No official judge model or prompt was found; the released rubric
and [v11 scoring rules](https://huggingface.co/datasets/Anthropic/BioMysteryBench-preview/blob/main/CHANGELOG.md)
are the grading specification. [SaferAI's independent implementation](https://www.safer-ai.org/u/2026/08/SaferAI-GLM-Evaluation-Report.pdf),
Appendix A.4.1, uses full-transcript grading with Opus 4.8, but reports pass@5.
[Vals](https://www.vals.ai/benchmarks/biomysterybench) uses its own harness/judge;
neither establishes reproduction of Sonnet 5's published partition scores.

Agree on solver/model versions, judge routing, prompts/tools, subset, images,
Harbor revision, limits, at least three repetitions and expected cost before paid
runs. Run 5–10 tasks on both sides, one full matched repetition, then agreed
repeats. Preserve raw runs, report mean ± sample SEM, and require overlapping
score ranges. Oracle and deterministic tests are separate evidence.

## Notes & Caveats

CC BY 4.0, with evaluation-only access terms; biological archives retain original repository terms. Log in with hf auth login after obtaining access. Export OPENAI_API_KEY and JUDGE_MODEL for verification. Large archives require substantial disk and download time.

Questions and rubrics are preserved verbatim. Only questions and input files enter the agent image. Rubrics and judge credentials remain in the separate verifier. ZIP traversal and symlinks are rejected before extraction. Network access follows the released domains plus subdomains and the PyPI file host; source rows cannot expand this approved set. Model API endpoints, Hugging Face and GitHub are excluded from the tested sandbox. The separate verifier can reach only its judge endpoint. The rules prohibit identifying source studies through accession IDs. The network policy does not prove that every allowed database query complies with this rule.

Anthropic has described its tools and network access in an
[author reply](https://huggingface.co/datasets/Anthropic/BioMysteryBench-full/discussions/5);
no original system prompt, judge implementation or container image was found.
This adapter supplies an explicit rubric judge with a user-selected model,
a bioinformatics image, and a file interface. The prepared experiment includes a
broader image recipe based on the author inventory. The metric reports both
partition accuracies plus verified/missing counts; any missing reward suppresses
accuracy rather than reporting a biased surviving subset. These are adapter rubric
scores, not established replicas of Anthropic's results. Provider and judge-format
failures leave no reward. Invalid answers receive zero. The analysis report is
agent-supplied evidence; the prepared host transcript audit supplies a separate
anti-cheat check.

No released reference solutions were found. --oracle-dir accepts ID.txt answers
and ID.md reports. Without them the oracle launcher fails explicitly. Independent
analysis solutions and GT acceptance fixtures must be labeled separately: the
prepared GT experiment checks verifier plumbing, not biological solvability.
--data-dir accepts a local HF snapshot but does not verify its claimed revision;
the experiment preparation uses pinned Hub downloads and records file hashes.
--split full|human-solvable|human-difficult selects a partition. Generated tasks
contain gated material and must remain local pending review of distribution terms.

## Installation / Prerequisites

Python 3.11+, uv, Docker, and external Harbor 0.24.0 with separate verifier support.
Run uv sync inside this adapter's independent project. Source-access, assets,
credential and platform requirements are listed in Notes.

Local validation from this independent project:

```bash
uv run pytest tests
uv run ruff check .
uv run ruff format --check .
uv run ty check
```

The upstream source environment variables enable integration cases without network
requests. Type checks cover generator code and ordinary tests; generated runtime
modules are checked in their own containers or evaluator environment. The custom
experiment agent requires the external Harbor environment. New experiment code
and the latest network/judge changes have not been executed under the preparation-only
instruction.

## Troubleshooting

Missing rewards after verifier errors indicate infrastructure failure; inspect
logs and fix the provider/install before retrying. Invalid submissions receive
zero. Regenerate with --overwrite after template changes. An oracle missing its
reference needs a validated solution or an explicitly labeled GT fixture. Keep
restricted generated data local. Review trial failures before starting additional
experiment jobs.

## Citation

~~~bibtex
@misc{biomysterybench,
  title={BioMysteryBench},
  url={https://huggingface.co/datasets/Anthropic/BioMysteryBench-full}
}
~~~

## Authors & Contributions

Prepared locally by Evgenii Zheltonozhskii with Codex assistance. Benchmark
prompts, data, code and authorship remain credited to upstream authors.

## Acknowledgement

No sponsored inference or paid parity runs were used for this implementation.
