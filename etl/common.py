"""Shared paths, registry loading, and the Phase 01 scope lock."""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REGISTRY_DIR = ROOT / "registry"
RAW_DIR = ROOT / "data" / "raw" / "acs"

# Phase 01 scope. Nothing outside this set may be built until the Phase 01
# gate passes (STRATA-TASKS.md, CURRENT DIRECTIVE).
PHASE_STATES = frozenset({"51"})
PHASE_VINTAGES = frozenset({"2016-2020"})
PHASE_LEVELS = frozenset({"tract"})
VINTAGE_ALIASES = {"2020": "2016-2020"}

SUMLEVEL_PREFIX = {"tract": "1400000US"}

# Anything below this in a built artifact is a jam value that escaped.
JAM_FLOOR = -1e8


class ScopeError(RuntimeError):
    """Raised when asked to build outside the current phase."""


def load_measures() -> dict:
    return json.loads((REGISTRY_DIR / "measures.seed.json").read_text())


def load_summary_files() -> dict:
    return json.loads((REGISTRY_DIR / "summary_files.json").read_text())


def jam_values() -> frozenset[int]:
    """Sentinels meaning missing data. They become null."""
    return frozenset(int(v) for v in load_measures()["jam_values"])


def controlled_moe_value() -> int:
    """-555555555: MOE of an estimate controlled to an independent total. Becomes 0."""
    return int(load_measures()["controlled_moe_value"])


def resolve_vintage(v: str) -> str:
    return VINTAGE_ALIASES.get(v, v)


def check_scope(states, vintages, level) -> None:
    bad = []
    if set(states) - PHASE_STATES:
        bad.append(f"states {sorted(set(states) - PHASE_STATES)}")
    if set(vintages) - PHASE_VINTAGES:
        bad.append(f"vintages {sorted(set(vintages) - PHASE_VINTAGES)}")
    if level not in PHASE_LEVELS:
        bad.append(f"level {level!r}")
    if bad:
        raise ScopeError(
            "Outside Phase 01 scope (Virginia, 2016-2020, tract): " + ", ".join(bad)
        )


def expand_cells(specs: list[str]) -> list[str]:
    """["002:005"] -> ["002", "003", "004", "005"]; plain cells pass through."""
    out = []
    for s in specs:
        m = re.fullmatch(r"(\d{3}):(\d{3})", s)
        if m:
            lo, hi = int(m[1]), int(m[2])
            if hi < lo:
                raise ValueError(f"bad cell range {s!r}")
            out.extend(f"{i:03d}" for i in range(lo, hi + 1))
        elif re.fullmatch(r"\d{3}", s):
            out.append(s)
        else:
            raise ValueError(f"unsupported cell spec {s!r} for a detailed table")
    return out


def raw_dir(vintage: str) -> Path:
    return RAW_DIR / vintage


def table_path(vintage: str, table: str) -> Path:
    cfg = load_summary_files()["vintages"][vintage]
    return raw_dir(vintage) / cfg["table_file"].format(table=table.lower())
