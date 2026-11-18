"""STRATA data dictionary: every measure the app shows, with its exact recipe
per period, generated from the registries the build itself reads.

    .venv/bin/python -m analysis.data_dictionary   # -> docs/data-dictionary.json, docs/DATA-DICTIONARY.md

Nothing here is written by hand: if a recipe changes, regenerating changes the
dictionary, and tests/test_data_dictionary.py fails if the committed copy is stale.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from etl.clean import _shell_labels
from etl.common import REGISTRY_DIR, expand_cells, load_measures, load_shares, load_summary_files

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"

MOE = {
    "percent": "Proportion MOE from the numerator and denominator MOEs (ACS Handbook: derived proportions), falling back to the ratio formula when the proportion radicand is negative.",
    "mean": "Ratio MOE: aggregate MOE and universe MOE combined by the ratio formula (ACS Handbook: derived ratios).",
    "count": "As published by Census.",
}


def labels(v: str) -> dict:
    try:
        return _shell_labels(v)
    except FileNotFoundError:
        return {}


INV = {r["table"]: r for r in json.loads((REGISTRY_DIR / "acs_inventory.json").read_text())["tables"]}


def cells_text(table: str, cells: list[str], lab: dict) -> list[dict]:
    inv = INV.get(table, {})
    return [{"variable": f"{table}_{c}", "label": lab.get(f"{table}_{c}"),
             "table_title": inv.get("title"), "universe": inv.get("universe")} for c in cells]


def build() -> dict:
    pres = json.loads((REGISTRY_DIR / "presentation.json").read_text())
    reg = load_measures()
    eq = json.loads((REGISTRY_DIR / "published_equivalents.json").read_text())
    vintages = sorted(load_summary_files()["vintages"])
    L = {v: labels(v) for v in vintages}
    core = {m["id"]: m for m in reg["measures"]}
    derived = {m["derives"]: m for m in reg["measures"] if m.get("derives")}
    den = reg["denominators"]
    out = []

    def published(mid):
        e = eq["equivalents"].get(mid)
        if e:
            return {v: {"op": x["op"], "variables": x["variables"], "labels": x["labels"]} for v, x in e.items()}
        return {"none": eq["no_equivalent"].get(mid, "")}

    def den_recipe(name, v):
        d = den[name]
        sub = d.get("summary_file_substitute", {}).get(v)
        t, c = (sub["table"], expand_cells(sub["cells"])) if sub else (d["table"], expand_cells(d["cells"]))
        return t, c

    for p in pres["measures"]:
        mid = p["id"]
        e = {"id": mid, "label": p["label"], "topic": p.get("topic"), "format": p["fmt"], "periods": {}}
        if mid in derived:
            m = derived[mid]
            e["kind"] = "mean"
            for v in vintages:
                src = m["sources"].get(v)
                if not src:
                    continue
                t = src["table"]
                cells = expand_cells(src["cells"])
                dt, dc = den_recipe(m["denominator"], v)
                rec = {"numerator": cells_text(t, cells, L[v]), "denominator": cells_text(dt, dc, L[v]),
                       "formula": f"{t} {'bin midpoints × counts' if 'top_bin' in src else '+'.join(cells)} / {dt}_{'+'.join(dc)}"}
                if "top_bin" in src:
                    rec["bins"] = src["bins"]
                    rec["top_bin"] = src["top_bin"]
                e["periods"][v] = rec
            e["note"] = m.get("bin_rule") or m.get("universe") or ""
        elif mid in core:
            m = core[mid]
            e["kind"] = "percent"
            for v in vintages:
                src = m["sources"].get(v)
                if not src:
                    continue
                if src.get("summary_file_substitute"):
                    s = src["summary_file_substitute"]
                    t, n, d = s["table"], expand_cells(s["numerator_cells"]), expand_cells(s["denominator_cells"])
                else:
                    t = m["numerator_source"]["table"]
                    n, d = expand_cells(m["numerator_source"]["cells"]), expand_cells(m["denominator_source"]["cells"])
                e["periods"][v] = {"numerator": cells_text(t, n, L[v]), "denominator": cells_text(t, d, L[v]),
                                   "formula": f"100 × {t}_{'+'.join(n)} / {t}_{'+'.join(d)}"}
        elif mid in den:
            e["kind"] = "count"
            for v in vintages:
                t, c = den_recipe(mid, v)
                if t in {k.rsplit("_", 1)[0] for k in L[v]}:
                    e["periods"][v] = {"numerator": cells_text(t, c, L[v]), "formula": f"{t}_{'+'.join(c)}"}
        out.append(e)

    for sh in load_shares():
        e = {"id": sh["id"], "label": sh["label"], "topic": sh["topic"], "format": "pct", "kind": "percent", "periods": {}}
        for v, src in sorted(sh["sources"].items()):
            t = src["table"]
            e["periods"][v] = {"numerator": cells_text(t, src["numerator_cells"], L[v]),
                               "denominator": cells_text(t, src["denominator_cells"], L[v]),
                               "formula": f"100 × {t}_{'+'.join(src['numerator_cells'])} / {t}_{'+'.join(src['denominator_cells'])}"}
        if sh.get("note"):
            e["note"] = sh["note"]
        out.append(e)

    for e in out:
        e["moe_method"] = MOE[e["kind"]]
        e["published_equivalent"] = published(e["id"])
        e["not_published_for"] = [v for v in vintages if v not in e["periods"]]
    return {"generated_from": ["registry/measures.seed.json", "registry/shares.json", "registry/presentation.json",
                               "registry/published_equivalents.json", "Census label files per period"],
            "periods": vintages, "measures": out}


def markdown(d: dict) -> str:
    lines = ["# STRATA data dictionary", "",
             "Generated by `analysis/data_dictionary.py` from the registries the build reads. Do not edit by hand.", "",
             f"Periods: {', '.join(d['periods'])}. {len(d['measures'])} measures.", ""]
    topic = None
    for e in sorted(d["measures"], key=lambda e: (e["topic"] or "", e["label"])):
        if e["topic"] != topic:
            topic = e["topic"]
            lines += [f"## {topic}", ""]
        lines += [f"### {e['label']}", "", f"`{e['id']}` · {e['kind']} · MOE: {e['moe_method']}", ""]
        for v, r in e["periods"].items():
            num = "; ".join(f"{x['variable']} “{x['label']}”" for x in r["numerator"])
            den = "; ".join(f"{x['variable']} “{x['label']}”" + (f" (universe: {x['universe']})" if x.get("universe") else "")
                            for x in r.get("denominator", []))
            lines.append(f"- **{v}**: `{r['formula']}`. Numerator: {num}." + (f" Denominator: {den}." if den else ""))
        if e["not_published_for"]:
            lines.append(f"- Not published for: {', '.join(e['not_published_for'])}.")
        pe = e["published_equivalent"]
        if "none" in pe:
            lines.append(f"- Checked against: no published Census equivalent. {pe['none']}")
        else:
            for v, x in pe.items():
                lines.append(f"- Checked against Census ({v}): {' + '.join(x['variables'])} “{' / '.join(x['labels'])}” ({x['op']}).")
        if e.get("note"):
            lines.append(f"- Note: {e['note']}")
        lines.append("")
    return "\n".join(lines)


def main() -> int:
    d = build()
    DOCS.mkdir(exist_ok=True)
    (DOCS / "data-dictionary.json").write_text(json.dumps(d, indent=1, ensure_ascii=False) + "\n")
    (DOCS / "DATA-DICTIONARY.md").write_text(markdown(d) + "\n")
    print(f"wrote docs/data-dictionary.json and docs/DATA-DICTIONARY.md ({len(d['measures'])} measures)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
