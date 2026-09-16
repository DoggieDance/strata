from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "build"
CUBE = BUILD / "acs" / "2016-2020" / "tract" / "51.parquet"


def built_artifacts():
    return sorted(BUILD.rglob("*.parquet")) if BUILD.exists() else []


@pytest.fixture(scope="session")
def cube():
    if not CUBE.exists():
        pytest.skip(f"{CUBE.relative_to(ROOT)} not built")
    import pyarrow.parquet as pq

    return pq.ParquetFile(CUBE)
