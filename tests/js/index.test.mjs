// Property tests for the index engine (spec 08, "Property tests").
import test from "node:test";
import assert from "node:assert/strict";
import { index, UnitError, SpecError } from "../../app/engine/index.js";

// Deterministic pseudo-random data.
function rng(seed) { let s = seed >>> 0; return () => ((s = (s * 1664525 + 1013904223) >>> 0) / 2 ** 32); }
function data(n = 60, seed = 7) {
  const r = rng(seed);
  const ids = Array.from({ length: n }, (_, i) => `t${i}`);
  const col = (f, unit) => ({ values: ids.map(() => f(r())), se: ids.map(() => 1 + 2 * r()), unit });
  return { ids, measures: {
    income: col((u) => 30000 + 90000 * u, "usd"),
    rent: col((u) => 600 + 1400 * u, "usd"),
    ba: col((u) => 100 * u, "pct"),
    white: col((u) => 100 * u, "pct"),
  } };
}
const base = (over = {}) => ({ aggregate: "mean", measures: [
  { id: "income", polarity: "+", weight: 1, transform: "log", normalize: "z" },
  { id: "rent", polarity: "+", weight: 1, transform: "log", normalize: "z" },
  { id: "ba", polarity: "+", weight: 1, transform: "none", normalize: "z" },
  { id: "white", polarity: "+", weight: 1, transform: "none", normalize: "z" },
], ...over });
const close = (a, b, eps = 1e-9) => a.every((x, i) => (x == null && b[i] == null) || Math.abs(x - b[i]) < eps);

for (const agg of ["mean", "geometric", "rank_sum"]) {
  test(`${agg}: permutation of measures changes no score`, () => {
    const d = data(), s = base({ aggregate: agg });
    const a = index(s, d), b = index({ ...s, measures: [...s.measures].reverse() }, d);
    assert.ok(close(a.score, b.score));
  });
  test(`${agg}: doubling every weight changes nothing`, () => {
    const d = data(), s = base({ aggregate: agg });
    const b = index({ ...s, measures: s.measures.map((m) => ({ ...m, weight: m.weight * 2 })) }, d);
    assert.ok(close(index(s, d).score, b.score));
  });
  test(`${agg}: rescaling dollars to thousands changes no rank`, () => {
    for (const norm of ["z", "percentile", "minmax", "robust"]) {
      const d = data(), s = base({ aggregate: agg, measures: base().measures.map((m) => ({ ...m, transform: "none", normalize: norm })) });
      const d2 = structuredClone(d);
      d2.measures.income.values = d2.measures.income.values.map((v) => v / 1000);
      assert.deepEqual(index(s, d).rank, index(s, d2).rank, norm);
    }
  });
}

test("mean: flipping one polarity negates exactly that contribution", () => {
  const d = data(), s = base();
  const a = index(s, d);
  const b = index({ ...s, measures: s.measures.map((m) => (m.id === "rent" ? { ...m, polarity: "-" } : m)) }, d);
  for (const id of ["income", "ba", "white"]) assert.ok(close(a.contributions[id], b.contributions[id]));
  assert.ok(close(a.contributions.rent, b.contributions.rent.map((x) => -x)));
});

test("mean: raising one positive measure never lowers that tract's score", () => {
  const d = data(), s = base();
  for (const i of [0, 7, 33]) {
    const d2 = structuredClone(d);
    d2.measures.ba.values[i] += 5;
    // Other tracts' z-scores shift slightly with the mean; this tract's score must not fall.
    assert.ok(index(s, d2).score[i] >= index(s, d).score[i] - 1e-12);
  }
});

test("contributions sum to the score (mean)", () => {
  const d = data(), r = index(base(), d);
  r.score.forEach((sc, i) => {
    const sum = Object.values(r.contributions).reduce((s, c) => s + c[i], 0);
    assert.ok(Math.abs(sum - sc) < 1e-12);
  });
});

test("the hard constraint: unnormalized measures of differing units are refused", () => {
  const s = base({ measures: base().measures.map((m) => ({ ...m, transform: "none", normalize: "none" })) });
  assert.throws(() => index(s, data()), UnitError);
  // Same units, unnormalized: allowed.
  const same = { aggregate: "mean", measures: [
    { id: "ba", polarity: "+", weight: 1, normalize: "none" }, { id: "white", polarity: "+", weight: 1, normalize: "none" }] };
  assert.doesNotThrow(() => index(same, data()));
});

test("polarity is required, not defaulted", () => {
  const s = base({ measures: base().measures.map((m, i) => (i ? m : { ...m, polarity: undefined })) });
  assert.throws(() => index(s, data()), SpecError);
});

test("log refuses negatives (change values must not be logged)", () => {
  const d = data();
  d.measures.income.values[3] = -5;
  assert.throws(() => index(base(), d), UnitError);
});

test("missing input -> null score with a flag, others unaffected", () => {
  const d = data();
  d.measures.ba.values[5] = null;
  const r = index(base(), d);
  assert.equal(r.score[5], null);
  assert.equal(r.flags[5], "missing");
  assert.ok(r.score.filter((x) => x != null).length === d.ids.length - 1);
});

test("SE in z-units: equal weights, unit SEs -> sqrt(sum w^2 se^2)", () => {
  const ids = ["a", "b", "c"];
  const d = { ids, measures: {
    x: { values: [0, 1, 2], se: [0.5, 0.5, 0.5], unit: "pct" },
    y: { values: [2, 1, 0], se: [0.5, 0.5, 0.5], unit: "pct" } } };
  const r = index({ aggregate: "mean", measures: [
    { id: "x", polarity: "+", weight: 1, normalize: "z" }, { id: "y", polarity: "+", weight: 1, normalize: "z" }] }, d);
  // sd = 1, so SE(z) = 0.5 for both; composite = sqrt(0.25*0.25 + 0.25*0.25) = 0.3536
  assert.ok(Math.abs(r.se[0] - Math.sqrt(2) * 0.25) < 1e-12);
});
