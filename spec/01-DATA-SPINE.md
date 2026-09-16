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

**The API is retained for one purpose only:** spot-check validation of the bulk
extract during Phase 01. It is never called by the application.

> **Operational constraint.** `census.gov` is blocked by the Cowork session's
> egress policy. The ETL cannot run from a chat session. It runs on GitHub
> Actions or on a local machine. This is also the correct design regardless.

## Jam values

ACS encodes non-answers as large negative sentinels. Any one of these reaching
arithmetic silently corrupts an index. The loader raises on all of them.

| Value | Meaning |
|---|---|
| `-666666666` | Estimate could not be computed — insufficient sample |
| `-999999999` | Insufficient sample cases for this geography |
| `-888888888` | Not applicable |
| `-222222222` | MOE could not be computed — insufficient sample |
| `-333333333` | MOE not computable — median in an open-ended interval |
| `-555555555` | MOE not appropriate — estimate is controlled to a population total |

**Test:** no value below `-1e8` may exist anywhere in a built cube. Hard fail.

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
| Aggregate gross rent | `B25065_001E` | Denominator `B25003_003E` |
| Aggregate home value | `B25075_002E`–`_025E` | Bin midpoints; collapse top bins across vintages, document the midpoint used |
| Bachelor's degree or higher | `S1501_C02_015E` | Subject table — separate file |
| Non-Hispanic white share | `B03002_003E / B03002_001E` | Near-zero baselines explode in percent change |
| Population 25+ | `S1501_C01_006E` | Education denominator |
| Total population | `B01003_001E` | General denominator, apportionment fallback |

Next additions, in order of usefulness: vacancy rate, tenure, gross rent as a
share of income, median year structure built, commute mode, limited English.
