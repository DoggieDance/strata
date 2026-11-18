"""Turn cached Summary File tables into clean per-tract measures.

- Jam values (missing data) become null before any arithmetic.
  -555555555 in an MOE field becomes 0: the estimate is controlled to an
  independent total and has no sampling error. In an estimate field it raises.
  An unrecognized value below the jam floor raises: it is a sentinel nobody
  has documented yet.
- Denominators come from the registry, never from code.
- Derived measures (means, shares, the binned home-value aggregate) carry an
  MOE propagated with the ACS Handbook approximation formulas.

No deflation happens here. The cube holds each vintage as published (2016-2020
in 2020 dollars, 2006-2010 in 2010 dollars) so the spot-check can demand exact
matches; deflators (registry/deflators.json) are applied where vintages meet.

Vintages come in two formats (registry/summary_files.json "format"): the
table-based Summary File, and the older sequence-based one, read by
etl.sequence_file into the same frame shape.
"""
from __future__ import annotations

import csv
import re
from functools import lru_cache

import numpy as np
import pandas as pd

from etl.common import (
    JAM_FLOOR,
    check_scope,
    controlled_moe_value,
    expand_cells,
    jam_values,
    level_cfg,
    load_measures,
    load_shares,
    load_summary_files,
    raw_dir,
    table_path,
    vintage_format,
)
from etl import sequence_file, zcta


class JamValueError(ValueError):
    pass


# --------------------------------------------------------------------------
# loading

def strip_jams(df: pd.DataFrame, jams=None, controlled=None) -> pd.DataFrame:
    """Jam values -> NaN; controlled-MOE sentinel -> 0 in M columns.

    Columns named M... are MOEs; everything else is an estimate. Raises on the
    controlled sentinel in an estimate, and on any unknown value below the floor.
    """
    jams = jam_values() if jams is None else jams
    controlled = controlled_moe_value() if controlled is None else controlled
    arr = df.to_numpy(dtype="float64", copy=True)
    is_moe = np.array([str(c).startswith("M") for c in df.columns])
    ctrl = arr == controlled
    if ctrl[:, ~is_moe].any():
        raise JamValueError(f"{controlled} (controlled MOE) found in an estimate column")
    arr[ctrl] = 0.0
    arr[np.isin(arr, np.array(sorted(jams), dtype="float64"))] = np.nan
    with np.errstate(invalid="ignore"):
        leftover = arr < JAM_FLOOR
    if leftover.any():
        bad = sorted(set(arr[leftover].tolist()))[:5]
        raise JamValueError(f"unrecognized sentinel value(s) below {JAM_FLOOR:g}: {bad}")
    return pd.DataFrame(arr, index=df.index, columns=df.columns)


def load_table(vintage: str, table: str, state: str, level: str = "tract") -> pd.DataFrame:
    """One table, one state, one level. Index = GEOID; columns E001, M001, ..."""
    lc = level_cfg(vintage, level)
    if vintage_format(vintage) == "sequence":
        df = sequence_file.load_table(vintage, table, state, level)
        return strip_jams(sequence_file.to_numeric(df, vintage))
    # ZCTA rows are national (no state in the GEO_ID); the universe picks the state's.
    prefix = lc["prefix"] + ("" if level == "zcta" else state)
    path = table_path(vintage, table)
    with open(path, encoding="latin-1") as f:
        header = f.readline().rstrip("\r\n").split("|")
        rows = [ln.rstrip("\r\n").split("|") for ln in f if ln.startswith(prefix)]
    if header[0] != "GEO_ID":
        raise ValueError(f"{path.name}: unexpected header {header[:3]}")
    df = pd.DataFrame(rows, columns=header).set_index("GEO_ID")
    tag = table.upper() + "_"
    df.columns = [c.removeprefix(tag) for c in df.columns]
    df = df.apply(pd.to_numeric, errors="raise")
    df.index = df.index.str.removeprefix(lc["prefix"])
    df.index.name = "GEOID"
    if not df.index.is_unique:
        raise ValueError(f"{path.name}: duplicate GEOIDs")
    return strip_jams(df)


GEOID_LENGTH = {"tract": 11, "county": 5, "place": 7, "zcta": 5}


@lru_cache(maxsize=None)
def _state_geos(vintage: str, state: str, level: str) -> pd.DataFrame:
    """Rows of the vintage's geography file for one state and level: GEOID, NAME."""
    lc = level_cfg(vintage, level)
    if vintage_format(vintage) == "sequence":
        return sequence_file.geos(vintage, state, level)
    cfg = load_summary_files()["vintages"][vintage]
    path = raw_dir(vintage) / cfg["geos"].rsplit("/", 1)[1]
    geos = pd.read_csv(path, dtype=str, encoding="latin-1", sep=cfg.get("geos_sep", ","), usecols=[
        "SUMLEVEL", "COMPONENT", "STATE", "COUNTY", "PLACE", "TRACT", "ZCTA5", "NAME"])
    sel = geos[(geos.SUMLEVEL == lc["sumlevel"]) & (geos.COMPONENT == "00")]
    if level == "zcta":
        sel = sel[sel.ZCTA5.isin(zcta.for_state(vintage, state))]
    else:
        sel = sel[sel.STATE == state]
    # This file writes short prefixes ("14000US"), the data files long ones
    # ("1400000US"); build the GEOID from its parts rather than trust either.
    geoid = sel[lc["geoid"]].astype(str).agg("".join, axis=1)
    return pd.DataFrame({"GEOID": geoid.values, "NAME": sel.NAME.values})


def geo_universe(vintage: str, state: str, level: str = "tract") -> pd.Index:
    """Every geography of this level the vintage's geography file lists for the state."""
    idx = pd.Index(sorted(_state_geos(vintage, state, level).GEOID), name="GEOID")
    n = GEOID_LENGTH[level]
    if idx.empty or not idx.is_unique or not (idx.str.len() == n).all():
        raise ValueError(f"geography file: {level} GEOIDs are not unique {n}-character codes")
    return idx


def geo_names(vintage: str, state: str, level: str = "tract") -> pd.Series:
    sel = _state_geos(vintage, state, level)
    return pd.Series(sel.NAME.values, index=sel.GEOID)


def tract_universe(vintage: str, state: str) -> pd.Index:
    return geo_universe(vintage, state, "tract")


def tract_names(vintage: str, state: str) -> pd.Series:
    return geo_names(vintage, state, "tract")


# --------------------------------------------------------------------------
# arithmetic (ACS Handbook, ch. 8 approximations)

def sum_moe(E: np.ndarray, M: np.ndarray) -> np.ndarray:
    """MOE of a row-wise sum of (already weighted) estimates E with MOEs M.

    Root-sum-of-squares over the nonzero estimates, plus the largest MOE among
    the zero estimates, once (Census: "When approximating a sum, use only the
    largest zero estimate MOE, once" -- ACS MOE training, 2016, slide 26;
    Worked Examples for Approximating Margins of Error). Zero-estimate MOEs are
    model-based, not sampled, so adding every one of them overstates the error
    (in 2006-10 tracts each is about +/-127; a 26-cell sum gained up to 20
    points of spurious MOE before this rule). Any null estimate or MOE -> null.
    """
    E = np.asarray(E, dtype="float64")
    M = np.abs(np.asarray(M, dtype="float64"))
    bad = np.isnan(E).any(axis=1) | np.isnan(M).any(axis=1)
    zero = E == 0
    nz = np.where(zero, 0.0, M) ** 2
    zmax = np.where(zero, M, 0.0).max(axis=1) if M.shape[1] else np.zeros(len(M))
    out = np.sqrt(nz.sum(axis=1) + zmax ** 2)
    return np.where(bad, np.nan, out)


def sum_cells(tbl: pd.DataFrame, cells: list[str], weights=None):
    """Weighted sum of cells and its MOE (sum_moe: Census zero-estimate rule).
    Any null cell -> null."""
    w = np.ones(len(cells)) if weights is None else np.asarray(weights, dtype="float64")
    E = tbl[[f"E{c}" for c in cells]].to_numpy(dtype="float64")
    M = tbl[[f"M{c}" for c in cells]].to_numpy(dtype="float64")
    est = E @ w  # NaN propagates
    moe = sum_moe(E * w, M * w)
    return pd.Series(est, index=tbl.index), pd.Series(moe, index=tbl.index)


def ratio(x, mx, y, my, *, proportion: bool, scale: float = 1.0):
    """X/Y with MOE. Proportion formula falls back to the ratio formula when
    the radicand goes negative, as the Handbook directs. Y <= 0 -> null."""
    x, mx, y, my = (pd.Series(s, dtype="float64") for s in (x, mx, y, my))
    y_ok = y.where(y > 0)
    r = x / y_ok
    if proportion and (r > 1 + 1e-9).any():
        raise ValueError("proportion numerator exceeds denominator")
    plus = mx**2 + r**2 * my**2
    if proportion:
        minus = mx**2 - r**2 * my**2
        rad = minus.where(minus >= 0, plus)
        # P = 1 is a special case: SE(P) = SE(X) / Y (Census, Instructions for
        # Applying Statistical Testing to ACS Data, 2015 and 2025). The general
        # formula's radicand is often negative there and would fall back to
        # the ratio form, overstating the MOE by up to sqrt(2).
        rad = rad.where(~np.isclose(r, 1.0), mx**2)
    else:
        rad = plus
    moe = np.sqrt(rad) / y_ok
    return r * scale, moe * scale


# --------------------------------------------------------------------------
# bin midpoints

_LESS = re.compile(r"Less than \$([\d,]+)")
_RANGE = re.compile(r"\$([\d,]+) to \$([\d,]+)")
_MORE = re.compile(r"\$([\d,]+) or more")


def _num(s: str) -> int:
    return int(s.replace(",", ""))


@lru_cache(maxsize=None)
def _shell_labels(vintage: str) -> dict:
    if vintage_format(vintage) == "sequence":
        return sequence_file.labels(vintage)
    cfg = load_summary_files()["vintages"][vintage]
    path = raw_dir(vintage) / cfg["table_shells"].rsplit("/", 1)[1]
    fmt = cfg.get("shells_format", {"sep": ",", "id": "Unique ID", "label": "Stub"})
    with open(path, encoding="latin-1", newline="") as f:
        return {r[fmt["id"]]: r[fmt["label"]].strip() for r in csv.DictReader(f, delimiter=fmt["sep"]) if r.get(fmt["id"])}


def parse_bin(label: str) -> tuple[int, int | None]:
    """'Less than $X' -> (0, X-1); '$a to $b' -> (a, b); '$a or more' -> (a, None)."""
    if m := _LESS.fullmatch(label):
        return 0, _num(m[1]) - 1
    if m := _RANGE.fullmatch(label):
        return _num(m[1]), _num(m[2])
    if m := _MORE.fullmatch(label):
        return _num(m[1]), None
    raise ValueError(f"cannot parse bin label {label!r}")


def midpoints_from_labels(labels: dict[str, str], top_bin: dict) -> list[list]:
    """[[cell, lower, upper, midpoint], ...] from label text alone.

    Every bin whose lower bound is at least top_bin.collapse_at_lower_bound gets
    top_bin.midpoint; the rest get (lower + upper + 1) / 2. An open-ended bin
    below the collapse point raises.
    """
    at = top_bin["collapse_at_lower_bound"]
    rows = []
    for cell, label in labels.items():
        lo, hi = parse_bin(label)
        if lo >= at:
            mid = top_bin["midpoint"]
        elif hi is None:
            raise ValueError(f"{cell} {label!r} is open-ended and not collapsed")
        else:
            mid = (lo + hi + 1) / 2
        rows.append([cell, lo, hi, mid])
    return rows


def bin_midpoints(vintage: str, table: str, src: dict) -> dict[str, float]:
    """Midpoint per bin for a registry source, derived from the vintage's own
    table shells and checked against the bins the registry records."""
    shells = _shell_labels(vintage)
    cells = expand_cells(src["cells"])
    labels = {c: shells[f"{table}_{c}"] for c in cells}
    top = src["top_bin"]
    rows = midpoints_from_labels(labels, top)
    collapse_from = next((r[0] for r in rows if r[1] >= top["collapse_at_lower_bound"]), None)
    if collapse_from != top["collapse_from"]:
        raise ValueError(
            f"{vintage} {table}: labels put the collapse at {collapse_from}, "
            f"registry says {top['collapse_from']}"
        )
    if rows != src["bins"]:
        raise ValueError(f"{vintage} {table}: registry bins disagree with the table shells")
    return {c: float(mid) for c, _, _, mid in rows}


# --------------------------------------------------------------------------
# measures

def _denominator_recipe(d: dict, vintage: str) -> tuple[str, list[str]]:
    sub = d.get("summary_file_substitute", {}).get(vintage)
    src = sub or d
    return src["table"], expand_cells(src["cells"])


def build_measures(vintage: str, state: str, level: str = "tract"):
    """Return (frame, notes). frame: index GEOID, columns {id}_e / {id}_m."""
    check_scope([state], [vintage], level)
    reg = load_measures()
    universe = geo_universe(vintage, state, level)

    tables: dict[str, pd.DataFrame] = {}

    def T(name):
        if name not in tables:
            tables[name] = load_table(vintage, name, state, level).reindex(universe)
        return tables[name]

    cols: dict[str, pd.Series] = {}
    notes: dict[str, dict] = {}

    for name, d in reg["denominators"].items():
        t, cells = _denominator_recipe(d, vintage)
        cols[f"{name}_e"], cols[f"{name}_m"] = sum_cells(T(t), cells)
        notes[name] = {"kind": "count", "units": "count", "source": f"{t}_{'+'.join(cells)}"}

    for m in reg["measures"]:
        mid, src = m["id"], m["sources"][vintage]
        if m["kind"] == "aggregate":
            cells = expand_cells(src["cells"])
            e, mo = sum_cells(T(src["table"]), cells)
            notes[mid] = {"kind": "aggregate", "units": "dollars", "source": f"{src['table']}_{'+'.join(cells)}"}
        elif m["kind"] == "derived" and m.get("method") == "bin_midpoint_sum":
            cells = expand_cells(src["cells"])
            mids = bin_midpoints(vintage, src["table"], src)
            e, mo = sum_cells(T(src["table"]), cells, [mids[c] for c in cells])
            notes[mid] = {"kind": "aggregate", "units": "dollars", "method": "bin_midpoint_sum",
                          "source": f"{src['table']}_{cells[0]}..{cells[-1]}", "midpoints": mids}
            if pub := m.get("published_aggregate"):
                # Census's own aggregate (estimate and replicate MOE) wherever it
                # is published; the midpoint sum only where it is blank.
                pe, pm = sum_cells(T(pub["table"]), [pub["cell"]])
                have = pe.notna() & pm.notna()
                e, mo = e.where(~have, pe), mo.where(~have, pm)
                notes[mid].update(method="published aggregate (B25079) where published, else bin-midpoint sum",
                                  published_share=round(float(have.mean()), 4),
                                  source=f"{pub['table']}_{pub['cell']} | {src['table']}_{cells[0]}..{cells[-1]}")
        elif m["kind"] == "percent":
            sub = src.get("summary_file_substitute")
            if not sub:
                raise ValueError(f"{mid}: no Summary File recipe for {vintage}")
            num = sum_cells(T(sub["table"]), expand_cells(sub["numerator_cells"]))
            den = sum_cells(T(sub["table"]), expand_cells(sub["denominator_cells"]))
            e, mo = ratio(*num, *den, proportion=True, scale=100.0)
            notes[mid] = {"kind": "percent", "units": "percent (0-100)",
                          "source": f"{sub['table']} {sub['numerator_cells']} / {sub['denominator_cells']}",
                          "substitute_for": f"{src['table']}_{src['cells'][0]}", "note": sub["note"]}
        elif m["kind"] == "ratio":
            n, d = m["numerator_source"], m["denominator_source"]
            if n["table"] != src["table"] or d["table"] != src["table"]:
                raise ValueError(f"{mid}: numerator/denominator table differs from {vintage} source")
            num = sum_cells(T(n["table"]), expand_cells(n["cells"]))
            den = sum_cells(T(d["table"]), expand_cells(d["cells"]))
            e, mo = ratio(*num, *den, proportion=True, scale=100.0)
            notes[mid] = {"kind": "percent", "units": "percent (0-100)",
                          "source": f"{n['table']}_{n['cells']} / {d['table']}_{d['cells']}"}
        else:
            raise ValueError(f"{mid}: unsupported kind {m['kind']!r}")
        cols[f"{mid}_e"], cols[f"{mid}_m"] = e, mo

        if derived := m.get("derives"):
            den = m["denominator"]
            cols[f"{derived}_e"], cols[f"{derived}_m"] = ratio(
                e, mo, cols[f"{den}_e"], cols[f"{den}_m"], proportion=False
            )
            notes[derived] = {"kind": "mean", "units": "dollars", "source": f"{mid} / {den}"}

        for legacy in m.get("legacy_derives", []):
            lid, den = legacy["id"], legacy["denominator"]
            cols[f"{lid}_e"], cols[f"{lid}_m"] = ratio(
                e, mo, cols[f"{den}_e"], cols[f"{den}_m"], proportion=False
            )
            notes[lid] = {"kind": "mean", "units": "dollars", "source": f"{mid} / {den}",
                          "legacy": True, "note": legacy["note"]}

    # Shares (registry/shares.json): numerator and denominator counts, then the
    # percent. Counts are what the harmonizer moves; the percent is recomputed
    # from them. A share with no source for this vintage is left out.
    for sh in load_shares():
        src = sh["sources"].get(vintage)
        if src is None:
            continue
        t = T(src["table"])
        for cid, key in ((sh["count_numerator"], "numerator_cells"), (sh["count_denominator"], "denominator_cells")):
            e, mo = sum_cells(t, expand_cells(src[key]))
            prior = notes.get(cid)
            source = f"{src['table']}_{'+'.join(src[key])}"
            if prior and prior.get("source") != source:
                raise ValueError(f"count {cid}: {source} conflicts with {prior['source']}")
            cols[f"{cid}_e"], cols[f"{cid}_m"] = e, mo
            notes[cid] = {"kind": "count", "units": "count", "source": source}
        num, den = sh["count_numerator"], sh["count_denominator"]
        cols[f"{sh['id']}_e"], cols[f"{sh['id']}_m"] = ratio(
            cols[f"{num}_e"], cols[f"{num}_m"], cols[f"{den}_e"], cols[f"{den}_m"], proportion=True, scale=100.0)
        notes[sh["id"]] = {"kind": "percent", "units": "percent (0-100)", "share": True,
                           "source": f"{num} / {den}"}

    frame = pd.DataFrame(cols, index=universe)
    return frame, notes
