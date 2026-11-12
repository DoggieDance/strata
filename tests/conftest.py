from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "build"
VINTAGES = ["2016-2020", "2006-2010"]
LEVELS = ["tract", "county", "place", "zcta"]


def cube_path(vintage, level="tract", state="51"):
    return BUILD / "acs" / vintage / level / f"{state}.parquet"


CUBE = cube_path("2016-2020")


def built_artifacts():
    return sorted(BUILD.rglob("*.parquet")) if BUILD.exists() else []


def open_cube(vintage, level="tract", state="51"):
    path = cube_path(vintage, level, state)
    if not path.exists():
        pytest.skip(f"{path.relative_to(ROOT)} not built")
    import pyarrow.parquet as pq

    return pq.ParquetFile(path)


def built_combos():
    """Every (vintage, level) Census published. A missing cube is collected and
    skipped (open_cube), never silently left out."""
    from etl.common import LevelUnavailable, level_cfg
    out = []
    for v in VINTAGES:
        for lv in LEVELS:
            try:
                level_cfg(v, lv)
            except LevelUnavailable:
                continue
            out.append((v, lv))
    return out


@pytest.fixture(scope="session", params=built_combos(), ids=lambda c: f"{c[0]}-{c[1]}")
def combo(request):
    return request.param


@pytest.fixture(scope="session")
def vintage(combo):
    return combo[0]


@pytest.fixture(scope="session")
def level(combo):
    return combo[1]


@pytest.fixture(scope="session")
def cube(vintage, level):
    return open_cube(vintage, level)
