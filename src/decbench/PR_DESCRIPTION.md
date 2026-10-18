# [WIP] Adapter: DecBench

Add a standalone Harbor adapter. 250 function tasks from the frozen sample-set across 223 binaries. Other leaderboard presets are excluded. IDs include project, optimization, binary and function plus a stable hash.

Pins upstream ae070b885b4e005ed37510a2c3445af6284dc2b9, provides the standard generator and separate verifier,
and records provenance. Perfect GED (0), type_match (1), byte_match (1), and Union, using per-metric measured denominators.

Full oracle and matched
model parity remain pending. This is not ready for registry acceptance; no parity
results are fabricated. Requested initial tag after acceptance: v1.0 (sample-set).
No online PR, push, upload or registration has been made.

See README Notes for exact harness scope, missing reference assets, credentials
and redistribution constraints.

Local validation:

- 4 behavioral tests pass; Ruff lint/format and generator type checks pass.
- Independent source and wheel builds pass, including packaged task templates.
- Structural validator: 28 checks pass, no warnings; the sole error is the
  intentionally absent unmeasured parity_experiment.json.
- Generated real ELF and Windows PE tasks using static parsing only.
- Built the native parser and private verifier image. Exact/fenced, changed,
  empty and malformed synthetic C pass the pinned evaluator contract.
- Real Harbor no-op trial yields zero with fixed eligibility denominators.
- The full 250-function generation/oracle job is not yet validated.
- Final one-task Harbor no-op job completes with zero infrastructure errors;
  the configured custom metric is exercised end to end without inference.
- Installed wheel imports and CLI help pass from outside the checkout.
