# 06 — Typology Mode

The same measures, classified by rules instead of scored. Continuous and
categorical are two views of one dataset, not two applications.

## Why both

A composite score answers "how much." A typology answers "which kind." Every
well-known gentrification study picked one and stayed there — Freeman, Governing,
NCRC and the Philadelphia Fed all use eligibility-plus-change screens; the CDC
SVI and the Area Deprivation Index use continuous scores. Offering both, over
identical inputs, is the thing none of them do.

## The shape of a rule set

Nearly every published gentrification typology is two stages:

1. **Eligibility** — was the tract in a position to gentrify at baseline?
   Typically low income and low education or value relative to its metro.
2. **Change** — did it then move, relative to its metro, on value and education?

```jsonc
{
  "v": 1,
  "name": "Freeman-style, metro-referenced",
  "reference": "cbsa",
  "stages": [
    { "id": "eligible", "all": [
      { "measure": "median_household_income", "vintage": "base",
        "op": "percentile_lt", "value": 40 },
      { "measure": "median_home_value", "vintage": "base",
        "op": "percentile_lt", "value": 40 },
      { "measure": "total_population", "vintage": "base",
        "op": "gte", "value": 500 }
    ]},
    { "id": "gentrifying", "requires": "eligible", "all": [
      { "measure": "pct_bachelors_plus", "mode": "change",
        "op": "percentile_gt", "value": 67 },
      { "measure": "median_home_value", "mode": "change_real",
        "op": "percentile_gt", "value": 67 }
    ]}
  ],
  "classes": [
    { "id": "gentrifying",  "when": "gentrifying" },
    { "id": "eligible_not", "when": "eligible" },
    { "id": "ineligible",   "when": "default" }
  ]
}
```

## Presets

Shipped as editable rule sets, each with its source cited in the UI.

| Preset | Eligibility | Change threshold |
|---|---|---|
| **Freeman / Governing** | bottom 40th pct income *and* home value, metro | top third on education *and* real value |
| **NCRC** | bottom 40th pct income *and* value, pop ≥ 500 | top 60th pct on value *and* education, plus real income growth |
| **UDP-style** | income tier vs. regional AMI (80% / 120% bands) | multi-window housing cost change, decision tree |

The UDP typology is a decision tree, not a threshold pair, so the rule schema
supports nested conditions. Their replication code is public
(`urban-displacement/displacement-typologies`) and is the reference implementation.

## Displacement is not gentrification

A tract can gentrify without displacement and lose low-income households without
gentrifying. NCRC flags "cultural displacement" separately, when a racial group's
share falls by more than two standard deviations *and* at least five percentage
points.

The app keeps these as separate outputs. Collapsing them is the most common
misreading in this literature, and the Philadelphia study's own implications
section — the Pew finding that 164 tracts *lost* income while 15 gentrified — is
exactly the case that gets lost when they are merged.

## Significance applies here too

Every threshold comparison runs through the same significance machinery as the
continuous engine. A tract that clears a threshold by less than its margin of
error is classified as **indeterminate**, which is a rendered class, not a gap.
