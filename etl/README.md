# ETL

Runs on the local build machine only. There is no CI pipeline; the old Actions
file is parked at `etl.workflow.yml.draft` and the Phase 03 workflow will be a
watchdog. **It cannot run from a Cowork session** —
`census.gov` is blocked by that session's egress policy. This is documented in
`spec/01-DATA-SPINE.md` and is not a bug to route around.

## Modules, in build order

| Module | Does |
|---|---|
| `check_releases` | Has the ACS release calendar moved? If not, the whole job no-ops. |
| `fetch_summary_file` | Downloads the files the registry names: `.dat` tables (table-based vintages) or sequence zips + lookup + geography file (2006–2010). Caches by ETag, else Last-Modified + Content-Length. |
| `sequence_file` | Reads 2006–2010 sequence files into the same per-table frame as the `.dat` loader. |
| `clean` | Strips jam values and missing tokens, computes derived measures. Values stay in each vintage's own dollars. |
| `build_crosswalk` | Block-weighted tract crosswalk, 2010 to 2020. Phase 02. |
| `harmonize` | Apportions a vintage onto target geometry. Refuses medians. |
| `build_cube` | Writes per-state Parquet, sorted by GEOID, 8k row groups, zstd. |
| `build_tiles` | CB shapefiles to a GEOID-only PMTiles archive. |
| `write_manifest` | The contract the app reads. Nothing reaches past it. |
| `spotcheck` | Validation only: fills a gate fixture from data.census.gov's published tables. |

## Local run

```bash
python3 -m venv .venv            # never global pip
.venv/bin/pip install -r etl/requirements.txt
.venv/bin/python -m etl.fetch_summary_file --vintage 2016-2020
.venv/bin/python -m etl.fetch_summary_file --vintage 2006-2010
.venv/bin/python -m etl.build_cube --states 51 --vintages 2016-2020,2006-2010 --out build/
.venv/bin/python -m pytest tests/ -q
```

If `python3 -m venv` fails for lack of ensurepip, use `--without-pip` and
bootstrap pip inside the venv with `get-pip.py`.

## Secrets

Only one credential exists in the system: the R2 key pair.

```
R2_ACCESS_KEY_ID
R2_SECRET_ACCESS_KEY
R2_ENDPOINT          https://<account>.r2.cloudflarestorage.com
R2_BUCKET
CENSUS_API_KEY       optional — validation spot-checks only, never the app
```
