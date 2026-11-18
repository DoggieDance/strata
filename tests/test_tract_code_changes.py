"""Census tract recodes after 2010 (registry/tract_code_changes.json, etl/harmonize.tract_changes)."""
import json

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import pytest

from etl.crosswalk import BASES
from etl.harmonize import tract_changes
from tests.conftest import BUILD, ROOT

REG = json.loads((ROOT / "registry" / "tract_code_changes.json").read_text())
BY_OLD = {c["old"]: c for c in REG["changes"]}
only = lambda *olds: [BY_OLD[o] for o in olds]  # the registry's own rows, for small synthetic crosswalks


def xw(rows):
    """rows: (source, target, pop, land); every base gets pop."""
    f = pd.DataFrame(rows, columns=["source", "target", "pop", "land"])
    for b in BASES[1:]:
        f[b] = f["pop"]
    return f


def test_recode_renames_without_changing_weights(monkeypatch):
    x = xw([("02270000100", "02158000100", 8000, 1.0), ("02270000100", "02158000200", 2000, 1.0), ("02013000100", "02013000100", 50, 1.0)])
    out, nulls, applied = tract_changes(x, "02", "2011-2015", only("02270000100"))
    assert nulls == [] and [c["new"] for c in applied] == ["02158000100"]
    w = out.set_index(["source", "target"]).weight_pop
    assert w[("02158000100", "02158000100")] == pytest.approx(0.8)
    assert "02270000100" not in set(out.source)


def test_not_applied_to_2006_2010():
    x = xw([("02270000100", "02158000100", 1, 1.0)])
    out, nulls, applied = tract_changes(x, "02", "2006-2010")
    assert applied == [] and out is x


def test_merge_of_empty_tract_moves_no_weight():
    x = xw([("36085008900", "36085009700", 0, 5.0), ("36085009700", "36085009700", 900, 50.0), ("36085009700", "36085009800", 100, 5.0)])
    out, nulls, _ = tract_changes(x, "36", "2015-2019", only("36085008900"))
    w = out[out.source == "36085009700"].set_index("target").weight_pop
    assert w["36085009700"] == pytest.approx(0.9) and w["36085009800"] == pytest.approx(0.1)


def test_merge_with_people_is_refused():
    x = xw([("36085008900", "36085009700", 10, 5.0), ("36085009700", "36085009700", 900, 50.0)])
    with pytest.raises(ValueError, match="merge of an empty tract"):
        tract_changes(x, "36", "2015-2019", only("36085008900"))


def test_boundary_change_nulls_every_target_it_touched():
    x = xw([("06037930401", "06037137000", 2500, 1.0), ("06037800204", "06037800204", 5000, 1.0),
            ("06037800204", "06037800205", 1500, 1.0), ("06037101110", "06037101110", 4000, 1.0)])
    out, nulls, _ = tract_changes(x, "06", "2011-2015", only("06037930401"))
    assert nulls == ["06037137000", "06037800204", "06037800205"]
    assert set(out.source) == {"06037101110"}


def test_weights_sum_to_one_per_source_after_changes():
    x = xw([("04019002701", "04019002704", 70, 1.0), ("04019002701", "04019002800", 30, 1.0)])
    out, _, _ = tract_changes(x, "04", "2015-2019", only("04019002701"))
    for b in BASES:
        assert np.allclose(out.groupby("source")[f"weight_{b}"].sum(), 1.0)


@pytest.mark.parametrize("vintage", REG["applies_to"])
def test_registry_matches_the_build(vintage):
    """Every old code is in the 2010 crosswalk; every new code is in the period's cube
    (boundary rows: the old code is gone from the cube); after re-keying, the crosswalk
    names no tract the cube lacks."""
    by_state = {}
    for c in REG["changes"]:
        by_state.setdefault(c["old"][:2], []).append(c)
    for st, cs in by_state.items():
        xp, cp = BUILD / "crosswalk/2010-2020/tract" / f"{st}.parquet", BUILD / "acs" / vintage / "tract" / f"{st}.parquet"
        if not (xp.exists() and cp.exists()):
            pytest.skip(f"{st} not built")
        x = pq.read_table(xp).to_pandas()
        cube = set(pq.read_table(cp, columns=["GEOID"]).column(0).to_pylist())
        for c in cs:
            assert c["old"] in set(x.source), c
            assert c["old"] not in cube, c
            assert c["new"] in cube, c
        out, _, _ = tract_changes(x, st, vintage)
        assert set(out.source) <= cube, (st, sorted(set(out.source) - cube)[:3])
