"""Apportion a vintage's tract cube onto another tract geography (spec 02).

    python -m etl.harmonize --states 51     # 2006-2010 values on 2020 tracts

Extensive columns (counts, dollar aggregates) are distributed by crosswalk
weight and summed into each target:

    E_t = sum_s w(s,t) * E_s
    M_t = sqrt( sum_s (w(s,t) * M_s)^2 )

The MOE is the Census approximation for a sum of independent estimates, applied
to the weighted pieces. It treats a source's pieces as independent, which they
are not; that error is small for a dominant piece and is documented rather than
hidden. Intensive columns (means, percents) are never apportioned: they are
recomputed from the apportioned numerator and denominator with the same
formulas the cube used. A median cannot be apportioned at all; asking raises.

An aggregate whose source universe is zero counts as zero there. A target that
receives no flow at all (water tracts nothing maps into) is null, not zero.

Output: build/harmonized/{source vintage}/tract-{target geography}/{state}.parquet,
with the same columns as the source cube and one row per target tract.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from etl.build_cube import to_table
from etl.clean import ratio
from etl.common import REGISTRY_DIR as REGISTRY, parse_states, check_scope, load_measures, load_shares, load_summary_files, resolve_vintage

EXTENSIVE = {"count", "aggregate"}


class MedianApportionError(ValueError):
    """A median cannot be apportioned. Recompute it from bins, or refuse."""


def basis_of_columns(notes: dict) -> dict[str, str]:
    """count/aggregate column -> weighting base, from the table it was built from."""
    import re
    reg = json.loads((Path(__file__).resolve().parent.parent / "registry" / "apportion_basis.json").read_text())["bases"]
    by_table = {t: b for b, d in reg.items() for t in d["tables"]}
    out = {}
    for name, n in notes.items():
        if n["kind"] not in EXTENSIVE:
            continue
        m = re.match(r"([BC]\d{5}[A-Z]?)_", n.get("source", ""))
        if not m or m.group(1) not in by_table:
            raise ValueError(f"{name}: no weighting base for source {n.get('source')!r} (registry/apportion_basis.json)")
        out[name] = by_table[m.group(1)]
    return out


def column_kinds(notes: dict) -> dict[str, str]:
    kinds = {}
    for name, n in notes.items():
        k = n["kind"]
        if k == "median" or "median" in name:
            raise MedianApportionError(f"{name}: a median cannot be apportioned")
        kinds[name] = k
    return kinds


def aggregate_universes() -> dict[str, str]:
    """aggregate measure -> the count of its universe (from the registry)."""
    return {m["id"]: m["denominator"] for m in load_measures()["measures"]
            if m["kind"] in ("aggregate", "derived") and m.get("denominator")}


def intensive_recipes() -> dict[str, tuple[str, str, bool]]:
    """measure -> (numerator count, denominator count, is_proportion), from the registry."""
    reg = load_measures()
    out = {}
    for m in reg["measures"]:
        if m.get("derives"):
            out[m["derives"]] = (m["id"], m["denominator"], False)
        for leg in m.get("legacy_derives", []):
            out[leg["id"]] = (m["id"], leg["denominator"], False)
        if m["kind"] in ("percent", "ratio"):
            out[m["id"]] = (m["count_numerator"], m["count_denominator"], True)
    for sh in load_shares():
        out[sh["id"]] = (sh["count_numerator"], sh["count_denominator"], True)
    return out


def tract_changes(xw: pd.DataFrame, state: str, vintage: str, changes: list[dict] | None = None) -> tuple[pd.DataFrame, list[str], list[dict]]:
    """Re-key the 2010->2020 crosswalk to the tract codes a later period uses
    (registry/tract_code_changes.json). Returns (crosswalk, 2020 tracts to
    leave without a value, changes applied).

    recode: rename the source. merge: rename onto the absorbing tract and
    re-normalize its weights (the absorbed tract had no 2010 people, households
    or housing units, so no weight moves; checked here). boundary: drop the
    affected sources; every target they touched is returned to be nulled.
    """
    from etl.crosswalk import BASES, pair_weights
    reg = json.loads((REGISTRY / "tract_code_changes.json").read_text())
    if vintage not in reg["applies_to"]:
        return xw, [], []
    mine = [c for c in (reg["changes"] if changes is None else changes) if c["old"][:2] == state]
    if not mine:
        return xw, [], []
    xw = xw.copy()
    applied, null_targets = [], set()
    for c in mine:
        rows = xw.source == c["old"]
        if not rows.any():
            raise ValueError(f"{c['old']}: in tract_code_changes.json but not in the {state} crosswalk")
        if c["kind"] in ("recode", "merge"):
            if c["kind"] == "recode" and (xw.source == c["new"]).any():
                raise ValueError(f"{c['old']} -> {c['new']}: a recode onto a tract the crosswalk already has; that is a merge")
            if c["kind"] == "merge" and xw.loc[rows, list(BASES)].to_numpy().sum() != 0:
                raise ValueError(f"{c['old']}: registered as a merge of an empty tract, but it has 2010 counts")
            xw.loc[rows, "source"] = c["new"]
        elif c["kind"] == "boundary":
            gone = xw.source.isin([c["old"], *c.get("also", [])])
            null_targets |= set(xw.loc[gone, "target"])
            xw = xw[~gone]
        else:
            raise ValueError(f"{c['old']}: unknown change kind {c['kind']!r}")
        applied.append(c)
    xw = pair_weights(xw[["source", "target", *BASES, "land"]])
    return xw, sorted(null_targets), applied


def apportion(source: pd.DataFrame, notes: dict, xw: pd.DataFrame, targets: pd.Index) -> pd.DataFrame:
    """source: index GEOID, columns {m}_e/{m}_m. xw: source, target, weight."""
    kinds = column_kinds(notes)
    recipes = intensive_recipes()
    missing = set(xw.source) - set(source.index)
    if missing:
        raise ValueError(f"crosswalk names {len(missing)} source tracts not in the cube, e.g. {sorted(missing)[:3]}")
    stray = set(xw.target) - set(targets)
    if stray:
        raise ValueError(f"crosswalk targets {len(stray)} tracts outside the target universe, e.g. {sorted(stray)[:3]}")

    universes = aggregate_universes()
    basis = basis_of_columns(notes)
    out = {}
    for name, kind in kinds.items():
        if kind not in EXTENSIVE:
            continue
        # The weight matched to this count's universe (registry/apportion_basis.json);
        # crosswalks from before the per-base weights carry only "weight".
        wcol = f"weight_{basis[name]}"
        w = (xw[wcol] if wcol in xw else xw.weight).to_numpy()
        se = source[f"{name}_e"].reindex(xw.source).to_numpy(dtype="float64")
        sm = source[f"{name}_m"].reindex(xw.source).to_numpy(dtype="float64")
        # An aggregate over an empty universe (0 households, 0 cash renters) is
        # published as "not computable" but means zero: it contributes nothing,
        # rather than blanking every target it touches (review of cac3bfd).
        uni = universes.get(name)
        if uni is not None and f"{uni}_e" in source:
            empty = source[f"{uni}_e"].reindex(xw.source).to_numpy(dtype="float64") == 0
            fill = empty & np.isnan(se)
            se = np.where(fill, 0.0, se)
            sm = np.where(fill, 0.0, sm)
        e = se * w
        wm = np.abs(sm * w)
        # Census zero-estimate rule (as in clean.sum_moe): nonzero pieces add in
        # quadrature; of the zero-estimate pieces only the largest MOE counts, once.
        zero = e == 0
        parts = pd.DataFrame({"t": xw.target.to_numpy(), "e": e, "m": wm,
                              "nz2": np.where(zero, 0.0, wm ** 2), "z": np.where(zero, wm, 0.0)})
        g = parts.groupby("t")
        # A null piece makes the target null rather than a silent undercount.
        complete = (g.e.count() == g.size()) & (g.m.count() == g.size())
        est = g.e.sum(min_count=1).where(complete)
        moe = np.sqrt(g.nz2.sum() + g.z.max() ** 2).where(complete)
        out[f"{name}_e"], out[f"{name}_m"] = est.reindex(targets), moe.reindex(targets)

    frame = pd.DataFrame(out, index=targets)
    for name, kind in kinds.items():
        if kind in EXTENSIVE:
            continue
        if name not in recipes:
            raise ValueError(f"{name}: intensive measure with no numerator/denominator recipe")
        num, den, prop = recipes[name]
        scale = 100.0 if prop else 1.0
        frame[f"{name}_e"], frame[f"{name}_m"] = ratio(
            frame[f"{num}_e"], frame[f"{num}_m"], frame[f"{den}_e"], frame[f"{den}_m"],
            proportion=prop, scale=scale)
    frame.index.name = "GEOID"
    return frame[[c for c in source.columns]]


def build(state: str, out: Path, source_vintage="2006-2010", target_vintage="2016-2020") -> Path:
    check_scope([state], [source_vintage, target_vintage], "tract")
    dest = out / "harmonized" / source_vintage / "tract-2020" / f"{state}.parquet"
    if dest.exists():
        raise FileExistsError(f"{dest} exists; delete it deliberately to rebuild.")
    src_path = out / "acs" / source_vintage / "tract" / f"{state}.parquet"
    tgt_path = out / "acs" / target_vintage / "tract" / f"{state}.parquet"
    xw_path = out / "crosswalk" / "2010-2020" / "tract" / f"{state}.parquet"

    src = pq.read_table(src_path)
    notes = json.loads(src.schema.metadata[b"strata"])["measures"]
    source = src.to_pandas().set_index("GEOID")
    targets = pd.Index(pq.read_table(tgt_path, columns=["GEOID"]).column("GEOID").to_pylist(), name="GEOID")
    xw = pq.read_table(xw_path).to_pandas()

    xw, null_targets, applied = tract_changes(xw, state, source_vintage)
    # Sources whose boundaries Census redrew are left out above; they stay in the
    # cube unused, and the 2020 tracts they fed are left without a value.
    frame = apportion(source, notes, xw, targets)
    if null_targets:
        frame.loc[frame.index.isin(null_targets), :] = np.nan
    table = to_table(frame, notes)
    sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
    meta = {"vintage": source_vintage, "level": "tract", "geography": "2020 tracts", "state": state,
            "harmonized": True, "method": "population-weighted apportionment (etl/harmonize.py)",
            "built": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "registry_version": load_measures()["registry_version"], "measures": notes,
            "inputs": {"source_cube": sha(src_path), "crosswalk": sha(xw_path)},
            "tract_code_changes": [{k: c[k] for k in ("old", "new", "kind")} for c in applied],
            "not_comparable_targets": null_targets}
    table = table.replace_schema_metadata({"strata": json.dumps(meta)})
    dest.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(table, dest, compression="zstd", row_group_size=8000, write_statistics=True)
    meta.update(bytes=dest.stat().st_size, sha256=sha(dest))
    dest.with_suffix(".meta.json").write_text(json.dumps(meta, indent=2) + "\n")
    print(f"wrote {dest} ({table.num_rows} rows)")
    return dest


def on_2010_tracts() -> list[str]:
    """Vintages tabulated on 2010 tracts: the ones the 2010-2020 crosswalk moves."""
    return sorted(v for v, c in load_summary_files()["vintages"].items() if c.get("tract_geography") == "2010")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--states", default="51", help="FIPS or postal codes, comma-separated, or 'all'")
    ap.add_argument("--out", type=Path, default=Path("build"))
    ap.add_argument("--vintages", default="2006-2010",
                    help="source vintages on 2010 tract lines, comma-separated, or 'all'")
    args = ap.parse_args(argv)
    vintages = on_2010_tracts() if args.vintages == "all" else [resolve_vintage(v) for v in args.vintages.split(",")]
    for v in vintages:
        for s in parse_states(args.states):
            build(s.strip(), args.out, source_vintage=v)
    return 0


if __name__ == "__main__":
    sys.exit(main())
