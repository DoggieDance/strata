// The index engine (spec 04). A pure function: spec in, scores out. No DOM, no
// network, no state, so it runs in the page, in a worker, and under node --test.
//
//   index(spec, data) -> { score, rank, percentile, contributions, se, flags }
//
// data: { ids: string[], measures: { [id]: { values: (number|null)[], se?: (number|null)[], unit } } }
// spec: { measures: [{ id, polarity: "+"|"-", weight, transform, normalize }], aggregate, missing }
//
// Pipeline per measure: transform -> normalize -> polarity -> weight; then
// aggregate across measures. Uncertainty is carried in normalized units:
// SE(z) = SE(x') / sigma, where x' is the transformed value and SE(x') its
// delta-method SE (log1p: SE / (1 + x)); the composite SE for the weighted mean
// is sqrt(sum w_i^2 SE(z_i)^2), treating measures as independent (stated, not
// hidden: they are not, so this is a lower bound). A CV is not reported: it is
// undefined for z-scores, whose mean is about 0 (methods audit 2026-11-17).

export class UnitError extends Error {}
export class SpecError extends Error {}

const TRANSFORMS = new Set(["none", "log"]);
const NORMALIZE = new Set(["z", "percentile", "minmax", "robust", "none"]);
const AGGREGATE = new Set(["mean", "geometric", "rank_sum"]);

const finite = (v) => v != null && Number.isFinite(v);

function mean(a) { return a.reduce((s, x) => s + x, 0) / a.length; }
function sd(a) { const m = mean(a); return Math.sqrt(a.reduce((s, x) => s + (x - m) ** 2, 0) / (a.length - 1)); }
function quantile(sorted, q) {
  const i = (sorted.length - 1) * q, lo = Math.floor(i), hi = Math.ceil(i);
  return sorted[lo] + (sorted[hi] - sorted[lo]) * (i - lo);
}

/** Average ranks (ties share the mean rank), scaled to [0, 1]. */
function percentileRanks(values) {
  const idx = values.map((v, i) => [v, i]).filter(([v]) => finite(v)).sort((a, b) => a[0] - b[0]);
  const out = values.map(() => null);
  const n = idx.length;
  for (let i = 0; i < n;) {
    let j = i;
    while (j + 1 < n && idx[j + 1][0] === idx[i][0]) j++;
    const r = (i + j) / 2;
    for (let k = i; k <= j; k++) out[idx[k][1]] = n > 1 ? r / (n - 1) : 0.5;
    i = j + 1;
  }
  return out;
}

export function validate(spec, data) {
  if (!spec?.measures?.length) throw new SpecError("an index needs at least one measure");
  const agg = spec.aggregate ?? "mean";
  if (!AGGREGATE.has(agg)) throw new SpecError(`unknown aggregate ${agg}`);
  const seen = new Set();
  for (const m of spec.measures) {
    if (seen.has(m.id)) throw new SpecError(`${m.id} appears twice`);
    seen.add(m.id);
    if (!data.measures[m.id]) throw new SpecError(`no data for ${m.id}`);
    if (m.polarity !== "+" && m.polarity !== "-") throw new SpecError(`${m.id}: polarity must be "+" or "-", not defaulted`);
    if (!TRANSFORMS.has(m.transform ?? "none")) throw new SpecError(`${m.id}: unknown transform ${m.transform}`);
    if (!NORMALIZE.has(m.normalize ?? "z")) throw new SpecError(`${m.id}: unknown normalization ${m.normalize}`);
    if (!(m.weight >= 0)) throw new SpecError(`${m.id}: weight must be a non-negative number`);
  }
  // The hard constraint (spec 04): never aggregate unnormalized measures of differing units.
  const raw = spec.measures.filter((m) => (m.normalize ?? "z") === "none");
  if (raw.length && spec.measures.length > 1) {
    const units = new Set(spec.measures.map((m) => ((m.normalize ?? "z") === "none" ? data.measures[m.id].unit : "normalized")));
    if (units.size > 1) {
      throw new UnitError(`refusing to combine unnormalized measures of differing units (${[...units].join(", ")}); normalize every measure first. See the Area Deprivation Index failure, spec 04.`);
    }
  }
  if (spec.measures.every((m) => m.weight === 0)) throw new SpecError("all weights are zero");
}

/** One measure through transform and normalize. Returns {z, se} arrays (null where missing). */
export function normalizeMeasure(m, d) {
  const n = d.values.length;
  const t = m.transform ?? "none", norm = m.normalize ?? "z";
  const x = new Array(n), xse = new Array(n);
  for (let i = 0; i < n; i++) {
    const v = d.values[i], s = d.se?.[i];
    if (!finite(v)) { x[i] = null; xse[i] = null; continue; }
    if (t === "log") {
      if (v < 0) throw new UnitError(`${m.id}: log transform refuses negative values (${v}); use a level map or another transform`);
      x[i] = Math.log1p(v);
      xse[i] = finite(s) ? s / (1 + v) : null;
    } else { x[i] = v; xse[i] = finite(s) ? s : null; }
  }
  const ok = x.filter(finite);
  let z, scale = null;
  if (norm === "z") {
    const mu = mean(ok), sigma = sd(ok);
    scale = sigma > 0 ? sigma : 1;
    z = x.map((v) => (finite(v) ? (v - mu) / scale : null));
  } else if (norm === "robust") {
    const s = [...ok].sort((a, b) => a - b), med = quantile(s, 0.5), iqr = quantile(s, 0.75) - quantile(s, 0.25);
    scale = iqr > 0 ? iqr : 1;
    z = x.map((v) => (finite(v) ? (v - med) / scale : null));
  } else if (norm === "minmax") {
    const lo = Math.min(...ok), hi = Math.max(...ok);
    scale = hi > lo ? hi - lo : 1;
    z = x.map((v) => (finite(v) ? (v - lo) / scale : null));
  } else if (norm === "percentile") {
    z = percentileRanks(x);
  } else {
    z = x;
    scale = 1;
  }
  const se = xse.map((s) => (scale != null && finite(s) ? s / scale : null));
  return { z, se };
}

export function index(spec, data) {
  validate(spec, data);
  const n = data.ids.length;
  const agg = spec.aggregate ?? "mean";
  const ms = spec.measures.filter((m) => m.weight > 0);
  const wsum = ms.reduce((s, m) => s + m.weight, 0);
  const w = ms.map((m) => m.weight / wsum);  // doubling every weight changes nothing
  const cols = ms.map((m) => {
    const r = normalizeMeasure(m, data.measures[m.id]);
    const sign = m.polarity === "-" ? -1 : 1;
    return { id: m.id, z: r.z.map((v) => (v == null ? null : sign * v)), se: r.se };
  });

  const score = new Array(n).fill(null), se = new Array(n).fill(null), flags = new Array(n).fill(null);
  const contributions = Object.fromEntries(cols.map((c) => [c.id, new Array(n).fill(null)]));
  let rows = [...Array(n).keys()];

  if (agg === "rank_sum") {
    // CDC SVI: percentile-rank each (polarity-adjusted) measure, sum, re-rank.
    const pr = cols.map((c) => percentileRanks(c.z));
    // Rounded so that float summation order (i.e. measure order) cannot split ties.
    const sums = rows.map((i) => (pr.every((p) => p[i] != null) ? Math.round(pr.reduce((s, p, k) => s + w[k] * p[i], 0) * 1e10) / 1e10 : null));
    const re = percentileRanks(sums);
    for (const i of rows) {
      if (sums[i] == null) { flags[i] = "missing"; continue; }
      score[i] = re[i];
      cols.forEach((c, k) => { contributions[c.id][i] = w[k] * pr[k][i]; });
    }
  } else {
    // Geometric needs positive inputs: rescale each normalized column to [1, 2].
    const vals = agg === "geometric"
      ? cols.map((c) => { const ok = c.z.filter(finite); const lo = Math.min(...ok), hi = Math.max(...ok), r = hi > lo ? hi - lo : 1;
          return c.z.map((v) => (v == null ? null : 1 + (v - lo) / r)); })
      : cols.map((c) => c.z);
    for (const i of rows) {
      if (vals.some((v) => v[i] == null)) { flags[i] = "missing"; continue; }
      if (agg === "mean") {
        score[i] = vals.reduce((s, v, k) => s + w[k] * v[i], 0);
        cols.forEach((c, k) => { contributions[c.id][i] = w[k] * vals[k][i]; });
        const ses = cols.map((c) => c.se[i]);
        se[i] = ses.every(finite) ? Math.sqrt(ses.reduce((s, x, k) => s + (w[k] * x) ** 2, 0)) : null;
      } else {
        const logsum = vals.reduce((s, v, k) => s + w[k] * Math.log(v[i]), 0);
        score[i] = Math.exp(logsum);
        cols.forEach((c, k) => { contributions[c.id][i] = w[k] * Math.log(vals[k][i]); });
      }
    }
  }
  const pct = percentileRanks(score);
  const order = rows.filter((i) => score[i] != null).sort((a, b) => score[b] - score[a]);
  const rank = new Array(n).fill(null);
  order.forEach((i, r) => { rank[i] = r + 1; });
  return { ids: data.ids, score, rank, percentile: pct, contributions, se, flags, weights: Object.fromEntries(ms.map((m, k) => [m.id, w[k]])) };
}
