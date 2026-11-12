"""Phase 01 gate: fill tests/fixtures/va_tract_spotcheck.csv from data.census.gov.

Draws a seeded random sample of (tract, published variable) pairs and fetches
each value from data.census.gov's table endpoint — the published tables, an
independent path from the Summary File prototype the cube is built from.

Validation only. The app never calls this, and nothing here touches the cube.

    python -m etl.spotcheck            # writes the fixture (refuses to overwrite)
    python -m etl.spotcheck --dry-run  # prints the sample only
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

CUBE = ROOT / "build" / "acs" / "2016-2020" / "tract" / "51.parquet"
FIXTURE = ROOT / "tests" / "fixtures" / "va_tract_spotcheck.csv"
ENDPOINT = "https://data.census.gov/api/access/data/table"
SEED = 51
N = 20

# Published variables the gate checks. Keep in sync with tests/test_spotcheck.py.
VARIABLES = [
    "B19025_001E", "B19025_001M",
    "B25065_001E", "B25065_001M",
    "B25003_001E", "B25003_002E", "B25003_003E", "B25003_003M",
    "B25063_002E", "B25063_002M",
    "B01003_001E", "B01003_001M",
    "B15003_001E", "S1501_C02_015E",
]


def table_id(variable):
    table = variable.split("_")[0]
    prefix = "ACSST5Y2020" if table.startswith("S") else "ACSDT5Y2020"
    return f"{prefix}.{table}"


def fetch(variable, geoid):
    q = urllib.parse.urlencode({"id": table_id(variable), "g": f"1400000US{geoid}"})
    req = urllib.request.Request(f"{ENDPOINT}?{q}", headers={"User-Agent": "strata-spotcheck"})
    for attempt in range(5):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
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
    value = row[variable]
    # Annotation columns (…EA/…MA) carry the published symbol when the value is suppressed.
    note = row.get(variable + "A")
    return note if value is None and note else ("" if value is None else value)


def sample():
    geoids = pq.read_table(CUBE, columns=["GEOID"]).column("GEOID").to_pylist()
    rng = random.Random(SEED)
    pairs = set()
    while len(pairs) < N:
        pairs.add((rng.choice(geoids), rng.choice(VARIABLES)))
    return sorted(pairs)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    pairs = sample()
    if args.dry_run:
        for p in pairs:
            print(*p)
        return
    if FIXTURE.exists():
        sys.exit(f"{FIXTURE} exists; the gate fixture is not regenerated. Delete it deliberately.")
    rows = []
    for geoid, var in pairs:
        rows.append({"GEOID": geoid, "variable": var, "value": fetch(var, geoid), "source": "data.census.gov"})
        print(geoid, var, rows[-1]["value"])
        time.sleep(0.5)
    with open(FIXTURE, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["GEOID", "variable", "value", "source"])
        w.writeheader()
        w.writerows(rows)


if __name__ == "__main__":
    main()
