"""Label gate (owner, 2026-11-17: "it is one thing to say we are showing bachelor
degrees, its another to make certain that is the field being shown").

For every measure with an independently published Census equivalent
(registry/published_equivalents.json):

1. Census's own label for that variable (api.census.gov variables.json, saved
   under data/raw/labels/) still reads exactly as recorded, so the equivalence
   is to the concept the app's menu names, not to a number that happens to match.
2. The value STRATA serves for the sampled tract or county equals the published
   one, within the publication's rounding. STRATA builds these values from the
   raw detailed tables, so agreement checks the cells, the universe and the label
   together.

Fixtures: tests/fixtures/published_equivalents_{vintage}.csv (etl/label_check.py).
"""
import csv
import json
import math
from collections import defaultdict

import pyarrow.parquet as pq
import pytest

from tests.conftest import BUILD, ROOT

REG = json.loads((ROOT / "registry/published_equivalents.json").read_text())
YEAR = {"2006-2010": 2010, "2011-2015": 2015, "2015-2019": 2019, "2016-2020": 2020, "2020-2024": 2024}
NULL = {"", "-", "N", "(X)", "**", "***", "null", "*****"}


def test_census_labels_unchanged():
    for v, y in YEAR.items():
        path = ROOT / f"data/raw/labels/acs5_profile_{y}.json"
        if not path.exists():
            pytest.skip("label metadata not downloaded")
        labels = json.loads(path.read_text())["variables"]
        for m, d in REG["equivalents"].items():
            if v in d:
                got = [labels[x]["label"] for x in d[v]["variables"]]
                assert got == d[v]["labels"], (m, v)


def test_every_app_measure_is_accounted_for():
    """No measure ships without either a published equivalent or a stated reason."""
    pres = json.loads((ROOT / "registry/presentation.json").read_text())
    shares = json.loads((ROOT / "registry/shares.json").read_text())["shares"]
    ids = [m["id"] for m in pres["measures"]] + [s["id"] for s in shares]
    covered = set(REG["equivalents"]) | set(REG["no_equivalent"])
    assert set(ids) - covered == set()


def _cases():
    out = []
    for v in YEAR:
        f = ROOT / f"tests/fixtures/published_equivalents_{v}.csv"
        if not f.exists():
            continue
        pub = defaultdict(dict)
        for r in csv.DictReader(open(f, newline="")):
            pub[(r["level"], r["GEOID"])][r["variable"]] = r["value"].strip()
        for (level, geoid), vals in sorted(pub.items()):
            for m, d in REG["equivalents"].items():
                if v in d and all(x in vals for x in d[v]["variables"]):
                    out.append(pytest.param(v, level, geoid, m, d[v], {x: vals[x] for x in d[v]["variables"]},
                                            id=f"{v}-{level}-{geoid}-{m}"))
    return out or [pytest.param(None, None, None, None, None, None, id="no-fixtures")]


@pytest.mark.parametrize("vintage,level,geoid,measure,eq,published", _cases())
def test_served_value_equals_published(vintage, level, geoid, measure, eq, published):
    if vintage is None:
        pytest.skip("fixtures not filled yet (python -m etl.label_check)")
    st = geoid[:2]
    path = BUILD / "acs" / vintage / level / f"{st}.parquet"
    col = f"{measure}_e"
    if not path.exists() or col not in pq.ParquetFile(path).schema_arrow.names:
        pytest.skip(f"{col} not in the built {vintage} {level} cube")
    t = pq.read_table(path, columns=["GEOID", col]).to_pydict()
    ours = t[col][t["GEOID"].index(geoid)]
    vals = list(published.values())
    if any(x in NULL for x in vals):
        # Census suppresses a percent whose base is zero; STRATA must not
        # invent one either.
        assert ours is None or math.isnan(ours), (ours, vals)
        return
    nums = [float(x.replace(",", "")) for x in vals]
    op = eq["op"]
    if op == "each":
        targets, tol = nums, (0.05 if eq["variables"][0].endswith("PE") else 0.5)
    elif op == "sum":
        targets, tol = [sum(nums)], 0.05 * len(nums)
    else:  # 100-minus
        targets, tol = [100 - nums[0]], 0.05
    assert ours is not None and not math.isnan(ours), (ours, vals)
    for want in targets:
        assert abs(ours - want) <= tol + 1e-6, f"{measure}: STRATA {ours:.3f} vs Census {want} ({eq['labels']})"


def test_percent_variables_are_percents():
    """A Data Profile 'percent' column can hold a count on heading rows (the
    DP05 65+ trap). Every PE variable we rely on must look like a percent in
    every sampled geography."""
    for v in YEAR:
        f = ROOT / f"tests/fixtures/published_equivalents_{v}.csv"
        if not f.exists():
            continue
        used = {x for d in REG["equivalents"].values() if v in d for x in d[v]["variables"] if x.endswith("PE")}
        for r in csv.DictReader(open(f, newline="")):
            if r["variable"] in used and r["value"].strip() not in NULL:
                assert 0 <= float(r["value"].replace(",", "")) <= 100, (v, r)


def test_no_equivalent_lists_a_variable_twice():
    """A repeated variable is summed twice on screen (tests/browser/labels.mjs) but
    collapses in a dict here, so this gate alone would not catch it (2011-15
    living alone, found 2026-11-17)."""
    for m, d in REG["equivalents"].items():
        for v, e in d.items():
            assert len(set(e["variables"])) == len(e["variables"]), (m, v, e["variables"])
