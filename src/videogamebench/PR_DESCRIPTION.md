# [WIP] Adapter: VideoGameBench

Add a standalone Harbor adapter. 4 Lite tasks: Kirby, Pokemon Crystal, Super Mario Land and Links Awakening. These are the released Game Boy games with checkpoint images (three test games plus Mario from dev). Five other Game Boy configs lack checkpoints. DOS games, secret games, real-time mode and extra non-benchmark configs are excluded.

Pins upstream faab53179cb4babdd102f35cb83c24a5f2c29d05, provides the standard generator and separate verifier,
and records provenance. Binary final-checkpoint completion for this explicit Lite subset; checkpoint-index diagnostics are retained separately.

Full oracle and matched
model parity remain pending. This is not ready for registry acceptance; no parity
results are fabricated. Requested initial tag after acceptance: v1.0 (game-boy-lite).
No online PR, push, upload or registration has been made.

See README Notes for exact harness scope, missing reference assets, credentials
and redistribution constraints.

Local validation:

- 3 behavioral tests pass; Ruff lint/format and generator type checks pass.
- Independent source and wheel builds pass, including packaged task templates.
- Structural validator: 28 checks pass, no warnings; the sole error is the
  intentionally absent unmeasured parity_experiment.json.
- Generated all four task layouts with clearly marked synthetic ROM placeholders;
  checked the real upstream checkpoint behavior and replay validation.
- Verifier image builds and missing-replay handling produces zero.
- No licensed game was run; commercial ROMs and winning replays are unavailable.
- Installed wheel imports and CLI help pass from outside the checkout.
