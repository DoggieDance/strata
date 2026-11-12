"""Philadelphia replication, Table 3 half (spec 08): top five neighborhoods by
percent change, 2006-10 -> 2016-20, for each of the study's five indicators.

    .venv/bin/python -m analysis.philly_table3

Reproduces the study's method as written: each vintage's own tracts are
area-weighted onto the OpenDataPhilly neighborhoods (159 polygons), dollars are
deflated with the study's factor (1.187), and percent change is taken per
neighborhood. Two readings of "area-weighted" are tried, because the study does
not say which it used:

  rate:   neighborhood value = area-weighted average of the tract values
  counts: counts and dollar totals apportioned by area share, then divided

The "rate" reading uses STRATA's published tract means (income over all
households), so for income it differs in definition as well as weighting.

The study used area weighting, not STRATA's population weighting; this script
is a replication of the study, not of STRATA's method.
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import geopandas as gpd
import pandas as pd
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "build"
HOOD = ROOT / "data/raw/philly/philadelphia-neighborhoods.geojson"
FIXTURE = ROOT / "tests/fixtures/philly_pct_change_top5.csv"
STUDY_FACTOR = 1.187
CRS = 2272  # NAD83 / Pennsylvania South (ftUS)

# indicator -> (rate column, numerator, denominator, scale, dollars)
INDICATORS = {
    # The study divided aggregate household income (B19025, all households) by
    # OWNER-occupied households (B25003_002). That reproduces all five Table 3
    # values within 0.8 points; dividing by all households does not (Roxborough
    # Park 60% vs 139%). A study error, kept here only to replicate it.
    "income": ("mean_household_income", "agg_household_income", "owner_households", 1, True),
    "rent": ("mean_gross_rent_philly_study", "agg_gross_rent", "renter_households", 1, True),
    "home_value": ("mean_home_value", "agg_home_value", "owner_households", 1, True),
    # NOT reproduced. Our correct definition puts McGuire at 126%, the study at
    # 1,969%. Counting only men in 2010 (B15002_015:018) reproduces the study's
    # top-5 set and McGuire's value (male/male 25+ both years: 1,969.0%), but no
    # numerator/denominator combination matches all five. Needs the study's sheet.
    "bachelors_plus": ("pct_bachelors_plus", "bachelors_plus", "pop_25_plus", 100, False),
    "nh_white": ("pct_nh_white", "nh_white", "race_universe", 100, False),
}


def tracts(vintage: str) -> gpd.GeoDataFrame:
    geo = gpd.read_file(BUILD / f"geo/{vintage}/tract/42.geojson")
    geo = geo[geo.GEOID.str.startswith("42101")].to_crs(CRS)
    cube = pq.read_table(BUILD / f"acs/{vintage}/tract/42.parquet").to_pandas().set_index("GEOID")
    cube = cube[[c for c in cube.columns if c.endswith("_e")]].rename(columns=lambda c: c[:-2])
    return geo.join(cube, on="GEOID")


def overlay(tr: gpd.GeoDataFrame, hoods: gpd.GeoDataFrame) -> pd.DataFrame:
    tr = tr.assign(tract_area=tr.geometry.area)
    x = gpd.overlay(tr, hoods[["NAME", "geometry"]], how="intersection", keep_geom_type=True)
    x["share"] = x.geometry.area / x.tract_area                 # of the tract inside the hood
    x["hood_share"] = x.geometry.area                            # for area-weighted averages
    return pd.DataFrame(x.drop(columns="geometry"))


def neighborhood_values(x: pd.DataFrame, method: str) -> pd.DataFrame:
    out = {}
    for ind, (rate, num, den, scale, _) in INDICATORS.items():
        if method == "rate":
            v = x[[rate, "hood_share", "NAME"]].dropna()
            out[ind] = v.groupby("NAME").apply(lambda g: (g[rate] * g.hood_share).sum() / g.hood_share.sum())
        else:
            v = x[[num, den, "share", "NAME"]].dropna()
            g = v.assign(n=v[num] * v.share, d=v[den] * v.share).groupby("NAME")[["n", "d"]].sum()
            out[ind] = (g.n / g.d.where(g.d > 0)) * scale
    return pd.DataFrame(out)


def table3(method: str = "counts") -> dict[str, pd.Series]:
    """indicator -> percent change by neighborhood NAME, highest first."""
    hoods = gpd.read_file(HOOD).to_crs(CRS)
    x10, x20 = overlay(tracts("2006-2010"), hoods), overlay(tracts("2016-2020"), hoods)
    a, b = neighborhood_values(x10, method), neighborhood_values(x20, method)
    out = {}
    for ind, (*_, dollars) in INDICATORS.items():
        f = STUDY_FACTOR if dollars else 1
        out[ind] = ((b[ind] - a[ind] * f) / (a[ind] * f) * 100).dropna().sort_values(ascending=False)
    out["_hoods"] = pd.Series(sorted(hoods.NAME))
    out["_with_values"] = pd.Series(sorted(b.dropna(how="all").index))
    return out


def main() -> int:
    hoods = gpd.read_file(HOOD).to_crs(CRS)
    print(f"{len(hoods)} neighborhood polygons")
    want = pd.read_csv(FIXTURE)
    want["neighborhood"] = want.neighborhood.str.upper().str.replace(" ", "_")
    x10, x20 = overlay(tracts("2006-2010"), hoods), overlay(tracts("2016-2020"), hoods)
    results = {}
    for method in ("rate", "counts"):
        a, b = neighborhood_values(x10, method), neighborhood_values(x20, method)
        rows, hits, err = [], 0, []
        for ind, (*_, dollars) in INDICATORS.items():
            f = STUDY_FACTOR if dollars else 1
            pct = ((b[ind] - a[ind] * f) / (a[ind] * f) * 100).dropna().sort_values(ascending=False)
            top = list(pct.index[:5])
            w = want[want.indicator == ind].sort_values("rank")
            for _, r in w.iterrows():
                got = pct.get(r.neighborhood)
                rank = list(pct.index).index(r.neighborhood) + 1 if r.neighborhood in pct.index else None
                hits += r.neighborhood in top
                if got is not None:
                    err.append(abs(got - r["pct_change"]))
                rows.append((ind, int(r["rank"]), r.neighborhood, r["pct_change"], None if got is None else round(got, 2), rank))
            results[(method, ind)] = top
        print(f"\n== {method}: {hits}/25 study top-5 entries also in our top 5; "
              f"median |pct diff| {pd.Series(err).median():.2f} pts")
        for r in rows:
            print("  %-15s #%d %-20s study %8.2f  ours %8s  our rank %s" % r)
    with_values = neighborhood_values(x20, "counts").dropna(how="all")
    print(f"\nneighborhoods with any 2016-20 value: {len(with_values)} of {len(hoods)}; "
          f"without: {sorted(set(hoods.NAME) - set(with_values.index))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
