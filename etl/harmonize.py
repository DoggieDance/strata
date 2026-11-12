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
from etl.common import check_scope, load_measures

EXTENSIVE = {"count", "aggregate"}


class MedianApportionError(ValueError):
    """A median cannot be apportioned. Recompute it from bins, or refuse."""


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
    return out


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

    w = xw.weight.to_numpy()
    universes = aggregate_universes()
    out = {}
    for name, kind in kinds.items():
        if kind not in EXTENSIVE:
            continue
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
        m = (sm * w) ** 2
        # A null piece makes the target null (sum with min_count) rather than a
        # silent undercount.
        parts = pd.DataFrame({"t": xw.target.to_numpy(), "e": e, "m": m})
        g = parts.groupby("t")
        est = g.e.sum(min_count=1).where(g.e.count() == g.size())
        moe = np.sqrt(g.m.sum(min_count=1).where(g.m.count() == g.size()))
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

    frame = apportion(source, notes, xw, targets)
    table = to_table(frame, notes)
    sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
    meta = {"vintage": source_vintage, "level": "tract", "geography": "2020 tracts", "state": state,
            "harmonized": True, "method": "population-weighted apportionment (etl/harmonize.py)",
            "built": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "registry_version": load_measures()["registry_version"], "measures": notes,
            "inputs": {"source_cube": sha(src_path), "crosswalk": sha(xw_path)}}
    table = table.replace_schema_metadata({"strata": json.dumps(meta)})
    dest.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(table, dest, compression="zstd", row_group_size=8000, write_statistics=True)
    meta.update(bytes=dest.stat().st_size, sha256=sha(dest))
    dest.with_suffix(".meta.json").write_text(json.dumps(meta, indent=2) + "\n")
    print(f"wrote {dest} ({table.num_rows} rows)")
    return dest


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--states", default="51")
    ap.add_argument("--out", type=Path, default=Path("build"))
    args = ap.parse_args(argv)
    for s in args.states.split(","):
        build(s.strip(), args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
