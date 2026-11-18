// Index specs in the URL, and the weight-sensitivity readout (spec 04).
// Pure functions: no DOM, no network, so they run in the page and under node --test.
//
// An index is a link: the whole spec rides in ?index=<base64url(JSON)>.
import { index } from "./index.js";

export const SPEC_VERSION = 1;
const KEYS = ["id", "polarity", "weight", "transform", "normalize"];

function b64urlEncode(s) {
  const bytes = new TextEncoder().encode(s);
  let bin = "";
  for (const b of bytes) bin += String.fromCharCode(b);
  return btoa(bin).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}
function b64urlDecode(s) {
  const bin = atob(s.replace(/-/g, "+").replace(/_/g, "/") + "===".slice((s.length + 3) % 4));
  return new TextDecoder().decode(Uint8Array.from(bin, (c) => c.charCodeAt(0)));
}

/** Keep only the fields a spec defines, in a fixed order, so equal specs make equal links. */
export function canonical(spec) {
  return {
    v: SPEC_VERSION,
    name: String(spec.name ?? "").slice(0, 120),
    level: spec.level,
    mode: spec.mode === "change" ? "change" : "level",
    vintages: [...(spec.vintages || [])],
    measures: (spec.measures || []).map((m) => Object.fromEntries(KEYS.map((k) => [k, m[k] ?? (k === "transform" ? "none" : k === "normalize" ? "z" : m[k])]))),
    aggregate: spec.aggregate ?? "mean",
  };
}

export function encodeSpec(spec) {
  return b64urlEncode(JSON.stringify(canonical(spec)));
}

/** Parse a link's spec. Throws on anything that is not a version-1 spec; the
 *  engine's validate() still checks the measures against the data. */
export function decodeSpec(s) {
  let o;
  try { o = JSON.parse(b64urlDecode(s)); } catch { throw new Error("this index link is damaged"); }
  if (!o || o.v !== SPEC_VERSION || !Array.isArray(o.measures) || !Array.isArray(o.vintages))
    throw new Error("this index link is from an unknown version");
  const c = canonical(o);
  if (c.mode === "change" ? c.vintages.length !== 2 : c.vintages.length !== 1)
    throw new Error("this index link names the wrong number of periods");
  for (const m of c.measures) {
    if (typeof m.id !== "string" || typeof m.weight !== "number") throw new Error("this index link has a malformed measure");
  }
  return c;
}

/** Quintile class (0-4) of each score, null where missing: breaks at the
 *  20/40/60/80th percentiles of the scores themselves. */
export function quintiles(score) {
  const s = score.filter((x) => x != null && Number.isFinite(x)).sort((a, b) => a - b);
  if (s.length < 5) return { cls: score.map(() => null), breaks: [] };
  const breaks = [1, 2, 3, 4].map((i) => s[Math.floor((i / 5) * (s.length - 1))]);
  const cls = score.map((x) => {
    if (x == null || !Number.isFinite(x)) return null;
    let c = 0;
    while (c < 4 && x > breaks[c]) c++;
    return c;
  });
  return { cls, breaks };
}

/**
 * Spec 04, "Sensitivity": raise and lower each measure's weight by `delta`
 * (default ±20%) and count the areas whose quintile moves. Returns, per
 * measure, the larger of the two shares, and the worst case overall.
 */
export function sensitivity(spec, data, { delta = 0.2 } = {}) {
  const base = quintiles(index(spec, data).score).cls;
  const n = base.filter((c) => c != null).length;
  const per = {};
  let worst = { id: null, share: 0 };
  for (const m of spec.measures) {
    if (!(m.weight > 0)) continue;
    let share = 0;
    for (const f of [1 + delta, 1 - delta]) {
      const s2 = { ...spec, measures: spec.measures.map((x) => (x.id === m.id ? { ...x, weight: x.weight * f } : x)) };
      const c2 = quintiles(index(s2, data).score).cls;
      let moved = 0;
      for (let i = 0; i < base.length; i++) if (base[i] != null && c2[i] != null && c2[i] !== base[i]) moved++;
      share = Math.max(share, n ? moved / n : 0);
    }
    per[m.id] = share;
    if (share > worst.share) worst = { id: m.id, share };
  }
  return { per, worst, n, delta };
}
