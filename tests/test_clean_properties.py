"""Property tests for cleaning and derivation — the spec 08 invariants that
exist at Phase 01. Engine and harmonizer invariants arrive with their phases."""
import numpy as np
import pandas as pd
import pytest
from hypothesis import given
from hypothesis import strategies as st

from etl.clean import bin_midpoints, midpoints_from_labels, parse_bin, ratio, sum_cells
from etl.common import ScopeError, check_scope, expand_cells, load_measures
from etl.fetch_summary_file import required_tables

counts = st.integers(min_value=0, max_value=50_000)
moes = st.integers(min_value=0, max_value=5_000)


def table(ests, errs):
    cols = {}
    for i, (e, m) in enumerate(zip(ests, errs), start=1):
        cols[f"E{i:03d}"] = [float(e)]
        cols[f"M{i:03d}"] = [float(m)]
    return pd.DataFrame(cols)


@given(st.lists(st.tuples(counts, moes), min_size=1, max_size=12), st.randoms())
def test_sum_cells_is_order_invariant(pairs, rnd):
    t = table(*zip(*pairs))
    cells = [f"{i:03d}" for i in range(1, len(pairs) + 1)]
    shuffled = cells[:]
    rnd.shuffle(shuffled)
    e1, m1 = sum_cells(t, cells)
    e2, m2 = sum_cells(t, shuffled)
    assert e1[0] == e2[0]
    assert m1[0] == pytest.approx(m2[0])


@given(st.lists(st.tuples(counts, moes), min_size=1, max_size=12))
def test_sum_cells_null_poisons(pairs):
    t = table(*zip(*pairs))
    t.iloc[0, 0] = np.nan
    e, m = sum_cells(t, [f"{i:03d}" for i in range(1, len(pairs) + 1)])
    assert np.isnan(e[0])


@given(counts, moes, counts, moes)
def test_proportion_bounded_and_moe_nonnegative(x, mx, extra, my):
    y = x + extra
    p, m = ratio([x], [mx], [y], [my], proportion=True, scale=100.0)
    if y == 0:
        assert np.isnan(p[0]) and np.isnan(m[0])
    else:
        assert 0 <= p[0] <= 100
        assert m[0] >= 0


@given(counts, moes, counts, moes)
def test_proportion_rejects_numerator_above_denominator(x, mx, y, my):
    if y == 0 or x <= y:
        return
    with pytest.raises(ValueError):
        ratio([x], [mx], [y], [my], proportion=True)


@given(
    st.lists(st.tuples(st.integers(1, 10**9), st.integers(0, 10**7), st.integers(1, 5000)), min_size=2, max_size=30),
    st.sampled_from([1e-3, 1e-2, 10.0]),
)
def test_mean_ranks_stable_under_dollar_rescaling(rows, k):
    """Rank stability under affine rescaling, at the derivation step."""
    agg, agg_m, hh = (np.array(c, dtype="float64") for c in zip(*rows))
    zeros = np.zeros_like(hh)
    a, _ = ratio(agg, agg_m, hh, zeros, proportion=False)
    b, _ = ratio(agg * k, agg_m * k, hh, zeros, proportion=False)
    assert (a.rank(method="min") == b.rank(method="min")).all()


def test_ratio_moe_matches_handbook_formula():
    # X=100±10, Y=400±20: proportion MOE = sqrt(10^2 - .25^2*20^2)/400
    p, m = ratio([100], [10], [400], [20], proportion=True)
    assert p[0] == 0.25
    assert m[0] == pytest.approx(np.sqrt(100 - 0.0625 * 400) / 400)
    # radicand negative -> ratio formula
    p, m = ratio([90], [1], [100], [30], proportion=True)
    assert m[0] == pytest.approx(np.sqrt(1 + 0.81 * 900) / 100)


def test_expand_cells():
    assert expand_cells(["002:004", "010"]) == ["002", "003", "004", "010"]
    with pytest.raises(ValueError):
        expand_cells(["C02_015"])
    with pytest.raises(ValueError):
        expand_cells(["005:002"])


def home_value_source(vintage):
    m = next(m for m in load_measures()["measures"] if m["id"] == "agg_home_value")
    return m["sources"][vintage]


def test_2016_2020_bins_match_table_shells():
    src = home_value_source("2016-2020")
    try:
        mids = bin_midpoints("2016-2020", "B25075", src)
    except FileNotFoundError:
        pytest.skip("table shells not fetched")
    assert mids["002"] == 5000
    assert mids["003"] == 12500
    assert mids["024"] == 875000
    assert {mids[c] for c in ("025", "026", "027")} == {1250000}


def test_bins_disagreeing_with_shells_raise():
    src = home_value_source("2016-2020")
    bad = {**src, "bins": [r[:] for r in src["bins"]]}
    bad["bins"][5][3] = 1
    try:
        with pytest.raises(ValueError, match="disagree"):
            bin_midpoints("2016-2020", "B25075", bad)
        with pytest.raises(ValueError, match="collapse"):
            bin_midpoints("2016-2020", "B25075", {**src, "top_bin": {**src["top_bin"], "collapse_from": "024"}})
    except FileNotFoundError:
        pytest.skip("table shells not fetched")


def label_for(lo, hi):
    if hi is None:
        return f"${lo:,} or more"
    if lo == 0:
        return f"Less than ${hi + 1:,}"
    return f"${lo:,} to ${hi:,}"


@pytest.mark.parametrize("vintage", ["2006-2010", "2016-2020"])
def test_registry_bins_follow_the_label_rule(vintage):
    """Recorded bins are contiguous and their midpoints/collapse obey bin_rule."""
    src = home_value_source(vintage)
    bins = src["bins"]
    assert [b[0] for b in bins] == expand_cells(src["cells"])
    for (_, _, hi, _), (_, lo, _, _) in zip(bins, bins[1:]):
        assert lo == hi + 1
    assert bins[-1][2] is None
    labels = {c: label_for(lo, hi) for c, lo, hi, _ in bins}
    assert all(parse_bin(labels[c]) == (lo, hi) for c, lo, hi, _ in bins)
    assert midpoints_from_labels(labels, src["top_bin"]) == bins
    first = next(c for c, lo, _, _ in bins if lo >= src["top_bin"]["collapse_at_lower_bound"])
    assert first == src["top_bin"]["collapse_from"]


def test_2006_2010_750k_bin_is_not_collapsed():
    """Registry v2 regression: 024 is $750,000-$999,999 and keeps its own midpoint."""
    bins = {b[0]: b for b in home_value_source("2006-2010")["bins"]}
    assert bins["024"] == ["024", 750000, 999999, 875000]
    assert bins["025"] == ["025", 1000000, None, 1250000]


def test_open_ended_bin_must_be_collapsed():
    with pytest.raises(ValueError, match="open-ended"):
        midpoints_from_labels({"027": "$2,000,000 or more"},
                              {"collapse_at_lower_bound": 10**9, "midpoint": 1})


def test_gross_rent_uses_cash_rent_universe():
    reg = load_measures()
    rent = next(m for m in reg["measures"] if m["id"] == "agg_gross_rent")
    assert rent["denominator"] == "cash_rent_renter_households"
    assert reg["denominators"]["cash_rent_renter_households"] == {
        **reg["denominators"]["cash_rent_renter_households"], "table": "B25063", "cells": ["002"]}
    (legacy,) = rent["legacy_derives"]
    assert legacy["id"] == "mean_gross_rent_philly_study"
    assert legacy["legacy"] is True and legacy["denominator"] == "renter_households"
    assert "B25063" in required_tables("2016-2020")


@pytest.mark.parametrize("states,vintages,level", [
    (["51", "42"], ["2016-2020"], "tract"),
    (["51"], ["2011-2015"], "tract"),
    (["51"], ["2016-2020"], "block group"),
])
def test_scope_lock(states, vintages, level):
    with pytest.raises(ScopeError):
        check_scope(states, vintages, level)


def test_2006_2010_in_phase_02_scope():
    check_scope(["51"], ["2006-2010", "2016-2020"], "tract")


def test_2006_2010_has_no_zcta():
    from etl.common import LevelUnavailable, level_cfg
    with pytest.raises(LevelUnavailable):
        level_cfg("2006-2010", "zcta")
