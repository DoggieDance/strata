# 03 — Cube, Tiles, and Hosting

## Storage shape

Two artifacts, joined in the browser by `GEOID`.

### The cube — attributes

One wide Parquet file per state per vintage per geography level.

```
acs/{vintage}/{level}/{state_fips}.parquet
```

- Rows: `GEOID`, sorted, so row groups align to counties.
- Columns: one `{measure}_e` and one `{measure}_m` per measure. Float32.
- Row group size ~8,000 rows. Compression zstd.

Parquet is columnar, so an index naming five measures fetches ten columns, not
the whole file. Read with **hyparquet** (~10 KB) using HTTP range requests.

**Projected size** (to be measured at Phase 01, not assumed):

| Scope | Rows | Est. compressed |
|---|---|---|
| Virginia, tracts, one vintage | ~2,200 | ~0.4 MB |
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
| ETL compute | GitHub Actions | unmetered on public repos | ~15 min/mo | ample |
| Job duration | GitHub Actions | 6 h per job | ~25 min national | watch |

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
