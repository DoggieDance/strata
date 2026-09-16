# ETL

Runs on GitHub Actions, or locally. **It cannot run from a Cowork session** —
`census.gov` is blocked by that session's egress policy. This is documented in
`spec/01-DATA-SPINE.md` and is not a bug to route around.

## Modules, in build order

| Module | Does |
|---|---|
| `check_releases` | Has the ACS release calendar moved? If not, the whole job no-ops. |
| `fetch_summary_file` | Downloads the `.dat` files the registry names. Caches by ETag. |
| `clean` | Strips jam values, applies deflators, computes derived measures. |
| `build_crosswalk` | Block-weighted tract crosswalk, 2010 to 2020. Phase 02. |
| `harmonize` | Apportions a vintage onto target geometry. Refuses medians. |
| `build_cube` | Writes per-state Parquet, sorted by GEOID, 8k row groups, zstd. |
| `build_tiles` | CB shapefiles to a GEOID-only PMTiles archive. |
| `write_manifest` | The contract the app reads. Nothing reaches past it. |

## Local run

```bash
pip install -r etl/requirements.txt
python -m etl.build_cube --states 51 --vintages 2020 --out build/
```

## Secrets

Only one credential exists in the system: the R2 key pair.

```
R2_ACCESS_KEY_ID
R2_SECRET_ACCESS_KEY
R2_ENDPOINT          https://<account>.r2.cloudflarestorage.com
R2_BUCKET
CENSUS_API_KEY       optional — validation spot-checks only, never the app
```
