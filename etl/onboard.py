"""Onboard a new ACS vintage: resolve every measure's cells by label.

    python -m etl.onboard --vintage 2015-2019 [--write]

For each share (registry/shares.json), each core measure and each denominator
(registry/measures.seed.json), try the recipes already verified for other
vintages. A recipe is accepted for the new vintage only if its table exists
there and every cell resolves to the same Census label: first at the same cell
number; failing that, at the one cell in the table that carries that label (a
row inserted above it, as when B25034 gained "Built 2010 or later"). Bin tables
(B25075) are re-derived from the vintage's own labels. Nothing is guessed: a
measure with no matching recipe is reported and left out of that vintage, and
the app then shows it as not published for that period.

Without --write it only reports. The label files are Census's own (sequence
lookup files; table shells).
"""
from __future__ import annotations

import argparse
import copy
import json
import re
import sys
from collections import defaultdict

from etl.clean import _shell_labels, midpoints_from_labels
from etl.common import REGISTRY_DIR, expand_cells, resolve_vintage

def _base(label: str | None) -> str:
    s = (label or "").lower().strip().rstrip(":")
    s = re.sub(r"\(in \d{4} inflation-adjusted dollars\)", "", s)
    return re.sub(r"[^a-z0-9$.%]+", " ", s).strip()


# Documented synonyms only (registry/label_synonyms.json, each with its reason).
SYN = {_base(x["a"]): _base(x["b"])
       for x in json.loads((REGISTRY_DIR / "label_synonyms.json").read_text())["synonyms"]}


def norm(label: str | None) -> str:
    s = _base(label)
    return SYN.get(s, s)


class Labels:
    def __init__(self, vintage: str):
        self.by_table = defaultdict(dict)
        for key, lab in _shell_labels(vintage).items():
            t, c = key.rsplit("_", 1)
            if re.fullmatch(r"\d{3}", c):
                self.by_table[t][c] = lab

    def has(self, table: str) -> bool:
        return table in self.by_table

    def resolve(self, table: str, cell: str, want: str) -> str | None:
        cells = self.by_table.get(table, {})
        if norm(cells.get(cell)) == norm(want):
            return cell
        hits = [c for c, lab in cells.items() if norm(lab) == norm(want)]
        return hits[0] if len(hits) == 1 else None


def labels_of(vintage: str):
    return Labels(vintage)


def resolve_cells(L: Labels, table: str, cells: list[str], template: Labels) -> list[str] | None:
    out = []
    for c in cells:
        want = template.by_table[table].get(c)
        got = L.resolve(table, c, want) if want else None
        if got is None:
            return None
        out.append(got)
    return out


def onboard_shares(vintage: str, L: Labels, cache: dict) -> tuple[list, list]:
    shares = json.loads((REGISTRY_DIR / "shares.json").read_text())
    report = []
    for sh in shares["shares"]:
        if vintage in sh["sources"]:
            continue
        done = None
        # Prefer the most recent verified recipe.
        for v in sorted(sh["sources"], reverse=True):
            src = sh["sources"][v]
            if not L.has(src["table"]):
                continue
            T = cache.setdefault(v, labels_of(v))
            num = resolve_cells(L, src["table"], src["numerator_cells"], T)
            den = resolve_cells(L, src["table"], src["denominator_cells"], T)
            if num and den:
                lab = L.by_table[src["table"]]
                done = {"table": src["table"], "numerator_cells": num, "denominator_cells": den,
                        "numerator_labels": [lab[c] for c in num], "denominator_labels": [lab[c] for c in den],
                        "resolved_from": v}
                break
        if done:
            sh["sources"][vintage] = done
            report.append(("ok", sh["id"], f"{done['table']} via {done['resolved_from']}"
                           + ("" if done["numerator_cells"] == sh["sources"][done["resolved_from"]]["numerator_cells"] else " (cells moved)")))
        else:
            tables = sorted({s["table"] for s in sh["sources"].values()})
            report.append(("MISSING", sh["id"], f"no table {'/'.join(tables)} with matching labels in {vintage}"))
    return shares, report


def onboard_core(vintage: str, L: Labels, cache: dict) -> tuple[dict, list]:
    reg = json.loads((REGISTRY_DIR / "measures.seed.json").read_text())
    report = []
    for m in reg["measures"]:
        if vintage in m["sources"]:
            continue
        ok = None
        for v in sorted(m["sources"], reverse=True):
            src = copy.deepcopy(m["sources"][v])
            T = cache.setdefault(v, labels_of(v))
            if m.get("method") == "bin_midpoint_sum" or "top_bin" in src:
                t = src["table"]
                if not L.has(t):
                    continue
                cells = sorted(c for c in L.by_table[t] if c != "001")
                labels = {c: L.by_table[t][c] for c in cells}
                rows = midpoints_from_labels(labels, src["top_bin"])
                src["cells"] = [f"{cells[0]}:{cells[-1]}"]
                src["bins"] = rows
                src["top_bin"]["collapse_from"] = next(r[0] for r in rows if r[1] >= src["top_bin"]["collapse_at_lower_bound"])
                ok = (src, f"{t} bins re-derived from {vintage} labels ({len(rows)} bins, collapse at {src['top_bin']['collapse_from']})")
                break
            sub = src.get("summary_file_substitute")
            if sub:
                t = sub["table"]
                if not L.has(t):
                    continue
                n = resolve_cells(L, t, expand_cells(sub["numerator_cells"]), T)
                d = resolve_cells(L, t, expand_cells(sub["denominator_cells"]), T)
                if n and d:
                    sub.update(numerator_cells=n, denominator_cells=d, resolved_from=v)
                    ok = (src, f"{t} via {v}")
                    break
                continue
            t = src["table"]
            if "cells" in src:
                if not L.has(t):
                    continue
                c = resolve_cells(L, t, expand_cells(src["cells"]), T)
                if c:
                    src["cells"] = c
                    ok = (src, f"{t} via {v}")
                    break
            elif L.has(t):  # ratio: cells live at measure level, checked below
                ok = (src, f"{t} via {v}")
                break
        if ok:
            m["sources"][vintage] = ok[0]
            report.append(("ok", m["id"], ok[1]))
        else:
            report.append(("MISSING", m["id"], "no matching recipe"))
    for name, d in reg["denominators"].items():
        sub = d.get("summary_file_substitute")
        if sub and vintage not in sub:
            for v in sorted(sub, reverse=True):
                s2 = copy.deepcopy(sub[v])
                T = cache.setdefault(v, labels_of(v))
                if L.has(s2["table"]):
                    c = resolve_cells(L, s2["table"], expand_cells(s2["cells"]), T)
                    if c:
                        s2.update(cells=c, resolved_from=v)
                        sub[vintage] = s2
                        report.append(("ok", f"denominator {name}", f"{s2['table']} via {v}"))
                        break
            else:
                report.append(("MISSING", f"denominator {name}", "no matching recipe"))
        elif not sub:
            T = cache.setdefault("2016-2020", labels_of("2016-2020"))
            c = resolve_cells(L, d["table"], expand_cells(d["cells"]), T) if L.has(d["table"]) else None
            report.append(("ok" if c == expand_cells(d["cells"]) else "MISSING", f"denominator {name}",
                           f"{d['table']}_{'+'.join(d['cells'])} " + ("labels match" if c else "labels differ")))
    # Ratio measures name their cells once for all vintages: check them here.
    for m in reg["measures"]:
        for key in ("numerator_source", "denominator_source"):
            if key in m:
                s = m[key]
                T = cache.setdefault("2016-2020", labels_of("2016-2020"))
                c = resolve_cells(L, s["table"], expand_cells(s["cells"]), T)
                if c != expand_cells(s["cells"]):
                    report.append(("MISSING", m["id"], f"{key} {s['table']} labels differ in {vintage}"))
    return reg, report


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--vintage", required=True)
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args(argv)
    v = resolve_vintage(args.vintage)
    L, cache = labels_of(v), {}
    shares, r1 = onboard_shares(v, L, cache)
    core, r2 = onboard_core(v, L, cache)
    for status, what, how in r2 + r1:
        print(f"{status:8s} {what:34s} {how}")
    if args.write:
        for name, obj, ind in (("shares.json", shares, 1), ("measures.seed.json", core, 2)):
            part = REGISTRY_DIR / f".{name}.part"  # atomic: builds may be reading it
            part.write_text(json.dumps(obj, indent=ind, ensure_ascii=False) + "\n")
            part.replace(REGISTRY_DIR / name)
        print("registries updated")
    return 0


if __name__ == "__main__":
    sys.exit(main())
