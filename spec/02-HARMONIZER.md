# 02 — The Harmonizer

## The problem

Census tract boundaries were redrawn between 2010 and 2020. Comparing a 2010
5-year estimate to a 2020 one at tract level is comparing different polygons
wearing similar names.

The Philadelphia study solved this by aggregating both vintages up to stable
neighborhood boundaries using **area weighting** — each tract contributed in
proportion to the share of its polygon inside the neighborhood. The study
correctly flagged the assumption: values are uniformly distributed within a
tract. They are not. A tract that is half industrial park and half dense
apartments gives the industrial half credit for people who do not live there.

## The decision: population weighting

Apportion using **2020 decennial census block population** as the weight rather
than polygon area. Blocks are small enough that the uniformity assumption
becomes tolerable, and their counts are a complete enumeration, not a sample.

```
weight(source_tract → target) = Σ block_pop(blocks ∩ source ∩ target)
                              / Σ block_pop(blocks ∩ source)
```

Free inputs, no license encumbrance:

- 2020 decennial block population (P1 table)
- Census tract relationship files, 2010 ↔ 2020
- TIGER/Line block geometry, per state

**IPUMS NHGIS is deliberately excluded.** It provides exactly this, pre-built and
better, but its terms prohibit redistribution and a public web app is not covered
by the academic exception. STRATA builds its own.

## The structural insight

**Temporal harmonization and spatial aggregation are the same operation.**

| Job | Source geometry | Target geometry |
|---|---|---|
| Compare 2010 to 2020 | 2010 tracts | 2020 tracts |
| The Philadelphia study | 2020 tracts | 158 neighborhoods |
| User-uploaded boundaries | 2020 tracts | whatever they drew |

One engine, three products. Custom geography support is a consequence of
building the crosswalk correctly, not a separate feature.

## Extensive vs. intensive

The apportionment rule depends on what the measure is.

- **Extensive** (counts, aggregates — population, aggregate income): distribute
  by weight, then sum into the target.
- **Intensive** (rates, medians, percentages): cannot be summed. Reconstruct from
  apportioned numerator and denominator. A median cannot be apportioned at all —
  it is recomputed from bins, or it is refused.

**The engine refuses to apportion a median.** Silently averaging medians is one
of the most common errors in applied demography and it will not be possible here.

## Free shortcuts — validate against these before writing the engine

Two pre-built crosswalks exist with terms that permit use in a public app. Neither
replaces the engine, but both collapse the risk of building it blind.

**HUD–USPS Census Tract Crosswalk.** Ships 2010↔2020 tract pairs with
`RES_RATIO` / `BUS_RATIO` / `OTH_RATIO` / `TOT_RATIO` allocation weights, updated
quarterly. Free registration, documented API. HUD's dataset page states *"No
special restrictions or limitations on using the item's content have been
provided"*; the API terms require an attribution notice and nothing more.

The weights are **address counts, not population** — a proxy, and a decent one for
housing measures, weaker for person-level measures like educational attainment.

**Geocorr (MABLE/Geocorr, Missouri Census Data Center).** Generates custom
correspondence files between arbitrary vintages with population and household
weights derived from block data. Form-driven, not an API. No terms of use are
published, which is permissive by silence rather than by grant — usable, credited,
but not iron-clad.

**How STRATA uses them:** as the reference answer. Build the block-weighted
crosswalk, then check it against HUD's ratios and a Geocorr extract. Agreement
across three independently derived weightings is far stronger evidence than a
conservation test alone. Disagreement localizes the bug.

**What is still not available:** IPUMS NHGIS publishes exactly the crosswalk this
project wants — 2010↔2020 tract-to-tract with population, household, and housing
weights — and its terms prohibit redistribution without written permission, with
no carve-out for crosswalk files. Esri's Living Atlas demographics carry a
named-user restriction and an explicit anti-scraping clause. Both are closed.

## Gate

1. **Conservation.** For every source geography, the sum of apportioned
   population across all targets equals its source population within rounding.
2. **Replication.** Philadelphia 2010 tract data apportioned onto 2020 tracts,
   then onto the OpenDataPhilly neighborhood boundaries, reproduces the study's
   neighborhood-level 2010 values within a documented tolerance.

Failure of either gate halts Phase 02. There is no partial pass.
