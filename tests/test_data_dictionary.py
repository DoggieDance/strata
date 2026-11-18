"""docs/data-dictionary.json is generated from the registries; it must match them."""
import json

from tests.conftest import ROOT


def test_dictionary_is_current():
    from analysis.data_dictionary import build
    committed = json.loads((ROOT / "docs/data-dictionary.json").read_text())
    assert build() == committed, "run: .venv/bin/python -m analysis.data_dictionary"


def test_every_app_measure_has_an_entry_with_labels():
    d = json.loads((ROOT / "docs/data-dictionary.json").read_text())
    for e in d["measures"]:
        assert e["periods"], e["id"]
        for v, r in e["periods"].items():
            assert all(x["label"] for x in r["numerator"] + r.get("denominator", [])), (e["id"], v)
