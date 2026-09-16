# STRATA worklog

Append-only. Every scheduled run writes here, including no-ops.

---

## 2026-09-11 — Phase 00 opened

Research pass complete across four fronts: ACS acquisition, free hosting,
geometry/browser analytics, index methodology and prior art. Findings and
sources in `spec/RESEARCH-LOG.md`.

Architecture settled: static build, no runtime API calls, Parquet attribute cube
joined to a GEOID-only PMTiles archive at runtime. Pilot region Virginia.

Scaffold committed. Nothing built. Blocked on R2 credentials before Phase 01.

## 2026-09-12 — cost and shortcut pass

Asked whether money makes this easier. Answer: not on the data side. Every
pre-built ACS/crosswalk product is either already free and in the plan, or
license-blocked for public redistribution (NHGIS, Esri Demographics, Social
Explorer, PolicyMap viewer tiers, ArcGIS Personal Use).

Two free shortcuts were under-weighted in the first pass and are now folded into
Phase 02: the HUD-USPS tract crosswalk (address-count weights, redistribution-clear)
and Geocorr (population weights, no published terms). Both become validation
references for the block-weighted engine rather than replacements for it.

Where money helps is build iteration, not hosting: a ~EUR 7/month VPS with PostGIS
replaces the push-and-wait CI loop. Noted in RESEARCH-LOG.md. No architecture change.

Files amended: spec/02-HARMONIZER.md, spec/RESEARCH-LOG.md.
