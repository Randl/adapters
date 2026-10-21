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
replays may diverge; elapsed times are retained as evidence but the replay policy
acts as soon as the game requests input. For games without checkpoints retain
human-reviewed trajectories and request upstream evaluation assets; do not claim
100% oracle success across the benchmark.

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

For human recordings of Game Boy Lite tasks, the game service serves a keyboard
player at `/`. Publish its container port 8080 to a localhost port (for example
`-p 127.0.0.1:8765:8080`) and bind-mount a recording directory at `/state`.
Open `http://localhost:8765`, click **Play & record**, and use arrows, Z/Space
(A), X (B), Enter (Start), and Shift (Select). **Pause game** or switching windows
stops sending actions; the video continues holding the latest observation.
WASD and J/K are alternate movement and A/B keys. The input indicator shows held
and transmitted buttons. Quick taps are retained until the next action, together
with any held buttons; **Hold run (B)** also supports running jumps on keyboards
that cannot report some multi-key combinations.
**Finish & save** finalizes `actions.json`, `gameplay.mp4`, and the result.
For a remote server, forward the localhost port over SSH. The emulator remains
headless. `action_frames` controls input duration and must match on replay.
Keep the upstream default of 15 frames for Super Mario Land: upstream releases
every pressed button at each action boundary, so short actions can turn a held
jump into short taps and reduce its height. A controlled test from the same
unobstructed starting state measured 17 pixels with four-frame actions and 33 pixels with
15-frame actions or a continuous hold. Lower values therefore change gameplay,
not just control responsiveness. Video rate is independent; use
`--set video_fps=15` for smoother observation recordings.

The browser recorder has a **Play speed** control (default ¼×) and
**Single-action mode**. Slower play adds wall-clock pauses between ordinary
upstream actions. In single-action mode, hold any combination of game buttons
and press `.` or click **Advance one action**; with no buttons held it sends a
no-op. The emulator stays frozen between advances. These controls preserve the
configured action frame count and replay format; they improve timing, but do not
make a 15-frame movement smaller. Browser preferences survive refresh and rewind.

To enable **Restart game & recording** and **Rewind & continue**, launch the
human recorder with `python /opt/game/runtime/server.py --allow-restart`.
Both controls finalize and archive the previous attempt under
`/state/attempts/<timestamp-id>/`, then start a fresh interpreter with a private
copy of the initial game assets. Rewind restores the nearest matching snapshot, replays the remaining actions, and
resumes normal play from that point; the new trace includes the prefix.
Choose the number of actions to undo and the reconstruction speed in the browser.
**Fastest** removes PyBoy's real-time throttle; frame counts and controls stay
unchanged. The new video shows reconstruction at its accelerated wall-clock speed.
`--replay-speed` configures the default multiplier (0 means unlimited), and
`--restart-timeout-sec` controls the browser's server-restart timeout.
Restart and rewind are disabled in benchmark containers and rejected for model
controllers, DOS games, and realtime mode. Boot preparation still runs before
reconstruction on the first launch. Subsequent restarts/rewinds load the exact
post-boot emulator state from `/state/.boot-cache`, keyed by task identity and
PyBoy version and checked for corruption. This cache survives attempt archival.
The recorder also saves emulator state and checkpoint progress every 100 actions
in `/state/.snapshots`. `--snapshot-interval N` changes this frequency; 0 disables
snapshots. Snapshot keys include task identity, PyBoy version, and the entire
action prefix, so branches cannot reuse incompatible states. Corrupt files are
skipped. The full action trace is retained; entries restored from snapshots are
marked `restored_from_snapshot` and omit replay timing. New videos begin at the
restored state; earlier footage remains in the archived attempt. Restoration
metrics record the snapshot position and number of actions actually replayed.
Use `--no-boot-cache` to repeat the full upstream boot. Caching is only enabled
for manual recordings launched with `--allow-restart`; benchmark/model runs
retain the upstream startup path. Frame-perfect repeatability should be
validated per ROM/config.

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
