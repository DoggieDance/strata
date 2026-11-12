"""Tract geometry for the local preview: build/geo/{vintage}/tract/{state}.geojson

GeoJSON stands in for the spec 03 PMTiles archive until tippecanoe / GDAL >= 3.8
is on the build box. Same contract either way: features carry only GEOID, and
attributes are joined in the browser from the cube via feature state.

    python -m etl.build_geometry --states 51 --vintages 2016-2020,2006-2010
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import geopandas as gpd
import pyarrow.parquet as pq
import requests

from etl.clean import tract_names
from etl.common import RAW_DIR, REGISTRY_DIR, ROOT, check_scope, resolve_vintage
from etl.fetch_summary_file import fetch

PRECISION = 5  # ~1 m; the 1:500k source is far coarser


def load_registry() -> dict:
    return json.loads((REGISTRY_DIR / "geometry.json").read_text())


def source(vintage: str, state: str) -> tuple[str, Path]:
    url = load_registry()["vintages"][vintage]["url"].format(state=state)
    return url, RAW_DIR.parent / "geo" / vintage / url.rsplit("/", 1)[1]


def build(state: str, vintage: str, out: Path) -> Path:
    check_scope([state], [vintage], "tract")
    cfg = load_registry()["vintages"][vintage]
    url, raw = source(vintage, state)
    with requests.Session() as s:
        s.headers["User-Agent"] = "strata-etl (static ACS build)"
        print(f"{fetch(url, raw, s):10s} {raw.resolve().relative_to(ROOT)}")

    gdf = gpd.read_file(f"zip://{raw}")
    key = cfg["geoid"]
    gdf["GEOID"] = gdf[key] if isinstance(key, str) else gdf[key].astype(str).agg("".join, axis=1)
    gdf = gdf[["GEOID", "geometry"]].to_crs(4326).sort_values("GEOID")
    if not gdf.GEOID.is_unique or not (gdf.GEOID.str.len() == 11).all():
        raise ValueError(f"{raw.name}: GEOIDs are not unique 11-character codes")

    cube = out / "acs" / vintage / "tract" / f"{state}.parquet"
    cube_ids = set(pq.read_table(cube, columns=["GEOID"]).column("GEOID").to_pylist())
    extra = set(gdf.GEOID) - cube_ids
    if extra:
        raise ValueError(f"{len(extra)} geometry tracts are not in the {vintage} cube, e.g. {sorted(extra)[:3]}")
    missing = sorted(cube_ids - set(gdf.GEOID))

    dest = out / "geo" / vintage / "tract" / f"{state}.geojson"
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    gdf.to_file(part, driver="GeoJSON", COORDINATE_PRECISION=PRECISION, RFC7946="YES")
    part.replace(dest)
    # Names ride beside the geometry, not in it: the tile contract stays GEOID-only.
    names = {g: n.split(";")[0].split(", Virginia")[0].replace("Census Tract ", "Tract ")
             for g, n in tract_names(vintage, state).items() if g in cube_ids}
    names_path = dest.with_name(f"{state}.names.json")
    names_path.write_text(json.dumps(dict(sorted(names.items())), separators=(",", ":")))
    meta = {"vintage": vintage, "state": state, "source": url, "features": len(gdf),
            "cube_tracts_without_geometry": missing, "bytes": dest.stat().st_size}
    dest.with_suffix(".meta.json").write_text(json.dumps(meta, indent=2) + "\n")
    print(f"wrote {dest.resolve().relative_to(ROOT)}: {len(gdf)} tracts, {dest.stat().st_size:,} bytes; "
          f"{len(missing)} cube tracts have no 1:500k polygon")
    return dest


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--states", default="51")
    ap.add_argument("--vintages", default="2016-2020,2006-2010")
    ap.add_argument("--out", type=Path, default=Path("build"))
    args = ap.parse_args(argv)
    for v in args.vintages.split(","):
        for s in args.states.split(","):
            build(s.strip(), resolve_vintage(v.strip()), args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
