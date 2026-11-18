"""MOE rules from Census's own worked examples (methods audit 2026-11-17)."""
import math

import numpy as np
import pandas as pd

from etl.clean import ratio, sum_cells, sum_moe


def test_zero_estimate_rule_matches_census_slide_26():
    # ACS MOE training (2016), slide 26: 36 +/- 56, 0 +/- 27, 0 +/- 29, 0 +/- 29.
    # Use the largest zero-estimate MOE once: sqrt(56^2 + 29^2) = 63.06.
    got = sum_moe(np.array([[36, 0, 0, 0]]), np.array([[56, 27, 29, 29]]))
    assert round(float(got[0]), 2) == 63.06


def test_no_zeros_is_plain_root_sum_of_squares():
    got = sum_moe(np.array([[10, 20]]), np.array([[3, 4]]))
    assert float(got[0]) == 5.0


def test_all_zero_cells_take_the_largest_once():
    got = sum_moe(np.array([[0, 0, 0]]), np.array([[127, 127, 90]]))
    assert float(got[0]) == 127.0


def test_null_propagates():
    got = sum_moe(np.array([[1, np.nan]]), np.array([[1, 1]]))
    assert math.isnan(got[0])


def test_sum_cells_uses_the_rule():
    t = pd.DataFrame({"E001": [36], "M001": [56], "E002": [0], "M002": [27], "E003": [0], "M003": [29]})
    e, m = sum_cells(t, ["001", "002", "003"])
    assert e.iloc[0] == 36 and round(m.iloc[0], 2) == 63.06


def test_proportion_of_one_uses_numerator_moe_over_denominator():
    # P = 1: SE(P) = SE(X)/Y (Census statistical-testing instructions).
    p, m = ratio([50], [12], [50], [12], proportion=True, scale=100)
    assert p.iloc[0] == 100 and math.isclose(m.iloc[0], 12 / 50 * 100)


def test_proportion_falls_back_to_ratio_when_radicand_negative():
    # Handbook 2020 ch. 8: substitute '+' for '-' under the root.
    p, m = ratio([10], [2], [20], [10], proportion=True)
    assert math.isclose(m.iloc[0], math.sqrt(2**2 + 0.25 * 10**2) / 20)
