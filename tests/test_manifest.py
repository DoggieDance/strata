"""build/manifest.json: the ETL/app contract (spec 03)."""
import json

import pyarrow.parquet as pq
import pytest

from etl.write_manifest import build, overlaps
from tests.conftest import BUILD


@pytest.fixture(scope="module")
def manifest():
    if not (BUILD / "acs").exists():
        pytest.skip("nothing built")
    return build(BUILD)


def files(m):
    for lv in m["levels"].values():
        for states in lv["vintages"].values():
            yield from states.values()
        for h in lv.get("harmonized", {}).values():
            yield from h["states"].values()


def test_every_listed_file_exists_with_its_row_count(manifest):
    entries = list(files(manifest))
    assert entries
    for e in entries:
        for k in ("cube", "geo", "names"):
            assert (BUILD / e[k]).exists(), e[k]
        assert pq.ParquetFile(BUILD / e["cube"]).metadata.num_rows == e["rows"]


def test_unpublished_levels_are_explained(manifest):
    z = manifest["levels"]["zcta"]
    assert "2006-2010" not in z["vintages"] and "2006-2010" in z["unavailable"]


def test_only_non_overlapping_periods_compare():
    assert not overlaps("2006-2010", "2016-2020")
    assert overlaps("2014-2018", "2016-2020")  # shares 2016-2018: spec 05 refuses


def test_comparisons_and_deflators(manifest):
    (c,) = manifest["comparisons"]
    assert c == {"from": "2006-2010", "to": "2016-2020", "valid": True, "why": "non-overlapping periods"}
    a = manifest["deflators"]["annual"]
    assert a["2020"] / a["2010"] == pytest.approx(1.1906, abs=1e-4)


def test_measures_carry_kind_and_dollar_flags(manifest):
    by = {m["id"]: m for m in manifest["measures"]}
    assert by["mean_household_income"]["dollars"] and by["mean_household_income"]["kind"] == "mean"
    assert not by["pct_bachelors_plus"]["dollars"]
    assert all("kind" in m for m in manifest["measures"])


def test_written_manifest_is_current(manifest):
    path = BUILD / "manifest.json"
    if not path.exists():
        pytest.skip("manifest not written")
    on_disk = json.loads(path.read_text())
    on_disk.pop("built"); manifest = dict(manifest); manifest.pop("built")
    assert on_disk == manifest, "build/manifest.json is stale: run python -m etl.write_manifest"
