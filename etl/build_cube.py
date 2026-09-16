"""Write the attribute cube: build/acs/{vintage}/{level}/{state}.parquet

Rows sorted by GEOID, ~8,000-row groups, zstd. Columns {measure}_e / {measure}_m.
Float32 per spec 03, except dollar aggregates, which are Float64: tract
aggregates reach ~1e9-1e10 dollars, where Float32 cannot hold the published
integer exactly and the Phase 01 spot-check demands exact matches.

Refuses to overwrite an existing cube. Vintages accumulate.

    python -m etl.build_cube --states 51 --vintages 2016-2020 --out build/
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from etl.clean import build_measures
from etl.common import (
    JAM_FLOOR,
    check_scope,
    load_measures,
    load_summary_files,
    raw_dir,
    resolve_vintage,
)
from etl.fetch_summary_file import required_tables

ROW_GROUP_SIZE = 8000


def cube_path(out: Path, vintage: str, level: str, state: str) -> Path:
    return out / "acs" / vintage / level / f"{state}.parquet"


def _sources(vintage: str) -> list[dict]:
    cfg = load_summary_files()["vintages"][vintage]
    names = [cfg["table_file"].format(table=t.lower()) for t in required_tables(vintage)]
    names += [cfg[k].rsplit("/", 1)[1] for k in ("geos", "table_shells")]
    out = []
    for n in names:
        meta = json.loads((raw_dir(vintage) / f"{n}.meta.json").read_text())
        out.append({k: meta.get(k) for k in ("url", "last_modified", "etag", "size", "sha256")})
    return out


def to_table(frame, notes) -> pa.Table:
    arrays = [pa.array(frame.index.to_numpy(dtype=str), pa.string())]
    fields = [pa.field("GEOID", pa.string(), nullable=False)]
    for col in frame.columns:
        measure = col.rsplit("_", 1)[0]
        wide = notes[measure]["kind"] == "aggregate"
        dtype = pa.float64() if wide else pa.float32()
        vals = frame[col].to_numpy(dtype="float64")
        if not wide:
            finite = vals[np.isfinite(vals)]
            if finite.size and np.abs(finite).max() >= 2**24 and notes[measure]["kind"] == "count":
                raise ValueError(f"{col}: count exceeds Float32 exact-integer range")
        arrays.append(pa.array(vals, type=dtype, from_pandas=True))  # NaN -> null
        fields.append(pa.field(col, dtype))
    return pa.Table.from_arrays(arrays, schema=pa.schema(fields))


def build(state: str, vintage: str, level: str, out: Path) -> Path:
    check_scope([state], [vintage], level)
    dest = cube_path(out, vintage, level, state)
    if dest.exists():
        raise FileExistsError(f"{dest} exists. Vintages accumulate; refusing to overwrite.")

    frame, notes = build_measures(vintage, state, level)
    frame = frame.sort_index()
    if not frame.index.is_monotonic_increasing or not frame.index.is_unique:
        raise ValueError("GEOID index must be unique and sorted")
    values = frame.to_numpy(dtype="float64")
    if (values[np.isfinite(values)] < JAM_FLOOR).any():
        raise ValueError("jam value survived cleaning")

    table = to_table(frame, notes)
    meta = {
        "vintage": vintage,
        "level": level,
        "state": state,
        "rows": table.num_rows,
        "built": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "registry_version": load_measures()["registry_version"],
        "summary_file": load_summary_files()["vintages"][vintage],
        "measures": notes,
        "sources": _sources(vintage),
    }
    table = table.replace_schema_metadata({"strata": json.dumps(meta)})

    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    pq.write_table(
        table, part, compression="zstd", row_group_size=ROW_GROUP_SIZE,
        write_statistics=True,
    )
    part.replace(dest)
    sha = hashlib.sha256(dest.read_bytes()).hexdigest()
    meta.update(bytes=dest.stat().st_size, sha256=sha)
    dest.with_suffix(".meta.json").write_text(json.dumps(meta, indent=2) + "\n")
    return dest


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--states", default="51")
    ap.add_argument("--vintages", default="2016-2020")
    ap.add_argument("--level", default="tract")
    ap.add_argument("--out", type=Path, default=Path("build"))
    args = ap.parse_args(argv)
    states = [s.strip() for s in args.states.split(",")]
    vintages = [resolve_vintage(v.strip()) for v in args.vintages.split(",")]
    check_scope(states, vintages, args.level)
    for v in vintages:
        for s in states:
            p = build(s, v, args.level, args.out)
            print(f"wrote {p} ({p.stat().st_size:,} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
