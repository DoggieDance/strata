"""Phase 01 gate: values hand-copied from data.census.gov must match the cube.

Fixture: tests/fixtures/va_tract_spotcheck.csv, columns GEOID,variable,value
(variable as data.census.gov names it, e.g. B19025_001E), plus a source column.
Filled once by `python -m etl.spotcheck` (seed 51) from data.census.gov's
published tables, an independent path from the Summary File prototype the cube
is built from. Never regenerated; skipped if absent.
"""
import csv
import math

import pytest

from tests.conftest import ROOT

FIXTURE = ROOT / "tests" / "fixtures" / "va_tract_spotcheck.csv"

# published variable -> (cube column, tolerance)
COLUMN = {
    "B19025_001E": ("agg_household_income_e", 0),
    "B19025_001M": ("agg_household_income_m", 0),
    "B25065_001E": ("agg_gross_rent_e", 0),
    "B25065_001M": ("agg_gross_rent_m", 0),
    "B25003_001E": ("households_e", 0),
    "B25003_001M": ("households_m", 0),
    "B25003_002E": ("owner_households_e", 0),
    "B25003_002M": ("owner_households_m", 0),
    "B25003_003E": ("renter_households_e", 0),
    "B25003_003M": ("renter_households_m", 0),
    "B25063_002E": ("cash_rent_renter_households_e", 0),
    "B25063_002M": ("cash_rent_renter_households_m", 0),
    "B01003_001E": ("total_population_e", 0),
    "B01003_001M": ("total_population_m", 0),
    "B15003_001E": ("pop_25_plus_e", 0),
    "S1501_C01_006E": ("pop_25_plus_e", 0),
    # S1501 publishes one decimal; the cube recomputes from B15003
    "S1501_C02_015E": ("pct_bachelors_plus_e", 0.05),
}


def rows():
    if not FIXTURE.exists():
        return []
    with open(FIXTURE, newline="") as f:
        return list(csv.DictReader(f))


@pytest.mark.parametrize("row", rows() or [None], ids=lambda r: r and f"{r['GEOID']}-{r['variable']}")
def test_spotcheck(row, cube):
    if row is None:
        pytest.skip("tests/fixtures/va_tract_spotcheck.csv not filled in yet")
    col, tol = COLUMN[row["variable"]]
    t = cube.read(columns=["GEOID", col]).to_pydict()
    got = t[col][t["GEOID"].index(row["GEOID"])]
    want = row["value"].strip()
    if want in ("", "-", "N", "(X)", "*****", "null"):
        assert got is None or math.isnan(got)
    else:
        assert abs(got - float(want.replace(",", ""))) <= tol
