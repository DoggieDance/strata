"""Label gate: every measure STRATA shows must equal the figure Census itself
publishes under that name (registry/published_equivalents.json).

    python -m etl.label_check --vintage 2016-2020      # fills the fixture

For sampled tracts and counties in Virginia, Pennsylvania and California, fetch
the Data Profile tables (DP02-DP05) from data.census.gov and record the
variables the registry names. tests/test_published_equivalents.py then checks
(a) Census's label for each variable still reads as recorded, and (b) the value
STRATA serves equals the published one. Validation only; the app never calls this.
"""
from __future__ import annotations

import argparse
import csv
import json
import random
import sys
import time
from pathlib import Path

import pyarrow.parquet as pq

from etl.common import REGISTRY_DIR, ROOT
from etl.spotcheck import GEO_PREFIX, fetch_row

STATES = {"51": 8, "42": 8, "06": 8}  # tracts per state; plus 2 counties each
YEAR = {"2006-2010": 2010, "2011-2015": 2015, "2015-2019": 2019, "2016-2020": 2020, "2020-2024": 2024}


def registry() -> dict:
    return json.loads((REGISTRY_DIR / "published_equivalents.json").read_text())


def fixture(vintage: str):
    return ROOT / "tests" / "fixtures" / f"published_equivalents_{vintage}.csv"


def sample(vintage: str, build=ROOT / "build", plan=None) -> list[tuple[str, str]]:
    """plan: {state: {level: count}}; default STATES (tracts, plus 2 counties)."""
    plan = plan or {st: {"tract": n, "county": 2} for st, n in STATES.items()}
    out = []
    for st, levels in plan.items():
        rng = random.Random(int(st) * 1000 + YEAR[vintage])
        for level, k in levels.items():
            ids = pq.read_table(build / "acs" / vintage / level / f"{st}.parquet", columns=["GEOID"]).column(0).to_pylist()
            out += [(level, g) for g in sorted(rng.sample(ids, k))]
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--vintage", choices=sorted(YEAR), required=True)
    ap.add_argument("--build", type=Path, default=ROOT / "build", help="build folder to sample GEOIDs from")
    ap.add_argument("--add", help="add geographies to an existing fixture, e.g. 25:tract=8,county=2;21:county=4,place=4. "
                    "Rows already there are kept untouched; new ones are appended.")
    args = ap.parse_args(argv)
    dest = fixture(args.vintage)
    plan, kept = None, []
    if args.add:
        plan = {st: {lv: int(n) for lv, n in (x.split("=") for x in spec.split(","))}
                for st, spec in (part.split(":") for part in args.add.split(";"))}
        if dest.exists():
            kept = list(csv.DictReader(open(dest, newline="")))
    elif dest.exists():
        sys.exit(f"{dest} exists; the gate fixture is not regenerated. Delete it deliberately (or use --add).")
    need = {}
    for m, d in registry()["equivalents"].items():
        if args.vintage in d:
            for v in d[args.vintage]["variables"]:
                need.setdefault(v.split("_")[0], set()).add(v)
    rows = []
    have = {(r["level"], r["GEOID"]) for r in kept}
    for level, geoid in sample(args.vintage, args.build, plan):
        if (level, geoid) in have:
            continue
        for table, variables in sorted(need.items()):
            row = fetch_row(f"ACSDP5Y{YEAR[args.vintage]}.{table}", GEO_PREFIX[level] + geoid)
            for v in sorted(variables):
                val = "" if row is None else (row.get(v + "A") or row.get(v) or "")
                rows.append({"level": level, "GEOID": geoid, "variable": v, "value": val})
            time.sleep(0.4)
        print(level, geoid, "ok", flush=True)
    with open(dest, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["level", "GEOID", "variable", "value"])
        w.writeheader()
        w.writerows(kept + rows)
    print(f"wrote {dest} ({len(kept)} kept + {len(rows)} new values)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
