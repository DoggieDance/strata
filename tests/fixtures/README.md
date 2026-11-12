# Fixtures

Ground truth from the Philadelphia study (GEOG 376, JMU, 2025), Table 3 and
Figure 5. These are published results, transcribed. STRATA must reproduce them
from raw ACS.

- `philly_pct_change_top5.csv` — Table 3, complete. Guards derivation,
  aggregation and percent-change math.
- `philly_2010_2020_zscores.csv` — **not yet transcribed.** Figure 5 carries the
  average z-score for all 159 neighborhoods. Transcribing it is the first Phase 04
  task, and it is the Phase 04 gate.

## Reading the top-5 fixture

Note the shape of the education and race columns: McGuire at +1968% and Glenwood
at +1053% are arithmetic artifacts of near-zero 2010 baselines, not demographic
events. A pipeline that reproduces those numbers exactly is correct. A pipeline
that presents them as findings is not — which is the entire argument for
standardization over raw percent change.

## Virginia spot-check

- `va_tract_spotcheck.csv` — the Phase 01 gate. 20 (tract, variable) pairs drawn
  with seed 51 by `etl/spotcheck.py` and fetched on 2026-11-12 from
  data.census.gov's table endpoint (`/api/access/data/table`), not copied by hand.
  The box has no CENSUS_API_KEY, but this endpoint serves the same published values
  the site's table viewer shows. The script refuses to overwrite the fixture.
