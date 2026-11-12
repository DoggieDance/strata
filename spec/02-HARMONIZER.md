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
