"""Which ZCTAs belong to a state.

ZCTAs are national geography: they have no state code and some cross state
lines. Each is assigned to exactly one state, so building every state covers
each ZCTA once. Which ZCTA definitions apply depends on the ACS release: the
2016-2020 ACS still tabulates **2010** ZCTAs (registry: levels.zcta.zcta_vintage),
so the 2010 relationship file decides, by 2010 population share.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import pandas as pd
import requests

from etl.common import RAW_DIR, level_cfg, load_summary_files


def zcta_vintage(vintage: str) -> str:
    return level_cfg(vintage, "zcta")["zcta_vintage"]


def relationship_target(vintage: str) -> tuple[str, Path]:
    url = load_summary_files()["zcta_state"][zcta_vintage(vintage)]["relationship"]
    return url, RAW_DIR.parent / "geo" / "rel" / url.rsplit("/", 1)[1]


def ensure_relationship(vintage: str) -> Path:
    url, path = relationship_target(vintage)
    if not (path.exists() and path.with_name(path.name + ".meta.json").exists()):
        from etl.fetch_summary_file import fetch  # late: fetch_summary_file imports this module
        with requests.Session() as s:
            s.headers["User-Agent"] = "strata-etl (static ACS build)"
            fetch(url, path, s)
    return path


def _pick(df: pd.DataFrame, by: list[str]) -> pd.Series:
    """Per ZCTA, the state with the largest value of the `by` columns, in order."""
    agg = df.groupby(["zcta", "state"], as_index=False)[by].sum()
    agg = agg.sort_values(["zcta", *by, "state"], ascending=[True] + [False] * len(by) + [True])
    return agg.drop_duplicates("zcta").set_index("zcta").state


@lru_cache(maxsize=None)
def assignments(zv: str) -> pd.Series:
    """ZCTA (zv definitions: "2010" or "2020") -> state FIPS."""
    url = load_summary_files()["zcta_state"][zv]["relationship"]
    path = RAW_DIR.parent / "geo" / "rel" / url.rsplit("/", 1)[1]
    if zv == "2010":
        rel = pd.read_csv(path, dtype=str, usecols=["ZCTA5", "STATE", "POPPT", "AREALANDPT"])
        rel = rel.rename(columns={"ZCTA5": "zcta", "STATE": "state"})
        rel["pop"] = rel.POPPT.astype("int64")
        rel["land"] = rel.AREALANDPT.astype("int64")
        return _pick(rel, ["pop", "land"])
    rel = pd.read_csv(path, sep="|", dtype=str, encoding="utf-8-sig",
                      usecols=["GEOID_ZCTA5_20", "GEOID_COUNTY_20", "AREALAND_PART"])
    rel = rel.dropna(subset=["GEOID_ZCTA5_20"]).rename(columns={"GEOID_ZCTA5_20": "zcta"})
    rel["state"] = rel.GEOID_COUNTY_20.str[:2]
    rel["land"] = rel.AREALAND_PART.astype("int64")
    return _pick(rel, ["land"])


def for_state(vintage: str, state: str) -> frozenset[str]:
    ensure_relationship(vintage)
    a = assignments(zcta_vintage(vintage))
    return frozenset(a.index[a == state])
