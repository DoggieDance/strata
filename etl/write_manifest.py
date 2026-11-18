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

from etl.common import load_shares, load_states, REGISTRY_DIR, LevelUnavailable, level_cfg, load_measures, load_summary_files
from etl.deflate import series, vintage_year
from etl.harmonize import on_2010_tracts


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
        f = (factor.get(m, 1.0) if isinstance(factor, dict) else factor) if dollars[m] else 1.0
        x1, m1 = base[f"{m}_e"].to_numpy("float64"), base[f"{m}_m"].to_numpy("float64")
        x2, m2 = new[f"{m}_e"].to_numpy("float64"), new[f"{m}_m"].to_numpy("float64")
        ok = np.isfinite(x1) & np.isfinite(m1) & np.isfinite(x2) & np.isfinite(m2)
        d = x2 - f * x1
        se = np.hypot(f * m1 / 1.645, m2 / 1.645)
        with np.errstate(divide="ignore", invalid="ignore"):
            sig = np.where(se == 0, d != 0, np.abs(d) / se >= 1.645)
        v = np.sort(np.abs(d[ok & sig]))
        res[m] = {"break": float(v[(len(v) - 1) // 2]) if len(v) else 0.0, "n": int(len(v)),
                  "tested": int(ok.sum())}
        # Benjamini-Hochberg threshold over every valid test nationally (app/engine/change.js bhThreshold).
        with np.errstate(divide="ignore", invalid="ignore"):
            z = np.where(se == 0, np.where(d != 0, np.inf, 0.0), np.abs(d) / se)[ok]
        res[m]["bh_z"] = bh_threshold(z, 0.10)
    return res


def bh_threshold(z: np.ndarray, q: float) -> float | None:
    """Smallest |Z| significant at false-discovery rate q (Benjamini-Hochberg 1995);
    None if no test passes. Mirrors bhThreshold in app/engine/change.js."""
    import math
    p = np.sort(np.array([math.erfc(abs(x) / math.sqrt(2)) if np.isfinite(x) else 0.0 for x in z]))
    m = len(p)
    if not m:
        return None
    ok = np.nonzero(p <= (np.arange(1, m + 1) / m) * q)[0]
    if not len(ok):
        return None
    pk = p[ok[-1]]
    lo, hi = 0.0, 40.0
    for _ in range(80):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if math.erfc(mid / math.sqrt(2)) > pk else (lo, mid)
    return hi


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

    all_v = sorted(load_summary_files()["vintages"])
    for m in pres["measures"]:
        m.setdefault("vintages", all_v)
    for sh in load_shares():
        pres["measures"].append({"id": sh["id"], "label": sh["label"], "fmt": "pct", "topic": sh["topic"],
                                 "vintages": sorted(sh["sources"]), **({"note": sh["note"]} if sh.get("note") else {})})
        kinds[sh["id"]] = {"kind": "percent", "dollars": False}
    measure_ids = [m["id"] for m in pres["measures"]]
    by_id = {m["id"]: m for m in pres["measures"]}

    def ids_for(v):
        return [i for i in measure_ids if v in by_id[i]["vintages"]]
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
                    out, [states[st]["cube"] for st in per_state], ids_for(v))
            if states:
                entry["vintages"][v] = states
        harm = {}
        # Periods on 2010 tracts, plus any re-keyed copies (Connecticut 2020-2024).
        for hv in sorted(set(on_2010_tracts()) | {d.name for d in (out / "harmonized").glob("*") if d.is_dir()}):
            for st in pres["states"]:
                h = f"harmonized/{hv}/{lv}-2020/{st}.parquet"
                if (out / h).exists():
                    harm.setdefault(hv, {"onto": "2016-2020", "states": {}})["states"][st] = {
                        "cube": h, "geo": f"geo/2016-2020/{lv}/{st}.geojson",
                        "names": f"geo/2016-2020/{lv}/{st}.names.json", "rows": rows(h)}
            if hv in harm and len(harm[hv]["states"]) == len(pres["states"]):
                harm[hv]["national_breaks"] = national_breaks(
                    out, [x["cube"] for x in harm[hv]["states"].values()], ids_for(hv))
        if harm:
            entry["harmonized"] = harm
        levels[lv] = entry

    # Change maps (spec 05): every pair of non-overlapping periods, at the levels
    # whose geography can be held fixed: tracts on 2020 lines (periods on 2010
    # tracts via the harmonized cubes) and counties (boundary changes registered
    # in county_changes.json). The shade split is computed nationally once every
    # state is built, with the same Z test the app runs.
    s = series()
    changes = json.loads((REGISTRY_DIR / "county_changes.json").read_text())
    dollars = {m["id"]: bool(kinds.get(m["id"], {}).get("dollars")) for m in pres["measures"]}
    n_states = len(pres["states"])
    tract_geo = {v: c.get("tract_geography") for v, c in load_summary_files()["vintages"].items()}

    def side(lv, v):
        e = levels[lv]
        h = e.get("harmonized", {}).get(v, {}).get("states", {})
        if lv == "tract" and tract_geo[v] == "2010":
            return h
        own = {k: x for k, x in e["vintages"].get(v, {}).items() if k != "us"}
        # A state re-keyed onto 2020 tract codes (Connecticut 2020-2024) uses that copy.
        return {**own, **h} if lv == "tract" else own

    # Dollar basis per measure: None = end-year dollars in every period;
    # an int N = pooled nominal values for vintages ending in year <= N.
    dollar_bases = {}
    for m in reg["measures"]:
        if m.get("derives") and m.get("dollar_basis"):
            dollar_bases[m["derives"]] = m["dollar_basis"]["nominal_pooled_through_endyear"]

    def pooled(v, basis):
        return basis is not None and vintage_year(v) <= basis

    def price_level(v, basis):
        if pooled(v, basis):
            a0, b0 = (int(x) for x in v.split("-"))
            return sum(s[y] for y in range(a0, b0 + 1)) / (b0 - a0 + 1)
        return s[vintage_year(v)]

    def basis_label(v, basis):
        return f"average {v} prices (not inflation-adjusted by Census)" if pooled(v, basis) else f"{vintage_year(v)} dollars"

    comparisons = []
    for i, a in enumerate(vintages):
        for b in vintages[i + 1:]:
            c = {"from": a, "to": b, "valid": not overlaps(a, b),
                 "why": "overlapping periods share sample years" if overlaps(a, b) else "non-overlapping periods"}
            if c["valid"]:
                c["factor"] = s[vintage_year(b)] / s[vintage_year(a)]
                # Per-measure factors where a measure's dollars are not end-year
                # dollars in every period (home value before 2018-22).
                c["factors"] = {mid: price_level(b, basis) / price_level(a, basis)
                                for mid, basis in dollar_bases.items() if basis}
                c["price_basis"] = {mid: [basis_label(a, basis), basis_label(b, basis)] for mid, basis in dollar_bases.items() if basis}
                c["measures"] = [i2 for i2 in ids_for(a) if b in by_id[i2]["vintages"]]
                c["levels"] = {}
                for lv in ("tract", "county"):
                    sa, sb = side(lv, a), side(lv, b)
                    both = sorted(set(sa) & set(sb))
                    if not both:
                        continue
                    lc = {"states": both}
                    if len(both) == n_states:
                        lc["national"] = change_magnitudes(
                            out, [sb[k]["cube"] for k in both], [sa[k]["cube"] for k in both],
                            c["measures"], dollars, {mid: c["factors"].get(mid, c["factor"]) for mid in c["measures"]},
                            changes if lv == "county" else None)
                    c["levels"][lv] = lc
            comparisons.append(c)
    years = sorted({vintage_year(v) for v in vintages})
    return {
        "built": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "base": ".",
        "registry_version": reg["registry_version"],
        "outlines": {"geo": "geo/states.geojson", "boxes": "geo/states.json"} if (out / "geo/states.json").exists() else None,
        "states": {k: v for k, v in pres["states"].items()
                   if any(k in e["vintages"].get(vv, {}) for e in levels.values() for vv in e["vintages"])},
        "vintages": {v: {**pres["vintages"].get(v, {"label": v}), "dollars_year": vintage_year(v),
                         "tract_geography": tract_geo.get(v)} for v in vintages},
        "levels": levels,
        "measures": [{**m, **kinds.get(m["id"], {}),
                      **({"nominal_pooled_through": dollar_bases[m["id"]]} if dollar_bases.get(m["id"]) else {})}
                     for m in pres["measures"]],
        "topic_order": pres.get("topic_order", []),
        "deflators": {"series": "R-CPI-U-RS", "annual": {str(y): s[y] for y in sorted(s) if min(years) - 4 <= y <= max(years)}},
        "comparisons": comparisons,
        "comparability_notes": json.loads((REGISTRY_DIR / "comparability_notes.json").read_text())["notes"],
        # Census errata: areas withheld or cautioned (registry/suppressed_geographies.json).
        "errata": json.loads((REGISTRY_DIR / "suppressed_geographies.json").read_text())["errata"],
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
    # Atomic: builds run in parallel and the app may read it at any moment.
    part = path.with_name(f"{path.name}.{__import__('os').getpid()}.part")
    part.write_text(json.dumps(m, indent=2, ensure_ascii=False) + "\n")
    part.replace(path)
    print(f"wrote {path} ({path.stat().st_size:,} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
