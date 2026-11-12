"""Shared paths, registry loading, and the Phase 01 scope lock."""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REGISTRY_DIR = ROOT / "registry"
RAW_DIR = ROOT / "data" / "raw" / "acs"

# Current phase scope (STRATA-TASKS.md, CURRENT DIRECTIVE). Phase 01 passed
# 2026-11-12 on Virginia. The same day the owner set the goal as nationwide, so
# the lock now admits the 50 states and DC (registry/states.json). Puerto Rico
# is deferred: its survey (PRCS) has its own tables and gets its own review.


def load_states() -> dict[str, dict]:
    """state FIPS -> {stusab, name, acs2010_dir, pl_dir}."""
    return json.loads((REGISTRY_DIR / "states.json").read_text())["states"]


def state_info(fips: str) -> dict:
    try:
        return load_states()[fips]
    except KeyError:
        raise ScopeError(f"state {fips!r} is not in registry/states.json") from None


def parse_states(arg: str) -> list[str]:
    """CLI helper: "51,42", "VA,PA" or "all" -> sorted FIPS codes."""
    states = load_states()
    if arg.strip().lower() == "all":
        return sorted(states)
    by_abbr = {v["stusab"]: k for k, v in states.items()}
    out = []
    for tok in (t.strip() for t in arg.split(",") if t.strip()):
        fips = by_abbr.get(tok.lower(), tok.zfill(2) if tok.isdigit() else tok)
        if fips not in states:
            raise ScopeError(f"unknown state {tok!r}")
        out.append(fips)
    return sorted(set(out))


PHASE_STATES = frozenset(json.loads((REGISTRY_DIR / "states.json").read_text())["states"])
PHASE_VINTAGES = frozenset({"2006-2010", "2016-2020"})
# Levels the owner asked for 2026-11-12: Census-published counties/cities,
# places and ZCTAs, alongside tracts. Values are Census's own estimates for
# those geographies, not sums of tracts.
PHASE_LEVELS = frozenset({"tract", "county", "place", "zcta"})
VINTAGE_ALIASES = {"2010": "2006-2010", "2020": "2016-2020"}

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
            f"Outside the current phase scope (50 states + DC; {', '.join(sorted(PHASE_VINTAGES))}; "
            f"{', '.join(sorted(PHASE_LEVELS))}): " + ", ".join(bad)
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


def vintage_format(vintage: str) -> str:
    """'table' (table-based Summary File) or 'sequence' (2006-2010 style)."""
    return load_summary_files()["vintages"][vintage].get("format", "table")


def level_cfg(vintage: str, level: str) -> dict:
    """Summary-level settings for one vintage. Raises if Census did not publish it."""
    v = load_summary_files()["vintages"][vintage]
    if level in v.get("unavailable_levels", {}):
        raise LevelUnavailable(f"{vintage} {level}: {v['unavailable_levels'][level]}")
    try:
        return v["levels"][level]
    except KeyError:
        raise ValueError(f"{vintage}: no {level!r} level in the registry") from None


class LevelUnavailable(ValueError):
    """Census did not publish this level for this vintage."""
