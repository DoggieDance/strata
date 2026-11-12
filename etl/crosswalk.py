"""2010 -> 2020 tract crosswalk weighted by 2020 block population (spec 02).

    weight(s -> t) = sum pop(2020 blocks ∩ s ∩ t) / sum pop(2020 blocks ∩ s)

Inputs (registry/crosswalk.json):
- Census 2010-2020 block relationship file: every 2010-block x 2020-block
  intersection, with its land area.
- 2020 PL 94-171 redistricting file: P1_001 (total population) per 2020 block.

A 2020 block's population is split across its intersections in proportion to
intersecting land. Blocks are small, so the "people are spread evenly" assumption
is applied at the finest grain Census publishes, not across a whole tract (the
Philadelphia study's area weighting). A source tract with no 2020 population at
all falls back to land-area weights, flagged basis="land".

Output: build/crosswalk/2010-2020/tract/{state}.parquet
    source (2010 tract), target (2020 tract), weight, pop, land, basis

    python -m etl.crosswalk --states 51
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import requests

from etl.common import RAW_DIR, REGISTRY_DIR, ROOT, check_scope


def registry() -> dict:
    return json.loads((REGISTRY_DIR / "crosswalk.json").read_text())


def _raw(url: str) -> Path:
    return RAW_DIR.parent / "crosswalk" / url.rsplit("/", 1)[1]


def fetch_inputs(state: str) -> dict[str, Path]:
    from etl.fetch_summary_file import fetch
    cfg = registry()["2010-2020"]["states"][state]
    out = {}
    with requests.Session() as s:
        s.headers["User-Agent"] = "strata-etl (static ACS build)"
        for key in ("blocks", "population", "tract_relationship"):
            url = cfg[key]
            out[key] = _raw(url)
            print(f"{fetch(url, out[key], s):10s} {out[key].resolve().relative_to(ROOT)}")
    return out


def block_population(pl_zip: Path, stusab: str) -> pd.Series:
    """2020 block GEOID (15 chars) -> P1_001 total population."""
    with zipfile.ZipFile(pl_zip) as z:
        with z.open(f"{stusab}geo2020.pl") as f:
            geo = pd.read_csv(io.TextIOWrapper(f, encoding="latin-1"), sep="|", header=None,
                              usecols=[2, 7, 9], names=["SUMLEV", "LOGRECNO", "GEOCODE"], dtype=str)
        with z.open(f"{stusab}000012020.pl") as f:
            seg = pd.read_csv(f, sep="|", header=None, usecols=[4, 5], names=["LOGRECNO", "P1_001"],
                              dtype={"LOGRECNO": str, "P1_001": "int64"})
    blocks = geo[geo.SUMLEV == "750"].merge(seg, on="LOGRECNO", how="left", validate="one_to_one")
    if blocks.P1_001.isna().any():
        raise ValueError("PL file: a block has no P1 row")
    if not (blocks.GEOCODE.str.len() == 15).all() or not blocks.GEOCODE.is_unique:
        raise ValueError("PL file: block GEOCODEs are not unique 15-character codes")
    return blocks.set_index("GEOCODE").P1_001


def intersections(rel_zip: Path) -> pd.DataFrame:
    with zipfile.ZipFile(rel_zip) as z:
        (name,) = [n for n in z.namelist() if n.endswith(".txt")]
        with z.open(name) as f:
            rel = pd.read_csv(f, sep="|", dtype=str, encoding="utf-8-sig")
    rel["block20"] = rel.STATE_2020 + rel.COUNTY_2020 + rel.TRACT_2020 + rel.BLK_2020
    rel["source"] = rel.STATE_2010 + rel.COUNTY_2010 + rel.TRACT_2010
    rel["target"] = rel.STATE_2020 + rel.COUNTY_2020 + rel.TRACT_2020
    rel["land"] = rel.AREALAND_INT.astype("int64")
    rel["water"] = rel.AREAWATER_INT.astype("int64")
    return rel[["source", "target", "block20", "land", "water"]]


def weights(rel: pd.DataFrame, pop20: pd.Series, state: str) -> tuple[pd.DataFrame, dict]:
    """Tract-to-tract weights. Returns (frame, diagnostics)."""
    rel = rel.copy()
    rel["block_pop"] = rel.block20.map(pop20)
    missing = rel.block_pop.isna() & rel.block20.str.startswith(state)
    if missing.any():
        raise ValueError(f"{int(missing.sum())} 2020 {state} blocks in the relationship file have no PL row")
    rel["block_pop"] = rel.block_pop.fillna(0)

    # Split each 2020 block's people by its share of intersecting land; a block
    # with no land in any intersection (water only) splits by water, then evenly.
    g = rel.groupby("block20")
    land_tot = g.land.transform("sum")
    water_tot = g.water.transform("sum")
    n = g.land.transform("size")
    share = np.where(land_tot > 0, rel.land / land_tot.where(land_tot > 0, 1),
                     np.where(water_tot > 0, rel.water / water_tot.where(water_tot > 0, 1), 1 / n))
    rel["pop"] = rel.block_pop * share

    # 2010 blocks from other states (boundary corrections) belong to those
    # states' 2010 tracts, not ours. Their people are counted and reported.
    foreign = ~rel.source.str.startswith(state)
    diag = {"pop_in_foreign_2010_blocks": float(rel.loc[foreign, "pop"].sum()),
            "pop_2020_state": int(pop20[pop20.index.str.startswith(state)].sum())}
    rel = rel[~foreign]

    pairs = rel.groupby(["source", "target"], as_index=False)[["pop", "land"]].sum()
    by_src = pairs.groupby("source")[["pop", "land"]].transform("sum")
    pairs["basis"] = np.where(by_src["pop"] > 0, "population", "land")
    with np.errstate(invalid="ignore", divide="ignore"):
        pairs["weight"] = np.where(by_src["pop"] > 0, pairs["pop"] / by_src["pop"],
                                   pairs["land"] / by_src["land"])
    # A source with neither people nor land (pure water) gets equal weights.
    nan = pairs.weight.isna()
    if nan.any():
        cnt = pairs.groupby("source").target.transform("size")
        pairs.loc[nan, "weight"] = 1 / cnt[nan]
        pairs.loc[nan, "basis"] = "even"
    pairs = pairs[pairs.weight > 0].sort_values(["source", "target"]).reset_index(drop=True)
    diag["pop_assigned"] = float(pairs["pop"].sum())
    diag["sources"] = int(pairs.source.nunique())
    diag["targets"] = int(pairs.target.nunique())
    diag["pairs"] = len(pairs)
    diag["basis_counts"] = pairs.drop_duplicates("source").basis.value_counts().to_dict()
    return pairs[["source", "target", "weight", "pop", "land", "basis"]], diag


def build(state: str, out: Path) -> Path:
    check_scope([state], ["2006-2010", "2016-2020"], "tract")
    dest = out / "crosswalk" / "2010-2020" / "tract" / f"{state}.parquet"
    if dest.exists():
        raise FileExistsError(f"{dest} exists; delete it deliberately to rebuild.")
    cfg = registry()["2010-2020"]["states"][state]
    paths = fetch_inputs(state)
    pop20 = block_population(paths["population"], cfg["stusab"])
    frame, diag = weights(intersections(paths["blocks"]), pop20, state)
    meta = {"from": "2010 tracts", "to": "2020 tracts", "state": state,
            "method": registry()["2010-2020"]["method"],
            "built": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "inputs": {k: json.loads(p.with_name(p.name + ".meta.json").read_text()) for k, p in paths.items()},
            "diagnostics": diag}
    table = pa.Table.from_pandas(frame, preserve_index=False)
    table = table.replace_schema_metadata({"strata": json.dumps(meta)})
    dest.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(table, dest, compression="zstd")
    meta.update(bytes=dest.stat().st_size, sha256=hashlib.sha256(dest.read_bytes()).hexdigest())
    dest.with_suffix(".meta.json").write_text(json.dumps(meta, indent=2) + "\n")
    print(f"wrote {dest}: {diag}")
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
