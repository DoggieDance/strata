"""Download the table-based Summary File tables the measure registry names.

Caches under data/raw/acs/{vintage}/. Each file gets a sidecar
`<name>.meta.json` holding the validators it was fetched with. A HEAD request
is compared against those validators before any download: ETag when the server
sends one, otherwise Last-Modified + Content-Length (www2.census.gov currently
sends no ETag for these files).

    python -m etl.fetch_summary_file --vintage 2016-2020
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests

from etl.common import (
    ROOT,
    check_scope,
    load_measures,
    load_summary_files,
    raw_dir,
    resolve_vintage,
    table_path,
)

TIMEOUT = 120
CHUNK = 1 << 20


def _detailed_table(entry: dict, vintage: str, where: str) -> str:
    """Resolve a registry source entry to a Summary File (detailed) table ID."""
    sub = entry.get("summary_file_substitute")
    if sub is not None and "table" not in sub:  # denominators key it by vintage
        sub = sub.get(vintage)
    if sub:
        return sub["table"]
    if entry.get("dataset", "acs5") != "acs5":
        raise ValueError(
            f"{where}: dataset {entry['dataset']!r} is not in the Summary File "
            f"and has no summary_file_substitute for {vintage}"
        )
    return entry["table"]


def required_tables(vintage: str) -> list[str]:
    reg = load_measures()
    tables = set()
    for m in reg["measures"]:
        src = m["sources"].get(vintage)
        if src is None:
            raise ValueError(f"measure {m['id']} has no source for {vintage}")
        tables.add(_detailed_table(src, vintage, m["id"]))
    for name, d in reg["denominators"].items():
        tables.add(_detailed_table(d, vintage, f"denominator {name}"))
    return sorted(tables)


def _validators(headers) -> dict:
    return {
        "etag": headers.get("ETag"),
        "last_modified": headers.get("Last-Modified"),
        "content_length": int(headers["Content-Length"])
        if headers.get("Content-Length")
        else None,
    }


def _fresh(cached: dict, remote: dict) -> bool:
    if remote["etag"]:
        return cached.get("etag") == remote["etag"]
    if remote["last_modified"] and remote["content_length"] is not None:
        return (
            cached.get("last_modified") == remote["last_modified"]
            and cached.get("content_length") == remote["content_length"]
        )
    return False  # no usable validator: always refetch


def fetch(url: str, dest: Path, session: requests.Session) -> str:
    """Fetch url to dest unless the cache is current. Returns 'cached' or 'downloaded'."""
    meta_path = dest.with_name(dest.name + ".meta.json")
    head = session.head(url, timeout=TIMEOUT, allow_redirects=True)
    head.raise_for_status()
    remote = _validators(head.headers)

    if dest.exists() and meta_path.exists():
        cached = json.loads(meta_path.read_text())
        if _fresh(cached, remote) and dest.stat().st_size == cached.get("size"):
            return "cached"

    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    sha = hashlib.sha256()
    size = 0
    with session.get(url, timeout=TIMEOUT, stream=True) as r:
        r.raise_for_status()
        got = _validators(r.headers)
        with open(part, "wb") as f:
            for chunk in r.iter_content(CHUNK):
                f.write(chunk)
                sha.update(chunk)
                size += len(chunk)
    if got["content_length"] is not None and size != got["content_length"]:
        part.unlink()
        raise IOError(f"{url}: got {size} bytes, expected {got['content_length']}")
    part.replace(dest)
    meta_path.write_text(
        json.dumps(
            {
                "url": url,
                **got,
                "size": size,
                "sha256": sha.hexdigest(),
                "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            },
            indent=2,
        )
        + "\n"
    )
    return "downloaded"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--vintage", default="2016-2020")
    args = ap.parse_args(argv)
    vintage = resolve_vintage(args.vintage)
    check_scope(["51"], [vintage], "tract")

    cfg = load_summary_files()["vintages"][vintage]
    targets = [
        (cfg["data_base"] + cfg["table_file"].format(table=t.lower()), table_path(vintage, t))
        for t in required_tables(vintage)
    ]
    for key in ("geos", "table_shells"):
        url = cfg[key]
        targets.append((url, raw_dir(vintage) / url.rsplit("/", 1)[1]))

    with requests.Session() as s:
        s.headers["User-Agent"] = "strata-etl (static ACS build)"
        for url, dest in targets:
            status = fetch(url, dest, s)
            print(f"{status:10s} {dest.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
