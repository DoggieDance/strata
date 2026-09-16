# 08 — Testing Regime

No phase passes on inspection. Every gate is a test that runs.

## Golden fixtures

The load-bearing tests. Real published numbers, checked against.

| Fixture | Source | Guards |
|---|---|---|
| `philly_2010_2020_zscores.csv` | The study's 159 neighborhood z-scores | The whole pipeline, end to end |
| `philly_pct_change_top5.csv` | The study's Table 3 | Derivation and percent-change math |
| `acs_handbook_moe_examples.json` | Census handbook worked examples | MOE propagation formulas |
| `va_tract_spotcheck.csv` | 20 values pulled from data.census.gov by hand | The bulk extract itself |

The Philadelphia fixture is already partly in hand — Table 3 gives the top five
neighborhoods per indicator with their percent changes (Roxborough Park 139.46%
income, Old Kensington 129.13%, Sharswood 91.82% rent, and so on), and Figure 5
gives every neighborhood's average z-score.

## Property tests

Invariants that must hold for any input, checked with generated data.

- **Permutation invariance.** Reordering the measures in a spec does not change
  any score.
- **Weight normalization.** Doubling every weight changes nothing.
- **Polarity.** Flipping one measure's polarity negates exactly that measure's
  contribution, and nothing else.
- **Monotonicity.** Increasing a positively-weighted, positively-polarized
  measure for one tract never decreases that tract's score.
- **Rank stability under affine rescaling.** Converting dollars to thousands of
  dollars changes no rank under any normalization method.
- **Conservation.** Apportioned population sums to source population.
- **Jam-value guard.** No value below −1e8 exists in any built artifact. Hard fail.
- **Median refusal.** Any attempt to apportion a median raises.
- **Unit guard.** Any attempt to aggregate unnormalized measures of differing
  units raises.

## Performance budgets

Measured, not estimated. A miss is a gate failure, not a note.

| Budget | Target | Scope |
|---|---|---|
| Time to first map | < 2.5 s | cold cache, pilot region |
| Index recompute | < 150 ms | all pilot tracts |
| National recompute | < 600 ms | 85,000 tracts, Phase 07 |
| App bundle | < 400 KB | excluding MapLibre |

## Infrastructure smoke tests

Run before anything depends on them. These are the assumptions most likely to be
quietly false.

- `Range: bytes=0-99` against the R2 data URL returns **206** with a correct
  `Content-Range` — in Chrome, Safari and Firefox. Not 200.
- CORS preflight on the data origin admits the `Range` header.
- A PMTiles tile loads from a cold browser in each of those three.
- The build machine can reach `www2.census.gov` (preflight before every build).
  Verified 2026-09-16: 200. It cannot be reached from a Cowork session.
- The Phase 03 watchdog workflow can reach whatever it checks from a runner.

## Visual regression

Screenshot the pilot map at three zoom levels in both themes, diff against
committed baselines. Catches legend collisions, hatching failures, and ramp
inversions — all of which are silent in unit tests.

## What is deliberately not tested

Whether an index is *good*. That is a judgment, and the app's job is to make the
judgment visible — contributions, sensitivity, margins — not to score it.
