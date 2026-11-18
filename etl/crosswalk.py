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

from etl.common import RAW_DIR, REGISTRY_DIR, ROOT, check_scope, parse_states, state_info


def registry() -> dict:
    return json.loads((REGISTRY_DIR / "crosswalk.json").read_text())


def _raw(url: str) -> Path:
    return RAW_DIR.parent / "crosswalk" / url.rsplit("/", 1)[1]


def state_urls(state: str) -> dict:
    info = state_info(state)
    return {k: u.format(fips=state, stusab=info["stusab"], pl_dir=info["pl_dir"])
            for k, u in registry()["2010-2020"]["urls"].items()} | {"stusab": info["stusab"]}


def fetch_inputs(state: str) -> dict[str, Path]:
    from etl.fetch_summary_file import fetch
    cfg = state_urls(state)
    out = {}
    with requests.Session() as s:
        s.headers["User-Agent"] = "strata-etl (static ACS build)"
        for key in ("blocks", "population", "tract_relationship"):
            url = cfg[key]
            out[key] = _raw(url)
            print(f"{fetch(url, out[key], s):10s} {out[key].resolve().relative_to(ROOT)}")
    return out


# Counts per 2020 block from the PL 94-171 file, each a weighting base:
#   pop    P1_001 total population                     (segment 1, field 5)
#   gq     P5_001 group-quarters population            (segment 3, field 5)
#   hu     H1_001 housing units                        (segment 2, field 149)
#   hh     H1_002 occupied housing units = households  (segment 2, field 150)
# Field positions are 0-based after the 5 header fields (FILEID, STUSAB,
# CHARITER, CIFSN, LOGRECNO); segment 2 holds P3 (71 cells) and P4 (73) before H1.
PL_FIELDS = {"pop": (1, 5), "gq": (3, 5), "hu": (2, 149), "hh": (2, 150), "vacant": (2, 151)}
BASES = ("pop", "hhpop", "hh", "hu")


def block_counts(pl_zip: Path, stusab: str) -> pd.DataFrame:
    """2020 block GEOID (15 chars) -> pop, gq, hu, hh, hhpop."""
    with zipfile.ZipFile(pl_zip) as z:
        with z.open(f"{stusab}geo2020.pl") as f:
            geo = pd.read_csv(io.TextIOWrapper(f, encoding="latin-1"), sep="|", header=None,
                              usecols=[2, 7, 9], names=["SUMLEVEL", "LOGRECNO", "GEOCODE"], dtype=str)
        blocks = geo[geo.SUMLEVEL == "750"].set_index("LOGRECNO")
        for name, (seg, col) in PL_FIELDS.items():
            with z.open(f"{stusab}0000{seg}2020.pl") as f:
                part = pd.read_csv(f, sep="|", header=None, usecols=[4, col], names=["LOGRECNO", name],
                                   dtype={"LOGRECNO": str, name: "int64"}).set_index("LOGRECNO")
            blocks = blocks.join(part, how="left", validate="one_to_one")
    if blocks[list(PL_FIELDS)].isna().any().any():
        raise ValueError("PL file: a block is missing a count")
    if not (blocks.hu == blocks.hh + blocks.vacant).all():
        raise ValueError("PL file: H1_001 != H1_002 + H1_003; field positions are wrong")
    if not ((blocks.gq >= 0) & (blocks.gq <= blocks["pop"])).all():
        raise ValueError("PL file: P5_001 outside [0, P1_001]; field positions are wrong")
    if not (blocks.GEOCODE.str.len() == 15).all() or not blocks.GEOCODE.is_unique:
        raise ValueError("PL file: block GEOCODEs are not unique 15-character codes")
    blocks["hhpop"] = blocks["pop"] - blocks.gq
    return blocks.set_index("GEOCODE")[["pop", "gq", "hu", "hh", "hhpop"]]


def block_population(pl_zip: Path, stusab: str) -> pd.Series:
    """2020 block GEOID -> P1_001 total population (kept for the tests)."""
    return block_counts(pl_zip, stusab)["pop"]


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


def pair_weights(pairs: pd.DataFrame) -> pd.DataFrame:
    """(source, target) rows with base counts and land -> per-base weights,
    normalized per source tract, with the land-then-even fallback recorded.
    Shared by weights() and by etl/harmonize.py, which re-keys and pools rows
    when Census recoded a 2010 tract (registry/tract_code_changes.json)."""
    pairs = pairs.groupby(["source", "target"], as_index=False)[[*BASES, "land"]].sum()
    cnt = pairs.groupby("source").target.transform("size")
    land_by_src = pairs.groupby("source").land.transform("sum")
    for b in BASES:
        by_src = pairs.groupby("source")[b].transform("sum")
        with np.errstate(invalid="ignore", divide="ignore"):
            w = np.where(by_src > 0, pairs[b] / by_src,
                         np.where(land_by_src > 0, pairs.land / land_by_src, 1 / cnt))
        pairs[f"weight_{b}"] = w
        pairs[f"basis_{b}"] = np.where(by_src > 0, b, np.where(land_by_src > 0, "land", "even"))
    # "weight" (total population) is kept for older readers.
    pairs["weight"], pairs["basis"] = pairs["weight_pop"], pairs["basis_pop"]
    keep = pairs[[f"weight_{b}" for b in BASES]].max(axis=1) > 0
    return pairs[keep].sort_values(["source", "target"]).reset_index(drop=True)


def weights(rel: pd.DataFrame, counts: pd.DataFrame, state: str) -> tuple[pd.DataFrame, dict]:
    """Tract-to-tract weights, one per base (BASES). Returns (frame, diagnostics).

    Each 2020 block's count is split across its 2010-block intersections by
    intersecting land (then water, then evenly), summed to (2010 tract, 2020
    tract) pairs and normalized per 2010 tract. This is target-density weighting
    (Schroeder 2007; the NHGIS 2010-2020 crosswalks): 2010 counts are spread by
    where the 2020 counts sit. A source tract with none of a base falls back to
    land area, then to even shares; the fallback is recorded per base.
    """
    if isinstance(counts, pd.Series):  # older callers pass total population only
        counts = pd.DataFrame({b: counts for b in BASES})
    rel = rel.copy()
    known = rel.block20.isin(counts.index)
    missing = ~known & rel.block20.str.startswith(state)
    if missing.any():
        raise ValueError(f"{int(missing.sum())} 2020 {state} blocks in the relationship file have no PL row")

    g = rel.groupby("block20")
    land_tot = g.land.transform("sum")
    water_tot = g.water.transform("sum")
    n = g.land.transform("size")
    share = np.where(land_tot > 0, rel.land / land_tot.where(land_tot > 0, 1),
                     np.where(water_tot > 0, rel.water / water_tot.where(water_tot > 0, 1), 1 / n))
    for b in BASES:
        rel[b] = rel.block20.map(counts[b]).fillna(0).to_numpy() * share

    # 2010 blocks from other states (boundary corrections) belong to those
    # states' 2010 tracts, not ours. Their people are counted and reported.
    foreign = ~rel.source.str.startswith(state)
    diag = {"pop_in_foreign_2010_blocks": float(rel.loc[foreign, "pop"].sum()),
            "hu_in_foreign_2010_blocks": float(rel.loc[foreign, "hu"].sum()),
            "pop_2020_state": int(counts.loc[counts.index.str.startswith(state), "pop"].sum()),
            "hu_2020_state": int(counts.loc[counts.index.str.startswith(state), "hu"].sum())}
    rel = rel[~foreign]

    pairs = rel.groupby(["source", "target"], as_index=False)[[*BASES, "land"]].sum()
    pairs = pair_weights(pairs)
    diag["basis_counts"] = {b: pairs.groupby("source")[f"basis_{b}"].first().value_counts().to_dict() for b in BASES}
    diag["pop_assigned"] = float(pairs["pop"].sum())
    diag["hu_assigned"] = float(pairs["hu"].sum())
    diag["sources"] = int(pairs.source.nunique())
    diag["targets"] = int(pairs.target.nunique())
    diag["pairs"] = len(pairs)
    cols = ["source", "target", "weight", "basis", "pop", "land", *[f"weight_{b}" for b in BASES],
            *[f"basis_{b}" for b in BASES], *BASES[1:]]
    return pairs[list(dict.fromkeys(cols))], diag


def build(state: str, out: Path) -> Path:
    check_scope([state], ["2006-2010", "2016-2020"], "tract")
    dest = out / "crosswalk" / "2010-2020" / "tract" / f"{state}.parquet"
    if dest.exists():
        raise FileExistsError(f"{dest} exists; delete it deliberately to rebuild.")
    cfg = state_urls(state)
    paths = fetch_inputs(state)
    counts = block_counts(paths["population"], cfg["stusab"])
    frame, diag = weights(intersections(paths["blocks"]), counts, state)
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
    ap.add_argument("--states", default="51", help="FIPS or postal codes, comma-separated, or 'all'")
    ap.add_argument("--out", type=Path, default=Path("build"))
    args = ap.parse_args(argv)
    for s in parse_states(args.states):
        build(s.strip(), args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
