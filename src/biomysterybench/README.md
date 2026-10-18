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
harbor run -c src/biomysterybench/run_biomysterybench.yaml -a codex -m MODEL
harbor job resume -p /path/to/job
~~~

Oracle is the default. This configuration does not assert oracle success; read
Notes for the required reference assets.

### Running Individual Trial

~~~bash
harbor trial start -p datasets/biomysterybench/TASK_ID -a oracle
harbor trial start -p datasets/biomysterybench/TASK_ID -a codex -m MODEL
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

No official executable original harness exists. Native Anthropic parity cannot currently be asserted. Coordinate an explicitly labeled released-harness or matched CLI-agent comparison, fixing the dataset, solver, model, judge, prompts, allowlist, images, budgets and attempt order. Repeated-attempt pass@5 is not the mean of five trial rewards.

Harbor-side compatibility command, which alone does not establish parity:

```bash
harbor run -c src/biomysterybench/run_biomysterybench.yaml -a codex -m MODEL
```

Agree on solver/model versions, judge routing, prompts/tools, subset, images,
Harbor revision, limits, at least three repetitions and expected cost before paid
runs. Run 5–10 tasks on both sides, one full matched repetition, then agreed
repeats. Preserve raw runs, report mean ± sample SEM, and require overlapping
score ranges. Oracle and deterministic tests are separate evidence.

## Notes & Caveats

CC BY 4.0, with evaluation-only access terms; biological archives retain original repository terms. Log in with hf auth login after obtaining access. Export OPENAI_API_KEY for verification. Large archives require substantial disk and download time.

Questions and rubrics are preserved verbatim. Only questions and input files enter the agent image. Rubrics and credentials remain in the separate verifier. ZIP traversal and symlinks are rejected before extraction. Network access follows the released domains plus subdomains, the PyPI file host, and model endpoints. The rules prohibit identifying source studies through accession IDs. The network policy does not prove that every allowed database query complies with this rule.

Anthropic has not released the original tools, system prompt, judge prompt or container. This adapter supplies an explicit rubric judge (gpt-4.1-2025-04-14, temperature 0), a bioinformatics image, and a file interface. The configured metric reports the human-solvable and human-difficult accuracy separately and excludes its partition marker from reported outcomes. These are adapter rubric scores; they are not established replicas of Anthropic's reported results. Provider and judge-format failures leave no reward. Invalid answers receive zero. The required analysis report is agent-supplied evidence, not an authenticated execution audit.

Reference solutions are not released. --oracle-dir accepts independently solved ID.txt answers and ID.md analyses. Without them the oracle launcher fails explicitly. Copying rubrics into answers is not oracle evidence. --data-dir accepts a pinned local HF snapshot; --split full|human-solvable|human-difficult selects a partition. Generated tasks contain gated material and must remain local pending review of distribution terms.

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
uv run pytest tests
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
