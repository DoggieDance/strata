"""The 2006-2010 sequence-file reader (etl/sequence_file.py)."""
import pandas as pd
import pytest

from etl import sequence_file as sf
from etl.common import raw_dir

V = "2006-2010"


def need(path):
    if not path.exists():
        pytest.skip(f"{path.name} not fetched")


@pytest.fixture(scope="module")
def lookup():
    need(sf.lookup_path(V))


@pytest.mark.parametrize("table,sequence,start,cells", [
    # From the 2010 lookup file (sha256 a458000b…ef9f00), checked by hand.
    ("B01003", 11, 192, 1),
    ("B03002", 13, 38, 21),
    ("B15002", 40, 90, 35),
    ("B19025", 53, 195, 1),
    ("B25003", 95, 11, 3),
    ("B25063", 98, 30, 24),
    ("B25065", 98, 55, 1),
    ("B25075", 99, 57, 25),
])
def test_layouts(lookup, table, sequence, start, cells):
    lay = sf.layout(V, table)
    assert (lay.sequence, lay.start, lay.cells) == (sequence, start, cells)


def test_education_cells_are_bachelors_and_above(lookup):
    labels = sf.labels(V)
    four = ["Bachelor's degree", "Master's degree", "Professional school degree", "Doctorate degree"]
    assert [labels[f"B15002_{c:03d}"] for c in range(15, 19)] == four
    assert [labels[f"B15002_{c:03d}"] for c in range(32, 36)] == four
    assert labels["B15002_002"] == "Male:" and labels["B15002_019"] == "Female:"


def test_unknown_table_raises(lookup):
    with pytest.raises(ValueError, match="not in"):
        sf.layout(V, "B15003")


def test_tracts():
    need(raw_dir(V) / sf.geos_name(V, "51"))
    t = sf.tracts(V, "51")
    assert len(t) == 1907
    assert t.GEOID.str.len().eq(11).all() and t.GEOID.str.startswith("51").all()


def test_cells_land_in_the_right_columns():
    """B25003 total = owner + renter in every tract: a shifted slice breaks this."""
    need(raw_dir(V) / sf.sequence_name(V, "51", 95))
    df = sf.to_numeric(sf.load_table(V, "B25003", "51"), V)
    assert (df.E001 == df.E002 + df.E003).all()
    assert len(df) == 1907


def test_missing_tokens_become_nan_and_others_raise(lookup):
    df = pd.DataFrame({"E001": ["1", ".", ""], "M001": ["2", ".", ""]})
    out = sf.to_numeric(df, V)
    assert out.E001.isna().tolist() == [False, True, True]
    with pytest.raises(ValueError, match="non-numeric"):
        sf.to_numeric(pd.DataFrame({"E001": ["N"]}), V)


def test_unknown_state_raises():
    from etl.common import ScopeError
    with pytest.raises(ScopeError, match="not in registry/states.json"):
        sf.state_cfg(V, "72")


def test_state_paths_from_registry():
    assert sf.state_cfg(V, "42") == {"state_name": "Pennsylvania", "stusab": "pa"}
    assert sf.data_url(V, "11", sf.geos_name(V, "11")).endswith(
        "/5_year_seq_by_state/DistrictOfColumbia/Tracts_Block_Groups_Only/g20105dc.csv")
