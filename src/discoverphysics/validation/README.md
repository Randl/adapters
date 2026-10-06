# Preserved oracle validation

These are historical results, not new runs of the migrated package. All 44
scored trials from the September 24 and September 30 successful jobs are
preserved in per-task CSVs and sanitized original job summaries/configurations.
Per-task digests and pinned upstream revisions appear in the CSVs. The September
30 task files match dataset snapshot `4952f1fe2e0104d6ae5467c52444dbd908b13828`.

`run-history.json` keeps infrastructure failures and cancellations separate:
- September 24 09:42: 22/22 scored passes.
- September 30 09:52: 22 infrastructure errors; no scored outcomes.
- September 30 10:03: four missing-reward infrastructure errors, two cancellations,
  and 16 unstarted tasks; no scored outcomes. The verifier exhausted retries;
  the underlying error was not recorded, so missing judge credentials remain
  a hypothesis, not a confirmed cause.
- September 30 10:25: fresh run, 22/22 scored passes, no errors or retries.

The successful fresh run is a separate recovery attempt, not a replacement of
the earlier failed records. Job-level `n_retries` remains the recorded value.
The Harbor runtime Git revisions were not recorded; provenance files retain
null rather than guessing. `harbor_commit_at_export` in those historical files
is the export checkout, not proof of the run's revision.

The complete sanitized archive also includes per-trial logs/configurations,
full-precision experiments, task snapshots, and check outputs. It is retained
locally as `discoverphysics-evidence-20260930-with-current-oracle.tar.gz`;
Hugging Face publication is pending coordination with the reviewer. No public
artifact URL is invented. Recreate bundles using `scripts/bundle_evidence.py`
and the original task directories; upload them under
`adapters/discoverphysics/` in `harborframework/parity-experiments`.

Dataset PR: https://github.com/harbor-framework/harbor-datasets/pull/259
Original review: https://github.com/harbor-framework/harbor/pull/2974

Archive SHA-256: `0cd1b040305baf840e7fbebcf42c883e57956c1284a4113498774f290ffd23aa`
