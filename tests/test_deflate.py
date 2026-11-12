import json

import pytest

from etl.common import REGISTRY_DIR
from etl.deflate import factor, series, vintage_year


def test_2010_to_2020_factor():
    assert factor(2010, 2020) == pytest.approx(380.75541666666663 / 319.8)
    assert factor(2010, 2020) == pytest.approx(1.1906, abs=1e-4)


def test_study_value_is_a_fixture_not_the_answer():
    """The Philadelphia study used 1.187. Our series gives 1.1906: within 0.5%,
    and the gap is to be explained at Phase 04, not copied."""
    study = json.loads((REGISTRY_DIR / "deflators.json").read_text())["fixtures"]["2010_to_2020_study_value"]
    assert abs(factor(2010, 2020) / study - 1) < 0.005


def test_round_trip_and_identity():
    assert factor(2020, 2020) == 1
    assert factor(2010, 2020) * factor(2020, 2010) == pytest.approx(1)


def test_series_is_annual_and_increasing_mostly():
    s = series()
    assert set(range(2004, 2026)) <= set(s)
    assert s[2009] < s[2008]  # the 2009 deflation year is real, not a typo


def test_unknown_year_raises():
    with pytest.raises(KeyError):
        factor(1990, 2020)


def test_vintage_year():
    assert vintage_year("2006-2010") == 2010 and vintage_year("2016-2020") == 2020
