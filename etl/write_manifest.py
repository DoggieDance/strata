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

import numpy as np
import pyarrow.parquet as pq

from etl.common import load_states, REGISTRY_DIR, LevelUnavailable, level_cfg, load_measures, load_summary_files
from etl.deflate import series, vintage_year


def _years(v: str) -> range:
    a, b = (int(x) for x in v.split("-"))
    return range(a, b + 1)


def overlaps(a: str, b: str) -> bool:
    return bool(set(_years(a)) & set(_years(b)))


def tier_ok(e: np.ndarray, m: np.ndarray) -> np.ndarray:
    """Reliable enough to color: the app's tier() is not "low" (spec 05: CV <= 40%,
    on the CV rounded to one decimal as displayed; an estimate of 0 only with MOE 0)."""
    with np.errstate(divide="ignore", invalid="ignore"):
        # Math.round in the app rounds halves up; np.round rounds them to even.
        cv = np.floor(m / 1.645 / np.abs(e) * 1000 + 0.5) / 10
    ok = np.isfinite(e) & np.isfinite(m) & (cv <= 40)
    return np.where(e == 0, np.isfinite(m) & (m == 0), ok)


def quintiles(values: np.ndarray) -> list[float]:
    """The app's quantileBreaks(values, 5), so national and state maps agree."""
    s = np.sort(values)
    return [float(s[int(np.floor(i / 5 * (len(s) - 1)))]) for i in range(1, 5)]


def national_breaks(out: Path, files: list[str], measures: list[str]) -> dict:
    cols = [c for m in measures for c in (f"{m}_e", f"{m}_m")]
    tables = [pq.read_table(out / f, columns=cols) for f in files]
    res = {}
    for m in measures:
        e = np.concatenate([t.column(f"{m}_e").to_numpy(zero_copy_only=False).astype("float64") for t in tables])
        mo = np.concatenate([t.column(f"{m}_m").to_numpy(zero_copy_only=False).astype("float64") for t in tables])
        v = e[tier_ok(e, mo)]
        if len(v) >= 5:
            res[m] = {"breaks": quintiles(v), "n": int(len(v))}
    return res


def _stack(out: Path, files: list[str], cols: list[str]):
    import pandas as pd
    return pd.concat([pq.read_table(out / f, columns=["GEOID", *cols]).to_pandas() for f in files]).set_index("GEOID")


def change_magnitudes(out: Path, new_files, base_files, measures, dollars, factor, changes) -> dict:
    """National split between the two shades of a change map: the median |d|
    over significant changes, with app/engine/change.js's test (Z >= 1.645,
    SE = MOE/1.645, the 2006-10 side deflated)."""
    cols = [c for m in measures for c in (f"{m}_e", f"{m}_m")]
    new, base = _stack(out, new_files, cols), _stack(out, base_files, cols)
    if changes:
        base = base.rename(index={r["was"]: g for g, r in changes["renamed"].items()})
        new = new.drop(index=[g for g in changes["not_comparable"] if g in new.index])
    base = base.reindex(new.index)
    res = {}
    for m in measures:
        f = factor if dollars[m] else 1.0
        x1, m1 = base[f"{m}_e"].to_numpy("float64"), base[f"{m}_m"].to_numpy("float64")
        x2, m2 = new[f"{m}_e"].to_numpy("float64"), new[f"{m}_m"].to_numpy("float64")
        ok = np.isfinite(x1) & np.isfinite(m1) & np.isfinite(x2) & np.isfinite(m2)
        d = x2 - f * x1
        se = np.hypot(f * m1 / 1.645, m2 / 1.645)
        with np.errstate(divide="ignore", invalid="ignore"):
            sig = np.where(se == 0, d != 0, np.abs(d) / se >= 1.645)
        v = np.sort(np.abs(d[ok & sig]))
        res[m] = {"break": float(v[(len(v) - 1) // 2]) if len(v) else 0.0, "n": int(len(v))}
    return res


def build(out: Path) -> dict:
    pres = json.loads((REGISTRY_DIR / "presentation.json").read_text())
    # Every state in scope is a candidate; only states with built files appear.
    pres["states"] = {k: v["name"] for k, v in sorted(load_states().items())}
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

    measure_ids = [m["id"] for m in pres["measures"]]
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
            us_cube, us_geo = f"acs/{v}/{lv}/us.parquet", f"geo/{v}/{lv}/us.geojson"
            if (out / us_cube).exists() and (out / us_geo).exists():
                states["us"] = {"cube": us_cube, "geo": us_geo, "names": f"geo/{v}/{lv}/us.names.json",
                                "rows": rows(us_cube)}
            per_state = [st for st in states if st != "us"]
            if len(per_state) == len(pres["states"]) and lv != "county":
                entry.setdefault("national_breaks", {})[v] = national_breaks(
                    out, [states[st]["cube"] for st in per_state], measure_ids)
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
            hs = harm["2006-2010"]["states"]
            if len(hs) == len(pres["states"]):
                harm["2006-2010"]["national_breaks"] = national_breaks(
                    out, [x["cube"] for x in hs.values()], measure_ids)
            entry["harmonized"] = harm
        levels[lv] = entry

    s = series()
    changes = json.loads((REGISTRY_DIR / "county_changes.json").read_text())
    factor = s[vintage_year("2016-2020")] / s[vintage_year("2006-2010")]
    dollars = {m["id"]: bool(kinds.get(m["id"], {}).get("dollars")) for m in pres["measures"]}
    n_states = len(pres["states"])
    for lv, entry in levels.items():
        new = {k: v for k, v in entry["vintages"].get("2016-2020", {}).items() if k != "us"}
        base = (entry.get("harmonized", {}).get("2006-2010", {}).get("states", {}) if lv == "tract"
                else {k: v for k, v in entry["vintages"].get("2006-2010", {}).items() if k != "us"} if lv == "county"
                else {})
        if len(new) == n_states and len(base) == n_states:
            entry["national_change"] = change_magnitudes(
                out, [new[k]["cube"] for k in sorted(new)], [base[k]["cube"] for k in sorted(base)],
                measure_ids, dollars, factor, changes if lv == "county" else None)
    years = sorted({vintage_year(v) for v in vintages})
    comparisons = [{"from": a, "to": b, "valid": not overlaps(a, b),
                    "why": "overlapping periods share sample years" if overlaps(a, b) else "non-overlapping periods"}
                   for i, a in enumerate(vintages) for b in vintages[i + 1:]]
    return {
        "built": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "base": ".",
        "registry_version": reg["registry_version"],
        "outlines": {"geo": "geo/states.geojson", "boxes": "geo/states.json"} if (out / "geo/states.json").exists() else None,
        "states": {k: v for k, v in pres["states"].items()
                   if any(k in e["vintages"].get(vv, {}) for e in levels.values() for vv in e["vintages"])},
        "vintages": {v: {**pres["vintages"].get(v, {"label": v}), "dollars_year": vintage_year(v)} for v in vintages},
        "levels": levels,
        "measures": [{**m, **kinds.get(m["id"], {})} for m in pres["measures"]],
        "deflators": {"series": "R-CPI-U-RS", "annual": {str(y): s[y] for y in years}},
        "comparisons": comparisons,
        "county_changes": {"renamed": {g: r["was"] for g, r in changes["renamed"].items()},
                           "not_comparable": sorted(changes["not_comparable"])},
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
