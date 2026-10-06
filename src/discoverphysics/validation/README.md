# Oracle validation

The latest judged oracle run, `discoverphysics-oracle-20260930-102507`, passed
all 22 tasks with zero errors or retries in 12m 6s. Mean reward was 1.0 and
mean explanation score was 0.95. These are the recorded results of that run;
no model evaluations were launched for the package migration.

`oracle-20260930-102507/` contains the per-task CSV, sanitized original job
summary/configuration, recomputed metrics, and provenance. All 22 task digests
match the recorded lockfiles and dataset snapshot
`4952f1fe2e0104d6ae5467c52444dbd908b13828`. Every scored outcome is retained.

The Harbor runtime Git revision was not recorded; provenance retains null.
`harbor_commit_at_export` identifies the export checkout, not the run's revision.

The complete sanitized evidence for this run also includes per-trial
logs/configurations, full-precision experiments, exact task snapshots, and
checksums. Hugging Face publication is pending coordination with the reviewer.
Use the repository's [upload skill](../../../skills/upload-parity-experiments/SKILL.md)
to publish under `adapters/discoverphysics/` in `harborframework/parity-experiments`.

Dataset PR: https://github.com/harbor-framework/harbor-datasets/pull/259
Original review: https://github.com/harbor-framework/harbor/pull/2974
Migration PR: https://github.com/harbor-framework/adapters/pull/9
