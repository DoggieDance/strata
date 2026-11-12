from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "build"
VINTAGES = ["2016-2020", "2006-2010"]


def cube_path(vintage):
    return BUILD / "acs" / vintage / "tract" / "51.parquet"


CUBE = cube_path("2016-2020")


def built_artifacts():
    return sorted(BUILD.rglob("*.parquet")) if BUILD.exists() else []


def open_cube(vintage):
    path = cube_path(vintage)
    if not path.exists():
        pytest.skip(f"{path.relative_to(ROOT)} not built")
    import pyarrow.parquet as pq

    return pq.ParquetFile(path)


@pytest.fixture(scope="session", params=VINTAGES)
def vintage(request):
    return request.param


@pytest.fixture(scope="session")
def cube(vintage):
    return open_cube(vintage)
