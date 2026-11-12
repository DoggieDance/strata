"""Structure of every built Virginia tract cube (spec 03), one run per vintage."""
import json

import numpy as np
import pyarrow as pa
import pytest

from etl.build_cube import build
from etl.clean import GEOID_LENGTH, geo_universe
from etl.common import load_measures


def test_geoid_sorted_unique_virginia(cube, level):
    g = cube.read(columns=["GEOID"]).column("GEOID").to_pylist()
    assert g == sorted(g)
    assert len(g) == len(set(g))
    assert all(len(x) == GEOID_LENGTH[level] for x in g)
    if level != "zcta":  # ZCTA codes carry no state FIPS
        assert all(x.startswith("51") for x in g)


def test_rows_match_geography_file(cube, vintage, level):
    g = cube.read(columns=["GEOID"]).column("GEOID").to_pylist()
    assert g == list(geo_universe(vintage, "51", level))


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


def test_refuses_to_overwrite(cube, vintage, level):
    from tests.conftest import BUILD
    with pytest.raises(FileExistsError):
        build("51", vintage, level, BUILD)


def test_cube_metadata_names_its_vintage_and_level(cube, vintage, level):
    meta = json.loads(cube.schema_arrow.metadata[b"strata"])
    assert (meta["vintage"], meta["level"]) == (vintage, level)


def test_all_cubes_share_columns():
    from tests.conftest import built_combos, cube_path
    import pyarrow.parquet as pq
    schemas = [pq.ParquetFile(cube_path(v, lv)).schema_arrow for v, lv in built_combos() if cube_path(v, lv).exists()]
    assert all(s.names == schemas[0].names for s in schemas)


def test_published_county_counts_equal_summed_tracts():
    """Population and households are controlled totals: tracts sum exactly to the
    published county. (Dollar aggregates need not: each geography is estimated.)"""
    from tests.conftest import cube_path
    import pyarrow.parquet as pq
    for v in ["2016-2020", "2006-2010"]:
        if not (cube_path(v, "county").exists() and cube_path(v).exists()):
            pytest.skip("county or tract cube not built")
        cols = ["GEOID", "total_population_e", "households_e"]
        tr = pq.read_table(cube_path(v), columns=cols).to_pandas()
        co = pq.read_table(cube_path(v, "county"), columns=cols).to_pandas().set_index("GEOID")
        summed = tr.groupby(tr.GEOID.str[:5])[cols[1:]].sum()
        assert (summed.reindex(co.index) == co).all().all(), v


def test_cube_is_current_with_registry(cube):
    """A cube built from an older registry is stale and must be rebuilt."""
    built = json.loads(cube.schema_arrow.metadata[b"strata"])["registry_version"]
    assert built == load_measures()["registry_version"], (
        f"cube built from registry v{built}, registry is now "
        f"v{load_measures()['registry_version']}: rebuild required"
    )
