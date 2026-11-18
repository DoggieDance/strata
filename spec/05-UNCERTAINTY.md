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

- Propagate uncertainty in z-units: SE(zᵢ) ≈ SE(xᵢ)/σᵢ, combined as √Σ wᵢ²·SE(zᵢ)². A CV is undefined for z-scored components (their mean is about 0), so CV is reserved for raw measures (methods audit 2026-11-17).
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
Z = |x₂ − f·x₁| / √((f·SE₁)² + SE₂²)     f = price-level ratio for dollar measures, else 1
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


## Methods audit, 2026-11-17

An independent audit checked every formula against Census documentation and
the literature. Outcomes:

| Finding | Outcome |
|---|---|
| MOE of sums added every zero-estimate cell's model MOE | **Fixed.** Census rule: use only the largest zero-estimate MOE, once (ACS MOE training 2016, slide 26). `clean.sum_moe`, also in the harmonizer. Test reproduces the slide (±63.06). 2006–10 VA unemployment MOE: median ±27.4 → ±7.2 pp. |
| Proportion MOE at P = 1 | **Fixed.** SE(P) = SE(X)/Y (Census statistical-testing instructions). |
| Home value treated as end-year dollars | **Fixed.** Census reported home values without inflation adjustment before the 2018–22 release (User Note 2023-07). Pooled periods use the mean R-CPI-U-RS over their years; labels say so. |
| Home value MOE from bin midpoints ~3× Census's | **Fixed where possible.** Census's published aggregate value (B25079, replicate MOE) is used wherever published; the midpoint sum (whose 2006–10 values equal B25079 to the dollar, so the $1.25M top midpoint is Census's convention) only where B25079 is blank, with a conservative MOE. |
| One total-population weight for every count | **Fixed.** Population, household-population, household and housing-unit weights from the 2020 PL file; each table's base in `registry/apportion_basis.json`. |
| Weight 2010 data by 2010 rather than 2020 blocks | **Not adopted; documented.** STRATA's choice is target-density weighting (Schroeder 2007), the method NHGIS names for its block crosswalks; LTDB's source-year weighting is the other published convention. 2020 block counts carry differential-privacy noise, which largely cancels when summed to tract pairs; the Virginia comparison found the choice immaterial (3 of 2,159 tracts moved more than 5%). |
| No multiple-comparison handling | **Added, opt-in.** Benjamini–Hochberg FDR at 10% (Benjamini & Hochberg 1995; Benjamini & Yekutieli 2001; Caldas de Castro & Singer 2006), national threshold in the manifest. The default stays per-area 90% testing, Census's practice, and the legend now states the expected false-positive rate. |
| CV tiers unattributed; 12% boundary | **Fixed.** Cited as Esri's convention and matched (CV ≤ 12 is high). |
| CV tiers on percents are asymmetric (CV(p) ≠ CV(1−p)) | **Open.** NCHS (Parker et al. 2017) proportion standards need effective sample sizes STRATA does not have; a symmetric rule is being evaluated. Until then the asymmetry is disclosed. |
| Apportioned MOE omits interpolation error | **Disclosed;** split targets to be flagged. Before any second-stage aggregation (tracts → neighborhoods) pieces of one source must be combined as perfectly correlated. |
| Unemployment from 52 summed cells | **Fixed.** B23025 (collapsed, Census MOEs) wherever published; B23001 only for 2006–10. |
| Comparability cautions missing | **Added.** `registry/comparability_notes.json`, shown under the change legend. |
| "No measurable change" | Now "No statistically significant change" (Census Quality Standard E1). |

Confirmed sound: proportion/ratio formulas and the negative-radicand fallback;
controlled MOEs → 0; the Z test with the deflator scaling SE₁; refusal of
overlapping periods; R-CPI-U-RS as the ACS index (Census still uses it for ACS;
only CPS ASEC moved to C-CPI-U); deflator values byte-identical to BLS; the
study's 1.187 is Census's chained published factor from pre-revision index values.
