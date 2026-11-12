"""Vintage gates: fill a Virginia tract spot-check fixture from data.census.gov.

Draws a seeded random sample of (tract, published variable) pairs and fetches
each value from data.census.gov's table endpoint — the published tables, an
independent path from the Summary File the cube is built from.

Validation only. The app never calls this, and nothing here touches the cube.

    python -m etl.spotcheck --vintage 2016-2020   # Phase 01 gate
    python -m etl.spotcheck --vintage 2006-2010   # Phase 02 first-task gate
    python -m etl.spotcheck --vintage 2006-2010 --dry-run

Published values come back as text. A suppressed value is published as a jam
value with a symbol in the annotation column (e.g. -666666666 with "-"); the
symbol is recorded, and the test reads it as null. A 204 means the table is
not published for that tract, recorded as "" (null).
"""
import argparse
import csv
import json
import random
import sys
import time
import urllib.parse
import urllib.request

import pyarrow.parquet as pq

from etl.common import ROOT

ENDPOINT = "https://data.census.gov/api/access/data/table"
SEED = 51
N = 20

COMMON = [
    "B19025_001E", "B19025_001M",
    "B25065_001E", "B25065_001M",
    "B25003_001E", "B25003_002E", "B25003_003E", "B25003_003M",
    "B25063_002E", "B25063_002M",
    "B01003_001E", "B01003_001M",
]
# Published variables each gate checks. Keep in sync with tests/test_spotcheck.py.
# 2006-2010 has no B15003; its S1501 uses a different column layout, so the
# education check there is the B15002 total the cube's pop_25_plus comes from.
VINTAGES = {
    "2016-2020": {"endyear": 2020, "fixture": "va_tract_spotcheck.csv",
                  "variables": COMMON + ["B15003_001E", "S1501_C02_015E"]},
    "2006-2010": {"endyear": 2010, "fixture": "va_tract_spotcheck_2006-2010.csv",
                  "variables": COMMON + ["B15002_001E", "B15002_001M"]},
}


def fixture_path(vintage):
    return ROOT / "tests" / "fixtures" / VINTAGES[vintage]["fixture"]


def cube_path(vintage):
    return ROOT / "build" / "acs" / vintage / "tract" / "51.parquet"


def table_id(variable, endyear):
    table = variable.split("_")[0]
    kind = "ST" if table.startswith("S") else "DT"
    return f"ACS{kind}5Y{endyear}.{table}"


def fetch(variable, geoid, endyear):
    q = urllib.parse.urlencode({"id": table_id(variable, endyear), "g": f"1400000US{geoid}"})
    req = urllib.request.Request(f"{ENDPOINT}?{q}", headers={"User-Agent": "strata-spotcheck"})
    no_content = 0
    for attempt in range(5):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                if r.status == 204:
                    # Not published for this geography -- but confirm it, so a
                    # throttled empty reply is not recorded as "not published".
                    no_content += 1
                    if no_content == 2:
                        return ""
                    time.sleep(5)
                    continue
                body = json.load(r)
            break
        except (json.JSONDecodeError, OSError) as e:  # throttled responses come back as non-JSON
            if attempt == 4:
                raise RuntimeError(f"{variable} {geoid}: {e}") from e
            time.sleep(5 * 2 ** attempt)
    header, *data = body["response"]["data"]
    if len(data) != 1:
        raise RuntimeError(f"{variable} {geoid}: expected 1 row, got {len(data)}")
    row = dict(zip(header, data[0]))
    if row["GEO_ID"] != f"1400000US{geoid}":
        raise RuntimeError(f"{variable} {geoid}: got {row['GEO_ID']}")
    # Annotation columns (…EA/…MA) carry the published symbol when the value is
    # suppressed; the value column then holds a jam value. The symbol wins.
    note = row.get(variable + "A")
    if note:
        return note
    return "" if row[variable] is None else row[variable]


def sample(vintage):
    geoids = pq.read_table(cube_path(vintage), columns=["GEOID"]).column("GEOID").to_pylist()
    variables = VINTAGES[vintage]["variables"]
    rng = random.Random(SEED)
    pairs = set()
    while len(pairs) < N:
        pairs.add((rng.choice(geoids), rng.choice(variables)))
    return sorted(pairs)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--vintage", choices=sorted(VINTAGES), required=True)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    pairs = sample(args.vintage)
    endyear = VINTAGES[args.vintage]["endyear"]
    fixture = fixture_path(args.vintage)
    if args.dry_run:
        for p in pairs:
            print(*p)
        return
    if fixture.exists():
        sys.exit(f"{fixture} exists; the gate fixture is not regenerated. Delete it deliberately.")
    rows = []
    for geoid, var in pairs:
        rows.append({"GEOID": geoid, "variable": var, "value": fetch(var, geoid, endyear), "source": "data.census.gov"})
        print(geoid, var, rows[-1]["value"])
        time.sleep(0.5)
    with open(fixture, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["GEOID", "variable", "value", "source"])
        w.writeheader()
        w.writerows(rows)


if __name__ == "__main__":
    main()
