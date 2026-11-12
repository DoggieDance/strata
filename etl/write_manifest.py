"""Write build/manifest.json: the contract between the ETL and the app (spec 03).

It lists what exists (cubes, geometry, harmonized cubes per state, level and
vintage), how to present it (registry/presentation.json), the deflators the app
needs where vintages meet, and which vintage pairs may be compared (spec 05:
non-overlapping periods only). Paths are relative to the manifest's own folder.
The app reads nothing it does not find here.

    python -m etl.write_manifest
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pyarrow.parquet as pq

from etl.common import REGISTRY_DIR, LevelUnavailable, level_cfg, load_measures, load_summary_files
from etl.deflate import series, vintage_year


def _years(v: str) -> range:
    a, b = (int(x) for x in v.split("-"))
    return range(a, b + 1)


def overlaps(a: str, b: str) -> bool:
    return bool(set(_years(a)) & set(_years(b)))


def build(out: Path) -> dict:
    pres = json.loads((REGISTRY_DIR / "presentation.json").read_text())
    reg = load_measures()
    vintages = sorted(load_summary_files()["vintages"])
    kinds = {}
    for m in reg["measures"]:
        kinds[m["id"]] = {"kind": m["kind"], "dollars": bool(m.get("dollars"))}
        if m.get("derives"):
            kinds[m["derives"]] = {"kind": "mean", "dollars": bool(m.get("dollars"))}
    for d in reg["denominators"]:
        kinds.setdefault(d, {"kind": "count", "dollars": False})

    def rows(rel: str) -> int:
        return pq.ParquetFile(out / rel).metadata.num_rows

    levels = {}
    for lv, p in pres["levels"].items():
        entry = {**p, "vintages": {}}
        for v in vintages:
            try:
                level_cfg(v, lv)
            except LevelUnavailable as e:
                entry.setdefault("unavailable", {})[v] = str(e).split(": ", 1)[1]
                continue
            states = {}
            for st in pres["states"]:
                cube = f"acs/{v}/{lv}/{st}.parquet"
                geo = f"geo/{v}/{lv}/{st}.geojson"
                if not (out / cube).exists() or not (out / geo).exists():
                    continue
                states[st] = {"cube": cube, "geo": geo, "names": f"geo/{v}/{lv}/{st}.names.json",
                              "rows": rows(cube)}
            if states:
                entry["vintages"][v] = states
        harm = {}
        for st in pres["states"]:
            h = f"harmonized/2006-2010/{lv}-2020/{st}.parquet"
            if (out / h).exists():
                harm.setdefault("2006-2010", {"onto": "2016-2020", "states": {}})["states"][st] = {
                    "cube": h, "geo": f"geo/2016-2020/{lv}/{st}.geojson",
                    "names": f"geo/2016-2020/{lv}/{st}.names.json", "rows": rows(h)}
        if harm:
            entry["harmonized"] = harm
        levels[lv] = entry

    s = series()
    years = sorted({vintage_year(v) for v in vintages})
    comparisons = [{"from": a, "to": b, "valid": not overlaps(a, b),
                    "why": "overlapping periods share sample years" if overlaps(a, b) else "non-overlapping periods"}
                   for i, a in enumerate(vintages) for b in vintages[i + 1:]]
    return {
        "built": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "base": ".",
        "registry_version": reg["registry_version"],
        "states": pres["states"],
        "vintages": {v: {**pres["vintages"].get(v, {"label": v}), "dollars_year": vintage_year(v)} for v in vintages},
        "levels": levels,
        "measures": [{**m, **kinds.get(m["id"], {})} for m in pres["measures"]],
        "deflators": {"series": "R-CPI-U-RS", "annual": {str(y): s[y] for y in years}},
        "comparisons": comparisons,
        "significance": {"z": 1.645, "confidence": 0.90, "source": "spec 05"},
        "reliability": {"cv_high_below": 12, "cv_low_above": 40, "source": "spec 05"},
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", type=Path, default=Path("build"))
    args = ap.parse_args(argv)
    m = build(args.out)
    path = args.out / "manifest.json"
    path.write_text(json.dumps(m, indent=2, ensure_ascii=False) + "\n")
    print(f"wrote {path} ({path.stat().st_size:,} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
