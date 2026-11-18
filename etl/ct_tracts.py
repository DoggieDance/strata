"""Connecticut, 2020-2024: put the planning-region tract codes back on 2020 codes.

    python -m etl.ct_tracts --out build

From the 2022 releases on, Census tabulates Connecticut by nine planning
regions instead of eight counties, and every tract's GEOID changed its county
part (09001xxxxxx -> 09110xxxxxx) although the tracts themselves did not move.
Census publishes no tract-code crosswalk for this, so this script builds one
from the boundaries: each 2024 tract's interior point must fall in exactly one
2020 tract, the mapping must be one-to-one, and the six-digit tract code must be
unchanged. Any failure stops the build.

Areas are compared on Census's recorded total area (ALAND + AWATER in the
cartographic files), not on the drawn polygons: the 2020 and 2024 files are
generalized differently, which moves drawn areas by up to 6% with no boundary
change. A few tracts' recorded areas did change (TIGER boundary corrections,
up to 4.8% in 2026-11-17's check). A tract whose recorded area changed by more
than 1% keeps its 2020-2024 values in the level map but is left out of change
maps (its re-keyed row is emptied), and is listed in the metadata. More than
10% stops the build: that is not a correction.

Writes harmonized/2020-2024/tract-2020/09.parquet: the 2020-2024 Connecticut
tract cube with 2020 GEOIDs, so change maps can join it to earlier periods.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import geopandas as gpd
import pyarrow as pa
import pyarrow.compute  # noqa: F401  (pa.compute)
import pyarrow.parquet as pq

SOURCE, TARGET, ST = "2020-2024", "2016-2020", "09"


def mapping(out: Path) -> dict[str, str]:
    new = gpd.read_file(out / "geo" / SOURCE / "tract" / f"{ST}.geojson").to_crs(5070)
    old = gpd.read_file(out / "geo" / TARGET / "tract" / f"{ST}.geojson").to_crs(5070)
    pts = new.assign(geometry=new.geometry.representative_point())
    j = gpd.sjoin(pts, old.rename(columns={"GEOID": "OLD"}), predicate="within", how="left")
    if j.OLD.isna().any() or j.GEOID.duplicated().any():
        raise ValueError(f"{int(j.OLD.isna().sum())} 2024 CT tracts fall in no 2020 tract, or in several")
    m = dict(zip(j.GEOID, j.OLD))
    if len(set(m.values())) != len(m):
        raise ValueError("Connecticut tract mapping is not one-to-one")
    if any(g[5:] != m[g][5:] for g in m):
        raise ValueError("a CT tract changed its six-digit tract code, not only its county part")
    return m


def recorded_area_ratio(m: dict[str, str]) -> dict[str, float]:
    """2024 / 2020 recorded total area (ALAND + AWATER) per 2024 tract."""
    from etl.build_geometry import source
    tot = lambda v: (lambda d: d.set_index("GEOID").ALAND.astype(float) + d.set_index("GEOID").AWATER.astype(float))(
        gpd.read_file(f"zip://{source(v, 'tract', ST)[1]}", ignore_geometry=True))
    a_new, a_old = tot(SOURCE), tot(TARGET)
    return {g: float(a_new[g] / a_old[m[g]]) for g in m}


def build(out: Path) -> Path:
    dest = out / "harmonized" / SOURCE / "tract-2020" / f"{ST}.parquet"
    if dest.exists():
        raise FileExistsError(f"{dest} exists; delete it deliberately to rebuild.")
    m = mapping(out)
    src = out / "acs" / SOURCE / "tract" / f"{ST}.parquet"
    t = pq.read_table(src)
    ids = t.column("GEOID").to_pylist()
    unmapped = [g for g in ids if g not in m]
    ratio = recorded_area_ratio(m)
    wild = {g: r for g, r in ratio.items() if abs(r - 1) > 0.10}
    if wild:
        raise ValueError(f"{len(wild)} CT tracts changed recorded area by more than 10%: {wild}")
    moved = {g: round(r, 4) for g, r in ratio.items() if abs(r - 1) > 0.01}
    rekeyed = [m.get(g, g) for g in ids]
    order = sorted(range(len(rekeyed)), key=lambda i: rekeyed[i])
    t = t.set_column(t.schema.get_field_index("GEOID"), "GEOID", pa.array(rekeyed)).take(order)
    # Boundary-corrected tracts: no change-map value (the row stays, emptied).
    gone = pa.array([g in {m[x] for x in moved} for g in t.column("GEOID").to_pylist()])
    for i, name in enumerate(t.column_names):
        if name != "GEOID":
            col = t.column(i)
            t = t.set_column(i, name, pa.compute.if_else(gone, pa.nulls(len(t), col.type), col))
    meta = json.loads(t.schema.metadata[b"strata"])
    meta.update(geography="2020 tracts", harmonized=True,
                method="Connecticut planning-region tract codes mapped back to 2020 codes by identical boundaries (etl/ct_tracts.py)",
                built=datetime.now(timezone.utc).isoformat(timespec="seconds"), mapped=len(m), unmapped_rows=unmapped,
                boundary_corrected={m[g]: r for g, r in moved.items()},
                boundary_rule="recorded total area (ALAND+AWATER) changed by more than 1% between the 2020 and 2024 files: emptied for change maps",
                inputs={"source_cube": hashlib.sha256(src.read_bytes()).hexdigest()})
    t = t.replace_schema_metadata({"strata": json.dumps(meta)})
    dest.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(t, dest, compression="zstd", row_group_size=8000, write_statistics=True)
    dest.with_suffix(".meta.json").write_text(json.dumps(meta, indent=2) + "\n")
    print(f"wrote {dest}: {len(m)} tracts mapped one-to-one; {len(moved)} boundary-corrected tracts emptied for change maps {moved}; {len(unmapped)} cube rows without a polygon kept as-is")
    return dest


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", type=Path, default=Path("build"))
    build(ap.parse_args(argv).out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
