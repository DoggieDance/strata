# Research Log

Verified 2026-09-11. Anything not verified is marked. Re-verify before a decision
depends on it — free tiers and federal data policy both move.

## Verified in this pass

**Census API keys are mandatory as of mid-2026.** The prior allowance of 500
anonymous queries per day is gone. Metadata endpoints (`variables.json`,
`groups.json`) remain keyless. Per-key rate limits are not published.

**Summary File format.** Table-based since the 2021 restructuring; the older
sequence-based format was discontinued after the 2017–2021 5-year release. One
file per table, all geographies.
`www2.census.gov/programs-surveys/acs/summary_file/{year}/table-based-SF/`

**ACS vintages.** 2020–2024 5-year released 29 Jan 2026. The 2025 1-year release
slipped to January 2026 because of the federal shutdown. 2021–2025 expected
around December 2026, not yet published.

**Jam values.** `-666666666`, `-999999999`, `-888888888`, `-222222222`,
`-333333333`, `-555555555`. Documented on the Census developers site.

**Inflation.** Census uses R-CPI-U-RS for dollar-denominated ACS variables. A
methodology change affected the B25075-family value tables starting with 2022
data — a silent unit change that breaks naive year-over-year comparison.

**NHGIS terms prohibit redistribution.** The academic carve-out does not cover a
public web app. Census relationship files + decennial block counts are the free,
unencumbered substitute.

**Cloudflare R2 free tier.** 10 GB storage, 1 M class-A ops, 10 M class-B ops per
month, and zero egress fees by pricing design rather than as a free-tier perk.

**GitHub Actions.** Unmetered minutes on public repositories. 6-hour job cap.
Scheduled workflows are delayed under load and **auto-disable after 60 days of
repository inactivity**.

**GitHub Pages.** 1 GB published site, 100 GB/month soft bandwidth, 100 MiB hard
per-file block. Git LFS explicitly does not work with Pages.

**PMTiles.** v3 spec; root directory 16 KB; any tile reachable in at most two
additional range requests. `pmtiles` JS at 4.x. Tippecanoe's maintained fork is
`felt/tippecanoe` (2.0.x); GDAL ≥ 3.8 can write PMTiles via `ogr2ogr -f PMTiles`.

**DuckDB-WASM.** Roughly 33 MB browser payload, ~600 ms cold start, documented
byte-range regressions in Safari and Firefox. hyparquet is ~10 KB for column
reads.

**EJScreen went offline 5 Feb 2025.** CEJST lost public access 22 Jan 2025; the
`usds/justice40-tool` repo is archived read-only (CC0). Community mirrors exist
under Public Environmental Data Partners and the Department of the Interior. This
is the evidentiary basis for treating build artifacts as an archive.

**Area Deprivation Index.** Applies PCA factor coefficients to unstandardized
values; home value and income alone explain 98.8% of the variance in the
published seventeen-variable index (*Health Affairs Scholar*, 2024).

**CDC SVI.** Percentile-rank each variable, sum within theme, re-rank the sum,
sum the themes, re-rank again. Equal weights throughout, no z-scores.

## Verified 2026-09-12 — cost and shortcut pass

**Paying does not make the data problem easier.** Every pre-built ACS or crosswalk
product is either already free and in the plan, or licensed in a way that forbids
serving it from a public app. NHGIS crosswalks: no redistribution, no carve-out.
Esri Demographics: named-user restriction plus an explicit anti-scraping clause.
Social Explorer and PolicyMap viewer subscriptions are not redistribution licenses;
PolicyMap sells that separately, by quote. ArcGIS for Personal Use ($100/yr) is
restricted to personal, noncommercial projects that benefit no third party.

**Two free shortcuts were under-weighted in the first pass.** HUD–USPS tract
crosswalk (address-count weights, "no special restrictions" terms, attribution
required) and Geocorr from the Missouri Census Data Center (population weights, no
published terms). Both now feed the Phase 02 validation strategy.

**LTDB** (Brown, Logan/Xu/Stults) normalizes to *2010* boundaries and Brown states
no plan to rebuild on 2020. Wrong direction for this project; useful only as a
historical cross-check.

**Where money actually helps: build iteration, not hosting.** A ~€7/month Hetzner
CX23 or CAX11 (2 vCPU, 4 GB, 40 GB, 20 TB traffic) gives a persistent machine with
PostGIS, unrestricted egress to census.gov, no 6-hour CI cap, and an interactive
loop instead of push-and-wait. Self-hosted PostGIS on that box beats Supabase Pro
($25/mo, 8 GB) for this workload. R2 beyond the free tier is $0.015/GB-month —
roughly $4.35/month at 300 GB-months, egress still zero. Mapbox bills tileset
hosting by hosting-day with 750 free per month, so one tileset is effectively free
there too.

## Flagged — not verified, verify before depending on it

- Actual byte sizes of `cb_*_us_tract_500k.zip` and of individual Summary File
  `.dat` files. Census blocked direct HEAD requests from every cloud IP tried.
- Whether a GitHub Actions runner can reach `www2.census.gov`. Untestable from a
  Cowork session, which is itself blocked by egress policy.
- MapLibre `setFeatureState` behavior at 85,000 features. The closest documented
  case is 20,000 features with reported zoom lag, since patched. No benchmark
  exists at this scale.
- Whether the "Parquet attributes + GEOID-only PMTiles, joined at runtime"
  pattern has a published precedent. None was found. Budget original engineering
  effort, not tutorial-following.
- Clean Sepia theme hex values. Marketplace would not yield the extension package.
- Exact numeric thresholds in Freeman (2005). The operational values in
  `06-TYPOLOGY.md` come from the Governing and NCRC replications, which describe
  themselves as reproducing his method.

## Rejected options, with reasons

| Option | Rejected because |
|---|---|
| Live Census API in the app | Mandatory key, 50-variable cap, state-by-state tract iteration, unprotectable credential |
| IPUMS NHGIS | Redistribution prohibited for a public app |
| DuckDB-WASM as the default engine | 33 MB payload for a weighted sum; range-request regressions |
| Tiles on GitHub Pages | Documented `.pmtiles` range-request failures, 100 MiB file cap |
| GitHub Releases as the data host | No CORS on release assets |
| Hugging Face Hub as the data host | Open issue: Xet backend fails CORS preflight and strips Range |
| jsDelivr for data | ~20 MB single-file ceiling |
| Area-weighted aggregation | Biased wherever density is uneven; the study's own stated limitation |
