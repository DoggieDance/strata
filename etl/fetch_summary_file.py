"""Download the table-based Summary File tables the measure registry names.

Caches under data/raw/acs/{vintage}/. Each file gets a sidecar
`<name>.meta.json` holding the validators it was fetched with. A HEAD request
is compared against those validators before any download: ETag when the server
sends one, otherwise Last-Modified + Content-Length (www2.census.gov currently
sends no ETag for these files).

    python -m etl.fetch_summary_file --vintage 2016-2020
    python -m etl.fetch_summary_file --vintage 2006-2010

Sequence-based vintages (2006-2010) fetch the lookup file first, check it
against the sha256 the registry records, then fetch the per-state sequence zips
that hold the required tables, plus the geography file.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import requests

from etl.common import (
    ROOT,
    LevelUnavailable,
    parse_states,
    check_scope,
    level_cfg,
    load_measures,
    load_shares,
    load_summary_files,
    raw_dir,
    resolve_vintage,
    table_path,
    vintage_format,
)
from etl import sequence_file

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
        if pub := m.get("published_aggregate"):
            tables.add(pub["table"])
    for name, d in reg["denominators"].items():
        tables.add(_detailed_table(d, vintage, f"denominator {name}"))
    for sh in load_shares():
        if vintage in sh["sources"]:
            tables.add(sh["sources"][vintage]["table"])
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
            and cached.get("content_length") in (remote["content_length"], None)
            and cached.get("size", remote["content_length"]) == remote["content_length"]
        )
    if remote["last_modified"]:
        # www2.census.gov sometimes omits Content-Length on HEAD; an unchanged
        # Last-Modified is then the only validator (the lookup file is also
        # pinned by sha256).
        return cached.get("last_modified") == remote["last_modified"]
    return False  # no usable validator: always refetch


class NotTheFile(IOError):
    """The server answered 200 with something other than the file asked for."""


def check_content(name: str, head: bytes, content_type: str | None = None) -> None:
    """Refuse a download that is not what its name says. www2.census.gov's
    firewall sometimes answers 200 with a 247-byte "Request Rejected" HTML page;
    two of 6,760 files in the 2026-11-17 rebuild were that page saved as .zip."""
    looks_html = head.lstrip()[:15].lower().startswith((b"<html", b"<!doctype", b"<head"))
    if name.lower().endswith((".html", ".htm")):
        return
    if looks_html or (content_type or "").lower().startswith("text/html"):
        raise NotTheFile(f"{name}: the server sent a web page, not the file (often a firewall rejection)")
    if name.lower().endswith(".zip") and not head.startswith(b"PK\x03\x04"):
        raise NotTheFile(f"{name}: not a zip archive (first bytes {head[:8]!r})")


def fetch(url: str, dest: Path, session: requests.Session, tries: int = 4) -> str:
    """Fetch url to dest unless the cache is current. Returns 'cached' or 'downloaded'.
    A rejected or truncated download is retried with a growing pause, then the
    error is raised: a file the server will not send stops the build."""
    for k in range(tries):
        try:
            return _fetch_once(url, dest, session)
        except (NotTheFile, IOError, requests.RequestException) as e:
            missing = isinstance(e, requests.HTTPError) and e.response is not None and e.response.status_code == 404
            if k == tries - 1 or missing:
                raise
            print(f"retrying {dest.name} in {15 * (k + 1)} s: {e}", file=sys.stderr)
            time.sleep(15 * (k + 1))


def _fetch_once(url: str, dest: Path, session: requests.Session) -> str:
    meta_path = dest.with_name(dest.name + ".meta.json")
    head = session.head(url, timeout=TIMEOUT, allow_redirects=True)
    head.raise_for_status()
    remote = _validators(head.headers)

    if dest.exists() and meta_path.exists():
        cached = json.loads(meta_path.read_text())
        if _fresh(cached, remote) and dest.stat().st_size == cached.get("size"):
            with open(dest, "rb") as f:
                try:
                    check_content(dest.name, f.read(64))
                    return "cached"
                except NotTheFile:
                    pass  # a bad page cached by an older fetcher: fetch again

    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(f"{dest.name}.{os.getpid()}.part")  # unique: parallel fetches share files
    sha = hashlib.sha256()
    size = 0
    first = b""
    with session.get(url, timeout=TIMEOUT, stream=True) as r:
        r.raise_for_status()
        got = _validators(r.headers)
        ctype = r.headers.get("Content-Type")
        with open(part, "wb") as f:
            for chunk in r.iter_content(CHUNK):
                if len(first) < 64:
                    first += chunk[: 64 - len(first)]
                f.write(chunk)
                sha.update(chunk)
                size += len(chunk)
    if got["content_length"] is not None and size != got["content_length"]:
        part.unlink()
        raise IOError(f"{url}: got {size} bytes, expected {got['content_length']}")
    try:
        check_content(dest.name, first, ctype)
        if dest.name.lower().endswith(".zip"):
            with zipfile.ZipFile(part) as z:
                if z.testzip() is not None:
                    raise NotTheFile(f"{dest.name}: zip archive fails its CRC check")
    except (NotTheFile, zipfile.BadZipFile) as e:
        part.unlink()
        raise NotTheFile(str(e)) from e
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


def raw_files(vintage: str, state: str = "51", level: str = "tract") -> list[tuple[str, Path]]:
    """(url, local path) for everything one (vintage, level) build reads, in fetch order.
    For sequence vintages the lookup file comes first: it resolves the sequences."""
    level_cfg(vintage, level)  # raises for a level Census did not publish
    if vintage_format(vintage) == "sequence":
        return sequence_targets(vintage, state, level)
    cfg = load_summary_files()["vintages"][vintage]
    targets = [
        (cfg["data_base"] + cfg["table_file"].format(table=t.lower()), table_path(vintage, t))
        for t in required_tables(vintage)
    ]
    for key in ("geos", "table_shells"):
        url = cfg[key]
        targets.append((url, raw_dir(vintage) / url.rsplit("/", 1)[1]))
    if level == "zcta":
        from etl.zcta import relationship_target
        targets.append(relationship_target(vintage))
    return targets


def lookup_target(vintage: str) -> tuple[str, Path]:
    return sequence_file.cfg(vintage)["lookup"], sequence_file.lookup_path(vintage)


def sequence_targets(vintage: str, state: str, level: str = "tract") -> list[tuple[str, Path]]:
    archive = sequence_file.archive_of(vintage, level)
    geo_archive = sequence_file.cfg(vintage)["geos_archive"]
    seqs = sorted({sequence_file.layout(vintage, t).sequence for t in required_tables(vintage)})
    out = [lookup_target(vintage)]
    for q in seqs:
        n = sequence_file.sequence_name(vintage, state, q)
        out.append((sequence_file.data_url(vintage, state, n, archive),
                    sequence_file.local_path(vintage, n, archive)))
    g = sequence_file.geos_name(vintage, state)
    out.append((sequence_file.data_url(vintage, state, g, geo_archive),
                sequence_file.local_path(vintage, g, geo_archive)))
    return out


def verify_lookup(vintage: str) -> None:
    want = sequence_file.cfg(vintage)["lookup_sha256"]
    got = hashlib.sha256(sequence_file.lookup_path(vintage).read_bytes()).hexdigest()
    if got != want:
        raise ValueError(f"{vintage} lookup file sha256 {got} != registry {want}; "
                         "cell positions cannot be trusted")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--vintage", default="2016-2020")
    ap.add_argument("--levels", default="tract", help="comma list: tract,county,place,zcta")
    ap.add_argument("--states", default="51", help="FIPS or postal codes, comma-separated, or 'all'")
    args = ap.parse_args(argv)
    vintage = resolve_vintage(args.vintage)
    levels = [x.strip() for x in args.levels.split(",")]
    states = parse_states(args.states)
    for level in levels:
        check_scope(states, [vintage], level)

    with requests.Session() as s:
        s.headers["User-Agent"] = "strata-etl (static ACS build)"
        if vintage_format(vintage) == "sequence":
            url, dest = lookup_target(vintage)
            print(f"{fetch(url, dest, s):10s} {dest.relative_to(ROOT)}")
            verify_lookup(vintage)
        seen = set()
        for level, st in ((lv, st) for lv in levels for st in states):
            try:
                targets = raw_files(vintage, st, level)
            except LevelUnavailable as e:
                print(f"skipped    {e}")
                continue
            for url, dest in targets:
                fetched_above = vintage_format(vintage) == "sequence" and url == lookup_target(vintage)[0]
                if dest in seen or fetched_above:
                    continue
                seen.add(dest)
                print(f"{fetch(url, dest, s):10s} {dest.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
