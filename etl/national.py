"""National layers for the nationwide default view (owner, 2026-11-12).

    python -m etl.national --out build

Writes, from the per-state builds:

- geo/states.geojson + geo/states.json: state outlines (1:20,000,000) and each
  state's bounding box, for the state picker and the viewport loader.
- acs/{vintage}/county/us.parquet: every state's county cube, stacked. Only
  written once all 51 states are built for that vintage; a partial national
  file would look complete and isn't.
- geo/{vintage}/county/us.geojson (+ names): county outlines at 1:5,000,000.
  The national view is drawn at country scale, where 1:500k detail is
  invisible and costs megabytes. State views keep the 1:500k files.

Values are not recomputed here: a county row is byte-for-byte the row in its
state's cube. Tracts, places and ZIP codes stay per state; the app loads the
states in view (spec 03's viewport-scoped fallback for Phase 07).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import geopandas as gpd
import pyarrow as pa
import pyarrow.parquet as pq
import requests

from etl.build_geometry import PRECISION
from etl.common import RAW_DIR, ROOT, load_states
from etl.fetch_summary_file import fetch

SOURCES = {
    "states": ("https://www2.census.gov/geo/tiger/GENZ2020/shp/cb_2020_us_state_20m.zip", "GEOID"),
    "2016-2020": ("https://www2.census.gov/geo/tiger/GENZ2020/shp/cb_2020_us_county_5m.zip", "GEOID"),
    "2006-2010": ("https://www2.census.gov/geo/tiger/GENZ2010/gz_2010_us_050_00_5m.zip", ["STATE", "COUNTY"]),
}


def _raw(url: str) -> Path:
    return RAW_DIR.parent / "geo" / "national" / url.rsplit("/", 1)[1]


def _read(key: str) -> gpd.GeoDataFrame:
    url, col = SOURCES[key]
    raw = _raw(url)
    with requests.Session() as s:
        s.headers["User-Agent"] = "strata-etl (static ACS build)"
        print(f"{fetch(url, raw, s):10s} {raw.resolve().relative_to(ROOT)}")
    gdf = gpd.read_file(f"zip://{raw}")
    gdf["GEOID"] = gdf[col] if isinstance(col, str) else gdf[col].astype(str).agg("".join, axis=1)
    return gdf.to_crs(4326)


def _write_geojson(gdf: gpd.GeoDataFrame, dest: Path, cols=("GEOID",)) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    gdf[[*cols, "geometry"]].sort_values("GEOID").to_file(
        part, driver="GeoJSON", COORDINATE_PRECISION=PRECISION, RFC7946="YES")
    part.replace(dest)


def states_layer(out: Path) -> None:
    states = load_states()
    gdf = _read("states")
    gdf = gdf[gdf.GEOID.isin(states)].copy()
    if set(gdf.GEOID) != set(states):
        raise ValueError(f"state outlines missing {sorted(set(states) - set(gdf.GEOID))}")
    gdf["NAME"] = gdf.GEOID.map(lambda g: states[g]["name"])
    _write_geojson(gdf, out / "geo" / "states.geojson", ("GEOID", "NAME"))
    # Alaska's Aleutians cross the antimeridian; a box from -180 to 180 would
    # make it "visible" everywhere. Clip boxes to the western hemisphere.
    boxes = {}
    for g, geom in zip(gdf.GEOID, gdf.geometry):
        parts = getattr(geom, "geoms", [geom])
        west = [p for p in parts if p.bounds[2] < 0] or parts
        xs = [b for p in west for b in (p.bounds[0], p.bounds[2])]
        ys = [b for p in west for b in (p.bounds[1], p.bounds[3])]
        boxes[g] = {"name": states[g]["name"], "abbr": states[g]["stusab"].upper(),
                    "bbox": [round(min(xs), 3), round(min(ys), 3), round(max(xs), 3), round(max(ys), 3)]}
    (out / "geo" / "states.json").write_text(json.dumps(dict(sorted(boxes.items())), separators=(",", ":")))
    print(f"wrote geo/states.geojson, geo/states.json ({len(boxes)} states)")


def county_layer(out: Path, vintage: str) -> bool:
    states = sorted(load_states())
    paths = [out / "acs" / vintage / "county" / f"{s}.parquet" for s in states]
    missing = [p.stem for p in paths if not p.exists()]
    if missing:
        print(f"skip {vintage} national counties: {len(missing)} states not built ({', '.join(missing[:8])}…)")
        return False
    dest = out / "acs" / vintage / "county" / "us.parquet"
    if not dest.exists():
        _write_cube(paths, dest, states, out)
    ids = pq.read_table(dest, columns=["GEOID"]).column("GEOID").to_pylist()
    geo = out / "geo" / vintage / "county" / "us.geojson"
    names_path = geo.with_name("us.names.json")
    if geo.exists() and names_path.exists():
        print(f"exists {dest.relative_to(out)} and its outlines")
        return True
    _write_outlines(out, vintage, ids, states)
    return True


def _write_cube(paths, dest, states, out):
    tables = [pq.read_table(p) for p in paths]
    meta = json.loads(tables[0].schema.metadata[b"strata"])
    for p, t in zip(paths, tables):
        if t.schema.remove_metadata() != tables[0].schema.remove_metadata():
            raise ValueError(f"{p}: schema differs from {paths[0]}")
    table = pa.concat_tables([t.replace_schema_metadata(None) for t in tables])
    ids = table.column("GEOID").to_pylist()
    if len(set(ids)) != len(ids) or ids != sorted(ids):
        raise ValueError("national county GEOIDs are not unique and sorted")
    meta.update(state="us", states=states, built_from=[str(p.relative_to(out)) for p in paths])
    table = table.replace_schema_metadata({"strata": json.dumps(meta)})
    part = dest.with_name(dest.name + ".part")
    pq.write_table(table, part, compression="zstd", row_group_size=8000, write_statistics=True)
    part.replace(dest)


def _write_outlines(out, vintage, ids, states):
    """Outlines and names; rerunnable on their own if a previous run stopped
    after the cube (review: a crash here used to strand us.parquet forever)."""
    gdf = _read(vintage)
    gdf = gdf[gdf.GEOID.isin(set(ids))]
    extra = set(ids) - set(gdf.GEOID)
    _write_geojson(gdf, out / "geo" / vintage / "county" / "us.geojson")
    names = {}
    for s in states:
        names.update(json.loads((out / "geo" / vintage / "county" / f"{s}.names.json").read_text()))
    state_names = load_states()
    names = {g: f"{n}, {state_names[g[:2]]['stusab'].upper()}" for g, n in names.items()}
    # Names last: their presence marks the outline step complete.
    (out / "geo" / vintage / "county" / "us.names.json").write_text(
        json.dumps(dict(sorted(names.items())), separators=(",", ":")))
    print(f"wrote national {vintage} counties: {len(ids)} rows, {len(gdf)} outlines "
          f"({len(extra)} without a 1:5M outline: {sorted(extra)[:5]})")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", type=Path, default=Path("build"))
    args = ap.parse_args(argv)
    states_layer(args.out)
    for v in ("2016-2020", "2006-2010"):
        county_layer(args.out, v)
    return 0


if __name__ == "__main__":
    sys.exit(main())
