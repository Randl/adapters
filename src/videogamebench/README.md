## VideoGameBench → Harbor Adapter

## Overview

This adapter runs all **20 public benchmark games** (7 test, 13 dev) in Lite or
real-time mode, using upstream VG-Agent, emulator interfaces and evaluator loops.
The three secret test games are not released. Extra calibration and non-benchmark
configs are outside this dataset.

Upstream: [VideoGameBench](https://github.com/alexzhang13/VideoGameBench), pinned to
[`faab53179cb4babdd102f35cb83c24a5f2c29d05`](https://github.com/alexzhang13/VideoGameBench/tree/faab53179cb4babdd102f35cb83c24a5f2c29d05).
This was also upstream main at implementation review. The generated manifest
records the source digest, game-asset hashes, settings and checkpoint count.

## What is VideoGameBench?

VideoGameBench evaluates visual game playing through screenshots and button,
keyboard and mouse actions. Game Boy games use PyBoy; DOS games use JS-DOS and
Playwright. Lite pauses during model deliberation; real-time runs while the model
thinks. The adapter reports the released evaluator's **final-checkpoint completion**
(binary), with the checkpoint index retained as diagnostic evidence. This is not
the paper's weighted progress percentage: the executable evaluator does not use
`checkpoint_percentages` and returns no aggregate score.

## Adapter Features

- All public games; `full`, `test`, `dev` and `parity` selection, stable task IDs,
  `--limit`, `--task-ids` and `--overwrite`.
- Direct upstream VG-Agent integration, plus a visual HTTP client for CLI agents.
- Isolated live game/evaluator service and a separate verifier. Live grading
  avoids assuming that DOS and real-time action replays are deterministic.
- Configurable generation, gameplay, model, routing, budget, resource and timeout
  settings. Immutable source revision and locked Python dependencies.
- MP4 observation videos and frame timestamps, collected with trial artifacts.
- Matched parity preparation, direct original-side runner, result aggregation,
  and a separate oracle candidate collection/revalidation workflow.

## Generated Task Structure

```text
videogamebench/TASK_ID/
├── task.toml
├── instruction.md
├── environment/
│   ├── Dockerfile                 # agent: visual client only
│   ├── Dockerfile.game            # private game/evaluator service
│   ├── docker-compose.yaml
│   ├── play.py
│   └── game/                      # upstream, assets, runtime, signing key
├── tests/                         # separate verifier + manifest + signing key
└── solution/                      # oracle launcher; optional candidate trace
```

The independent adapter project contains `pyproject.toml`, `uv.lock`,
`adapter_metadata.json`, `run_videogamebench.yaml`, experiment settings, tests,
and `src/videogamebench/`. Generated game assets must stay local unless their
licenses permit redistribution. `parity_experiment.json` is intentionally absent
until real matched runs are completed.

## Run Evaluation / Harness

### Running with Datasets Registry

This dataset is not published. After publication use the assigned registry ID
with `harbor run -d ORG/DATASET`; currently use generated local tasks.

### Using Job Configurations

Install this adapter into the same environment as Harbor so its custom agent is
importable. From the adapter directory:

```bash
uv sync --extra harbor --extra runtime
uv run harbor run -c run_videogamebench.yaml
```

The reference YAML uses `datasets/videogamebench` relative to the current working
directory and defaults to `oracle`. Generate there, or change its dataset path.
It requires supplied candidate traces; it does not claim prevalidated solutions.
Prepared parity YAMLs use absolute paths.

### Running Individual Trial

```bash
uv run harbor trial start -p datasets/videogamebench/TASK_ID -a oracle
uv run harbor trial start -p datasets/videogamebench/TASK_ID -a codex -m openai/gpt-5
```

The custom agent is `videogamebench.agent:VideoGameBenchAgent`. It executes the
original VG-Agent in the game service. CLI-agent runs are compatibility evidence,
not a substitute for upstream-agent parity.

## Usage: Create Task Directories

```bash
cd src/videogamebench
uv sync --extra harbor --extra runtime
uv run videogamebench --rom-dir /absolute/path/to/roms \
  --output-dir datasets/videogamebench
```

The default downloads only the pinned upstream code/configs. `--source-dir` accepts
an existing upstream checkout; its content digest is recorded (a locally changed
checkout must not be described as pristine). `--revision` requires a full commit
hash. Use `--bundle-dir` for local DOS bundles named `<game>.jsdos`; otherwise the
upstream game URLs and custom HTML are retained.

```bash
uv run videogamebench --rom-dir /absolute/path/to/roms --split parity \
  --settings experiments/parity.yaml --output-dir datasets/parity
uv run videogamebench --rom-dir /absolute/path/to/roms --task-ids doom2 kirby \
  --set mode=realtime --set max_steps=100 --set threshold=8 \
  --output-dir datasets/diagnostic
```

`--settings FILE` accepts any field in `settings.py`; repeat `--set KEY=VALUE` to
override any field using YAML scalar syntax. Unknown settings fail. Controls cover
mode; steps, frames, delays and threshold; model, temperature, tokens, history,
context, screenshots, cost, API base and API-key environment variable; optional
Python/NumPy seed; server port; image, CPUs, memory, storage and timeouts. Defaults
preserve effective upstream values. Upstream-internal emulator behavior (such as
boot frames and DOS Lite's forced three screenshots) stays in pinned upstream
code. Changing those requires a separate source revision, not a silent override.

`--task-ids` accepts upstream names or generated IDs; names remain stable across
runs. Existing tasks are skipped unless `--overwrite` is supplied. Mode is part
of the ID. Different experiments should use separate output directories. Use
`--oracle-dir DIR` to copy available `<game>.json` candidate traces; missing traces
remain explicit oracle prerequisites.

## Comparison with Original Benchmark (Parity)

**Prepared, not executed.** Selected setting: seven public test games, Lite,
VG-Agent at the pinned revision, `gpt-4o-2024-08-06`, 15,000 steps, 15 action frames,
temperature 0.7, 1,024 output tokens, 20-message context, 4,000 history tokens,
upstream thresholds, and three independent repetitions on each side. See
`experiments/parity.yaml`. No seed is imposed by default because upstream does not
set one. Dependencies, source, game assets and effective settings must match.

| Agent | Model | Metric | Number of Runs | Dataset Size | Original Benchmark Performance | Harbor Adapter Performance |
|-------|-------|--------|----------------|--------------|--------------------------------|----------------------------|
| vgagent@faab531 | gpt-4o-2024-08-06 | Final-checkpoint completion | 3 planned | 7 (35%) | Not measured | Not measured |

```bash
uv run videogamebench --rom-dir /absolute/path/to/roms --split parity \
  --settings experiments/parity.yaml --output-dir datasets/parity
uv run videogamebench-experiment prepare --dataset datasets/parity \
  --output experiments/prepared-parity --runs 3 --kind parity
```

Preparation creates `plan.json` with an attempt ledger, matched Harbor YAMLs,
`run.sh`, an oracle validation config, and a CLI compatibility config. Inspect the
plan before running. Its nominal upstream model-cost allowance is $1,260 total
(7 games × 3 repetitions × 2 sides × $30); upstream checks the cap before a call
and can overshoot by one request. No API spending has occurred here.

After team coordination and provisioning the key named by `api_key_env`, start
with a separate diagnostic dataset using a small `max_steps`, inspect both sides,
then run the prepared full repetitions:

```bash
bash experiments/prepared-parity/run.sh
uv run harbor run -c experiments/prepared-parity/harbor-compatibility.yaml
uv run videogamebench-experiment summarize \
  --plan experiments/prepared-parity/plan.json \
  --output experiments/prepared-parity/summary.json
```

`run.sh` invokes Harbor and `videogamebench-experiment original`. The original
control builds the same pinned gameplay image and calls the upstream launchers
directly, without Harbor or HTTP transport. Both sides use identical observational
instrumentation and the security fixes below. This establishes packaging/lifecycle
parity; the additional deterministic contract tests compare instrumented execution
against uninstrumented upstream loops. They are not measured model parity.

The summary requires every task and repetition, rejects incomplete/unscored runs,
reports per-run arithmetic means and mean ± sample SEM, and checks overlap of raw
run-score ranges. SEM is undefined for one run. Preserve failed attempts; do not
select the better score after retrying genuine failures. After actual experiments,
record measured data in the repository's `parity_experiment.json` schema and link
the result upload. No dataset/result PR or registry publication exists yet.

## Notes & Caveats

**Coverage and assets.** All seven public test games have released checkpoints.
Among the thirteen dev games, only Super Mario Land does. The remaining twelve
are runnable and collect trajectories, but the verifier explicitly reports
missing upstream grading data without writing a reward. They are not silently
assigned failure/success scores. The three secret games need upstream release.

| Split | Platform | Games |
|-------|----------|-------|
| test | Game Boy | pokemon_crystal, zelda, kirby |
| test | DOS | doom2, civ, need_for_speed, incredible-machine |
| dev | Game Boy | pokemon_red, super_mario_land, mega_man, donkey_kong, castlevania, scooby_doo |
| dev | DOS | doom, quake, warcraft2, oregon_trail, x-com, prince, age_of_empires |

Supply legally obtained uncompressed ROMs with exactly these upstream filenames:
`pokemon_red.gb`, `pokemon_crystal.gbc`, `zelda_links_awakening.gbc`,
`super_mario_land.gb`, `kirby_dream_land.gb`, `mega_man_dr_wilys_revenge.gb`,
`donkey_kong_land_2.gb`, `castlevania_the_adventure.gb`, and
`scooby_doo_classic_creep_capers.gbc`. Match the versions described upstream.
DOS uses upstream JS-DOS URLs by default; network availability and licensing are
operator prerequisites. For controlled experiments supply licensed local
`<game>.jsdos` bundles, which are hashed. JS-DOS CDN assets still need network access. Warcraft II's custom HTML
uses upstream's mutable `latest` CDN URL; record/freeze those assets separately
for strict reproducibility, and retain its grid overlay. Code is MIT; game-asset licenses are separate.

**Harness fidelity.** The original loaders resolve config defaults. Doom II uses
threshold 8; the other released configs default to 10. Threshold 0 falls back to
10 upstream. Kirby's checkpoint-specific thresholds/percentages are unused.
The checker uses average hashes, inclusive distance, monotonic forward scanning,
and permits jumping to later checkpoints. Completing the final checkpoint does
not stop the original loop. Game Boy uses the original 18,000-frame boot,
`action_frames + 1` button ticks and `action_frames` no-op ticks. Real-time checks
Game Boy checkpoints during model-wait no-ops, preserving the upstream omission
of checks after normal button steps. DOS preserves its preload sequence,
platform viewport, screenshot crop `(50, 0, 640, 400)`, pause toggles, input delays
and Lite's forced three screenshots. The `--headless` DOS flag is not propagated
upstream, so the service supplies Xvfb instead of changing browser behavior.
The config `press_key_delay` does not override the runner's truthy default 100;
we retain that behavior.

**Security and failure handling.** The agent container contains only the visual
client. The game service owns emulators, checkpoints and signing key. Harbor
collects `/state` directly from that service and transfers it to the separate
verifier. Results are authenticated and bound to the task manifest; public HTTP
endpoints expose observations/actions/status, not arbitrary paths or score writes.
A per-generation key intentionally changes on regeneration; task IDs and content
identity remain stable. Never publish generated private keys with a live service.

Two symmetric security changes are applied at runtime: the upstream Game Boy
parser's `eval` becomes `ast.literal_eval` (same valid literal actions, no Python
execution), and its DOS web server only serves its game page/config/local bundle,
preventing filesystem browsing into private checkpoints. Provider `Error:` replies
and prematurely terminated loops produce infrastructure errors rather than scored
zeros. Invalid model action parsing otherwise keeps upstream behavior. An
explicit API base also sets LiteLLM's global route because upstream otherwise
ignores it for some providers. These changes apply equally to both parity sides.
Python/model dependency versions are pinned for the new experiment; the upstream
requirements do not lock its historical paper environment. Live DOS timings and
remote asset availability can still vary.

**Separate oracle experiment.** Games have no released winning action traces.
A candidate is a gameplay policy, not a ground-truth answer. Prepare independent
model/human candidate collection across all public games:

```bash
uv run videogamebench --rom-dir /absolute/path/to/roms \
  --settings experiments/oracle.yaml --output-dir datasets/oracle
uv run videogamebench-experiment prepare --dataset datasets/oracle \
  --output experiments/prepared-oracle --kind oracle --runs 1
# Once candidate collection is authorized:
bash experiments/prepared-oracle/run.sh
uv run videogamebench-experiment export-oracles \
  --job experiments/prepared-oracle/harbor --output oracle-candidates
uv run videogamebench --rom-dir /absolute/path/to/roms \
  --settings experiments/oracle.yaml --oracle-dir oracle-candidates \
  --output-dir datasets/oracle --overwrite
uv run harbor run -c experiments/prepared-oracle/harbor-oracle.yaml
```

Export takes the first observed completed candidate per game, only for oracle
construction. It never selects parity scores. Independently replay and inspect
screens/checkpoints before calling a candidate validated. DOS and real-time
replays may diverge. The default replay policy acts as soon as the game requests
input. For new human recordings, `python /opt/game/play.py --replay actions.json
--replay-timing recorded` preserves the recorded action times relative to the
first input-ready state. This requires `control_elapsed_sec` on every action;
older traces cannot reconstruct their initial idle time reliably. For games without checkpoints retain
human-reviewed trajectories and request upstream evaluation assets; do not claim
100% oracle success across the benchmark.

A human **Warcraft II first-mission replay** is included separately as
`oracle-inputs/warcraft2-mission-1.json`. All 302 timed actions (8m 12s) were
replayed from a fresh boot using the same bundle, cached browser assets, seed,
and capture settings. Both the recording and replay completed the first Orc
mission and reached **II. Raid at Hillsbrad**. Maximum input dispatch drift was
89ms. Final screenshots were visually matching but not pixel-identical.
`experiments/oracle-warcraft2-mission-1-result.json` records the configuration,
asset checksums and evidence; the matching YAML contains game settings. This is
one successful game-service replay, not a Harbor trial, full-campaign oracle,
or benchmark reward: the pinned upstream Warcraft II configuration has no
released checkpoints. Its mission-specific filename prevents automatic use as
a full-game oracle. Use `--replay-timing recorded` for this input.

The **Warcraft II mission I stock replay** in
`oracle-inputs/warcraft2-mission-1-stock.tar.gz` uses the first 359 timed
inputs of the human campaign recording. With the licensed `warcraft2.jsdos` in
`BUNDLE_DIR`, generate the mission I task from the adapter directory:

```bash
mkdir -p oracle-candidates
tar -xzf oracle-inputs/warcraft2-mission-1-stock.tar.gz -C oracle-candidates
uv run videogamebench --task-ids warcraft2 --bundle-dir "$BUNDLE_DIR" \
  --oracle-dir oracle-candidates --set mode=realtime --set max_steps=1325 \
  --output-dir datasets/warcraft2-mission-1
```

The replay uses the pinned [companion replayer](https://github.com/Randl/videogamebench-replayers).
It uses ordinary game inputs to recover worker
selections and send one scout along its recorded northwestern route.
Eleven fresh stock boots reached the mission II briefing. A separate test
deliberately selected the Great Hall instead of a peon and also reached the
briefing. The eleven scores were 660 or 720. Per-run evidence is in
`experiments/oracle-warcraft2-mission-1-stock-result.json`.

A human **Super Mario Land (dev set)** oracle is included in
`oracle-inputs/super_mario_land.json`. Its 8,939 actions were replayed from a fresh
boot through Harbor 0.24.0 on 2026-10-21, with recorder caches disabled. The
separate verifier returned **reward 1.0**, reaching both released checkpoints,
with no infrastructure exception. This measures final-checkpoint completion,
not the paper's weighted progress metric. This is one successful oracle replay;
model parity and validation of the other games remain pending. Settings, ROM and
source hashes, input checksum, and result details are recorded in
`experiments/oracle-super-mario-land-result.json`. No ROM is included.

Reproduce from this adapter directory with the licensed `super_mario_land.gb`
matching the recorded ROM hash:

```bash
uv run videogamebench --task-ids super_mario_land \
  --rom-dir /absolute/path/to/roms \
  --settings experiments/oracle-super-mario-land.yaml \
  --oracle-dir oracle-inputs --output-dir datasets/mario-oracle
uv run harbor trial start \
  -p datasets/mario-oracle/videogamebench-super-mario-land-lite -a oracle
```

The replay takes about 40 minutes at the upstream emulator speed. It uses the
full input sequence, without loading human-recorder snapshots.

**Run progress and scores.** Oracle replay logs show action count, percentage,
actions/second, elapsed time, and ETA every ten seconds. `play.py
--progress-interval SECONDS` changes the interval; zero disables periodic updates.
The game service writes `progress.jsonl` and flushed console messages with action
count/budget, checkpoint index/count, binary final-checkpoint score, elapsed time,
model cost, and errors. Checkpoint changes and the final summary are always logged;
`VIDEOGAMEBENCH_LOG_INTERVAL_SEC` configures periodic messages (default 10; zero
disables them). Set it in the host environment for Harbor's Docker Compose game
service, or inside a standalone game container. Games without released checkpoints
and infrastructure failures report a null score. The checkpoint index is the
upstream next-checkpoint position, not a weighted score or count of independently
matched checkpoints. Score information stays in private game/verifier logs; the
agent-facing HTTP API exposes no score. The separate verifier prints the final
score and writes `verifier/reward.txt`. Harbor retains game progress under
`artifacts/state/progress.jsonl` and replay output in the oracle agent logs.

**Servers and video logs.** No physical screen, desktop session, host X server,
GPU or forwarded `DISPLAY` is required. PyBoy is headless and DOS runs Chromium
under a container-local Xvfb display (with an init process for reliable startup).
Use Docker on a headless Linux server and inspect downloaded screenshots/videos
from another machine.

Human play, recording, rewind, save restoration and replay diagnostics are documented in the [standalone replayers repository](https://github.com/Randl/videogamebench-replayers). Task generation stages its pinned runtime in the Harbor game service.

Recording defaults to `record_video: true`, `video_fps: 5`. Change these with
`--set record_video=false` or `--set video_fps=10` and regenerate. The service
writes `/state/gameplay.mp4` and `/state/video-timestamps.jsonl`; Harbor collects
them under the trial's `artifacts/state/`. Original controls write them in each
task's result directory. These are **observation videos**: between observations
the latest screen is held, rather than taking additional screenshots that change
upstream timing. JSONL records capture and observation times. The recorder uses
bounded memory and a background writer; its overhead can still affect real-time
play, so both parity sides must use the same recording settings. Video failures
are reported separately as `video_error`, without altering gameplay scores.

## Installation / Prerequisites

Python 3.12+, uv, Docker Compose, network access to package/browser/game hosts,
licensed game assets, and API credentials for model runs. Harbor is an external
optional dependency pinned to 0.24.0; it is not vendored. Install the `harbor` and
`runtime` extras for experiment execution and contract tests. Docker installs the
same runtime dependency export from `uv.lock`, plus Chromium and Xvfb.

```bash
VIDEOGAMEBENCH_SOURCE=/path/to/pinned/upstream uv run pytest tests
uv run ruff check .
uv run ruff format --check .
uv run ty check
# From the repository root:
python3 scripts/validate_adapter.py videogamebench
```

Contract tests use deterministic emulator/model doubles with the real upstream
runners, agent prompts/history and evaluators. They compare request payloads and
actions across both platforms/modes. Generation tests cover all 20 tasks, Harbor
schemas, configuration, filtering, key isolation and tamper rejection. These do
not establish gameplay success. The local test suite, lint, type checks, and package build are run before committing. A live one-action Doom II trial ran
through Harbor with host `DISPLAY` unset: zero infrastructure exceptions, valid
reward 0, authenticated sidecar evidence, and a decoded 5-fps MP4. This is a
lifecycle/video smoke test. The separate Super Mario Land oracle replay described
above subsequently passed with reward 1.0; neither run establishes model parity. The structural validator still requires measured
`parity_experiment.json`; preparation alone cannot truthfully satisfy that gate.

## Troubleshooting

Inspect game-service `/state/logs`, `effective-settings.json`, `actions.json` and
`result.json`, plus Harbor verifier logs. Missing rewards indicate infrastructure
failure or absent upstream checkpoints. Missing licensed assets fail generation
with the expected filename. Missing oracle traces fail explicitly. Regenerate
with `--overwrite` after template/settings changes. Use separate output paths for
new experiments and preserve previous attempts and manifests. A DOS URL can load
an error page without an exception; inspect the initial screenshot during preflight.

## Citation

```bibtex
@misc{videogamebench,
  title={VideoGameBench},
  author={Zhang, Alex L. and Griffiths, Thomas L. and Narasimhan, Karthik R. and Press, Ofir},
  url={https://github.com/alexzhang13/VideoGameBench}
}
```

## Authors & Contributions

Adapter: Evgenii Zheltonozhskii (zheltonozhskiy@gmail.com), with Codex assistance.
Benchmark code, prompts and evaluation remain credited to the upstream authors.

## Acknowledgement

No paid inference, dataset publication or result upload was performed while
preparing this implementation.

### Reconstructing and extending checkpoints

`checkpoints/plan.json` records source videos, exact timestamps, normalized crops,
labels, source review status, paper percentages, and source-video/reference SHA-256 hashes
for all 20 public games. It includes every released checkpoint and the paper's
166 test milestones. Dev additions are separately identified, selected
intermediate milestones; they are not an official exhaustive checkpoint list.
`checkpoints/durations.csv` ranks walkthrough lengths, including both Age of
Empires parts and the 76-video X-COM playlist. These durations are proxies, not
expected human or emulator execution times.

```bash
uv sync --extra checkpoints
uv run videogamebench-checkpoints \
  --plan checkpoints/plan.json \
  --video-dir /path/to/walkthrough-cache \
  --source-dir /path/to/pinned/VideoGameBench \
  --output-dir /path/to/checkpoint-audit \
  --download-missing
```

The output contains `reconstructed-upstream/`, `expanded/`, `report.json`, and a
local `index.html` gallery. Download concurrency, chunk size, retries, timeout,
decoder, and progress interval are CLI options; timestamps, crops, formats,
labels, and comparison thresholds live in the JSON plan. `--overwrite` explicitly
regenerates images. `--strict-reference-matches` exits with status 2 if any
reconstruction exceeds the published threshold. Video-content changes fail
validation so edited walkthroughs cannot silently invalidate timestamps. Published
reference hashes also pin the images used for comparison.

The comparison uses upstream's 64-bit `imagehash.average_hash`, including Doom
II's threshold of 8 and the other released defaults of 10. The audit also lists
checkpoint pairs that collide under that matcher. A matching video frame is not
proof of emulator compatibility or unique milestone detection. Remastered/source
ports, color palettes, creator overlays, repeated credits, and similar result
screens require replay validation. The X-COM sources have an overlapping webcam;
those references need clean emulator captures before oracle use.

`checkpoints/collision_probe.json` records a direct probe of the unmodified Doom II
matcher: repeatedly supplying the published map-1 image reaches checkpoint 30
after 16 checks. This is a matcher probe, not a game episode or Harbor result.
Scoring is preserved for parity; the collision limits what a checkpoint reward
alone can establish about game completion.

These reconstructed and expanded images are **experimental references**, not
validated oracle inputs. Task generation and parity continue to use the pinned
upstream checkpoint set. Generated images and downloaded videos stay outside the
adapter package; the extraction plan, comparison summary, and tool are versioned.
See `checkpoints/audit_summary.json` for the measured comparisons and remaining
limitations. The existing validated Mario oracle remains tied to its original
checkpoint set.
