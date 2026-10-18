# [WIP] Adapter: CodeReviewBench (offline)

Add a standalone Harbor adapter. 50 tasks = 10 PRs each from cal.com, Discourse, Grafana, Keycloak and Sentry. All 173 golden comments are retained. Strict/core/all profiles include 139/158/173 issues. The online benchmark is excluded.

Pins upstream e616e849755441da38f18bf3adba2c9583b03803, provides the standard generator and separate verifier,
and records provenance. Core micro F2; strict/core/all precision, recall, F1 and F2 are retained.

Full oracle and matched
model parity remain pending. This is not ready for registry acceptance; no parity
results are fabricated. Requested initial tag after acceptance: v1.0 (offline).
No online PR, push, upload or registration has been made.

See README Notes for exact harness scope, missing reference assets, credentials
and redistribution constraints.

Local validation:

- 4 behavioral tests pass; Ruff lint/format and generator type checks pass.
- Independent source and wheel builds pass, including packaged task templates.
- Structural validator: 28 checks pass, no warnings; the sole error is the
  intentionally absent unmeasured parity_experiment.json.
- Generated all 50 tasks deterministically and checked upstream judge bytes.
- Default pinned source download succeeds. A real Harbor no-op trial produces
  upstream profile counts without judge calls.
- Final one-task Harbor no-op job completes with zero infrastructure errors;
  the configured custom metric is exercised end to end without inference.
- Installed wheel imports and CLI help pass from outside the checkout.
