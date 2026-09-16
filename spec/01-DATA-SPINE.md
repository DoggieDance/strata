# 01 — Data Spine

## Decision: bulk files, not the API

The Census Data API is the wrong door for this application.

- **Keys are mandatory.** As of mid-2026 every data call requires one; the old
  500-anonymous-queries-per-day allowance is gone. A key embedded in a static
  page is a key anyone can take.
- **50 variables per call.** Bypassable with `group(TABLE)`, but still a
  per-request ceiling to engineer around.
- **Tracts cannot be pulled nationwide.** `for=tract:*` requires `in=state:XX`.
  That is 52 calls per table per vintage, every refresh.
- **Release slippage is real.** The 2025 government shutdown pushed a release by
  months. Nothing should schedule against assumed dates.

The **ACS Summary File** has none of these problems. Since the 2021 restructuring
to a table-based format, it ships one flat file per table containing every
geography Census publishes, keyless.

```
https://www2.census.gov/programs-surveys/acs/summary_file/{year}/table-based-SF/
  data/5YRData/acsdt5y{year}-{table}.dat      one table, all geographies
  documentation/  Table shells, geography labels
```

### Where each vintage actually lives

The template above holds from the 2021 release onward. Earlier vintages differ,
and `registry/summary_files.json` records the real location per vintage.

- **2016–2020.** There is no `2020/table-based-SF/` (404). The table-based
  files exist only as a Census **prototype**:
  `summary_file/2020/prototype/5YRData/acsdt5y2020-{table}.dat`, with
  `Geos20205YR.csv` and `ACS2020_Table_Shells.csv` beside it. Accepted as the
  2016–2020 source at Phase 01. It carries detailed tables only.
- **2006–2010.** Sequence-based format only. See `02-HARMONIZER.md`.

`www2.census.gov` sends no `ETag` for these files. The fetcher caches on
`Last-Modified` + `Content-Length` and uses an ETag only when one is served.

**The API is retained for one purpose only:** spot-check validation of the bulk
extract during Phase 01. It is never called by the application.

> **Operational constraint.** `census.gov` is blocked by the Cowork session's
> egress policy. The ETL cannot run from a chat session. It runs on the local
> build machine (the laptop), which downloads, computes and pushes artifacts
> out. There is no CI build pipeline. The old Actions file is parked at
> `etl/etl.workflow.yml.draft`; the real workflow is written at Phase 03 as a
> watchdog, not a pipeline.

## Jam values

ACS encodes special cases as large negative sentinels. Any one of these reaching
arithmetic silently corrupts an index. They fall into two groups, and they are
handled differently.

**Missing data — become null.**

| Value | Meaning |
|---|---|
| `-666666666` | Estimate could not be computed — insufficient sample |
| `-999999999` | Insufficient sample cases for this geography |
| `-888888888` | Not applicable |
| `-222222222` | MOE could not be computed — insufficient sample |
| `-333333333` | MOE not computable — median in an open-ended interval |

**Controlled estimate — becomes an MOE of zero.**

| Value | Meaning |
|---|---|
| `-555555555` | The estimate is controlled to an independent total and has no sampling error |

`-555555555` is not missing data. The estimate beside it is published and
exact, so its MOE is 0, and 0 propagates correctly through every derived-MOE
formula; null would wrongly void the MOE of anything built on it. Example:
total population in single-tract counties (51045, 51091, 51720 in 2016–2020).
It is only valid in an MOE field. In an estimate field the loader raises.

The registry carries the two groups separately (`jam_values`,
`controlled_moe_value`). Any other value below `-1e8` is an undocumented
sentinel and the loader raises.

**Test:** no value below `-1e8`, and none of the six sentinels, may exist
anywhere in a built cube. Hard fail.

## Inflation adjustment

Census adjusts dollar-denominated variables with **R-CPI-U-RS** (BLS Consumer
Price Index Research Series). Factors are stored in `registry/deflators.json`
with their source and retrieval date, never computed inline.

```
adjusted = raw × (CPI_target / CPI_source)
```

The Philadelphia study used 1.187 for 2010→2020. That value is a fixture, not a
constant — the registry carries the series.

## Measure registry

`registry/measures.seed.json` defines each measure as a recipe, not a variable ID.

```jsonc
{
  "id": "agg_household_income",
  "label": "Aggregate household income",
  "kind": "aggregate",              // aggregate | percent | ratio | derived
  "dollars": true,                  // subject to deflation
  "sources": { "2020": { "table": "B19025", "cells": ["001"] } },
  "denominator": "households",
  "notes": "Divide by weighted households for a per-household mean."
}
```

**Per-vintage sources are mandatory.** Table definitions drift: the B25075 home
value bins differ between the 2010 and 2020 vintages, and the dollar-adjustment
methodology for the value tables changed with the 2022 data. One global schema
would encode a lie.

## Seed measures

From the Philadelphia study's Table 1, which already solved the hard parts.

| Measure | Source | Notes |
|---|---|---|
| Aggregate household income | `B19025_001E` | Deflate |
| Aggregate gross rent | `B25065_001E` | Denominator `B25063_002E` (see below) |
| Aggregate home value | `B25075_002E`–`_025E` (2010), `_002E`–`_027E` (2020) | Bin midpoints; collapse point set from label text (see below) |
| Bachelor's degree or higher | `S1501_C02_015E` | Subject table, not in the Summary File; recomputed from `B15003` (see below) |
| Non-Hispanic white share | `B03002_003E / B03002_001E` | Near-zero baselines explode in percent change |
| Population 25+ | `S1501_C01_006E` | Education denominator; `B15003_001E` in the Summary File (same universe) |
| Total population | `B01003_001E` | General denominator, apportionment fallback |

### Mean gross rent — the denominator

`B25065`'s universe is *renter-occupied housing units paying cash rent*, in both
2006–2010 and 2016–2020 (read from the table shells). The denominator must be the
same universe: **`B25063_002E` "With cash rent:"**. `B25003_003E` (all renter
units) includes no-cash-rent units and biases the mean low; in one Virginia tract
it gave $171/month. `B25070_001E` is also wrong: its total includes a "Not
computed" line.

The study's definition is kept in the registry as a flagged legacy variant,
`mean_gross_rent_philly_study` (`B25065 / B25003_003`), so the Phase 04
replication can reproduce the study and quantify the difference. It is not for
new indices.

### Aggregate home value — bins

Bin boundaries are read from each vintage's own labels and recorded in the
registry with the midpoint used. The collapse point is found from the label
text, not by cell number: every bin with a lower bound ≥ $1,000,000 gets the top
midpoint, $1,250,000. Other bins take (lower + upper + 1) / 2; "Less than
$10,000" takes $5,000.

| Vintage | Top bins as published | Collapsed |
|---|---|---|
| 2006–2010 | `025` $1,000,000 or more | `025` |
| 2016–2020 | `025` $1M–1.5M, `026` $1.5M–2M, `027` $2M or more | `025`–`027` |

The seed registry said `024` for 2006–2010. That bin is $750,000–$999,999, so
the error would have valued it at $1.25M. Fixed in registry v3. The build
re-parses the labels and fails if they disagree with the registry.

$1,250,000 comes from the source Philadelphia study, not from Census. It is a
modeling choice for an open-ended bin, not a derived value: an open-ended bin
has no true midpoint, and collapsing 2020's upper bins understates tracts with
many $1.5M+ homes. **Revisit later:** Pareto interpolation over the upper bins
is the rigorous alternative.

### Bachelor's degree or higher — the B15003 recomputation

Subject tables are not in the Summary File. `pct_bachelors_plus` is recomputed as
`(B15003_022 + _023 + _024 + _025) / B15003_001`: bachelor's, master's,
professional and doctorate over population 25+, which is how S1501_C02_015 is
defined. The numerator MOE is the root-sum-square of the component MOEs, and
the percent MOE uses the proportion formula. That is the Census-documented
method for derived estimates (ACS Handbook, *Calculating Measures of Error for
Derived Estimates*), not an ad hoc approximation. Estimates should agree with
S1501 to its published decimal. Census computes S1501's own MOE directly, so the
two MOEs may differ slightly; the spot-check compares estimates only.

Next additions, in order of usefulness: vacancy rate, tenure, gross rent as a
share of income, median year structure built, commute mode, limited English.
