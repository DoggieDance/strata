# STRATA — Task Ledger and Build Discipline

The operating document. Scheduled tasks read this first, every run.

---

## GIT DISCIPLINE

Inherited verbatim from the ORACLE fork incident of July 2026. These are not
suggestions.

1. **Pull before build.** Always. `git pull --ff-only` before touching anything.
2. **Fast-forward only on push.** If the push is rejected, stop. Do not merge,
   do not force, do not invent a version number.
3. **Stale means halt.** If the local build tag is behind what is deployed,
   halt and report. Do not build on a stale base.
4. **No auto-push.** A guarded publish script only, which pulls, verifies the
   build is strictly ahead, pushes fast-forward, and rolls back on rejection.
5. **One version ledger.** Below. A version is minted here before it is built,
   never after.

---

## VERSION LEDGER

| Version | Reserved for | Status |
|---|---|---|
| v0.1 | Phase 00 — spec files committed | in progress |
| v0.2 | Phase 01 — Virginia data spine | **gate passed 2026-11-12** — 20/20 data.census.gov values match; zero jams |
| v0.2.1 | Published levels: county, place, ZCTA (owner request) | **passed 2026-11-12**: 100/100 spot-check values. Entered after the build, not before; the reserve-first rule was missed |
| v0.3 | Phase 02 — harmonizer | in progress — 2006–2010 loader gate passed 2026-11-12; crosswalk next |

Rule: reserve here first. A build that discovers its version is taken halts.

---

## PHASE GATES

A phase ships when its gate passes. Writing the code is not shipping it.

- **00 Governance** — spec files committed; two scheduled tasks running without collision.
- **01 Data spine** — 20 random tract values match data.census.gov exactly; zero jam values survive into the cube.
- **02 Harmonizer** — apportioned population sums to source within rounding; Philadelphia 2010 reproduced on 2020 tracts.
- **03 Map surface** — byte-range requests verified against R2 in Safari and Firefox; full-pilot recolor under 150 ms.
- **04 Index engine** — **the Philadelphia replication**: the 159-neighborhood average z-score map reproduced from raw ACS within tolerance.
- **05 Uncertainty** — propagation matches the Census handbook worked examples; no change reported below its significance threshold.
- **06 Typology** — published classifications for one metro reproduced from a preset.
- **07 National** — 85,000 tracts recolor within budget, or the viewport-scoped fallback ships.
- **08 Reading room** — a non-GIS reader reaches a correct interpretation unaided.

---

## CURRENT DIRECTIVE

**Phase 02, crosswalk.** The 2006–2010 loader passed its gate 2026-11-12.
Next: the 2020-block-population-weighted 2010→2020 tract crosswalk for
Virginia (spec 02), checked for conservation and against HUD/Geocorr.
The Phase 02 gate itself needs Philadelphia (PA, FIPS 42); widening the
scope lock to PA is an owner decision, not yet taken.

Phase 01 gate passed 2026-11-12. Still blocked for Phase 03: Cloudflare R2
bucket + repo secrets. See `spec/03-CUBE-AND-TILES.md`.

---

## STANDING RULES FOR SCHEDULED TASKS

- Read this file and `worklog.md` before doing anything else.
- One task per run does one thing. Alternate engine work and interface work.
- Append to `worklog.md` every run, including no-op runs and why.
- Never commit a build that fails `tests/`.
- Never overwrite a published data vintage. Vintages accumulate; they are the archive.
- If the Census release calendar has not moved, no-op. Do not manufacture work.
