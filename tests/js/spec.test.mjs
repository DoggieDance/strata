// Index links and the sensitivity readout (spec 04).
import test from "node:test";
import assert from "node:assert/strict";
import { encodeSpec, decodeSpec, canonical, quintiles, sensitivity } from "../../app/engine/spec.js";

const PHILLY = {
  name: "Philadelphia study, 2010–2020 — ünïcode survives",
  level: "tract", mode: "change", vintages: ["2006-2010", "2016-2020"], aggregate: "mean",
  measures: ["mean_household_income", "mean_gross_rent", "mean_home_value", "pct_bachelors_plus", "pct_nh_white"]
    .map((id) => ({ id, polarity: "+", weight: 1, transform: "none", normalize: "z" })),
};

test("a spec survives the round trip through a link", () => {
  const s = encodeSpec(PHILLY);
  assert.match(s, /^[A-Za-z0-9_-]+$/, "URL-safe, no padding");
  assert.deepEqual(decodeSpec(s), canonical(PHILLY));
});

test("equal specs make equal links regardless of key order or extra fields", () => {
  const shuffled = { aggregate: "mean", extra: 1, vintages: PHILLY.vintages, measures: PHILLY.measures.map((m) => ({ normalize: m.normalize, weight: 1, id: m.id, transform: "none", polarity: "+", junk: true })), mode: "change", level: "tract", name: PHILLY.name };
  assert.equal(encodeSpec(shuffled), encodeSpec(PHILLY));
});

test("damaged or foreign links are refused, not guessed at", () => {
  assert.throws(() => decodeSpec("not*base64"), /damaged/);
  assert.throws(() => decodeSpec(Buffer.from(JSON.stringify({ v: 2, measures: [], vintages: [] })).toString("base64url")), /version/);
  assert.throws(() => decodeSpec(Buffer.from(JSON.stringify({ v: 1, mode: "change", measures: [], vintages: ["2016-2020"] })).toString("base64url")), /periods/);
});

test("quintiles: five equal classes over distinct scores, nulls kept null", () => {
  const score = Array.from({ length: 100 }, (_, i) => i);
  score[3] = null;
  const { cls } = quintiles(score);
  assert.equal(cls[3], null);
  const counts = [0, 0, 0, 0, 0];
  cls.forEach((c) => c != null && counts[c]++);
  assert.ok(counts.every((c) => c >= 19 && c <= 21), counts.join());
});

test("sensitivity: a single-measure index never reshuffles; a balanced one moves some", () => {
  const ids = Array.from({ length: 200 }, (_, i) => `t${i}`);
  let s = 3;
  const r = () => ((s = (s * 1664525 + 1013904223) >>> 0) / 2 ** 32);
  const d = { ids, measures: { a: { values: ids.map(r), unit: "pct" }, b: { values: ids.map(r), unit: "pct" } } };
  const one = sensitivity({ aggregate: "mean", measures: [{ id: "a", polarity: "+", weight: 1 }] }, d);
  assert.equal(one.worst.share, 0);
  const two = sensitivity({ aggregate: "mean", measures: [{ id: "a", polarity: "+", weight: 1 }, { id: "b", polarity: "+", weight: 1 }] }, d);
  assert.ok(two.worst.share > 0 && two.worst.share < 0.5, String(two.worst.share));
  assert.equal(two.n, 200);
});
