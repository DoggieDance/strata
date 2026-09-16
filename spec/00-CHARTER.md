# 00 — Charter

## What STRATA is

A static web application that lets a person build a composite index out of
American Community Survey measures and map it, at census tract level, with
margins of error carried through the calculation.

## What it is not

- Not a live Census API client. See `01-DATA-SPINE.md` for why.
- Not a general GIS. No editing, no routing, no arbitrary spatial analysis.
- Not a replacement for Social Explorer or PolicyMap. Those are catalogs. This is
  an instrument for one operation: turning several measures into one number and
  seeing where that number is high.

## The one sentence

*Pick what matters to you, decide how much each part counts, and see where it lands.*

## Audience, both ends

**The layperson** opens a preset, sees a map, and reads a plain sentence
explaining what the colors mean. They never see the word "normalization."

**The analyst** opens the same page, replaces every default, inspects the
per-measure contribution to each tract's score, checks the coefficient of
variation, and exports the result with a reproducible spec.

Neither is a separate mode. The complexity is one disclosure away, always.

## Non-negotiables

1. No measure is aggregated with another measure of different units without
   normalization. Hard constraint in the engine, not a warning. See the ADI
   failure in `04-INDEX-ENGINE.md`.
2. No change between two ACS vintages is reported as change unless it passes a
   significance test.
3. No tract above the unreliability threshold is rendered as though it were
   reliable.
4. Every index is a URL. Reproducibility is the product.

## Provenance

The Philadelphia study established the method: five indicators, area-weighted
aggregation from tracts to 158 neighborhoods, inflation-adjusted, differenced,
z-scored, averaged. STRATA generalizes it and fixes two of its stated
limitations — area weighting, and equal weights assumed without examination.

The study is also the acceptance test. Phase 04 does not pass until STRATA
reproduces its result from raw ACS.
