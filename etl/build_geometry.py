"""Geometry for the local preview: build/geo/{vintage}/{level}/{state}.geojson

GeoJSON stands in for the spec 03 PMTiles archive until tippecanoe / GDAL >= 3.8
is on the build box. Same contract either way: features carry only GEOID, and
attributes are joined in the browser from the cube via feature state. Display
names go beside the geometry in {state}.names.json.

    python -m etl.build_geometry --states 51 --vintages 2016-2020,2006-2010 \
        --levels tract,county,place,zcta
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import geopandas as gpd
import pyarrow.parquet as pq
import requests

from etl.clean import geo_names
from etl.common import parse_states, state_info, RAW_DIR, REGISTRY_DIR, ROOT, LevelUnavailable, check_scope, level_cfg, resolve_vintage
from etl.fetch_summary_file import fetch

PRECISION = 5  # ~1 m; the 1:500k source is far coarser
# National files: cut to the cube's GEOIDs (and, for counties, the state prefix).
NATIONAL = {"county", "zcta"}


def load_registry() -> dict:
    return json.loads((REGISTRY_DIR / "geometry.json").read_text())


def source(vintage: str, level: str, state: str) -> tuple[str, Path]:
    url = load_registry()["vintages"][vintage][level]["url"].format(state=state)
    return url, RAW_DIR.parent / "geo" / vintage / url.rsplit("/", 1)[1]


def display_name(level: str, name: str, state_name: str = "Virginia") -> str:
    name = name.split(";")[0].removesuffix(f", {state_name}")
    if level == "tract":
        return name.replace("Census Tract ", "Tract ")
    if level == "zcta":
        return "ZIP " + name.removeprefix("ZCTA5 ").removeprefix("ZCTA ").strip()
    return name


def balance_polygons(gdf, cube_ids: set, names) -> "gpd.GeoDataFrame":
    """Consolidated city-counties (Louisville, Nashville, ...). The ACS publishes
    the "(balance)": the consolidated government minus the separately
    incorporated places inside it. Boundary files may also carry the whole
    consolidated area under a sibling code (cb_2020_21_place: 2148000 beside
    2148006), which overlaps the balance and the places in it.
    - balance has its own polygon: drop the overlapping whole-area polygon;
    - balance has none: draw it as the whole area minus the cube places inside.
    """
    balances = [g for g in cube_ids if "(balance)" in str(names.get(g, ""))]
    for b in balances:
        whole = gdf[(~gdf.GEOID.isin(cube_ids)) & (gdf.GEOID.str[:6] == b[:6])]
        if len(whole) != 1:
            continue
        wid = whole.GEOID.iloc[0]
        gdf = gdf[gdf.GEOID != wid]
        if b in set(gdf.GEOID):
            print(f"balance    {b} has its own polygon; dropped overlapping consolidated area {wid}")
            continue
        geom = whole.geometry.iloc[0]
        inside = gdf[gdf.GEOID.isin(cube_ids) & gdf.intersects(geom)]
        if len(inside):
            geom = geom.difference(inside.geometry.union_all())
        gdf = gpd.GeoDataFrame([*gdf.to_dict("records"), {"GEOID": b, "geometry": geom}], crs=gdf.crs)
        print(f"balance    {b} drawn as {wid} minus {len(inside)} places inside it")
    return gdf


def build(state: str, vintage: str, level: str, out: Path) -> Path:
    check_scope([state], [vintage], level)
    level_cfg(vintage, level)  # raises LevelUnavailable where Census published nothing
    cfg = load_registry()["vintages"][vintage][level]
    url, raw = source(vintage, level, state)
    with requests.Session() as s:
        s.headers["User-Agent"] = "strata-etl (static ACS build)"
        print(f"{fetch(url, raw, s):10s} {raw.resolve().relative_to(ROOT)}")

    cube = out / "acs" / vintage / level / f"{state}.parquet"
    cube_ids = set(pq.read_table(cube, columns=["GEOID"]).column("GEOID").to_pylist())

    gdf = gpd.read_file(f"zip://{raw}")
    key = cfg["geoid"]
    gdf["GEOID"] = gdf[key] if isinstance(key, str) else gdf[key].astype(str).agg("".join, axis=1)
    if level in NATIONAL:
        gdf = gdf[gdf.GEOID.isin(cube_ids)]
    gdf = gdf[["GEOID", "geometry"]].to_crs(4326).sort_values("GEOID")
    if level == "place":
        gdf = balance_polygons(gdf, cube_ids, geo_names(vintage, state, level))
    if gdf.empty or not gdf.GEOID.is_unique:
        raise ValueError(f"{raw.name}: GEOIDs are empty or not unique")
    extra = set(gdf.GEOID) - cube_ids
    if extra:
        raise ValueError(f"{len(extra)} {level} polygons are not in the {vintage} cube, e.g. {sorted(extra)[:3]}")
    missing = sorted(cube_ids - set(gdf.GEOID))

    dest = out / "geo" / vintage / level / f"{state}.geojson"
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    gdf.to_file(part, driver="GeoJSON", COORDINATE_PRECISION=PRECISION, RFC7946="YES")
    part.replace(dest)

    # Names ride beside the geometry, not in it: the tile contract stays GEOID-only.
    names = {g: display_name(level, n, state_info(state)["name"]) for g, n in geo_names(vintage, state, level).items() if g in cube_ids}
    dest.with_name(f"{state}.names.json").write_text(json.dumps(dict(sorted(names.items())), separators=(",", ":")))

    meta = {"vintage": vintage, "level": level, "state": state, "source": url, "features": len(gdf),
            "cube_rows_without_geometry": missing, "bytes": dest.stat().st_size}
    dest.with_suffix(".meta.json").write_text(json.dumps(meta, indent=2) + "\n")
    print(f"wrote {dest.resolve().relative_to(ROOT)}: {len(gdf)} {level} polygons, {dest.stat().st_size:,} bytes; "
          f"{len(missing)} cube rows have no 1:500k polygon")
    return dest


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--states", default="51", help="FIPS or postal codes, comma-separated, or 'all'")
    ap.add_argument("--vintages", default="2016-2020,2006-2010")
    ap.add_argument("--levels", default="tract")
    ap.add_argument("--out", type=Path, default=Path("build"))
    args = ap.parse_args(argv)
    for v in args.vintages.split(","):
        for level in args.levels.split(","):
            for s in parse_states(args.states):
                try:
                    build(s.strip(), resolve_vintage(v.strip()), level.strip(), args.out)
                except LevelUnavailable as e:
                    print(f"skipped {e}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
