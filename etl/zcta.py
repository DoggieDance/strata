"""Which ZCTAs belong to a state.

ZCTAs are national geography: they have no state code and some cross state
lines. Each is assigned to the one state that holds the largest share of its
land area, from the Census 2020 ZCTA-to-county relationship file
(registry/summary_files.json "zcta_state"). Every ZCTA lands in exactly one
state, so building every state would cover each ZCTA once.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import pandas as pd
import requests

from etl.common import RAW_DIR, load_summary_files


def relationship_target() -> tuple[str, Path]:
    url = load_summary_files()["zcta_state"]["relationship"]
    return url, RAW_DIR.parent / "geo" / "rel" / url.rsplit("/", 1)[1]


def ensure_relationship() -> Path:
    url, path = relationship_target()
    if not (path.exists() and path.with_name(path.name + ".meta.json").exists()):
        from etl.fetch_summary_file import fetch  # late: fetch_summary_file imports this module
        with requests.Session() as s:
            s.headers["User-Agent"] = "strata-etl (static ACS build)"
            fetch(url, path, s)
    return path


@lru_cache(maxsize=None)
def assignments() -> pd.Series:
    """ZCTA -> state FIPS of its largest land share."""
    rel = pd.read_csv(ensure_relationship(), sep="|", dtype=str, encoding="utf-8-sig",
                      usecols=["GEOID_ZCTA5_20", "GEOID_COUNTY_20", "AREALAND_PART"])
    rel = rel.dropna(subset=["GEOID_ZCTA5_20"])
    rel["state"] = rel.GEOID_COUNTY_20.str[:2]
    rel["land"] = rel.AREALAND_PART.astype("int64")
    by_state = rel.groupby(["GEOID_ZCTA5_20", "state"], as_index=False).land.sum()
    # Largest land share wins; ties (none in 2020) break toward the lower FIPS.
    by_state = by_state.sort_values(["GEOID_ZCTA5_20", "land", "state"], ascending=[True, False, True])
    return by_state.drop_duplicates("GEOID_ZCTA5_20").set_index("GEOID_ZCTA5_20").state


def for_state(state: str) -> frozenset[str]:
    a = assignments()
    return frozenset(a.index[a == state])
