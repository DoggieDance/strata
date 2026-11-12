"""Vintage gates: published data.census.gov values must match the cube.

Fixtures (columns GEOID,variable,value,source; variable as data.census.gov
names it, e.g. B19025_001E):

- va_tract_spotcheck.csv            2016-2020, Phase 01 gate
- va_tract_spotcheck_2006-2010.csv  2006-2010, Phase 02 first-task gate
- va_tract_nulls_2006-2010.csv      2006-2010 missing-value cases ('.' and blank)
- va_tract_education_2006-2010.csv  2006-2010 B15002 recomputation vs published S1501

The random ones are filled once by `python -m etl.spotcheck --vintage …`
(seed 51) from data.census.gov's published tables, an independent path from
the Summary File the cube is built from. Never regenerated; skipped if absent.
"""
import csv
import math

import pytest

from tests.conftest import ROOT, open_cube

FIXTURES = ROOT / "tests" / "fixtures"

COMMON = {
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
}

# published variable -> (cube column, tolerance), per vintage
COLUMN = {
    "2016-2020": {
        **COMMON,
        "B15003_001E": ("pop_25_plus_e", 0),
        "S1501_C01_006E": ("pop_25_plus_e", 0),
        # S1501 publishes one decimal; the cube recomputes from B15003
        "S1501_C02_015E": ("pct_bachelors_plus_e", 0.05),
    },
    "2006-2010": {
        **COMMON,
        "B15002_001E": ("pop_25_plus_e", 0),
        "B15002_001M": ("pop_25_plus_m", 0),
        # 2010 S1501 puts percent bachelor's-or-higher in C01_015 (2020: C02_015).
        # One decimal published; the cube recomputes from B15002.
        "S1501_C01_015E": ("pct_bachelors_plus_e", 0.05),
    },
}

FILES = [
    ("2016-2020", "va_tract_spotcheck.csv"),
    ("2006-2010", "va_tract_spotcheck_2006-2010.csv"),
    ("2006-2010", "va_tract_nulls_2006-2010.csv"),
    ("2006-2010", "va_tract_education_2006-2010.csv"),
]

NULL = ("", "-", "N", "(X)", "*****", "**", "null")


def cases():
    out = []
    for vintage, name in FILES:
        path = FIXTURES / name
        if not path.exists():
            out.append(pytest.param(vintage, name, None, id=f"{name}-missing"))
            continue
        with open(path, newline="") as f:
            for row in csv.DictReader(f):
                out.append(pytest.param(vintage, name, row,
                                        id=f"{vintage}-{row['GEOID']}-{row['variable']}"))
    return out


@pytest.mark.parametrize("vintage,name,row", cases())
def test_spotcheck(vintage, name, row):
    if row is None:
        pytest.skip(f"tests/fixtures/{name} not filled in yet")
    cube = open_cube(vintage)
    col, tol = COLUMN[vintage][row["variable"]]
    t = cube.read(columns=["GEOID", col]).to_pydict()
    got = t[col][t["GEOID"].index(row["GEOID"])]
    want = row["value"].strip()
    if want in NULL:
        assert got is None or math.isnan(got)
    else:
        assert got is not None and abs(got - float(want.replace(",", ""))) <= tol


def test_random_fixtures_have_twenty_rows():
    for vintage, name in FILES[:2]:
        path = FIXTURES / name
        if path.exists():
            with open(path, newline="") as f:
                assert len(list(csv.DictReader(f))) == 20, name
