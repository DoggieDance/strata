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

## 2026-09-16 — Phase 01 build, stopped at the gate

Build box: 15 GiB RAM, 182 GB free, Python 3.12.3, www2.census.gov → 200.
`git pull --ff-only`: already up to date. v0.2 marked in progress in the ledger.
Environment: python3.12-venv/ensurepip missing, so `.venv` was created with
`--without-pip` and pip bootstrapped inside it via get-pip.py. No global pip.

**Built** (uncommitted, not pushed, not uploaded):
- `etl/common.py`, `etl/fetch_summary_file.py`, `etl/clean.py`, `etl/build_cube.py`
- `registry/summary_files.json` (new): per-vintage Summary File location.
- `registry/measures.seed.json` → registry_version 2: B15003 substitute recipes
  for `pct_bachelors_plus` and `pop_25_plus` (2016-2020 only).
- `tests/`: jam guard (artifact scan + poisoned-file + hypothesis), clean-step
  property tests, cube structure tests, spot-check harness. 41 pass, 1 skip.
- `build/acs/2016-2020/tract/51.parquet`: 2,198 rows, 27 columns, 268,407 bytes,
  one row group, zstd. sha256 d49b86f0…620d95. Zero jam values.

**Found, differs from spec:**
- There is no `2020/table-based-SF/` (404). 2016-2020 exists in table-based form
  only under `summary_file/2020/prototype/5YRData/`. That is what was used.
- www2.census.gov sends no ETag. The cache compares Last-Modified +
  Content-Length on a HEAD request instead; a rerun reports all 9 files cached.
- Subject tables (S1501) are not in the Summary File. `pct_bachelors_plus` is
  recomputed from B15003_022..025 / B15003_001. Estimates should match S1501;
  the MOEs are approximations and will differ.
- Dollar aggregates are Float64, not Float32: tract aggregates are too large
  for Float32 to store the published integers exactly.
- 2016-2020 tracts are **2020** tract geography (all 2,147 B25065 rows match the
  2020 Gazetteer). Geos file lists 2,198 VA tracts; B25065 has 2,147 rows and
  B19025 2,196. The Geos file defines the rows; tracts missing from a table get nulls.
- Geos20205YR.csv writes `14000US`, data files `1400000US`; GEOID is built from
  STATE+COUNTY+TRACT.

**Open decisions (not taken):**
- `-555555555` MOEs (B01003/B03002 in 51045, 51091, 51720 — single-tract,
  controlled counties) were stripped to null. Census treats them as a zero MOE.
- `mean_gross_rent` divides B25065 (cash-rent units only) by all renter
  households (B25003_003), per the registry/study. Leads to low means
  (e.g. 51067020400: $171).
- Proportion MOEs above 100 points occur for tiny denominators (max 450). Left for Phase 05.
- Zero-owner tracts get agg_home_value 0 with a nonzero MOE from the zero bins
  (the usual Handbook caveat).
- Registry 2006-2010 B25075 `collapse_from: "024"` looks like it puts the
  $750k–999k bin at $1.25M. Check against the 2010 shells at Phase 02. Not touched.
- `.github/workflows/etl.yml` calls modules that don't exist (`check_releases`,
  `build_tiles`) and ends in `git pull --rebase && git push`, which the git
  discipline rules forbid. Not touched.

**Not done, by scope:** harmonizer, tiles, index engine, app, deflator series
(2016-2020 is already in 2020 dollars), manifest, R2 upload. Spec 08 property
tests for the engine and harmonizer (permutation, weights, polarity,
monotonicity, conservation, median refusal, unit guard) wait for those phases.

**Gate status:** zero jam values, checked by test. The 20-value data.census.gov
match is still pending: it needs a person to fill
`tests/fixtures/va_tract_spotcheck.csv` (GEOID,variable,value). Sample printed
with seed 51. No CENSUS_API_KEY on this box; keyless API → 302.

## 2026-09-16 (later) — Phase 01 decisions applied, nothing built

The four open decisions were settled by the project owner, and the spec
deviations were accepted. Specs, registry and tests were updated. No data was
built or fetched; the only download was the 2010 lookup file, read to check
labels.

**Registry → v3** (`registry/measures.seed.json`)
- `jam_values` now lists the five missing-data sentinels. `-555555555` moved to
  `controlled_moe_value`: it becomes an MOE of 0, and raises if it appears in an
  estimate field.
- `agg_gross_rent` denominator → new `cash_rent_renter_households`
  (`B25063_002`, "With cash rent:" in both vintages, which is B25065's
  universe). B25070_001 was rejected because its total includes "Not
  computed". The old definition is kept as legacy variant
  `mean_gross_rent_philly_study` (B25065 / B25003_003), flagged, for the
  Phase 04 replication.
- `agg_home_value`: bins for both vintages are recorded from label text
  (cell, lower, upper, midpoint used). The 2006–2010 labels came from
  `2010/documentation/5_year/user_tools/Sequence_Number_and_Table_Number_Lookup.txt`
  (sha256 a458000b…ef9f00). **The seed's 2006-2010 `collapse_from: "024"` was
  wrong.** 024 is $750,000–$999,999 and the top bin is 025, "$1,000,000 or
  more". The collapse rule is now "lower bound ≥ $1,000,000 → $1,250,000".
  2016–2020 collapses 025–027. The $1.25M midpoint's provenance is unverified;
  confirm against the study at Phase 04.
- B15003 note now describes the RSS + proportion MOE as the Census-documented
  method for derived estimates.

**Code**
- `clean.strip_jams` splits missing from controlled.
- `clean.bin_midpoints` derives the collapse point from the labels and fails if
  the registry's bins or collapse_from disagree.
- Legacy-derived measures are computed.

**Specs**
- 01: two sentinel groups; per-vintage locations (2016–2020 prototype, no
  ETag); cash-rent denominator and legacy variant; bin rule and table; B15003
  method; local build machine.
- 02: new first task, obtaining 2006–2010. It exists only in the
  sequence-based format, and B15003 does not exist in 2010 (B15002 needed).
- 03: Float64 dollar aggregates; one row per geography-file tract, with nulls;
  measured VA size 0.27 MB; laptop builds, Actions becomes a watchdog.
- 08: smoke test reworded.
- READMEs: local build.

**Workflow**
- `.github/workflows/etl.yml` → `etl/etl.workflow.yml.draft` (git mv, with a
  DRAFT header listing its defects). `.github/` removed.

**Tests:** 48 pass, 1 skip (spot-check fixture not filled), **1 fail by design**:
`test_cube_is_current_with_registry`. The local cube was built from registry v2,
so it has null population MOEs in 3 tracts, the old rent denominator, and no
cash-rent or legacy columns. Rebuilding needs the unpublished local
`build/acs/2016-2020/tract/51.parquet` removed (build_cube refuses to
overwrite) and B25063 fetched. Not done: this session was told to build nothing
new. The published cells in the earlier 20-tract sample are unaffected by
these changes and still valid for the spot-check.

## 2026-09-16 (later) — cube rebuilt from registry v3, committed

`git pull --ff-only`: already up to date.

- **Registry** (still v3, notes only): the $1,250,000 top-bin midpoint comes from
  the source Philadelphia study, not from Census. It is a modeling choice for an
  open-ended bin, not a derived value. Pareto interpolation is recorded as the
  rigorous alternative to revisit. Spec 01 says the same. This closes the
  unverified-midpoint item.
- **Rebuild:** deleted the unpublished local
  `build/acs/2016-2020/tract/51.parquet` + `.meta.json` (registry v2). Fetched
  B25063 (the other 9 files came from cache), then rebuilt.
  - 2,198 rows, 31 columns, 302,021 bytes, sha256 1b3b4785…78f10.
  - Population MOEs in 51045050100, 51091970100 and 51720960100 are now 0, so
    pct_nh_white MOEs exist there too.
  - Null counts: population MOE 3 → 0, pct_nh_white MOE 33 → 30. Others unchanged.
  - New columns: cash_rent_renter_households, mean_gross_rent_philly_study.
  - 51067020400 mean gross rent: $691 with the cash-rent denominator, $171 with
    the study's. Across tracts, fixed minus legacy: median +$36, max +$2,188.
- **Tests:** 49 passed, 1 skipped (spot-check fixture not yet filled).
- **Commit:** one commit with everything from today's three entries (ETL,
  registry v3, specs, tests, workflow move). build/ and data/ stay gitignored
  and local; nothing was uploaded to R2.
- **Gate:** still pending the manual data.census.gov spot-check. B25063_002E is
  now also checkable (e.g. 51067020400 = 129).

## 2026-11-12 — Phase 01 gate passed

`git pull --ff-only`: already up to date.

- No CENSUS_API_KEY on this box (keyless api.census.gov → 302 "Missing Key").
  data.census.gov's own table endpoint (`/api/access/data/table?id=ACSDT5Y2020.<table>&g=1400000US<geoid>`)
  is keyless and serves the published tables. Validation only, per spec 01.
- New `etl/spotcheck.py`: seeded (51) sample of 20 (tract, variable) pairs over
  the variables `tests/test_spotcheck.py` knows, fetched from that endpoint,
  written once to `tests/fixtures/va_tract_spotcheck.csv` (refuses to overwrite).
  Retries with backoff: one call came back as non-JSON (throttled) on the first try.
- **20/20 match exactly**, including 4 S1501 percentages recomputed from B15003.
  No suppressed values happened to be drawn.
- **Deviation:** the fixture was supposed to be hand-copied. It was fetched by
  script from the same published tables. Recorded in fixtures README and spec 08.
- Tests: 69 passed, 0 skipped.
- Ledger: v0.2 gate passed. v0.3 in progress. Directive → Phase 02 first task
  (2006–2010 loader). Nothing uploaded; R2 still blocked.
