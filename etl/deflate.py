"""Inflation factors from registry/deflators.json (R-CPI-U-RS, as Census uses for ACS).

    adjusted = raw * factor(source_year, target_year)

ACS 5-year dollars are in the end year's dollars: 2006-2010 is in 2010 dollars.
Applied where vintages meet (change over time), never inside a cube, which keeps
published values exactly as published.
"""
from __future__ import annotations

import json

from etl.common import REGISTRY_DIR


def series() -> dict[int, float]:
    d = json.loads((REGISTRY_DIR / "deflators.json").read_text())
    return {int(y): float(v) for y, v in d["annual"].items()}


def factor(source_year: int, target_year: int) -> float:
    s = series()
    missing = [y for y in (source_year, target_year) if y not in s]
    if missing:
        raise KeyError(f"no R-CPI-U-RS annual average for {missing}")
    return s[target_year] / s[source_year]


def vintage_year(vintage: str) -> int:
    """'2006-2010' -> 2010: the year whose dollars a 5-year vintage is published in."""
    return int(vintage.split("-")[1])
