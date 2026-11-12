# 02 — The Harmonizer

## The problem

Census tract boundaries were redrawn between 2010 and 2020. Comparing a 2010
5-year estimate to a 2020 one at tract level is comparing different polygons
wearing similar names.

The Philadelphia study solved this by aggregating both vintages up to stable
neighborhood boundaries using **area weighting** — each tract contributed in
proportion to the share of its polygon inside the neighborhood. The study
correctly flagged the assumption: values are uniformly distributed within a
tract. They are not. A tract that is half industrial park and half dense
apartments gives the industrial half credit for people who do not live there.

## First task: obtaining 2006–2010

**Resolve this before any crosswalk work.** Nothing below matters until the
2010 side of the comparison can be loaded.

The 2006–2010 5-year vintage predates the table-based Summary File. It is
published only in the old **sequence-based** format:

```
https://www2.census.gov/programs-surveys/acs/summary_file/2010/
  data/5_year_by_state/ …                 per-state archives
  data/5_year_seq_by_state/ …             per-state, per-sequence files
  data/2010_5yr_SummaryFileTemplates.zip  column headers per sequence
  documentation/5_year/user_tools/Sequence_Number_and_Table_Number_Lookup.txt
```

A table is not a file there. Its cells are spread across a numbered sequence
file (e.g. B25075 is sequence 99, B25063 and B25065 are sequence 98), with
estimates and MOEs in separate `e`/`m` files. Rows are keyed by `LOGRECNO`,
joined to GEOID through a separate geography file, and tract and block-group
rows live in a separate archive (`Virginia_Tracts_Block_Groups_Only.zip`
vs `Virginia_All_Geographies_Not_Tracts_Block_Groups.zip`). There is no 2010 table-based prototype;
`summary_file/2010/` has only `data/` and `documentation/`.

The task is to decide and document:

1. **Source.** Sequence-based Summary File, or another keyless static source,
   with the reason. The Census API is not a build source (spec 01).
2. **Loader.** A 2006–2010 reader that produces the same per-table frame the
   2016–2020 loader does (GEOID index, `E###` / `M###` columns), so `clean.py`
   stays vintage-agnostic.
3. **Subject tables.** S1501 is not in the 2010 Summary File either. The
   2006–2010 `pct_bachelors_plus` needs its own detailed-table recipe.
   **B15003 does not exist in the 2010 lookup file**; the recipe must use
   B15002 (sex by educational attainment, population 25+, sequence 40), summing
   the bachelor's-and-above cells for both sexes. `pop_25_plus` likewise
   becomes `B15002_001`.
4. **Registry.** A `2006-2010` entry in `registry/summary_files.json`.
   Already verified from the 2010 lookup file: B25075 bins (registry v3),
   B25063_002 "With cash rent:", B25065's cash-rent universe.

Gate for this task: 20 Virginia 2006–2010 tract values match data.census.gov,
and the jam guard passes, exactly as for Phase 01.

### Decided and passed — 2026-11-12

1. **Source:** the sequence-based Summary File, per-state per-sequence zips under
   `5_year_seq_by_state/Virginia/Tracts_Block_Groups_Only/`, plus `g20105va.csv`.
   Only the 7 sequences the registry needs are fetched (~11 MB), not the state archive.
   The lookup file is pinned by sha256 in `registry/summary_files.json`; the
   fetcher refuses a lookup file that differs, because every cell position comes from it.
2. **Loader:** `etl/sequence_file.py`. Field of table line *n* =
   Start Position + *n* − 1 (1-based, counting the 6 header fields). Rows join
   to GEOID through LOGRECNO; the geography file's own GEOID is checked against
   STATE+COUNTY+TRACT. Output matches the `.dat` loader's frame.
3. **Missing values.** No negative jam sentinels appear in these sequences.
   Missing cells are `.` (not computable — for tract aggregates, a zero
   universe; data.census.gov publishes `-666666666`) or blank (table not
   published for the tract; data.census.gov returns 204). Both become null.
   Any other non-numeric token raises. 39 tracts lack B19025, 102 lack B25065.
4. **Education:** `B15002_015:018 + _032:035` over `B15002_001`. Matches the
   2010 S1501 (where the percent is `C01_015`, not `C02_015`) to its decimal.
5. **Registry v4.** Rebuilding 2016–2020 under v4 produced identical data.

**Gate:** 20/20 random values match (`tests/fixtures/va_tract_spotcheck_2006-2010.csv`),
both missing-value cases match, jam guard passes. 1,907 tracts, 2010 geography.

## The decision: population weighting

Apportion using **2020 decennial census block population** as the weight rather
than polygon area. Blocks are small enough that the uniformity assumption
becomes tolerable, and their counts are a complete enumeration, not a sample.

```
weight(source_tract → target) = Σ block_pop(blocks ∩ source ∩ target)
                              / Σ block_pop(blocks ∩ source)
```

Free inputs, no license encumbrance:

- 2020 decennial block population (P1 table)
- Census tract relationship files, 2010 ↔ 2020
- TIGER/Line block geometry, per state

**IPUMS NHGIS is deliberately excluded.** It provides exactly this, pre-built and
better, but its terms prohibit redistribution and a public web app is not covered
by the academic exception. STRATA builds its own.

### Built — Virginia, 2026-11-12

`etl/crosswalk.py` builds `build/crosswalk/2010-2020/tract/51.parquet`.
`etl/harmonize.py` uses it to put 2006–10 values on 2020 tracts
(`build/harmonized/2006-2010/tract-2020/51.parquet`).

- **Inputs:** 322,610 block intersections (Census 2010–2020 block relationship
  file) and 163,491 2020 block counts (PL 94-171 P1_001).
- **Conservation:** all 8,631,393 people in Virginia's 2020 blocks are assigned.
  7.6 of them sit in 2010 blocks belonging to other states (boundary
  corrections) and are reported, not dropped.
- **Coverage and basis:** 2,943 tract pairs. All 1,907 2010 tracts are sources:
  1,890 population-weighted, 7 land-weighted (no 2020 residents), 10 even
  (pure water).
- **Cross-check:** pair land areas equal Census's 2020–2010 tract relationship
  file exactly. Census lists 477 more land-overlap pairs that hold nobody.
- **Population vs area weights:** they differ by more than 0.2 in 173 of 2,929
  pairs. That is the whole case for population weighting, concentrated where
  it should be.
- **Harmonized 2006–10:** counts are conserved statewide to Float32 precision.
  County totals change only by the 4,184 people whose tracts cross a 2010→2020
  county line (boundary corrections; Bedford city's merger counted as same-county).
  Percents and means are recomputed from apportioned counts. Registry v5 stores
  the numerators (`bachelors_plus`, `nh_white`) so they can be.

- **Zero universes.** An aggregate published as "not computable" because its
  universe is empty (0 households, 0 cash renters) counts as zero when
  apportioned. Treating it as unknown blanked 47 populated targets' income and
  58 targets' rent through weights as small as 0.00001 (caught in review).
  Only a source with a real but small universe and a suppressed value still
  nulls a target. Six 2020 tracts receive no flow at all and stay null.

**Weights: 2010 vs 2020 population (checked for Virginia).** Splitting 2010
data by *2010* block population instead (2010 PL file, 285,762 blocks,
8,001,024 people conserved) moves 53 of 1,752 split pairs by more than 0.1. It
changes harmonized 2010 mean income by more than 5% in only 3 of 2,159 tracts,
so the 2020 weights stand. Rerun the comparison for Philadelphia, where the
decade changed more.

**Open question, not yet decided.** The spec weights 2010 data by *2020*
population. People who arrived after 2010 (new subdivisions) therefore pull
2010 values toward places that were empty in 2010. Splitting 2010 tracts by
*2010* block population (2010 PL file) would follow where people lived in the
source year. Worth comparing before the Philadelphia replication, where it
could explain part of the deviation.

**Still owed for the gate:** the Philadelphia replication (needs Pennsylvania in
scope), and agreement with HUD's ratios (needs an API token) and a Geocorr extract.

## The structural insight

**Temporal harmonization and spatial aggregation are the same operation.**

| Job | Source geometry | Target geometry |
|---|---|---|
| Compare 2010 to 2020 | 2010 tracts | 2020 tracts |
| The Philadelphia study | 2020 tracts | 158 neighborhoods |
| User-uploaded boundaries | 2020 tracts | whatever they drew |

One engine, three products. Custom geography support is a consequence of
building the crosswalk correctly, not a separate feature.

## Extensive vs. intensive

The apportionment rule depends on what the measure is.

- **Extensive** (counts, aggregates — population, aggregate income): distribute
  by weight, then sum into the target.
- **Intensive** (rates, medians, percentages): cannot be summed. Reconstruct from
  apportioned numerator and denominator. A median cannot be apportioned at all —
  it is recomputed from bins, or it is refused.

**The engine refuses to apportion a median.** Silently averaging medians is one
of the most common errors in applied demography and it will not be possible here.

## Free shortcuts — validate against these before writing the engine

Two pre-built crosswalks exist with terms that permit use in a public app. Neither
replaces the engine, but both collapse the risk of building it blind.

**HUD–USPS Census Tract Crosswalk.** Ships 2010↔2020 tract pairs with
`RES_RATIO` / `BUS_RATIO` / `OTH_RATIO` / `TOT_RATIO` allocation weights, updated
quarterly. Free registration, documented API. HUD's dataset page states *"No
special restrictions or limitations on using the item's content have been
provided"*; the API terms require an attribution notice and nothing more.

The weights are **address counts, not population** — a proxy, and a decent one for
housing measures, weaker for person-level measures like educational attainment.

**Geocorr (MABLE/Geocorr, Missouri Census Data Center).** Generates custom
correspondence files between arbitrary vintages with population and household
weights derived from block data. Form-driven, not an API. No terms of use are
published, which is permissive by silence rather than by grant — usable, credited,
but not iron-clad.

**How STRATA uses them:** as the reference answer. Build the block-weighted
crosswalk, then check it against HUD's ratios and a Geocorr extract. Agreement
across three independently derived weightings is far stronger evidence than a
conservation test alone. Disagreement localizes the bug.

**What is still not available:** IPUMS NHGIS publishes exactly the crosswalk this
project wants — 2010↔2020 tract-to-tract with population, household, and housing
weights — and its terms prohibit redistribution without written permission, with
no carve-out for crosswalk files. Esri's Living Atlas demographics carry a
named-user restriction and an explicit anti-scraping clause. Both are closed.

## Gate

1. **Conservation.** For every source geography, the sum of apportioned
   population across all targets equals its source population within rounding.
2. **Replication.** Philadelphia 2010 tract data apportioned onto 2020 tracts,
   then onto the OpenDataPhilly neighborhood boundaries, reproduces the study's
   neighborhood-level 2010 values within a documented tolerance.

Failure of either gate halts Phase 02. There is no partial pass.

## Replication results (2026-11-12, Table 3 half)

`analysis/philly_table3.py`, tested by `tests/test_philly_replication.py`. The
study's method, reproduced as written: each vintage's own tracts area-weighted
onto the OpenDataPhilly neighborhoods, dollars × 1.187, percent change per
neighborhood.

- **Area weighting meant counts, not rates.** Apportioning counts and dollar
  totals by area share and then dividing reproduces the study; area-averaging
  tract rates does not (15/25 vs 20/25 top-five hits before the income fix).
- **Rent, home value, non-Hispanic white: reproduced.** Every study entry in
  the same rank, within 1 point (Glenwood nh_white 1,049.5% vs 1,053.5%, 0.4%
  relative).
- **Income: reproduced once the study's denominator is used.** The study divided
  aggregate household income (B19025, all households) by owner-occupied
  households (B25003_002). With that, all five within 0.8 points, same order.
  With all households, Roxborough Park is 60%, not 139%. This is an error in the
  study, like the renter-household rent denominator; STRATA's
  `mean_household_income` stays correct and the replication uses the study's.
- **Bachelor's or higher: not reproduced.** STRATA puts McGuire at 126%; the
  study at 1,969%. Counting only men's degrees in 2010 (B15002_015:018)
  reproduces the study's top-five set and McGuire's exact value (male/male 25+
  both years: 1,969.0%), but no numerator/denominator combination matches all
  five. Needs the study's worksheet; the test is a strict xfail until then.
- **158 vs 159 resolved.** The boundary file has 159 polygons; Airport has no
  estimates (no residents), so 158 neighborhoods carry values. Both the charter
  and the index spec were right.

Still owed for the gate: the 159-neighborhood z-score fixture (Figure 5 values)
and STRATA-method results beside the study's.
