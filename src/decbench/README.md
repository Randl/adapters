## DecBench → Harbor Adapter

## Overview

Manually reconstruct C from stripped binaries and measure control-flow, type and recompilation recovery.

250 function tasks from the frozen sample-set across 223 binaries. Published metric denominators are 246 GED, 236 type, and 158 byte-match functions. Other leaderboard presets are excluded. IDs include project, optimization, binary and function plus a stable hash.

Source: [DecBench](https://github.com/Noelo-Lab/decbench), revision ae070b885b4e005ed37510a2c3445af6284dc2b9. Licensing details are in Notes.

## What is DecBench?

Manually reconstruct C from stripped binaries and measure control-flow, type and recompilation recovery. Perfect GED (0), type_match (1), byte_match (1), and Union, using the published fixed per-metric measurable denominators.

## Adapter Features

- Stable IDs, selection, limits and overwriting.
- Pinned sources and self-contained generated tasks.
- Separate private verifier and explicit failure behavior.
- Retained verifier evidence and reproduction configuration.

## Generated Task Structure

~~~text
decbench/TASK_ID/
├── task.toml
├── instruction.md
├── environment/   # public inputs and agent build context
├── tests/         # private verifier and references
└── solution/      # oracle launcher and available references
~~~

The independent project at src/decbench/ contains pyproject.toml, uv.lock, metadata,
run_decbench.yaml, and src/decbench/ with adapter.py, main.py and task-template/.
parity_experiment.json will be added only after real coordinated runs.

## Run Evaluation / Harness

### Running with Datasets Registry

This dataset is unpublished. After registry acceptance, use the assigned registry
ID with harbor run -d ORG/DATASET. Current verification uses local paths.

### Using Job Configurations

Install Harbor separately with uv tool install harbor==0.24.0. From this branch's
repository root, after generation:

~~~bash
harbor run -c src/decbench/run_decbench.yaml
harbor run -c src/decbench/run_decbench.yaml -a codex -m MODEL
harbor job resume -p /path/to/job
~~~

Oracle is the default. This configuration does not assert oracle success; read
Notes for the required reference assets.

### Running Individual Trial

~~~bash
harbor trial start -p datasets/decbench/TASK_ID -a oracle
harbor trial start -p datasets/decbench/TASK_ID -a codex -m MODEL
~~~

## Usage: Create Task Directories

~~~bash
cd src/decbench
uv sync
uv run decbench --output-dir ../../datasets/decbench --limit 1
~~~

Standard flags: --output-dir, --limit, --overwrite, --task-ids ID [ID ...].
Unknown IDs and negative limits are rejected. Existing tasks are skipped without
--overwrite. Default output is datasets/decbench relative to invocation directory;
use ../../datasets/decbench from the project to match the repo-root run config.

## Comparison with Original Benchmark (Parity)

No measured model parity is claimed. No placeholder parity JSON is committed;
the structural validator will report that required file as pending.

| Agent | Model | Metric | Number of Runs | Dataset Size | Original Benchmark Performance | Harbor Adapter Performance |
|-------|-------|--------|----------------|--------------|--------------------------------|----------------------------|
| Pending | Pending | See text | 0 | 250 | Not measured | Not measured |

Scenario 1: pin Codex or Claude Code, tool policy, stripped binary, address, target name, budgets, images, dependencies and parser. Upstream also supplies an architecture and disassembly hint; agree on an identical prompt on both sides before parity. Evaluate both through decbench.pipeline.evaluate.evaluate_decompilation with the same published reference sources. Do not compare against cached website scores as a parity substitute.

Harbor-side compatibility command, which alone does not establish parity:

```bash
harbor run -c src/decbench/run_decbench.yaml -a codex -m MODEL
```

Agree on solver/model versions, judge routing, prompts/tools, subset, images,
Harbor revision, limits, at least three repetitions and expected cost before paid
runs. Run 5–10 tasks on both sides, one full matched repetition, then agreed
repeats. Preserve raw runs, report mean ± sample SEM, and require overlapping
score ranges. Oracle and deterministic tests are separate evidence.

## Notes & Caveats

The upstream pyproject declares MIT but has no standalone license text at this revision. Corpus licenses are independent. Install GNU objcopy and arm-none-eabi-objcopy on the generator host. Container builds need Rust, network, several GB of disk and substantial build time. --data-dir accepts a local HF snapshot; --oracle-dir accepts independently reconstructed TASK_ID.c files.

Dataset revision: 815eb96f130b6d2ef7fa600e04669bf20139bf27. Rust Joern revision: 9f8cad170d6b6883fe08627fa524ecb28128380d. The upstream manual tool policy is preserved verbatim. Inputs are stripped; DWARF and reference source stay private. Neither original nor reconstructed binaries are executed, including malware corpus targets.

Released CFG caches identify pyjoern as generator while current upstream uses Rust Joern. The verifier rebuilds reference CFGs from pinned published source with the same parser as submissions and uses upstream DWARF translation-unit resolution. Normalized published sources may differ from the maintainer's full build tree; exact website fidelity is unproven.

The private image uses pinned upstream source, locked Python dependencies and the pinned native parser. It invokes upstream GED, type and byte pipelines, including fenced-code cleanup, renaming and optional address-line parsing. Parser installation and evaluator exceptions leave no reward; invalid reconstructions follow upstream failures/abstentions. Parser/compiler work is bounded by container resources and verifier timeout.

Union is binary per task; metric.py reports metric-perfect percentages with measured denominators and Union over functions with at least one measurable metric. A candidate parse failure remains a miss in a measurable metric, rather than shrinking its denominator. The frozen function_results index determines measurability uniformly across decompilers. Empty/infrastructure-failed verification is rejected by aggregation. No perfect independent oracle is released; absent supplied reconstructions the oracle fails explicitly. Published decompiler outputs are not perfect references. The generator and upstream share the decbench Python namespace; install upstream only in the verifier image, not the generator environment.

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

The isolated evaluator contract can be run inside a built verifier image:

```bash
docker run --rm --network none -v "$PWD/tests:/contracts:ro" IMAGE \
  python /contracts/evaluator_contract.py /tests/verify.py
```

It checks exact/fenced C, a changed computation, and empty/malformed C against
the pinned evaluator. Run from src/decbench after building the private image.

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
@misc{decbench,
  title={DecBench},
  url={https://github.com/Noelo-Lab/decbench}
}
~~~

## Authors & Contributions

Prepared locally by Evgenii Zheltonozhskii with Codex assistance. Benchmark
prompts, data, code and authorship remain credited to upstream authors.

## Acknowledgement

No sponsored inference or paid parity runs were used for this implementation.
