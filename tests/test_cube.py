"""Structure of the Phase 01 cube (spec 03)."""
import json

import numpy as np
import pyarrow as pa
import pytest

from etl.build_cube import build
from etl.clean import tract_universe
from etl.common import load_measures


def test_geoid_sorted_unique_virginia(cube):
    g = cube.read(columns=["GEOID"]).column("GEOID").to_pylist()
    assert g == sorted(g)
    assert len(g) == len(set(g))
    assert all(len(x) == 11 and x.startswith("51") for x in g)


def test_rows_match_geography_file(cube):
    g = cube.read(columns=["GEOID"]).column("GEOID").to_pylist()
    assert g == list(tract_universe("2016-2020", "51"))


def test_layout(cube):
    md = cube.metadata
    assert all(md.row_group(i).num_rows <= 8000 for i in range(md.num_row_groups))
    for i in range(md.num_row_groups):
        rg = md.row_group(i)
        for j in range(rg.num_columns):
            assert rg.column(j).compression == "ZSTD"


def test_columns_paired_and_typed(cube):
    schema = cube.schema_arrow
    names = schema.names[1:]
    assert schema.names[0] == "GEOID"
    stems_e = {n[:-2] for n in names if n.endswith("_e")}
    stems_m = {n[:-2] for n in names if n.endswith("_m")}
    assert stems_e == stems_m and len(names) == 2 * len(stems_e)
    notes = json.loads(schema.metadata[b"strata"])["measures"]
    for n in names:
        kind = notes[n[:-2]]["kind"]
        want = pa.float64() if kind == "aggregate" else pa.float32()
        assert schema.field(n).type == want, n


def test_published_integers_survive_exactly(cube):
    t = cube.read(columns=["agg_household_income_e", "agg_gross_rent_e", "households_e",
                           "total_population_e", "pop_25_plus_e"])
    for name, col in zip(t.column_names, t.columns):
        v = col.to_numpy(zero_copy_only=False)
        v = v[~np.isnan(v)]
        assert (v == np.round(v)).all(), name


def test_no_nan_only_nulls(cube):
    t = cube.read()
    for name, col in zip(t.column_names[1:], t.columns[1:]):
        v = col.to_numpy(zero_copy_only=False)
        assert np.isnan(v).sum() == col.null_count, f"{name} has NaN that is not null"


def test_refuses_to_overwrite(cube, tmp_path):
    from tests.conftest import BUILD
    with pytest.raises(FileExistsError):
        build("51", "2016-2020", "tract", BUILD)


def test_cube_is_current_with_registry(cube):
    """A cube built from an older registry is stale and must be rebuilt."""
    built = json.loads(cube.schema_arrow.metadata[b"strata"])["registry_version"]
    assert built == load_measures()["registry_version"], (
        f"cube built from registry v{built}, registry is now "
        f"v{load_measures()['registry_version']}: rebuild required"
    )
