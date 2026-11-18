"""Inventory of every ACS 5-year detailed table, 2006-2010 vs 2016-2020.

    .venv/bin/python -m analysis.acs_inventory      # -> registry/acs_inventory.json

For each table: topic, title, universe, cell count per vintage, whether its
cell labels match across vintages (comparability for change maps), and whether
2006-2010 publishes it at tract level (checked against every Virginia tract
row in the 118 tract sequence files, not assumed).

Sources, all already-downloaded Census files:
- 2016-2020: ACS2020_Table_Shells.csv, plus the 5YRData/ directory listing
  (which tables have a data file).
- 2006-2010: Sequence_Number_and_Table_Number_Lookup.txt, plus the Virginia
  Tracts_Block_Groups_Only sequence files (data/raw/acs/2006-2010/inventory_va/).
"""
from __future__ import annotations

import csv
import io
import json
import re
import sys
import zipfile
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data/raw/acs"
SHELLS = RAW / "2016-2020/ACS2020_Table_Shells.csv"
LOOKUP = RAW / "2006-2010/Sequence_Number_and_Table_Number_Lookup.txt"
VA_SEQ = RAW / "2006-2010/inventory_va"
TABLES_2020 = Path(sys.argv[1]) if len(sys.argv) > 1 else None

TOPICS = {
    "01": "Age & sex", "02": "Race", "03": "Hispanic origin", "04": "Ancestry",
    "05": "Citizenship & nativity", "06": "Place of birth", "07": "Migration (moved in past year)",
    "08": "Commuting & work travel", "09": "Children & relationship", "10": "Grandparents",
    "11": "Household & family type", "12": "Marital status", "13": "Fertility",
    "14": "School enrollment", "15": "Educational attainment", "16": "Language",
    "17": "Poverty", "18": "Disability", "19": "Income", "20": "Earnings",
    "21": "Veterans", "22": "SNAP (food stamps)", "23": "Employment status",
    "24": "Occupation & industry", "25": "Housing", "26": "Group quarters",
    "27": "Health insurance", "28": "Computers & internet", "29": "Citizen voting-age population",
    "98": "Data quality", "99": "Imputation (data quality)",
}
RACE_ITER = re.compile(r"^([BC]\d{5})([A-I])$")  # B19013A..I: the same table per race group
NORM = re.compile(r"[^a-z0-9$]+")


def norm(label: str) -> str:
    return NORM.sub(" ", label.lower().replace("(in 2020 inflation-adjusted dollars)", "")
                    .replace("(in 2010 inflation-adjusted dollars)", "")).strip()


def shells_2020() -> dict:
    out = defaultdict(lambda: {"title": None, "universe": None, "cells": []})
    with open(SHELLS, encoding="latin-1", newline="") as f:
        for r in csv.DictReader(f):
            t = (r["Table ID"] or "").strip()
            if not t:
                continue
            line, stub = (r["Line"] or "").strip(), (r["Stub"] or "").strip()
            if not line:
                if stub.lower().startswith("universe"):
                    out[t]["universe"] = stub.split(":", 1)[1].strip()
                elif out[t]["title"] is None:
                    out[t]["title"] = stub
            else:
                out[t]["cells"].append(norm(stub))
    return dict(out)


def lookup_2010() -> tuple[dict, dict]:
    tables = defaultdict(lambda: {"title": None, "universe": None, "cells": [], "subject": None})
    layout = {}
    with open(LOOKUP, encoding="latin-1", newline="") as f:
        for r in csv.DictReader(f):
            t = r["Table ID"].strip()
            if r["Start Position"].strip():
                tables[t]["title"] = r["Table Title"].strip()
                tables[t]["subject"] = r["Subject Area"].strip()
                n = int(r["Total Cells in Table"].split()[0])
                layout[t] = (int(r["Sequence Number"]), int(r["Start Position"]), n)
            elif not r["Line Number"].strip() or r["Line Number"].strip() in (".", "0.5"):
                if r["Table Title"].lower().startswith("universe"):
                    tables[t]["universe"] = r["Table Title"].split(":", 1)[1].strip()
            else:
                try:
                    float(r["Line Number"])
                except ValueError:
                    continue
                if "." not in r["Line Number"]:
                    tables[t]["cells"].append(norm(r["Table Title"]))
    return dict(tables), layout


def tract_published_2010(layout: dict) -> dict[str, bool]:
    """A table is published at tract level if any Virginia tract row has a
    non-blank estimate in it ('.' counts: published, not computable)."""
    tract_logs = set()
    geo = next(VA_SEQ.glob("g20105va.csv"), None) or (RAW / "2006-2010/g20105va.csv")
    with open(geo, encoding="latin-1") as f:
        for row in csv.reader(f):
            if row[2] == "140":
                tract_logs.add(row[4])
    by_seq = defaultdict(list)
    for t, (seq, start, n) in layout.items():
        by_seq[seq].append((t, start, n))
    out = {}
    for seq, items in by_seq.items():
        z = VA_SEQ / f"20105va{seq:04d}000.zip"
        if not z.exists():
            continue
        with zipfile.ZipFile(z) as zf:
            with zf.open(f"e20105va{seq:04d}000.txt") as f:
                seen = {t: False for t, _, _ in items}
                for line in io.TextIOWrapper(f, encoding="latin-1"):
                    parts = line.rstrip("\n").split(",")
                    if parts[5] not in tract_logs:
                        continue
                    for t, start, n in items:
                        if not seen[t] and any(v.strip() for v in parts[start - 1:start - 1 + n]):
                            seen[t] = True
                out.update(seen)
    return out


def main() -> int:
    s20 = shells_2020()
    t10, layout = lookup_2010()
    tract10 = tract_published_2010(layout)
    files20 = None
    if TABLES_2020 and TABLES_2020.exists():
        files20 = {re.search(r"acsdt5y2020-([a-z0-9]+)\.dat", l).group(1).upper()
                   for l in TABLES_2020.read_text().split()}
    rows = []
    for t in sorted(set(s20) | set(t10)):
        a, b = t10.get(t), s20.get(t)
        if b is not None and files20 is not None and t not in files20:
            b = None  # in the shells but no 5-year data file
        if a is None and b is None:
            continue  # in the 2020 shells, but 1-year only: no 5-year file
        m = RACE_ITER.match(t)
        base = m.group(1) if m else t
        if a and b:
            if a["cells"] == b["cells"]:
                comp = "identical"
            elif len(a["cells"]) == len(b["cells"]):
                comp = "same cells, labels reworded"
            else:
                comp = "restructured"
        else:
            comp = "2016-20 only" if b else "2006-10 only"
        rows.append({
            "table": t, "base": base, "race_group": m.group(2) if m else None,
            "topic": TOPICS.get(t[1:3], "Other"),
            "title": (b or a)["title"], "universe": (b or a)["universe"],
            "cells_2010": len(a["cells"]) if a else None, "cells_2020": len(b["cells"]) if b else None,
            "tract_2010": tract10.get(t) if a else None,
            "comparable": comp, "collapsed": t.startswith("C"),
        })
    dest = ROOT / "registry/acs_inventory.json"
    dest.write_text(json.dumps({"note": __doc__.split("\n\n")[1].replace("\n", " "), "tables": rows}, indent=1) + "\n")
    from collections import Counter
    print(len(rows), "tables;", Counter(r["comparable"] for r in rows))
    print("2010 tract-published:", Counter(r["tract_2010"] for r in rows))
    return 0


if __name__ == "__main__":
    sys.exit(main())
