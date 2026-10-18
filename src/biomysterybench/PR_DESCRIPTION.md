# [WIP] Adapter: BioMysteryBench

Add a standalone Harbor adapter. 90 tasks = 73 human-solvable + 17 human-difficult problems in the revised v11 full set. No problems are excluded. The original 99-problem paper results use an earlier answer key.

Pins upstream b5a889c4757214ec9a6ade876b734f920a7799db, provides the standard generator and separate verifier,
and records provenance. Binary rubric acceptance, reported separately for the 73/17 partitions.

Full oracle and matched
model parity remain pending. This is not ready for registry acceptance; no parity
results are fabricated. Requested initial tag after acceptance: v1.0 (full).
No online PR, push, upload or registration has been made.

See README Notes for exact harness scope, missing reference assets, credentials
and redistribution constraints.

Local validation:

- 7 behavioral tests pass; Ruff lint/format and generator type checks pass.
- Independent source and wheel builds pass, including packaged task templates.
- Structural validator: 28 checks pass, no warnings; the sole error is the
  intentionally absent unmeasured parity_experiment.json.
- Generated a real pinned hb001 task and verified its private image in Harbor
  with the no-op agent (zero reward, no inference). Metadata enumerates all
  90 released problems; the full data archives were not downloaded.
- Final one-task Harbor no-op job completes with zero infrastructure errors;
  the configured custom metric is exercised end to end without inference.
- Installed wheel imports and CLI help pass from outside the checkout.
