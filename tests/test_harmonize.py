"""Crosswalk and harmonizer (spec 02 gate: conservation; medians refused)."""
import json

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import pytest

from etl.crosswalk import _raw, registry
from etl.harmonize import MedianApportionError, apportion
from tests.conftest import BUILD, cube_path

XW = BUILD / "crosswalk" / "2010-2020" / "tract" / "51.parquet"
HARM = BUILD / "harmonized" / "2006-2010" / "tract-2020" / "51.parquet"


def need(p):
    if not p.exists():
        pytest.skip(f"{p.name} not built")
    return p


@pytest.fixture(scope="module")
def xw():
    return pq.read_table(need(XW)).to_pandas()


def test_weights_sum_to_one(xw):
    s = xw.groupby("source").weight.sum()
    assert np.allclose(s, 1.0, atol=1e-9)
    assert (xw.weight > 0).all()


def test_every_2010_tract_is_a_source_and_targets_are_2020_tracts(xw):
    src = set(pq.read_table(need(cube_path("2006-2010")), columns=["GEOID"]).column(0).to_pylist())
    tgt = set(pq.read_table(need(cube_path("2016-2020")), columns=["GEOID"]).column(0).to_pylist())
    assert set(xw.source) == src
    assert set(xw.target) <= tgt


def test_block_population_conserved():
    meta = json.loads(pq.ParquetFile(need(XW)).schema_arrow.metadata[b"strata"])["diagnostics"]
    assert meta["pop_assigned"] + meta["pop_in_foreign_2010_blocks"] == pytest.approx(meta["pop_2020_state"], abs=1e-6)


def test_pair_land_matches_census_tract_relationship_file(xw):
    path = _raw(registry()["2010-2020"]["states"]["51"]["tract_relationship"])
    if not path.exists():
        pytest.skip("tract relationship file not fetched")
    rel = pd.read_csv(path, sep="|", dtype=str, encoding="utf-8-sig")
    rel = rel[rel.GEOID_TRACT_10.str.startswith("51")]
    rel = rel.assign(land=rel.AREALAND_PART.astype("int64"))
    rel = rel[rel.land > 0].set_index(["GEOID_TRACT_10", "GEOID_TRACT_20"]).land
    ours = xw[xw.land > 0].set_index(["source", "target"]).land
    common = ours.index.intersection(rel.index)
    assert len(common) > 2000
    assert (ours[common] == rel[common]).all()
    # Every 2010 tract Census pairs with land also appears as one of our sources.
    assert set(rel.index.get_level_values(0)) <= set(xw.source)
    # Pairs we have that Census does not must carry (almost) nobody.
    extra = xw.set_index(["source", "target"]).loc[ours.index.difference(rel.index)]
    assert extra["pop"].sum() < 10


@pytest.fixture(scope="module")
def harmonized():
    return pq.read_table(need(HARM)).to_pandas().set_index("GEOID")


# Holds by construction once weights sum to 1 and counts are never null; kept as
# a guard against those preconditions breaking.
@pytest.mark.parametrize("col", ["total_population_e", "households_e", "pop_25_plus_e", "bachelors_plus_e", "nh_white_e"])
def test_counts_conserved_statewide(harmonized, col):
    src = pq.read_table(cube_path("2006-2010"), columns=[col]).column(0).to_pandas()
    assert harmonized[col].sum() == pytest.approx(src.sum(), rel=1e-9)


def test_county_totals_change_only_by_cross_county_pairs(harmonized, xw):
    """Tracts nest in counties. The equality re-adds the same weighted pieces
    (a check of the grouping, not the weights); the independent claim is that
    cross-county flow is boundary-correction sized."""
    src = pq.read_table(cube_path("2006-2010"), columns=["GEOID", "total_population_e"]).to_pandas().set_index("GEOID").total_population_e
    # Bedford city (51515) became part of Bedford County (51019) in 2013.
    flows = xw.assign(p=xw.weight * xw.source.map(src),
                      sc=xw.source.str[:5].str.replace("51515", "51019"), tc=xw.target.str[:5])
    expected = flows.groupby("tc").p.sum()
    got = harmonized.total_population_e.groupby(harmonized.index.str[:5]).sum()
    assert np.allclose(got.reindex(expected.index), expected, rtol=1e-6)  # Float32 storage
    moved = flows[flows.sc != flows.tc].p.sum()
    assert moved < 0.001 * src.sum()  # boundary corrections, not wholesale moves


def test_percents_recomputed_not_apportioned(harmonized):
    h = harmonized.dropna(subset=["pct_bachelors_plus_e"])
    assert np.allclose(h.pct_bachelors_plus_e, h.bachelors_plus_e / h.pop_25_plus_e * 100, rtol=1e-5)


# ---- synthetic cases: the formulas themselves ----

NOTES = {"pop": {"kind": "count"}, "agg": {"kind": "aggregate"}}


def frame(**cols):
    return pd.DataFrame(cols, index=pd.Index(["a", "b"], name="GEOID"))


def test_apportion_formula(monkeypatch):
    monkeypatch.setattr("etl.harmonize.intensive_recipes", lambda: {})
    monkeypatch.setattr("etl.harmonize.aggregate_universes", lambda: {})
    src = frame(pop_e=[100.0, 40.0], pop_m=[10.0, 8.0], agg_e=[1.0, 2.0], agg_m=[0.0, 0.0])
    xw = pd.DataFrame({"source": ["a", "a", "b"], "target": ["X", "Y", "Y"], "weight": [0.25, 0.75, 1.0]})
    out = apportion(src, NOTES, xw, pd.Index(["X", "Y", "Z"], name="GEOID"))
    assert out.loc["X", "pop_e"] == 25 and out.loc["Y", "pop_e"] == 115
    assert out.loc["Y", "pop_m"] == pytest.approx(np.hypot(7.5, 8.0))
    assert np.isnan(out.loc["Z", "pop_e"])  # nothing flows to Z


def test_zero_universe_piece_counts_as_zero(monkeypatch):
    """Review of cac3bfd: an aggregate over 0 households is 'not computable' in
    the source but means zero; it must not blank the target it touches."""
    monkeypatch.setattr("etl.harmonize.intensive_recipes", lambda: {})
    monkeypatch.setattr("etl.harmonize.aggregate_universes", lambda: {"agg": "pop"})
    src = frame(pop_e=[100.0, 0.0], pop_m=[10.0, 0.0], agg_e=[5.0, np.nan], agg_m=[1.0, np.nan])
    xw = pd.DataFrame({"source": ["a", "b"], "target": ["Y", "Y"], "weight": [1.0, 1e-5]})
    out = apportion(src, NOTES, xw, pd.Index(["Y"], name="GEOID"))
    assert out.loc["Y", "agg_e"] == 5.0 and out.loc["Y", "agg_m"] == 1.0


def test_reviewed_targets_keep_their_values(harmonized):
    # Both were blanked by tiny zero-universe pieces before the fix.
    assert not np.isnan(harmonized.loc["51059482505", "mean_household_income_e"])
    assert not np.isnan(harmonized.loc["51810044004", "mean_gross_rent_e"])


def test_single_source_targets_equal_their_source(harmonized, xw):
    """Independent of the apportion arithmetic: a 2020 tract fed only by one
    2010 tract at weight 1 must equal that tract in every column."""
    src = pq.read_table(cube_path("2006-2010")).to_pandas().set_index("GEOID")
    one = xw[xw.groupby("target").source.transform("size") == 1]
    one = one[np.isclose(one.weight, 1.0) & (one.groupby("source").target.transform("size") == 1)]
    assert len(one) > 900  # 986 one-to-one tracts in Virginia
    a = harmonized.loc[one.target.values].reset_index(drop=True)
    b = src.loc[one.source.values].reset_index(drop=True)
    for c in src.columns:
        x, y = a[c].to_numpy(dtype="float64"), b[c].to_numpy(dtype="float64")
        ok = np.isclose(x, y, rtol=1e-5, equal_nan=True) | (np.isnan(y) & (x == 0))
        assert ok.all(), c


def test_null_piece_nulls_target(monkeypatch):
    monkeypatch.setattr("etl.harmonize.intensive_recipes", lambda: {})
    monkeypatch.setattr("etl.harmonize.aggregate_universes", lambda: {})
    src = frame(pop_e=[100.0, np.nan], pop_m=[10.0, np.nan], agg_e=[1.0, 2.0], agg_m=[0.0, 0.0])
    xw = pd.DataFrame({"source": ["a", "b"], "target": ["Y", "Y"], "weight": [1.0, 1.0]})
    out = apportion(src, NOTES, xw, pd.Index(["Y"], name="GEOID"))
    assert np.isnan(out.loc["Y", "pop_e"])  # not a silent undercount of 100


def test_median_refused():
    src = frame(med_e=[1.0, 2.0], med_m=[0.0, 0.0])
    xw = pd.DataFrame({"source": ["a"], "target": ["Y"], "weight": [1.0]})
    with pytest.raises(MedianApportionError):
        apportion(src, {"med": {"kind": "median"}}, xw, pd.Index(["Y"], name="GEOID"))
