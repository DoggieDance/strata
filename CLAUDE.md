# STRATA — project instructions

A static web app that maps American Community Survey data and lets a user build
custom composite indices out of it. Descended from a 2025 study of gentrification
in Philadelphia, which is also the acceptance test.

## Read before doing anything

1. `STRATA-TASKS.md` — governance, git discipline, version ledger, CURRENT DIRECTIVE
2. `spec/` — numbered, in order. `00-CHARTER.md` first.
3. The tail of `worklog.md` — what the last run did

## Hard rules

- **The app never calls the Census API at runtime.** All data is built ahead of
  time into static files. The API is used only for validation spot-checks.
- **Work only on the current phase.** The directive in `STRATA-TASKS.md` names it.
  Do not generalize to other states, geography levels, or vintages before its
  gate passes. Virginia (FIPS 51), tract level, until Phase 01 is green.
  Phase 01 passed 2026-11-12; the owner then set the scope to nationwide
  (50 states + DC, `registry/states.json`), Pennsylvania first.
- **Jam values are a hard failure.** `-666666666`, `-999999999`, `-888888888`,
  `-222222222`, `-333333333`, `-555555555`. None may survive into a built artifact.
- **Per-vintage variable registries, never one global schema.** ACS table
  definitions drift between vintages.
- **Never aggregate unnormalized measures of differing units.** Raise instead.
  See the Area Deprivation Index failure in `spec/04-INDEX-ENGINE.md`.
- **Never apportion a median.** Raise instead.
- **Vintages accumulate.** Never overwrite a published data vintage.

## Git discipline

Inherited from a real fork incident on a prior project. Not optional.

- `git pull --ff-only` before building. If it fails, halt and report.
- Push fast-forward only. If rejected, stop — do not merge, do not force.
- If the local build is behind what is deployed, halt.
- Reserve a version in the VERSION LEDGER *before* building it, never after.
- No auto-push scripts.

## Environment

- This machine is the build box. It downloads from census.gov, computes, and
  pushes finished artifacts out. Nothing ever connects *to* it.
- Large working data (TIGER shapefiles, Summary File downloads, PostGIS) stays
  local and is gitignored. Only small artifacts and the manifest are published.
- Do not put the repo inside a cloud-sync folder.

## Every session

Append to `worklog.md`: what changed, what didn't, why. Including no-op runs.
Never commit a build that fails `tests/`.
