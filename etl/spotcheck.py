"""Vintage gates: fill a state's spot-check fixture from data.census.gov.

Draws a seeded random sample of (tract, published variable) pairs and fetches
each value from data.census.gov's table endpoint — the published tables, an
independent path from the Summary File the cube is built from.

Validation only. The app never calls this, and nothing here touches the cube.

    python -m etl.spotcheck --vintage 2016-2020   # Phase 01 gate
    python -m etl.spotcheck --vintage 2006-2010   # Phase 02 first-task gate
    python -m etl.spotcheck --vintage 2006-2010 --dry-run
    python -m etl.spotcheck --vintage 2016-2020 --level county   # also place, zcta

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

from etl.common import ROOT, parse_states, state_info

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


# data.census.gov GEO_ID prefix per level.
GEO_PREFIX = {"tract": "1400000US", "county": "0500000US", "place": "1600000US", "zcta": "8600000US"}


def fixture_path(vintage, level="tract", state="51"):
    """Virginia keeps its original gate names; every other state is
    {stusab}_{level}_spotcheck_{vintage}.csv."""
    if state == "51" and level == "tract":
        return ROOT / "tests" / "fixtures" / VINTAGES[vintage]["fixture"]
    ab = state_info(state)["stusab"]
    return ROOT / "tests" / "fixtures" / f"{ab}_{level}_spotcheck_{vintage}.csv"


def cube_path(vintage, level="tract", state="51"):
    return ROOT / "build" / "acs" / vintage / level / f"{state}.parquet"


def table_id(variable, endyear):
    table = variable.split("_")[0]
    kind = "ST" if table.startswith("S") else "DT"
    return f"ACS{kind}5Y{endyear}.{table}"


def fetch(variable, geoid, endyear, level="tract"):
    ucgid = GEO_PREFIX[level] + geoid
    q = urllib.parse.urlencode({"id": table_id(variable, endyear), "g": ucgid})
    req = urllib.request.Request(f"{ENDPOINT}?{q}", headers={"User-Agent": "strata-spotcheck"})
    # data.census.gov also answers 204 when throttling, sometimes several times
    # running. "Not published" is recorded only after five 204s spread over
    # about two minutes; anything else is retried.
    no_content = 0
    for attempt in range(8):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                if r.status == 204:
                    no_content += 1
                    if no_content == 5:
                        return ""
                    time.sleep(8 * no_content)
                    continue
                body = json.load(r)
            break
        except (json.JSONDecodeError, OSError) as e:  # throttled responses come back as non-JSON
            if attempt == 7:
                raise RuntimeError(f"{variable} {geoid}: {e}") from e
            time.sleep(5 * 2 ** min(attempt, 4))
    else:
        raise RuntimeError(f"{variable} {geoid}: no usable response")
    header, *data = body["response"]["data"]
    if len(data) != 1:
        raise RuntimeError(f"{variable} {geoid}: expected 1 row, got {len(data)}")
    row = dict(zip(header, data[0]))
    if row["GEO_ID"] != ucgid:
        raise RuntimeError(f"{variable} {geoid}: got {row['GEO_ID']}")
    # Annotation columns (…EA/…MA) carry the published symbol when the value is
    # suppressed; the value column then holds a jam value. The symbol wins.
    note = row.get(variable + "A")
    if note:
        return note
    return "" if row[variable] is None else row[variable]


def sample(vintage, level="tract", state="51"):
    geoids = pq.read_table(cube_path(vintage, level, state), columns=["GEOID"]).column("GEOID").to_pylist()
    variables = VINTAGES[vintage]["variables"]
    # Seed = the state's FIPS number (Virginia's 51 was the original seed).
    rng = random.Random(SEED if state == "51" else int(state))
    pairs = set()
    while len(pairs) < N:
        pairs.add((rng.choice(geoids), rng.choice(variables)))
    return sorted(pairs)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--vintage", choices=sorted(VINTAGES), required=True)
    ap.add_argument("--level", default="tract", choices=sorted(GEO_PREFIX))
    ap.add_argument("--state", default="51", help="FIPS or postal code")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    (state,) = parse_states(args.state)
    pairs = sample(args.vintage, args.level, state)
    endyear = VINTAGES[args.vintage]["endyear"]
    fixture = fixture_path(args.vintage, args.level, state)
    if args.dry_run:
        for p in pairs:
            print(*p)
        return
    if fixture.exists():
        sys.exit(f"{fixture} exists; the gate fixture is not regenerated. Delete it deliberately.")
    rows = []
    for geoid, var in pairs:
        rows.append({"GEOID": geoid, "variable": var, "value": fetch(var, geoid, endyear, args.level), "source": "data.census.gov"})
        print(geoid, var, rows[-1]["value"])
        time.sleep(0.5)
    with open(fixture, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["GEOID", "variable", "value", "source"])
        w.writeheader()
        w.writerows(rows)


if __name__ == "__main__":
    main()
