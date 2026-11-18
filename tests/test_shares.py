"""Share measures (registry/shares.json, v0.3.3).

1. Every stored cell resolves, in Census's own label files, to the label it was
   chosen for. A renumbered or misread cell fails here, not on the map.
2. Identities on the built cubes: the race groups partition B03002's total and
   the age groups partition B01001's, exactly (they are sums of the same cells).
3. Published values: random share counts match data.census.gov
   ({st}_tract_shares_spotcheck_{vintage}.csv, filled by
   `python -m etl.spotcheck --set shares`).
"""
import csv
import math
from collections import defaultdict

import numpy as np
import pyarrow.parquet as pq
import pytest

from etl.common import load_shares
from etl.spotcheck import share_variables
from tests.conftest import BUILD, ROOT

RAW = ROOT / "data/raw/acs"
SHARES = load_shares()


def test_cells_resolve_to_their_recorded_labels():
    """Every vintage's cells, against that vintage's own Census label file."""
    from etl.clean import _shell_labels
    for v in sorted({v for sh in SHARES for v in sh["sources"]}):
        try:
            labels = _shell_labels(v)
        except FileNotFoundError:
            pytest.skip(f"{v} label file not fetched")
        for sh in SHARES:
            src = sh["sources"].get(v)
            if not src:
                continue
            got = [labels.get(f"{src['table']}_{c}") for c in src["numerator_cells"]]
            assert [x.strip() if x else x for x in got] == [x.strip() for x in src["numerator_labels"]], (sh["id"], v)
            got = [labels.get(f"{src['table']}_{c}") for c in src["denominator_cells"]]
            assert [x.strip() if x else x for x in got] == [x.strip() for x in src["denominator_labels"]], (sh["id"], v)


def test_registry_shape():
    ids = [s["id"] for s in SHARES]
    assert len(ids) == len(set(ids)) == 40
    for sh in SHARES:
        assert "2016-2020" in sh["sources"]
        assert sh["count_numerator"] != sh["count_denominator"]
    # A count name always means the same cells (the cube builder also enforces this).
    seen = {}
    for sh in SHARES:
        for v, src in sh["sources"].items():
            for cid, key in ((sh["count_numerator"], "numerator_cells"), (sh["count_denominator"], "denominator_cells")):
                k = (cid, v)
                assert seen.setdefault(k, (src["table"], src[key])) == (src["table"], src[key]), k


RACE = ["nh_white", "nh_black", "nh_aian", "nh_asian", "nh_nhpi", "nh_other", "nh_multi", "hispanic"]
AGE = ["age_under_18", "age_18_24", "age_25_34", "age_35_44", "age_45_64", "age_65_plus"]


def _cubes():
    out = []
    for v in ("2016-2020", "2006-2010"):
        for p in sorted((BUILD / "acs" / v / "tract").glob("[0-9][0-9].parquet")):
            out.append(pytest.param(p, id=f"{v}-{p.stem}"))
    return out


@pytest.mark.parametrize("path", _cubes())
def test_partitions_are_exact(path):
    names = pq.ParquetFile(path).schema_arrow.names
    if "hispanic_e" not in names:
        pytest.skip("cube predates the share measures (registry v7)")
    t = pq.read_table(path, columns=[f"{c}_e" for c in RACE + AGE + ["race_universe", "age_universe"]]).to_pandas()
    ok = t.race_universe_e.notna()
    assert np.allclose(t.loc[ok, [f"{c}_e" for c in RACE]].sum(axis=1), t.loc[ok, "race_universe_e"])
    ok = t.age_universe_e.notna()
    assert np.allclose(t.loc[ok, [f"{c}_e" for c in AGE]].sum(axis=1), t.loc[ok, "age_universe_e"])
    shares = pq.read_table(path, columns=[f"{s['id']}_e" for s in SHARES if f"{s['id']}_e" in names]).to_pandas()
    v = shares.to_numpy(dtype="float64")
    v = v[np.isfinite(v)]
    assert (v >= 0).all() and (v <= 100 + 1e-4).all()


def _fixture_cases():
    out = []
    for f in sorted((ROOT / "tests/fixtures").glob("*_tract_shares_spotcheck_*.csv")):
        st = {"va": "51", "pa": "42", "ca": "06"}[f.name[:2]]
        vintage = f.stem.rsplit("_", 1)[1]
        for row in csv.DictReader(open(f, newline="")):
            out.append(pytest.param(st, vintage, row, id=f"{f.name[:2]}-{vintage}-{row['GEOID']}-{row['variable']}"))
    return out or [pytest.param(None, None, None, id="no-fixtures")]


@pytest.mark.parametrize("state,vintage,row", _fixture_cases())
def test_share_counts_match_data_census_gov(state, vintage, row):
    if row is None:
        pytest.skip("share spot-check fixtures not filled yet")
    path = BUILD / "acs" / vintage / "tract" / f"{state}.parquet"
    if not path.exists() or "hispanic_e" not in pq.ParquetFile(path).schema_arrow.names:
        pytest.skip("cube not built with the share measures yet")
    col = share_variables(vintage)[row["variable"]]
    t = pq.read_table(path, columns=["GEOID", col]).to_pydict()
    got = t[col][t["GEOID"].index(row["GEOID"])]
    want = row["value"].strip()
    if want == "*****":
        assert row["variable"].endswith("M") and got == 0
    elif want in ("", "-", "N", "(X)", "**", "null"):
        assert got is None or math.isnan(got)
    else:
        assert got is not None and abs(got - float(want.replace(",", ""))) <= 0, (got, want)
