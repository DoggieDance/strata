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

## 2026-11-12 (later) — Phase 02 first task: 2006–2010 loader, gate passed

`git pull --ff-only`: already up to date.

- **Registry v4.** `summary_files.json` gains `2006-2010` (format `sequence`,
  per-state URL templates, lookup file pinned by sha256, geography-file column
  positions, missing tokens). `measures.seed.json`: 2006–2010 B15002 recipes for
  `pct_bachelors_plus` and `pop_25_plus`.
- **Code.** New `etl/sequence_file.py`. `clean`, `fetch_summary_file`,
  `build_cube` dispatch on the vintage format. Scope lock widened to
  2006-2010 (Virginia, tract only).
- **Data.** Fetched lookup + 7 sequence zips + `g20105va.csv` (~11 MB, local only).
  Built `build/acs/2006-2010/tract/51.parquet`: 1,907 rows, 31 columns, same
  columns as 2016–2020. Rebuilt 2016–2020 under v4: data identical to the v3 build.
- **Missing values.** No negative sentinels in the 2010 sequences. `.` = zero
  universe (data.census.gov: -666666666), blank = table not published (204).
  Both → null. Unknown tokens raise.
- **Gate:** 20/20 random 2006–2010 values match data.census.gov. Also checked:
  4 missing-value cases, and 3 tracts' recomputed bachelor's+ against the 2010
  S1501 (C01_015 in that layout). VA population sums to 7,841,754.
- `etl/spotcheck.py` now takes `--vintage`. Fixed: suppressed values come back
  as a jam in the value field with the symbol in the annotation; the symbol is
  now recorded. 204 = not published, confirmed by a second request.
- Tests: 124 passed.
- Not done: deflators (registry/deflators.json still empty — needed when
  vintages meet), crosswalk. Nothing uploaded.

## 2026-11-12 (later) — local preview (owner request), pushed Phase 01/02 commits

Owner asked to see STRATA running on their machine; it is not a GitHub Pages
site. Interface work, outside the Phase 02 directive by explicit request.
Labeled a preview, not Phase 03 — that phase's gate (R2 byte ranges, PMTiles)
is untouched.

- Pushed dc48768 and 0fbf618 to origin/main (fast-forward).
- `registry/geometry.json` + `etl/build_geometry.py`: 1:500k Cartographic
  Boundary tracts → `build/geo/{vintage}/tract/51.geojson`, GEOID only.
  2020: 2,186 polygons (12 cube tracts, all 99xxxx water tracts, have none).
  2010: 1,905 (2 water tracts). Any polygon not in the cube raises.
- `app/` (index.html, app.js, style.css): MapLibre + hyparquet, feature-state
  join, quintiles, spec 05 hatching, spec 07 tokens and type, both themes,
  phone layout. `./preview.sh` builds what is missing and serves it.
- Checked in headless Chromium: light/dark, both vintages, inspector, 390 px.
  Recolor 8–89 ms on 2,186 tracts. First ramp step was nearly the paper color
  and indistinguishable from no-data; darkened, and no-data got its own gray.
- Tests: unchanged (no app tests yet; visual regression is spec 08 Phase 03 work).

## 2026-11-12 (later) — preview accessibility pass (WCAG 2.2 AA)

Owner request: make the preview accessible without losing the palette.
- Before: axe-core flagged text contrast (`--ink-3` both themes, `--warn` light).
  By hand: tract values were mouse-only, the vintage toggle was not a real radio
  group, and the dark-theme high class (#6B3311) sat at 1.9:1 on the ground.
- Tokens: lightness-only shifts (spec 07 updated): ink-3 #6A5C4B / #9A8870,
  warn #815512 (light), new `--control` borders at 3:1. Dark ramp reversed in
  lightness (dim → bright, 2.2:1 → 12:1).
- Table view with search, sort and "Show on map"; skip link to it; tract names
  (`build/geo/{v}/tract/51.names.json`, kept out of the GEOID-only geometry);
  native radios; labels; aria-live inspector; reduced motion; 24 px targets;
  selection outline in accent on a paper casing.
- Reliability tier now uses the CV as displayed (one decimal), so 12.0% is Medium.
- Verified: axe-core 4.10, WCAG 2.0/2.1/2.2 A+AA + best practice: 0 violations,
  both themes, map and table views. Scripted keyboard-only run: skip link →
  search → Show on map → canvas focus + inspector → arrow-key vintage change.
  Not done: a human screen-reader pass.

## 2026-11-12 (later) — published county, place and ZCTA levels (v0.2.1)

Owner asked for counties and cities, with ZIP codes as an option.
- Census publishes all three directly in the same Summary File, so the cubes
  hold Census's own estimates and margins, not sums of tracts. A test confirms
  that controlled counts (population, households) sum exactly from tracts to
  counties. Dollar aggregates differ by up to 0.17%: separate estimates.
- Registry: per-vintage `levels` (sumlevel, GEO_ID prefix, GEOID parts); 2010
  non-tract rows come from the second archive (`all_geographies/` locally);
  `zcta_state` rule (largest land share, 2020 relationship file).
- 2006–2010 has **no ZCTA rows** anywhere in the Summary File (checked state
  and national geo files). `LevelUnavailable` is raised; fetch/build/geometry skip it.
- Cubes: VA 2016–20 county 133, place 672, zcta 883; 2006–10 county 134
  (Bedford city), place 591. Every row has a polygon.
- Spot-check: 20 per new (vintage, level) = 100 values, all match.
  **Bug found and fixed:** data.census.gov answers 204 when throttling, even
  twice running, so 4 fixture values were wrongly recorded as "not published".
  The cube was right every time. Now 5 × 204 over ~2 min are required. The
  committed tract fixtures had no such blanks. `*****` (controlled MOE) now
  checks for 0.
- Preview: Geography selector; unavailable combinations disabled with a reason;
  stale-hover race on level switch fixed; ZIP names fixed. axe: 0 violations.
- Tests: 276 passed.
- Ledger v0.2.1 entered after the build; the rule says before. Noted there.

## 2026-11-12 (later) — milestone review, fixes before push

An independent review of origin/main..HEAD (3 commits) before pushing:
1. **ZCTAs were on the wrong definitions.** The 2016–20 ACS tabulates 2010 ZCTAs
   (33,120 rows = the 2010 count), but state assignment and polygons used 2020
   files. Effect: 13 VA ZCTAs with data were dropped (e.g. 23806, Virginia State
   University), and some 2010-defined estimates sat on redrawn 2020 shapes. Fixed:
   `zcta_county_rel_10.txt` (assignment by 2010 population share, land if none)
   and `cb_2019_us_zcta510_500k` (2010 definitions). VA ZCTAs: 883 → 896, all
   with polygons. The ZCTA spot-check fixture stays valid: same rows, same values.
2. **App reload race** (fast second switch could flash "Error"): reload() now
   drops a stale load.
3. **Tests that could not fail:** level membership is now checked against raw
   .dat rows (tests/test_levels.py), not the geography code path that built the
   cube; `built_combos` lists every published (vintage, level) so a missing cube
   is skipped visibly; the county-sum test runs per vintage; the ZCTA rule has a
   unit test.
4. Not changed: tier() calls estimate 0 with MOE 0 "High" (CV undefined). No
   such rows exist; an exact zero is reliable.
Tests: 276 passed. Browser: all levels load; axe 0 violations.

## 2026-11-12 (later) — crosswalk + harmonizer (Phase 02, conservation half)

- Pushed f980448 (levels + review fixes). Milestones page published
  (https://claude.ai/artifact/4neVSE1MouULa94ajXJNGn).
- `etl/crosswalk.py` + `registry/crosswalk.json`: 2020-block-population
  crosswalk, VA 2010→2020 tracts. All 8,631,393 people conserved (7.6 in
  foreign 2010 blocks, reported). Pair land = Census tract relationship file exactly.
- Registry v5: `bachelors_plus` and `nh_white` counts stored, plus
  `count_numerator`/`count_denominator` on the percent measures. All 7 cubes
  rebuilt; every v4 column is byte-identical.
- `etl/harmonize.py`: extensive columns apportioned (MOE: RSS of weighted MOEs,
  documented as an approximation); intensive recomputed; medians refused; a null
  piece nulls the target instead of undercounting. 6 2020 tracts get no data
  (water, or tracts nothing maps into).
- Tests: tests/test_harmonize.py (weights, coverage, conservation, land vs
  Census, county identity, recomputed percents, synthetic formula, null rule,
  median refusal). 291 passed.
- Preview: "Show on 2020 tract lines" for 2006–10 tracts. Fixed: the check row
  ignored [hidden]. Browser: toggle works; rapid level switching no longer flashes
  "Error"; axe 0 violations.
- Open question recorded in spec 02: 2010 vs 2020 block population as weights.

## 2026-11-12 (later) — review of cac3bfd; deflators; manifest; change engine

Review findings, fixed before push:
1. **Zero-universe pieces blanked targets.** A null aggregate whose source
   universe is 0 now counts as 0. Harmonized null income 59 → 12, rent 138 → 80.
   Regression tests for the synthetic case and the reviewed tracts (51059482505, 51810044004).
2. Weak tests: new independent identity test (986 one-to-one tracts equal their
   source in every column); land test now requires real overlap and full Census
   source coverage; circular tests relabeled for what they show.
3. pct_nh_white is recomputed over B03002_001 (`race_universe`, registry v6),
   matching the cube. All cubes rebuilt: earlier columns identical.
4. Empty 2020 water targets null rather than 0: documented.
Also:
- **Deflators**: R-CPI-U-RS annual 2004–2025 in registry/deflators.json (BLS 403s
  scripted requests; fetched via a web-fetch tool, sha256 recorded).
  2010→2020 = 1.1906; the study used 1.187 (0.3% gap, to explain at Phase 04).
  `etl/deflate.py` + tests.
- **2010 vs 2020 weights** compared for VA: immaterial (spec 02).
- **Manifest**: `etl/write_manifest.py` + `registry/presentation.json` →
  build/manifest.json (inventory, labels, deflators, valid comparisons,
  significance and reliability thresholds). The app does not read it yet.
- **Change engine**: `app/engine/change.js` (spec 05 Z-test with deflation;
  "no measurable change" state), node tests run under pytest (tests/test_js.py).
Tests: 307 passed.
