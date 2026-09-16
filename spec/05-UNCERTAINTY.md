# 05 — Uncertainty

ACS estimates are samples. An application that maps them without saying so is
lying by omission. STRATA carries margins of error through every calculation.

## Propagation

Census Bureau formulas, applied as published.

**Aggregating across geographies** (apportionment, summing tracts into a target):
```
MOE_total = √( Σ MOE_i² )
```

**Derived proportion**, numerator a subset of the denominator:
```
MOE(P) = (1/Y) · √( MOE_X² − P² · MOE_Y² )
```
If the radicand is negative, fall back to the ratio formula. This is the Census
Bureau's own instruction, not an improvisation.

**Ratio**, numerator not a subset:
```
MOE(R) = (1/Y) · √( MOE_X² + R² · MOE_Y² )
```

**Standard error** from a published 90% margin:
```
SE = MOE / 1.645
```

**Clamping.** A lower confidence bound computed as estimate − MOE can go
negative. A negative number of people is not a thing. Clamp at zero for counts.

## Through the index

The composite score's uncertainty is the weighted combination of its components'
standard errors. Exact propagation through a z-score is not closed-form, because
μ and σ are themselves estimated from uncertain values — so:

- Report the composite CV as the weighted root-sum-square of component CVs, and
  **label it an approximation in the UI**, because it is one.
- Offer an optional Monte Carlo mode for a single tract: resample each input
  from its confidence interval, recompute, report the score's distribution.
  Slow, honest, and worth it on demand.

## Reliability tiers

Coefficient of variation, `CV = SE / estimate × 100`:

| CV | Tier | Treatment |
|---|---|---|
| < 12% | high | rendered normally |
| 12–40% | medium | rendered, flagged on inspection |
| > 40% | low | **hatched, not colored** |

These thresholds are a field convention, not Census doctrine — the Bureau
explicitly declines to publish a hard cutoff. The app says so where the legend
is explained.

## Change over time

**Only non-overlapping periods may be differenced.** 2006–2010 against 2016–2020
is valid. 2014–2018 against 2016–2020 shares three years of sample and is not.
The engine refuses overlapping pairs.

**Significance test**, before any change is reported as change:
```
Z = |x₁ − x₂| / √(SE₁² + SE₂²)
```
Against 1.645 (90%), 1.96 (95%), or 2.576 (99%). Below threshold, the tract is
rendered as "no measurable change" — a distinct visual state, not zero.

This is the single most important honesty feature in the application. A change
map without it invents movement out of sampling noise, and the tracts where it
invents the most are the small, poor, high-margin ones that matter most.

## Presentation

Default: hatching on low-reliability tracts, legend note, CV in the inspector.

Optional: the three-layer confidence display — point estimate, lower bound, and
upper bound rendered together at matched breaks, so a wide margin reads visually
as a blurred, uncertain area rather than a confident color.
