"""Phase 02 gates for every state built (national scope, 2026-11-12):
conservation of the 2020 population through the crosswalk, and of counts
through the harmonizer; one row per target tract; weights summing to 1."""
import json

import numpy as np
import pyarrow.parquet as pq
import pytest

from tests.conftest import BUILD

XW = sorted((BUILD / "crosswalk/2010-2020/tract").glob("[0-9][0-9].parquet"))
HARM = sorted((BUILD / "harmonized/2006-2010/tract-2020").glob("[0-9][0-9].parquet"))


@pytest.mark.parametrize("path", XW, ids=[p.stem for p in XW])
def test_crosswalk_conserves_2020_population(path):
    d = json.loads(pq.ParquetFile(path).schema_arrow.metadata[b"strata"])["diagnostics"]
    assert d["pop_assigned"] + d["pop_in_foreign_2010_blocks"] == pytest.approx(d["pop_2020_state"], abs=1e-6)
    xw = pq.read_table(path).to_pandas()
    assert np.allclose(xw.groupby("source").weight.sum(), 1.0)
    assert xw.source.str[:2].eq(path.stem).all()


@pytest.mark.parametrize("path", HARM, ids=[p.stem for p in HARM])
def test_harmonized_counts_conserved(path):
    st = path.stem
    src = pq.read_table(BUILD / f"acs/2006-2010/tract/{st}.parquet", columns=["total_population_e", "households_e"]).to_pandas()
    got = pq.read_table(path, columns=["GEOID", "total_population_e", "households_e"]).to_pandas()
    tgt = pq.read_table(BUILD / f"acs/2016-2020/tract/{st}.parquet", columns=["GEOID"]).column(0).to_pylist()
    assert got.GEOID.tolist() == tgt  # one row per 2020 tract, same order
    for c in ("total_population_e", "households_e"):
        # Float32 storage; a 2010 tract that maps only into another state's
        # 2020 tracts would leave the state, which the crosswalk forbids.
        assert got[c].sum() == pytest.approx(src[c].sum(), rel=1e-6), c


def test_national_county_file_matches_states():
    us = BUILD / "acs/2016-2020/county/us.parquet"
    if not us.exists():
        pytest.skip("national county file not built yet")
    t = pq.read_table(us)
    parts = sorted(p for p in (BUILD / "acs/2016-2020/county").glob("[0-9][0-9].parquet"))
    assert len(parts) == 51
    assert t.num_rows == sum(pq.ParquetFile(p).metadata.num_rows for p in parts)
    for p in parts[:: 10]:
        s = pq.read_table(p)
        ids = set(s.column("GEOID").to_pylist())
        sub = t.filter(np.isin(t.column("GEOID").to_numpy(zero_copy_only=False), list(ids)))
        assert sub.drop(["GEOID"]).to_pydict() == s.drop(["GEOID"]).to_pydict()
