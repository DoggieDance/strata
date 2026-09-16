# STRATA

An ACS data viewer with a built-in custom index-map builder.

Pick census measures, choose how they are standardized and weighted, and get a
composite index mapped at tract level — with margins of error carried through
the whole calculation instead of discarded.

Descended from *Gentrification in Philadelphia: 2010–2020* (GEOG 376, JMU, 2025),
which did this once, by hand, for one city.

## Principles

1. **The app never calls the Census API.** All data is built ahead of time into
   static files. No key, no rate limit, no backend, no request that can fail.
2. **Spec before code.** `spec/` stabilizes before an engine is written. Governance
   discipline carried over from ORACLE.
3. **Uncertainty is not optional.** Any number the app shows can report its own
   margin of error. Anything too unreliable to map is hatched, not colored.
4. **Free is a design constraint, not an aspiration.** Every layer stays inside a
   documented free tier, and the ledger in `spec/03-CUBE-AND-TILES.md` says which
   ceiling breaks first.
5. **Legible to a layperson, rebuildable by a GIS analyst.** Both, on one page.

## Layout

```
spec/        design documents — read these first, in order
registry/    measure definitions (which ACS variables, how derived)
etl/         build pipeline — runs on the local build machine, never in a chat session
app/         the single-file web app
tests/       golden fixtures and property tests
tasks/       scheduled-task specifications
```

## Status

Phase 00 — governance. Nothing built yet. See `STRATA-TASKS.md`.
