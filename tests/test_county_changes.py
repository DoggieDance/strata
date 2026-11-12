"""County change maps difference counties by GEOID; this guards the exceptions
(registry/county_changes.json). Review of the national change map: Bedford
County, VA read "+11,268 people, significant" because it absorbed Bedford city."""
import json

import pyarrow.parquet as pq

from tests.conftest import BUILD, ROOT

REG = json.loads((ROOT / "registry/county_changes.json").read_text())


def ids(vintage):
    out = set()
    for p in (BUILD / "acs" / vintage / "county").glob("[0-9][0-9].parquet"):
        out |= set(pq.read_table(p, columns=["GEOID"]).column("GEOID").to_pylist())
    return out


def test_one_period_counties_are_registered():
    a, b = ids("2006-2010"), ids("2016-2020")
    states = {g[:2] for g in a} & {g[:2] for g in b}
    a = {g for g in a if g[:2] in states}
    b = {g for g in b if g[:2] in states}
    covered = set(REG["not_comparable"]) | set(REG["renamed"]) | {r["was"] for r in REG["renamed"].values()}
    assert (a ^ b) - covered == set()


def test_bedford_is_not_comparable():
    assert "51019" in REG["not_comparable"] and "51515" in REG["not_comparable"]
