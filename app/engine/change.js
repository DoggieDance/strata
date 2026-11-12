// Change between two non-overlapping ACS vintages (spec 05). Pure functions:
// no DOM, no network, so the same code runs in the page and under `node --test`.
//
//   SE = MOE / 1.645                         (ACS MOEs are 90%)
//   d  = x2 - f·x1                           (f: deflator for dollar measures, else 1)
//   Z  = |d| / sqrt((f·SE1)² + SE2²)
//
// A change whose Z is below the threshold is "no measurable change": a distinct
// state, never drawn as zero and never as a direction.

export const Z90 = 1.645;

export function se(moe) {
  return moe / Z90;
}

/**
 * @param {number|null} x1 earlier estimate, @param {number|null} m1 its 90% MOE
 * @param {number|null} x2 later estimate,   @param {number|null} m2 its 90% MOE
 * @param {{factor?: number, z?: number}} opts factor deflates x1 into x2's dollars
 * @returns {{state: "none"|"nochange"|"up"|"down", d: number|null, moe: number|null, z: number|null}}
 */
export function change(x1, m1, x2, m2, { factor = 1, z = Z90 } = {}) {
  const bad = (v) => v == null || Number.isNaN(v);
  if (bad(x1) || bad(m1) || bad(x2) || bad(m2)) return { state: "none", d: null, moe: null, z: null };
  const d = x2 - factor * x1;
  const s = Math.hypot(factor * se(m1), se(m2));
  const moe = s * Z90;
  if (s === 0) return { state: d === 0 ? "nochange" : d > 0 ? "up" : "down", d, moe, z: d === 0 ? 0 : Infinity };
  const zz = Math.abs(d) / s;
  return { state: zz < z ? "nochange" : d > 0 ? "up" : "down", d, moe, z: zz };
}

/** Diverging class for significant changes: -2..-1 down, 1..2 up, 0 for "no measurable change". */
export function changeClass(c, breakAbs) {
  if (c.state === "none") return null;
  if (c.state === "nochange") return 0;
  const big = Math.abs(c.d) > breakAbs;
  return c.state === "up" ? (big ? 2 : 1) : big ? -2 : -1;
}

/** Median of |d| over significant changes: the split between the two shades. */
export function magnitudeBreak(changes) {
  const v = changes.filter((c) => c.state === "up" || c.state === "down").map((c) => Math.abs(c.d)).sort((a, b) => a - b);
  return v.length ? v[Math.floor((v.length - 1) / 2)] : 0;
}
