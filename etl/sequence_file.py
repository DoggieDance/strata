"""Reader for the sequence-based Summary File (2006-2010 and earlier).

A table is not a file here. Its cells sit inside a numbered sequence file,
split into an estimate file (e…txt) and an MOE file (m…txt) inside one zip.
Rows are keyed by LOGRECNO and joined to GEOID through the geography file.
The lookup file gives each table's sequence, start position and line labels.

load_table() returns the same frame the table-based loader does — index GEOID,
columns E001… / M001… — so clean.py stays vintage-agnostic.
"""
from __future__ import annotations

import csv
import io
import zipfile
from dataclasses import dataclass
from functools import lru_cache

import pandas as pd

from etl.common import load_summary_files, raw_dir


@dataclass(frozen=True)
class TableLayout:
    table: str
    sequence: int
    start: int  # 1-based field of line 1, counting the header fields
    cells: int
    labels: tuple[tuple[str, str], ...]  # (cell "001", label)


def cfg(vintage: str) -> dict:
    c = load_summary_files()["vintages"][vintage]
    if c.get("format") != "sequence":
        raise ValueError(f"{vintage} is not a sequence-based vintage")
    return c


def state_cfg(vintage: str, state: str) -> dict:
    try:
        return cfg(vintage)["states"][state]
    except KeyError:
        raise ValueError(f"{vintage}: no sequence-file location recorded for state {state}") from None


def lookup_path(vintage: str):
    return raw_dir(vintage) / cfg(vintage)["lookup"].rsplit("/", 1)[1]


def geos_name(vintage: str, state: str) -> str:
    return cfg(vintage)["geos"].format(**state_cfg(vintage, state))


def sequence_name(vintage: str, state: str, sequence: int) -> str:
    return cfg(vintage)["sequence_file"].format(sequence=sequence, **state_cfg(vintage, state))


def data_url(vintage: str, state: str, name: str) -> str:
    return cfg(vintage)["data_base"].format(**state_cfg(vintage, state)) + name


@lru_cache(maxsize=None)
def _layouts(vintage: str) -> dict[str, TableLayout]:
    raw: dict[str, dict] = {}
    with open(lookup_path(vintage), encoding="latin-1", newline="") as f:
        for r in csv.DictReader(f):
            t = r["Table ID"].strip()
            d = raw.setdefault(t, {"labels": []})
            start = r["Start Position"].strip()
            line = r["Line Number"].strip()
            if start:
                d["sequence"] = int(r["Sequence Number"])
                d["start"] = int(start)
                d["cells"] = int(r["Total Cells in Table"].split()[0])
            elif line and line.isdigit():  # "0.5"-style lines are headings, not cells
                d["labels"].append((f"{int(line):03d}", r["Table Title"].strip()))
    out = {}
    for t, d in raw.items():
        if "start" not in d:
            continue
        out[t] = TableLayout(t, d["sequence"], d["start"], d["cells"], tuple(d["labels"]))
    return out


def layout(vintage: str, table: str) -> TableLayout:
    try:
        lay = _layouts(vintage)[table.upper()]
    except KeyError:
        raise ValueError(f"{table} is not in the {vintage} lookup file") from None
    if [c for c, _ in lay.labels] != [f"{i:03d}" for i in range(1, lay.cells + 1)]:
        raise ValueError(f"lookup: {table} cell lines are not 001..{lay.cells:03d}")
    return lay


def labels(vintage: str) -> dict[str, str]:
    """{"B25075_002": "Less than $10,000", ...} for every table in the lookup file."""
    return {f"{t}_{c}": lab for t, lay in _layouts(vintage).items() for c, lab in lay.labels}


@lru_cache(maxsize=None)
def tracts(vintage: str, state: str) -> pd.DataFrame:
    """Tract rows of the geography file: LOGRECNO, GEOID, NAME.

    The GEOID column is checked against STATE+COUNTY+TRACT rather than trusted.
    """
    c = cfg(vintage)
    col = c["geos_columns"]
    rows = []
    with open(raw_dir(vintage) / geos_name(vintage, state), encoding="latin-1", newline="") as f:
        for r in csv.reader(f):
            if r[col["SUMLEVEL"]] != "140" or r[col["STATE"]] != state:
                continue
            geoid = r[col["STATE"]] + r[col["COUNTY"]] + r[col["TRACT"]]
            if r[col["GEOID"]] != "14000US" + geoid:
                raise ValueError(f"geography file: {r[col['GEOID']]} != 14000US{geoid}")
            rows.append((r[col["LOGRECNO"]], geoid, r[col["NAME"]]))
    df = pd.DataFrame(rows, columns=["LOGRECNO", "GEOID", "NAME"])
    if df.empty or not df.GEOID.is_unique or not df.LOGRECNO.is_unique:
        raise ValueError(f"geography file: tract rows for {state} are empty or not unique")
    return df


def _read_part(zf: zipfile.ZipFile, name: str, lay: TableLayout, logrecnos: set):
    lo = lay.start - 1
    hi = lo + lay.cells
    out = {}
    with zf.open(name) as fh:
        for r in csv.reader(io.TextIOWrapper(fh, encoding="latin-1", newline="")):
            if int(r[4]) != lay.sequence:
                raise ValueError(f"{name}: row for sequence {r[4]}")
            if r[5] in logrecnos:
                if len(r) < hi:
                    raise ValueError(f"{name}: row {r[5]} has {len(r)} fields, need {hi}")
                out[r[5]] = r[lo:hi]
    return out


def load_table(vintage: str, table: str, state: str) -> pd.DataFrame:
    """Raw tract frame for one table: index GEOID, columns E001.. then M001..,
    still as strings with the vintage's missing tokens. clean.load_table
    converts and applies the jam guard."""
    lay = layout(vintage, table)
    geo = tracts(vintage, state)
    logs = set(geo.LOGRECNO)
    header = cfg(vintage)["sequence_header_fields"]
    if lay.start <= header:
        raise ValueError(f"{table}: start position {lay.start} falls inside the header fields")
    name = sequence_name(vintage, state, lay.sequence)
    stem = name.removesuffix(".zip")
    with zipfile.ZipFile(raw_dir(vintage) / name) as zf:
        est = _read_part(zf, f"e{stem}.txt", lay, logs)
        moe = _read_part(zf, f"m{stem}.txt", lay, logs)
    if set(est) != set(moe):
        raise ValueError(f"{name}: estimate and MOE files cover different LOGRECNOs")
    cells = [c for c, _ in lay.labels]
    by_log = geo.set_index("LOGRECNO").GEOID
    rows = {by_log[k]: est[k] + moe[k] for k in est}
    df = pd.DataFrame.from_dict(rows, orient="index",
                                columns=[f"E{c}" for c in cells] + [f"M{c}" for c in cells])
    df.index.name = "GEOID"
    return df.sort_index()


def to_numeric(df: pd.DataFrame, vintage: str) -> pd.DataFrame:
    """Missing tokens -> NaN. Any other non-numeric value raises."""
    tokens = set(cfg(vintage)["missing_tokens"])
    out = df.replace(list(tokens), float("nan"))
    try:
        return out.apply(pd.to_numeric, errors="raise")
    except (ValueError, TypeError) as e:
        raise ValueError(f"unrecognized non-numeric value in sequence file: {e}") from None
