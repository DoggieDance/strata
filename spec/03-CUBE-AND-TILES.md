# 03 — Cube, Tiles, and Hosting

## Storage shape

Two artifacts, joined in the browser by `GEOID`.

### The cube — attributes

One wide Parquet file per state per vintage per geography level.

```
acs/{vintage}/{level}/{state_fips}.parquet
```

- Rows: `GEOID`, sorted, so row groups align to counties. **One row per
  geography the vintage's geography file lists** (for 2016–2020 Virginia,
  `Geos20205YR.csv`: 2,198 tracts). Tables do not all carry every row (B25065
  has 2,147, B19025 2,196). A tract missing from a table gets nulls for that
  table's measures; it is never dropped. The row set is identical across every
  measure in a file.
- Columns: one `{measure}_e` and one `{measure}_m` per measure. Float32, except
  **dollar aggregates, which are Float64.** Tract aggregates reach 1e9–1e10
  dollars, where Float32 cannot hold the published integer exactly (spacing is
  32 at 3e8 and 1,024 at 1e10), and the Phase 01 gate requires exact matches.
  Means, percents and counts stay Float32; counts are checked against Float32's
  exact-integer range (2^24) at build time. Missing values are Parquet nulls,
  never NaN.
- Row group size ~8,000 rows. Compression zstd.

### Geography levels

Added 2026-11-12 at the owner's request. Each level is Census's **published**
estimate for that geography, read from the same Summary File, never a sum of
tracts. Published values carry Census's own margins of error; summed tracts do
not reproduce them. Population and households (controlled totals) sum exactly
from tracts to counties, which is tested. Dollar aggregates differ by up to 0.17%.

| Level | Summary level | Virginia 2016–20 | 2006–10 | Note |
|---|---|---|---|---|
| `tract` | 140 | 2,198 | 1,907 | 2020 vs 2010 tract geography |
| `county` | 050 | 133 | 134 | Includes the 38 independent cities. Bedford city (51515) exists only in 2010 |
| `place` | 160 | 672 | 591 | Incorporated places + CDPs; does not cover the state |
| `zcta` | 860 | 896 | — | **2010 ZCTA definitions**: the 2016–20 ACS still tabulates them (2020 ZCTAs start with 2018–22). National rows, assigned to the state with most of their 2010 population. None published for 2006–10 |

Every level gets the same 20-value data.census.gov spot-check as tracts.

**Comparing years across boundary changes** (tracts redrawn, ZCTAs redefined,
Bedford city merged, places annexing land) is the harmonizer's job (spec 02),
not the level's. Level maps show one vintage at a time.

**Candidate levels, roughly in order of usefulness:** congressional districts
(500), state legislative districts (610/620), school districts (950–970),
county subdivisions (060: townships/magisterial districts), metro and
micropolitan areas (310), PUMAs (795), block groups (150; finer than tracts,
high margins). User-drawn and city-specific neighborhoods (Philadelphia first)
come through the harmonizer as custom targets, since there is no national
neighborhood standard.

Parquet is columnar, so an index naming five measures fetches ten columns, not
the whole file. Read with **hyparquet** (~10 KB) using HTTP range requests.

**Projected size** (to be measured at Phase 01, not assumed):

| Scope | Rows | Est. compressed |
|---|---|---|
| Virginia, tracts, one vintage | 2,198 | ~0.4 MB — **measured 0.27 MB** (Phase 01, 26 value columns) |
| National, tracts, one vintage | ~85,000 | ~15–25 MB |
| National, block groups | ~240,000 | ~45–70 MB |

### The tileset — geometry

A single PMTiles archive per geography level, carrying **only `GEOID`**.

Attributes are deliberately not baked in: a user moving a weight slider changes
every value on the map, and rebuilding tiles is not an option. Values arrive via
`setFeatureState` at runtime.

Build from Cartographic Boundary files at 1:500,000 — `cb_{year}_us_tract_500k.zip`
— using `felt/tippecanoe` (2.0.x) or `ogr2ogr -f PMTiles` (GDAL ≥ 3.8).

```
tippecanoe -zg --drop-densest-as-needed -y GEOID \
  -o tract_2020.pmtiles tract_2020.geojson
```

**Projected size:** Virginia ~4 MB, national ~60–120 MB. Measure at Phase 03.

## Why DuckDB-WASM is not the default

It is the obvious choice and it is wrong here. The WASM payload is roughly 33 MB
with a cold start near 600 ms, there are documented byte-range regressions in
Safari and Firefox, and the entire workload is a projection and a weighted sum —
not arbitrary SQL.

hyparquet does the column reads at ~10 KB. A DuckDB-WASM SQL console is a
reasonable **power-user feature for a later phase**, loaded on demand. It is not
the default path.

## Hosting

| Layer | Host | Free allowance | Projected | Headroom |
|---|---|---|---|---|
| App shell | GitHub Pages | 1 GB site, 100 GB/mo | < 1 MB | ample |
| Cube + tiles | Cloudflare R2 | 10 GB, **zero egress** | ~150–300 MB | ample |
| Read ops | Cloudflare R2 | 10 M class-B/mo | ~30 per session | ample |
| ETL compute | Local build machine | — | minutes per state | n/a |
| Watchdog | GitHub Actions | unmetered on public repos | seconds/mo | ample |

**The build runs on the laptop, not in CI.** It downloads from census.gov,
computes, and pushes finished artifacts out. The Actions workflow, written at
this phase, is a **watchdog**: it checks the release calendar and whether what
is deployed is stale, and reports. It does not build or push data. The earlier
pipeline draft is parked at `etl/etl.workflow.yml.draft` for reference.

**Data goes to R2, not GitHub Pages, deliberately.** Pages has a documented
history of mangling byte-range requests for `.pmtiles` archives and a hard
100 MiB per-file block. R2 has zero egress fees by pricing design, not as a
free-tier perk.

### The R2 trap

A Cloudflare cache rule in front of an R2 custom domain can **strip the `Range`
header** and return the full object with a 200 instead of a 206. That silently
turns every partial read into a full download and defeats the entire
architecture.

**Mitigation, decided at the Phase 03 gate:** serve from the `r2.dev` URL, or
add a cache rule that bypasses caching on the data route, or front it with a
Worker that forwards `Range` explicitly. Verify a real 206 with `Content-Range`
in Chrome, Safari and Firefox before anything depends on it.

### Fallback

**Source Cooperative** (Radiant Earth) — free, S3-compatible, purpose-built for
cloud-native geospatial. Still in beta with no published SLA; CORS headers must
be verified before committing. Documented here so the decision is not made under
pressure later.

## Manifest

The app reads one small JSON, committed to the repo, that says what exists.

```jsonc
{
  "built": "2026-09-11T00:00:00Z",
  "base": "https://data.example.workers.dev",
  "vintages": ["2006-2010", "2016-2020"],
  "levels": { "tract": { "tiles": "tiles/tract_2020.pmtiles", "states": ["51"] } },
  "registry_version": 3
}
```

The manifest is the contract between the ETL and the app. Neither reaches past it.

## National scope (2026-11-12)

The owner set the goal as nationwide, with the national view as the default.
`registry/states.json` holds the 50 states and DC (Puerto Rico deferred: PRCS).
`etl/national.sh` builds every state, resumably; `etl/national.py` writes:

- `geo/states.geojson` (1:20M outlines) and `geo/states.json` (bounding boxes),
- `acs/{vintage}/county/us.parquet`: the 51 state county cubes stacked, written
  only when all 51 exist, with `geo/{vintage}/county/us.geojson` at 1:5M.

The manifest lists per-state files plus `us` where it exists, and
`national_breaks` per level and vintage: quintiles over every reliable U.S.
tract (place, ZIP), computed with the app's own tier rule, so a color means the
same thing in every state. The app opens on national counties; tracts, places
and ZIP codes load for the states in view from zoom 5.5 (at most six states),
which is the viewport-scoped fallback Phase 07 allows. Picking a state shows it
alone on its own breaks; `#PA` deep-links a state.
