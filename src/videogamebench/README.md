## VideoGameBench → Harbor Adapter

## Overview

Play classic games through screenshots and button actions.

4 Lite tasks: Kirby, Pokemon Crystal, Super Mario Land and Links Awakening. These are the released Game Boy games with checkpoint images (three test games plus Mario from dev). Five other Game Boy configs lack checkpoints. DOS games, secret games, real-time mode and extra non-benchmark configs are excluded.

Source: [VideoGameBench](https://github.com/alexzhang13/VideoGameBench), revision faab53179cb4babdd102f35cb83c24a5f2c29d05. Licensing details are in Notes.

## What is VideoGameBench?

Play classic games through screenshots and button actions. Binary final-checkpoint completion for this explicit Lite subset; checkpoint-index diagnostics are retained separately.

## Adapter Features

- Stable IDs, selection, limits and overwriting.
- Pinned sources and self-contained generated tasks.
- Separate private verifier and explicit failure behavior.
- Retained verifier evidence and reproduction configuration.

## Generated Task Structure

~~~text
videogamebench/TASK_ID/
├── task.toml
├── instruction.md
├── environment/   # public inputs and agent build context
├── tests/         # private verifier and references
└── solution/      # oracle launcher and available references
~~~

The independent project at src/videogamebench/ contains pyproject.toml, uv.lock, metadata,
run_videogamebench.yaml, and src/videogamebench/ with adapter.py, main.py and task-template/.
parity_experiment.json will be added only after real coordinated runs.

## Run Evaluation / Harness

### Running with Datasets Registry

This dataset is unpublished. After registry acceptance, use the assigned registry
ID with harbor run -d ORG/DATASET. Current verification uses local paths.

### Using Job Configurations

Install Harbor separately with uv tool install harbor==0.24.0. From this branch's
repository root, after generation:

~~~bash
harbor run -c src/videogamebench/run_videogamebench.yaml
harbor run -c src/videogamebench/run_videogamebench.yaml -a codex -m MODEL
harbor job resume -p /path/to/job
~~~

Oracle is the default. This configuration does not assert oracle success; read
Notes for the required reference assets.

### Running Individual Trial

~~~bash
harbor trial start -p datasets/videogamebench/TASK_ID -a oracle
harbor trial start -p datasets/videogamebench/TASK_ID -a codex -m MODEL
~~~

## Usage: Create Task Directories

~~~bash
cd src/videogamebench
uv sync
uv run videogamebench --rom-dir /path/to/licensed/roms --output-dir ../../datasets/videogamebench
~~~

Standard flags: --output-dir, --limit, --overwrite, --task-ids ID [ID ...].
Unknown IDs and negative limits are rejected. Existing tasks are skipped without
--overwrite. Default output is datasets/videogamebench relative to invocation directory;
use ../../datasets/videogamebench from the project to match the repo-root run config.

## Comparison with Original Benchmark (Parity)

No measured model parity is claimed. No placeholder parity JSON is committed;
the structural validator will report that required file as pending.

| Agent | Model | Metric | Number of Runs | Dataset Size | Original Benchmark Performance | Harbor Adapter Performance |
|-------|-------|--------|----------------|--------------|--------------------------------|----------------------------|
| Pending | Pending | See text | 0 | 4 | Not measured | Not measured |

Scenario 3: VG-Agent has a custom visual loop. A CLI-agent run is compatibility evidence only. Reproduce its history, images, action parsing and model settings on both sides, using the same ROM hashes and PyBoy. Original command: python main.py --game GAME --lite --max-steps 15000 --action-frames 15. The original loop has no returned score; compare the exact checker and label this completion criterion. Do not compare it to website progress percentages.

Harbor-side compatibility command, which alone does not establish parity:

```bash
harbor run -c src/videogamebench/run_videogamebench.yaml -a codex -m MODEL
```

Agree on solver/model versions, judge routing, prompts/tools, subset, images,
Harbor revision, limits, at least three repetitions and expected cost before paid
runs. Run 5–10 tasks on both sides, one full matched repetition, then agreed
repeats. Preserve raw runs, report mean ± sample SEM, and require overlapping
score ranges. Oracle and deterministic tests are separate evidence.

## Notes & Caveats

MIT benchmark code; ROMs have separate licenses and are not provided. Supply kirby_dream_land.gb, pokemon_crystal.gbc, super_mario_land.gb and zelda_links_awakening.gbc. Docker Compose and a vision-capable agent with screenshot access are required. --source-dir accepts pinned upstream source; --oracle-dir accepts winning GAME.json replays.

ROM digests identify the exact game assets. No ROM is committed. Generated tasks contain ROM copies and must remain local unless redistribution is authorized. The main container has only the HTTP control client. A sidecar owns the emulator, exposing screenshots and button actions, with no hidden checkpoints. The verifier receives actions.json and independently replays it using a fresh emulator and private checkpoints. Forged screenshots or claimed scores cannot replace a successful replay. No verifier token or judge secret enters the agent container.

The unchanged upstream Game Boy interface preserves the 18,000-frame boot, 15-frame no-op, 16-tick button action (skip_frames + 1), 15,000-action cap and Lite pause. The checkpoint checker is extracted verbatim: average-image hash, inclusive threshold, monotonic scan and jumping to later checkpoints. Effective threshold is the upstream global default 10. Kirby's per-checkpoint thresholds are unused by the original runner and are not substituted.

The released executable harness returns no paper/website progress score; checkpoint_percentages is unused by its evaluator. This integration reports final-checkpoint completion, not the weighted leaderboard percentage. Synthetic screen tests establish checker behavior only, not game completion. No winning traces or commercial ROMs exist in this workspace. Without supplied traces the oracle fails explicitly. Full gameplay, oracle and model runs remain pending. Boot alone takes five minutes at capped emulator speed; maximum replays can exceed an hour and verifier timeout is 6,000 seconds.

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
VIDEOGAMEBENCH_SOURCE=/path/to/pinned/upstream uv run pytest tests
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
@misc{videogamebench,
  title={VideoGameBench},
  url={https://github.com/alexzhang13/VideoGameBench}
}
~~~

## Authors & Contributions

Prepared locally by Evgenii Zheltonozhskii with Codex assistance. Benchmark
prompts, data, code and authorship remain credited to upstream authors.

## Acknowledgement

No sponsored inference or paid parity runs were used for this implementation.
