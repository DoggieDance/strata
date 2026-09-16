"""Jam-value guard (spec 08). No value below -1e8 in any built artifact. Hard fail."""
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq
import pytest
from hypothesis import given
from hypothesis import strategies as st

from etl.clean import JamValueError, strip_jams
from etl.common import JAM_FLOOR, controlled_moe_value, jam_values
from tests.conftest import built_artifacts

CONTROLLED = controlled_moe_value()
JAMS = sorted(jam_values())
ALL_SENTINELS = sorted(JAMS + [CONTROLLED])


def test_registry_separates_missing_from_controlled():
    assert set(JAMS) == {-666666666, -999999999, -888888888, -222222222, -333333333}
    assert CONTROLLED == -555555555


def assert_no_jams(path):
    table = pq.read_table(path)
    for name, col in zip(table.column_names, table.columns):
        if not pa.types.is_integer(col.type) and not pa.types.is_floating(col.type):
            continue
        col = pc.cast(col, pa.float64())
        low = pc.min(col).as_py()
        assert low is None or low >= JAM_FLOOR, f"{path.name}:{name} has {low}"
        for j in ALL_SENTINELS:
            assert not pc.any(pc.equal(col, j)).as_py(), f"{path.name}:{name} has {j}"


@pytest.mark.parametrize("path", built_artifacts() or [None], ids=lambda p: p and p.name)
def test_no_jam_value_in_any_built_artifact(path):
    if path is None:
        pytest.skip("no built artifacts")
    assert_no_jams(path)


@pytest.mark.parametrize("jam", ALL_SENTINELS)
@pytest.mark.parametrize("dtype", [pa.float32(), pa.float64(), pa.int64()])
def test_guard_catches_a_poisoned_file(tmp_path, jam, dtype):
    path = tmp_path / "poisoned.parquet"
    pq.write_table(pa.table({"GEOID": ["51001090101", "51001090102"],
                             "x_e": pa.array([1, jam], type=pa.float64()).cast(dtype)}), path)
    with pytest.raises(AssertionError):
        assert_no_jams(path)


plain = st.one_of(
    st.integers(min_value=0, max_value=10**11),
    st.floats(min_value=0, max_value=1e11, allow_nan=False),
)
estimates = st.one_of(st.sampled_from(JAMS), plain)
margins = st.one_of(st.sampled_from(ALL_SENTINELS), plain)
row = st.tuples(estimates, margins, estimates, margins)


@given(st.lists(row, min_size=1, max_size=40))
def test_strip_jams_leaves_nothing_below_floor(rows):
    df = pd.DataFrame(rows, columns=["E001", "M001", "E002", "M002"])
    out = strip_jams(df)
    arr = out.to_numpy()
    assert not (arr[np.isfinite(arr)] < JAM_FLOOR).any()
    src = df.to_numpy(dtype="float64")
    is_jam = np.isin(src, JAMS)
    is_ctrl = src == CONTROLLED
    assert np.isnan(arr[is_jam]).all()          # missing -> null
    assert (arr[is_ctrl] == 0).all()             # controlled MOE -> zero
    keep = ~is_jam & ~is_ctrl
    np.testing.assert_array_equal(arr[keep], src[keep])


def test_controlled_value_in_an_estimate_raises():
    with pytest.raises(JamValueError, match="estimate"):
        strip_jams(pd.DataFrame({"E001": [5103.0, float(CONTROLLED)], "M001": [0.0, 0.0]}))


def test_controlled_moe_propagates_as_zero():
    from etl.clean import ratio
    t = strip_jams(pd.DataFrame({"E001": [5103.0], "M001": [float(CONTROLLED)],
                                 "E002": [2000.0], "M002": [150.0]}))
    p, m = ratio(t.E002, t.M002, t.E001, t.M001, proportion=True)
    assert m[0] == pytest.approx(150.0 / 5103.0)


@given(st.integers(max_value=int(JAM_FLOOR) - 1).filter(lambda v: v not in ALL_SENTINELS))
def test_unknown_sentinel_raises(v):
    with pytest.raises(JamValueError):
        strip_jams(pd.DataFrame({"E001": [1.0, float(v)]}))
