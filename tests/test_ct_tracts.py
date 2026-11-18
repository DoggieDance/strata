"""Connecticut 2020-24 tracts re-keyed to 2020 codes (etl/ct_tracts.py)."""
import json

import pyarrow.parquet as pq
import pytest

from tests.conftest import BUILD

P = BUILD / "harmonized/2020-2024/tract-2020/09.parquet"
pytestmark = pytest.mark.skipif(not P.exists(), reason="CT 2020-24 not re-keyed in this build")


def test_rekeyed_codes_are_2020_codes_and_one_to_one():
    got = pq.read_table(P, columns=["GEOID"]).column(0).to_pylist()
    ref = set(pq.read_table(BUILD / "acs/2016-2020/tract/09.parquet", columns=["GEOID"]).column(0).to_pylist())
    meta = json.loads(P.with_suffix(".meta.json").read_text())
    assert len(got) == len(set(got))
    mapped = [g for g in got if g not in meta["unmapped_rows"]]
    assert set(mapped) <= ref and len(mapped) == meta["mapped"]


def test_boundary_corrected_tracts_are_empty_and_others_are_not():
    meta = json.loads(P.with_suffix(".meta.json").read_text())
    t = pq.read_table(P, columns=["GEOID", "total_population_e"]).to_pandas().set_index("GEOID")
    bad = set(meta["boundary_corrected"])
    assert 0 < len(bad) <= 10 and all(abs(r - 1) > 0.01 for r in meta["boundary_corrected"].values())
    assert t.loc[sorted(bad), "total_population_e"].isna().all()
    others = t.drop(index=sorted(bad) + meta["unmapped_rows"], errors="ignore")
    assert others.total_population_e.notna().mean() > 0.99
