"""Level membership, checked against the raw data files rather than the
geography-file code path that built the cubes (which would be circular)."""
import pandas as pd
import pyarrow.parquet as pq
import pytest

from etl.common import raw_dir
from etl.zcta import _pick
from tests.conftest import cube_path

V = "2016-2020"


def cube_ids(level):
    p = cube_path(V, level)
    if not p.exists():
        pytest.skip(f"{level} cube not built")
    return set(pq.read_table(p, columns=["GEOID"]).column("GEOID").to_pylist())


def raw_ids(prefix):
    path = raw_dir(V) / "acsdt5y2020-b01003.dat"
    if not path.exists():
        pytest.skip("raw B01003 not fetched")
    with open(path, encoding="latin-1") as f:
        return {ln.split("|", 1)[0].removeprefix(prefix[:9]) for ln in f if ln.startswith(prefix)}


@pytest.mark.parametrize("level,prefix", [("county", "0500000US51"), ("place", "1600000US51")])
def test_state_levels_hold_every_published_row(level, prefix):
    assert cube_ids(level) == raw_ids(prefix)


def test_zcta_cube_is_published_rows_assigned_to_virginia():
    from etl.zcta import assignments, ensure_relationship
    ensure_relationship(V)
    a = assignments("2010")
    va = set(a.index[a == "51"])
    published = raw_ids("8600000US")
    assert cube_ids("zcta") == published & va
    # Review regression: these were dropped when 2020 ZCTA files were used.
    assert {"23806", "20118", "24628"} <= cube_ids("zcta")


def test_zcta_rows_are_2010_definitions():
    """The 2016-2020 ACS tabulates 2010 ZCTAs: 33,120 nationally."""
    assert len(raw_ids("8600000US")) == 33120


def test_zcta_state_rule():
    df = pd.DataFrame({
        "zcta":  ["A", "A", "B", "B", "C", "C"],
        "state": ["51", "54", "51", "24", "51", "11"],
        "pop":   [10, 90, 0, 0, 5, 5],
        "land":  [900, 100, 10, 20, 1, 1],
    })
    got = _pick(df, ["pop", "land"]).to_dict()
    assert got == {"A": "54", "B": "24", "C": "11"}  # most people; land if none; tie -> lower FIPS
