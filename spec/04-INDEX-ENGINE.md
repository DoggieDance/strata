# 04 — The Index Engine

A pure function in a Web Worker. Spec in, scores out. No network, no state,
no DOM. This is the piece that gets golden-fixture regression tests.

```
index(spec, cube) → { score, rank, percentile, contributions, cv, flags }
```

## The spec

A JSON object. It lives in the URL. **An index is a link.**

```jsonc
{
  "v": 1,
  "name": "Gentrification-aligned change, 2010–2020",
  "geography": { "level": "tract", "extent": "place:4260000" },
  "mode": "change",                    // level | change
  "vintages": ["2006-2010", "2016-2020"],
  "measures": [
    { "id": "mean_household_income", "polarity": "+", "weight": 1,
      "transform": "log", "normalize": "z" },
    { "id": "mean_gross_rent",       "polarity": "+", "weight": 1,
      "transform": "log", "normalize": "z" },
    { "id": "mean_home_value",       "polarity": "+", "weight": 1,
      "transform": "log", "normalize": "z" },
    { "id": "pct_bachelors_plus",    "polarity": "+", "weight": 1,
      "transform": "none", "normalize": "z" },
    { "id": "pct_nh_white",          "polarity": "+", "weight": 1,
      "transform": "none", "normalize": "z" }
  ],
  "aggregate": "mean",                 // mean | geometric | rank_sum
  "reference": "extent"                // extent | national | state
}
```

That spec is the Philadelphia study, with `transform: "log"` added on the three
dollar measures — the one change the study itself suggested it needed.

## Pipeline

```
select → derive → difference → deflate → transform → normalize → polarity
       → weight → aggregate → classify
```

### Transform
`none` · `log` (log1p, refuses negatives) · `box-cox` · `winsorize(p)`

Right skew is the norm for income, rent and value. The study noted the data was
not normally distributed and used z-scores anyway, which is defensible — z-scores
emphasize deviation from the mean, which was the point. Log-then-z is offered
because it is the more conventional answer and the difference should be visible.

### Normalize
| Method | Behavior |
|---|---|
| `z` | `(x − μ)/σ`. Keeps magnitude. Inherits outliers — μ and σ both move with extremes. |
| `percentile` | Rank to [0,1]. Immune to outliers. Discards magnitude entirely. |
| `minmax` | [0,1]. One outlier redefines an endpoint and compresses everyone else. |
| `robust` | `(x − median)/IQR`. Resistant without discarding magnitude. |

### Polarity
Per measure. Every measure must point the same direction before anything is
combined. Not optional, not defaulted.

### Weight
`equal` · `manual` · `pca` (first component loadings) · `entropy`

### Aggregate
| Method | Character |
|---|---|
| `mean` | Full compensability — one large move can carry a tract. The study's method. |
| `geometric` | Penalizes imbalance. A tract must move on most dimensions. Requires positive inputs, so normalized values are rescaled first. |
| `rank_sum` | Sum percentile ranks, then re-rank. The CDC SVI method. Robust, coarse. |

## The hard constraint

> **The engine refuses to aggregate unnormalized measures of differing units.**

This is not a warning dialog. It is a thrown error.

The reason is the Area Deprivation Index, which applies PCA-derived weights to
raw values. Because home value is measured in hundreds of thousands of dollars
and every other input in percentages, two variables end up explaining 98.8% of
the variance in a seventeen-variable index, and high-poverty urban tracts score
as *less* deprived because housing there is expensive. A published, widely used,
federally referenced index, wrong for a reason a type check would have caught.

## Contributions

For every tract the engine returns each measure's signed contribution to the
final score. This is what makes the index arguable rather than oracular — a user
can see that a tract scored high almost entirely on rent change, and decide for
themselves whether they believe it.

## Sensitivity

A live readout, not an academic exercise: as a weight slider moves, show how many
tracts change quintile. An index that reshuffles violently under a ±20% weight
perturbation is telling the user something, and the app should say it.

## Gate — the Philadelphia replication

Phase 04 does not pass until the engine, fed raw ACS through the harmonizer,
reproduces the study's 159-neighborhood average z-score map.

Fixture: `tests/fixtures/philly_2010_2020_zscores.csv` — the published
neighborhood z-scores. Tolerance documented, deviations explained individually,
not waved through in aggregate.

Known expected deviations, to be confirmed rather than assumed:
- The study used area weighting; STRATA uses population weighting. Values will
  differ, and the differences should concentrate in tracts with large uninhabited
  areas. If they do not, something else is wrong.
- Airport was null in the study because all its variables were suppressed.
  STRATA should independently arrive at null, via the jam-value path.
