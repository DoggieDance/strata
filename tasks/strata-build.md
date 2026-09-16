# Scheduled task — STRATA build

Cadence: daily while a machine is on. One task, one run, one thing.

## Every run, in order

1. `git pull --ff-only`. If it fails, **halt and report**. Do not merge.
2. Read `STRATA-TASKS.md` and the tail of `worklog.md`.
3. Compare the local build tag to what is deployed. **If local is behind, halt.**
   This is the staleness guard. The ORACLE fork happened without it.
4. Check the current directive under CURRENT DIRECTIVE. Do that, and only that.
5. Run `pytest tests/ -q`. A failure ends the run — do not commit, do not push.
6. Append to `worklog.md`: what changed, what did not, why. No-op runs get an
   entry too.
7. Publish via the guarded script only. No auto-push.

## Alternation

Odd runs advance the engine. Even runs advance the interface. A run that would
break the alternation because the other side is blocked says so in the worklog
rather than doubling up silently.

## Never

- Mint a version not reserved in the VERSION LEDGER.
- Overwrite a published data vintage.
- Generalize past the current phase. Virginia until Phase 01's gate passes.
- Commit a build that fails tests, "temporarily."
