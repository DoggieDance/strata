// STRATA local preview. Reads build/manifest.json, then the cubes (Parquet)
// and geometry it lists, and joins them in the browser by GEOID via feature
// state (spec 03). Never calls a Census API.
//
// Opens on the whole country (owner, 2026-11-12). Counties draw nationally
// from one file. Tracts, places and ZIP codes are per state: in the national
// view the states in view load as you zoom in (spec 03's viewport-scoped
// fallback for Phase 07), colored on national breaks so a color means the same
// thing in every state. Picking a state shows just that state on its own breaks.
//
// Accessibility: every value on the map is also in the table view (search,
// sort, "Show on map"), so nothing depends on seeing color or using a mouse.
import { parquetReadObjects } from "https://cdn.jsdelivr.net/npm/hyparquet@1.31.5/+esm";
import { compressors } from "https://cdn.jsdelivr.net/npm/hyparquet-compressors@1.1.2/+esm";
import { change, changeClass, magnitudeBreak, Z90 } from "./engine/change.js";

const DATA = new URL("../build/", import.meta.url);
const US = "us";
const US_BOUNDS = [[-125, 24.3], [-66.9, 49.5]];
const MIN_ZOOM_PER_STATE = 5.5; // national view: per-state levels load from here in
const MAX_STATES_IN_VIEW = 6;

// Warm half of the diverging ramp (spec 07), lowest to highest. One hue family
// stepping in lightness, so it reads under every common color-vision deficiency.
// Paper: dark ink rises out of light ground. Vellum: the same hues run dim to
// bright, so high values never sink into the dark ground.
const RAMPS = {
  light: ["#E2C994", "#CDA460", "#B47B36", "#925722", "#6B3311"],
  dark: ["#6B4423", "#8F5E2C", "#B47B36", "#D4A25E", "#EBCB93"],
};

// Change maps: spec 07's diverging ramp, decline (warm) to rise (cool), with the
// middle step reserved for "no measurable change" (dotted, never a direction).
// Vellum keeps the hues and reverses lightness so the strongest classes are
// the most visible on the dark ground.
const DIVERGING = {
  light: { "-2": "#8C4A16", "-1": "#C08A3E", 0: "#E3D3AE", 1: "#7FA9A4", 2: "#25585F" },
  dark: { "-2": "#E0A866", "-1": "#A06A30", 0: "#3A3128", 1: "#3F716D", 2: "#8CC7BE" },
};
const BASE_VINTAGE = "2006-2010", NEW_VINTAGE = "2016-2020";
const CHANGE_LEVELS = ["tract", "county"];

const reduceMotion = matchMedia("(prefers-reduced-motion: reduce)");

const fmt = {
  usd: (v) => "$" + Math.round(v).toLocaleString("en-US"),
  pct: (v) => v.toFixed(1) + "%",
  count: (v) => Math.round(v).toLocaleString("en-US"),
};

// spec 05: CV = SE / estimate × 100, SE = MOE / 1.645 (90% MOEs).
// etl/write_manifest.py's tier_ok() mirrors this for the national breaks.
function tier(e, m) {
  if (e == null || m == null || Number.isNaN(e)) return null;
  if (e === 0) return m === 0 ? "high" : "low";
  // Tier on the CV as displayed (one decimal), so "12.0%" never reads as High.
  const cv = Math.round((m / 1.645 / Math.abs(e)) * 1000) / 10;
  return cv < 12 ? "high" : cv <= 40 ? "medium" : "low";
}
const cvOf = (e, m) => (e ? (m / 1.645 / Math.abs(e)) * 100 : null);
const TIER_TEXT = { high: "High", medium: "Medium, use with care", low: "Low, not colored" };

let M; // the manifest
let BOXES = {}; // state FIPS -> {name, abbr, bbox}

const state = {
  scope: US,
  vintage: "2016-2020",
  mode: "level", // "level": one vintage; "change": 2006-10 -> 2016-20
  level: "county",
  onNew: false, // 2006-10 tract values on 2020 tract lines (harmonized)
  measure: "mean_household_income",
  view: "map",
  store: {}, // `${ds}|${st}` -> {cube: Map, geo, names}
  active: [], // states (or "us") currently drawn
  cube: new Map(), features: [], names: {},
  breaks: [], breakSource: "",
  selected: null,
  sort: { key: "name", dir: 1 },
  filter: "",
  bbox: {},
};

const $ = (id) => document.getElementById(id);
const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const measureDef = () => M.measures.find((x) => x.id === state.measure);
const levelDef = () => M.levels[state.level];
const national = () => state.scope === US;
const stateName = (st) => M.states[st] || BOXES[st]?.name || st;
const placeName = () => (national() ? "the United States" : stateName(state.scope));

async function getJSON(path) {
  const url = new URL(path, DATA);
  const res = await fetch(url);
  if (!res.ok) throw new Error(`${url.pathname}: ${res.status}`);
  return res.json();
}

// ---------------------------------------------------------------- datasets

// Harmonized view: 2006-10 values apportioned onto 2020 tracts (etl/harmonize.py).
const changing = () => state.mode === "change";
const harmonized = () => !changing() && state.onNew && state.level === "tract" && state.vintage === "2006-2010";
const ds = () => (changing() ? `change/${state.level}` : harmonized() ? "harmonized" : `${state.vintage}/${state.level}`);

/** {st: {cube, geo, names, rows}} available for the current dataset. */
function entries() {
  const lv = levelDef();
  if (changing()) return changeEntries(state.level);
  if (harmonized()) return lv.harmonized?.["2006-2010"]?.states || {};
  return lv.vintages?.[state.vintage] || {};
}
function entriesFor(level, vintage) {
  return M.levels[level]?.vintages?.[vintage] || {};
}
/** Change mode compares like with like: tracts via the harmonized 2006-10 cube
 *  (2010 values on 2020 lines), counties directly (county lines barely moved;
 *  the few that did show as "no estimate"). Places and ZIP codes are not
 *  harmonized, so they get no change map. */
function baseEntries(level) {
  return level === "tract" ? M.levels.tract.harmonized?.[BASE_VINTAGE]?.states || {} : entriesFor(level, BASE_VINTAGE);
}
function changeEntries(level) {
  const a = entriesFor(level, NEW_VINTAGE), b = baseEntries(level);
  return Object.fromEntries(Object.keys(a).filter((k) => k in b).map((k) => [k, a[k]]));
}
/** Whether a (level, vintage) pair can be shown in the current scope. */
function available(level, vintage) {
  if (vintage === "change" && !CHANGE_LEVELS.includes(level)) return false;
  const e = vintage === "change" ? changeEntries(level) : entriesFor(level, vintage);
  if (!national()) return state.scope in e;
  return Object.keys(e).length > 0;
}

function nationalBreaks() {
  const lv = levelDef();
  const nb = harmonized() ? lv.harmonized?.["2006-2010"]?.national_breaks : lv.national_breaks?.[state.vintage];
  return nb?.[state.measure];
}

const overlaps = (a, b) => a[0] < b[2] && a[2] > b[0] && a[1] < b[3] && a[3] > b[1];

/** Which files to draw: one state, the national county file, or the states in view. */
function wantedStates() {
  const e = entries();
  if (!national()) return state.scope in e ? [state.scope] : [];
  // Until every state is built there is no national county file; draw the
  // states that exist (labelled as partial) rather than nothing.
  if (state.level === "county") return US in e ? [US] : Object.keys(e).sort();
  if (map.getZoom() < MIN_ZOOM_PER_STATE) return [];
  const b = map.getBounds();
  const view = [b.getWest(), b.getSouth(), b.getEast(), b.getNorth()];
  const area = (x) => Math.max(0, Math.min(x[2], view[2]) - Math.max(x[0], view[0])) *
                      Math.max(0, Math.min(x[3], view[3]) - Math.max(x[1], view[1]));
  return Object.keys(e).filter((st) => st !== US && BOXES[st] && overlaps(BOXES[st].bbox, view))
    .sort((a, b2) => area(BOXES[b2].bbox) - area(BOXES[a].bbox))
    .slice(0, MAX_STATES_IN_VIEW).sort();
}

const inflight = {};
const STORE_LIMIT = 16; // loaded (dataset, state) files kept; the oldest unused go first
async function loadOne(d, st, ent, { cubeOnly = false } = {}) {
  const k = `${d}|${st}`;
  if (state.store[k]) { state.store[k].used = performance.now(); return state.store[k]; }
  inflight[k] ??= (async () => {
    const res = await fetch(new URL(ent.cube, DATA));
    if (!res.ok) throw new Error(`${ent.cube}: ${res.status}`);
    const rows = await parquetReadObjects({ file: await res.arrayBuffer(), compressors });
    const [geo, names] = cubeOnly ? [null, {}]
      : await Promise.all([getJSON(ent.geo), getJSON(ent.names).catch(() => ({}))]);
    state.store[k] = { cube: new Map(rows.map((r) => [r.GEOID, r])), geo, names, used: performance.now() };
    evict();
    return state.store[k];
  })().finally(() => delete inflight[k]);
  return inflight[k];
}
function evict() {
  const keep = new Set(state.active.flatMap((st) => [`${ds()}|${st}`, `base/${state.level}|${st}`]));
  const old = Object.entries(state.store).filter(([k]) => !keep.has(k)).sort((a, b) => a[1].used - b[1].used);
  for (const [k] of old.slice(0, Math.max(0, Object.keys(state.store).length - STORE_LIMIT))) delete state.store[k];
}

function quantileBreaks(values, k) {
  const s = values.slice().sort((a, b) => a - b);
  const out = [];
  for (let i = 1; i < k; i++) out.push(s[Math.floor((i / k) * (s.length - 1))]);
  return out;
}

// ---------------------------------------------------------------- theme

function currentTheme() {
  const set = document.documentElement.dataset.theme;
  return set || (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
}
const ramp = () => RAMPS[currentTheme()];

function syncThemeButton() {
  $("theme").setAttribute("aria-pressed", String(currentTheme() === "dark"));
  $("theme").textContent = "Dark theme";
}

// ---------------------------------------------------------------- map

const map = new maplibregl.Map({
  container: "map",
  style: { version: 8, sources: {}, layers: [
    { id: "bg", type: "background", paint: { "background-color": css("--paper") } },
  ] },
  bounds: US_BOUNDS,
  fitBoundsOptions: { padding: 20 },
  attributionControl: { compact: true, customAttribution: "U.S. Census Bureau, ACS 5-year &amp; Cartographic Boundary files" },
  dragRotate: false,
  pitchWithRotate: false,
  renderWorldCopies: false,
});
map.touchZoomRotate.disableRotation();
map.keyboard.disableRotation();
map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");

function hatchImage(color) {
  const n = 8, c = document.createElement("canvas");
  c.width = c.height = n;
  const g = c.getContext("2d");
  g.strokeStyle = color; g.lineWidth = 1.25;
  g.beginPath();
  for (let o = -n; o <= n; o += n) { g.moveTo(o, n); g.lineTo(o + n, 0); }
  g.stroke();
  return g.getImageData(0, 0, n, n);
}

// "No measurable change": sparse dots, so it never reads as a pale direction.
function dotsImage(color) {
  const n = 8, c = document.createElement("canvas");
  c.width = c.height = n;
  const g = c.getContext("2d");
  g.fillStyle = color;
  g.beginPath(); g.arc(2, 2, 1.1, 0, 2 * Math.PI); g.arc(6, 6, 1.1, 0, 2 * Math.PI); g.fill();
  return g.getImageData(0, 0, n, n);
}

function fillColor() {
  if (changing()) {
    const d = DIVERGING[currentTheme()];
    return ["match", ["feature-state", "chg"], -2, d["-2"], -1, d["-1"], 0, d[0], 1, d[1], 2, d[2], css("--nodata")];
  }
  const r = ramp();
  return ["match", ["feature-state", "cls"],
    0, r[0], 1, r[1], 2, r[2], 3, r[3], 4, r[4],
    -2, css("--paper"),   // low reliability: uncolored ground under the hatch
    css("--nodata")];     // no estimate
}

function applyTheme() {
  syncThemeButton();
  if (!map.getLayer("tract-fill")) return;
  map.setPaintProperty("bg", "background-color", css("--paper"));
  map.setPaintProperty("tract-line", "line-color", css("--rule"));
  map.setPaintProperty("state-line", "line-color", css("--ink-2"));
  map.setPaintProperty("state-ground", "fill-color", css("--surface-2"));
  map.setPaintProperty("tract-sel-casing", "line-color", css("--paper"));
  map.setPaintProperty("tract-sel", "line-color", css("--accent"));
  map.setPaintProperty("tract-fill", "fill-color", fillColor());
  if (map.hasImage("hatch")) map.removeImage("hatch");
  map.addImage("hatch", hatchImage(css("--ink-2")));
  if (map.hasImage("dots")) map.removeImage("dots");
  map.addImage("dots", dotsImage(css("--ink-2")));
  if (state.breaks.length || changing()) renderLegend();
}

function addLayers() {
  const empty = { type: "FeatureCollection", features: [] };
  map.addSource("states", { type: "geojson", data: new URL(M.outlines.geo, DATA).href, promoteId: "GEOID" });
  map.addSource("tracts", { type: "geojson", data: empty, promoteId: "GEOID" });
  map.addImage("hatch", hatchImage(css("--ink-2")));
  // Land under the data, so "not loaded yet" reads as ground, not as no data.
  map.addLayer({ id: "state-ground", type: "fill", source: "states", paint: { "fill-color": css("--surface-2") } });
  map.addLayer({ id: "tract-fill", type: "fill", source: "tracts",
    paint: { "fill-color": fillColor(), "fill-color-transition": { duration: reduceMotion.matches ? 0 : 180 } } });
  map.addLayer({ id: "tract-hatch", type: "fill", source: "tracts",
    paint: { "fill-pattern": "hatch",
             "fill-opacity": ["case", ["boolean", ["feature-state", "low"], false], 1, 0] } });
  map.addImage("dots", dotsImage(css("--ink-2")));
  map.addLayer({ id: "tract-dots", type: "fill", source: "tracts",
    paint: { "fill-pattern": "dots",
             "fill-opacity": ["case", ["boolean", ["feature-state", "nc"], false], 1, 0] } });
  map.addLayer({ id: "tract-line", type: "line", source: "tracts",
    paint: { "line-color": css("--rule"), "line-width": lineWidth() } });
  map.addLayer({ id: "state-line", type: "line", source: "states",
    paint: { "line-color": css("--ink-2"), "line-width": ["interpolate", ["linear"], ["zoom"], 3, 0.6, 8, 1.6] } });
  // Selection: accent line on a paper casing, visible on every ramp step in both themes.
  map.addLayer({ id: "tract-sel-casing", type: "line", source: "tracts",
    paint: { "line-color": css("--paper"),
             "line-width": ["case", ["boolean", ["feature-state", "sel"], false], 6, 0] } });
  map.addLayer({ id: "tract-sel", type: "line", source: "tracts",
    paint: { "line-color": css("--accent"),
             "line-width": ["case", ["boolean", ["feature-state", "sel"], false], 3, 0] } });
}

function lineWidth() {
  const big = state.level === "county" ? (national() ? 0.2 : 1.4) : state.level === "tract" ? 0 : 0.5;
  return ["interpolate", ["linear"], ["zoom"], 4, 0.1, 6, 0.2 + big * 0.5, 11, 1 + big];
}

// ---------------------------------------------------------------- render

let generation = 0;
async function reload({ keepSelection = false } = {}) {
  const gen = ++generation;
  syncAvailability();
  const d = ds(), e = entries();
  const want = wantedStates();
  const missing = want.filter((st) => !state.store[`${d}|${st}`]);
  if (missing.length) $("status").textContent = `Loading ${missing.map((s) => (s === US ? "U.S." : BOXES[s]?.abbr || s)).join(", ")}…`;
  const loaded = await Promise.all(want.map((st) => loadOne(d, st, e[st])));
  const base = changing()
    ? await Promise.all(want.map((st) => loadOne(`base/${state.level}`, st, baseEntries(state.level)[st], { cubeOnly: true })))
    : [];
  if (gen !== generation) return; // a newer switch happened while loading; it renders
  const sameSet = want.join() === state.active.join() && state.activeDs === d;
  state.active = want; state.activeDs = d;
  if (!sameSet) {
    if (state.selected && !keepSelection) {
      map.setFeatureState({ source: "tracts", id: state.selected }, { sel: false });
      state.selected = null;
    }
    state.cube = new Map(loaded.flatMap((x) => [...x.cube]));
    const renamed = Object.fromEntries(Object.entries(M.county_changes?.renamed || {}).map(([now, was]) => [was, now]));
    state.base = new Map(base.flatMap((x) => [...x.cube]).map(([g, r]) => [state.level === "county" ? renamed[g] || g : g, r]));
    state.features = loaded.flatMap((x) => x.geo.features);
    state.names = Object.assign({}, ...loaded.map((x) => x.names));
    state.bbox = {};
    map.getSource("tracts").setData({ type: "FeatureCollection", features: state.features });
    if (state.selected && !state.cube.has(state.selected)) {
      map.setFeatureState({ source: "tracts", id: state.selected }, { sel: false });
      state.selected = null;
    }
  }
  map.setPaintProperty("tract-line", "line-width", lineWidth());
  recolor();
  renderInspector();
  renderLabels();
  syncAvailability(); // again, now that the loaded set is known
}

// A level Census did not publish for a vintage, or not built for this scope,
// cannot be picked with it.
function syncAvailability() {
  const lv = levelDef();
  const v = changing() ? "change" : state.vintage;
  for (const o of $("level").options) {
    o.disabled = !available(o.value, v);
    const why = changing() && !CHANGE_LEVELS.includes(o.value) ? " (no change map)"
      : M.levels[o.value].unavailable?.[v] ? " (2016–20 only)" : o.disabled ? " (not built)" : "";
    o.textContent = M.levels[o.value].label + why;
  }
  for (const r of document.querySelectorAll('input[name="vintage"]')) {
    r.disabled = !available(state.level, r.value);
    r.checked = r.value === (changing() ? "change" : state.vintage);
    r.closest("label").title = r.disabled ? `No ${lv.plural} for this period here` : "";
  }
  $("level-note").textContent = lv.note || "";
  $("level-note").hidden = !lv.note;
  const harm = M.levels.tract.harmonized?.["2006-2010"]?.states || {};
  const can = !changing() && state.level === "tract" && state.vintage === "2006-2010" &&
    (national() ? Object.keys(harm).length > 0 : state.scope in harm);
  $("on-new").disabled = !can;
  $("on-new-row").hidden = !can;
  if (!can && state.onNew) { state.onNew = false; $("on-new").checked = false; }
  const zoomIn = national() && state.level !== "county" && map.getZoom() < MIN_ZOOM_PER_STATE;
  const nothingHere = national() && !zoomIn && state.activeDs === ds() && state.active.length === 0;
  $("zoom-hint").hidden = !(zoomIn || nothingHere) || state.view !== "map";
  $("zoom-hint").textContent = zoomIn
    ? `Zoom in, or pick a state, to load ${lv.plural}. They load for the states in view.`
    : `No ${changing() ? "2006–10 to 2016–20 comparison" : lv.plural} built for the states in view yet.`;
}

function renderLabels() {
  const lv = levelDef();
  const cap = (s) => s[0].toUpperCase() + s.slice(1);
  $("inspector-title").textContent = `Selected ${lv.noun}`;
  $("filter-label").textContent = `Find a ${lv.noun}`;
  $("name-col").textContent = cap(lv.noun);
  $("place-title").textContent = national() ? "The United States, place by place" : `${stateName(state.scope)}, place by place`;
  document.title = `STRATA — ${national() ? "United States" : stateName(state.scope)}`;
  $("map").setAttribute("aria-label", `Map of ${placeName()}, ${lv.plural}. Arrow keys pan, plus and minus zoom. Every value is also in the table view.`);
}

const notComparable = (id) => state.level === "county" && (M.county_changes?.not_comparable || []).includes(id);

function changeOf(id) {
  const m = state.measure, def = measureDef();
  if (notComparable(id)) return { state: "none", d: null, moe: null, z: null, x1: null, x2: null, factor: 1, boundary: true };
  const r1 = state.base.get(id), r2 = state.cube.get(id);
  const factor = def.dollars ? M.deflators.annual[String(M.vintages[NEW_VINTAGE].dollars_year)] /
    M.deflators.annual[String(M.vintages[BASE_VINTAGE].dollars_year)] : 1;
  return { ...change(r1?.[`${m}_e`] ?? null, r1?.[`${m}_m`] ?? null, r2?.[`${m}_e`] ?? null, r2?.[`${m}_m`] ?? null, { factor }),
           x1: r1?.[`${m}_e`] == null ? null : r1[`${m}_e`] * factor, x2: r2?.[`${m}_e`] ?? null, factor };
}

function recolorChange(t0) {
  const changes = new Map(state.features.map((f) => [f.properties.GEOID, changeOf(f.properties.GEOID)]));
  // National view: the national split, so a shade means the same in every state
  // (review: a per-viewport median moved as you panned).
  const nat = national() ? levelDef().national_change?.[state.measure] : null;
  state.magnitude = nat ? nat.break : magnitudeBreak([...changes.values()]);
  state.magnitudeSource = nat ? "national" : national() ? "loaded" : "state";
  const counts = { "-2": 0, "-1": 0, 0: 0, 1: 0, 2: 0, none: 0 };
  for (const [id, c] of changes) {
    const k = changeClass(c, state.magnitude);
    counts[k ?? "none"]++;
    map.setFeatureState({ source: "tracts", id }, { chg: k ?? -9, nc: k === 0, low: false, cls: -1 });
  }
  state.changeCounts = counts;
  state.changes = changes;
  state.breaks = [];
  renderLegend();
  const lv = levelDef();
  $("status").textContent = `${state.features.length.toLocaleString()} ${lv.plural} · ${(performance.now() - t0).toFixed(0)} ms`;
  renderTable();
  if (state.selected) renderInspector();
}

function recolor() {
  if (state.activeDs !== ds()) return; // the new dataset is still loading; reload() recolors
  const t0 = performance.now();
  map.setPaintProperty("tract-fill", "fill-color", fillColor());
  if (changing()) return recolorChange(t0);
  const m = state.measure;
  const local = [];
  for (const r of state.cube.values()) {
    const e = r[`${m}_e`];
    if (e != null && !Number.isNaN(e) && tier(e, r[`${m}_m`]) !== "low") local.push(e);
  }
  const nb = national() && state.level !== "county" ? nationalBreaks() : null;
  const lv = levelDef();
  if (nb) {
    state.breaks = nb.breaks;
    state.breakSource = `Fifths (quintiles) of all ${nb.n.toLocaleString()} reliable U.S. ${lv.plural}, so a color means the same in every state.`;
  } else {
    state.breaks = local.length >= 5 ? quantileBreaks(local, 5) : [];
    const n = local.length.toLocaleString();
    const partialUS = national() && state.active[0] !== US;
    state.breakSource = !national()
      ? `Fifths (quintiles) of ${n} reliable ${stateName(state.scope)} ${lv.plural}.`
      : !partialUS
        ? `Fifths (quintiles) of ${n} reliable U.S. ${lv.plural}.`
        : `Fifths (quintiles) of the ${n} reliable ${lv.plural} in the states loaded. National breaks arrive when every state is built.`;
  }
  let low = 0, none = 0;
  for (const f of state.features) {
    const id = f.properties.GEOID;
    const r = state.cube.get(id);
    const e = r?.[`${m}_e`];
    const t = tier(e, r?.[`${m}_m`]);
    let cls = -1;
    if (t === null) none++;
    else if (t === "low") { low++; cls = -2; }
    else if (state.breaks.length) cls = classOf(e);
    map.setFeatureState({ source: "tracts", id }, { cls, low: t === "low", nc: false });
  }
  state.counts = { low, none };
  renderLegend();
  const ms = performance.now() - t0;
  const n = state.features.length;
  const where = national() && state.level !== "county"
    ? (state.active.length ? ` in ${state.active.map((s) => BOXES[s]?.abbr || s).join(", ")}` : "")
    : "";
  $("status").textContent = `${n.toLocaleString()} ${lv.plural}${where} · ${ms.toFixed(0)} ms`;
  renderTable();
  if (state.selected) renderInspector();
}

function classOf(e) {
  let c = 0;
  while (c < state.breaks.length && e > state.breaks[c]) c++;
  return c;
}

function rangeLabel(i) {
  const f = fmt[measureDef().fmt], b = state.breaks;
  if (i === 0) return `${f(b[0])} or less`;
  if (i === 4) return `more than ${f(b[3])}`;
  return `${f(b[i - 1])} to ${f(b[i])}`;
}

const fmtDelta = (v) => {
  const def = measureDef();
  const sign = v > 0 ? "+" : v < 0 ? "−" : "±";
  const a = Math.abs(v);
  return sign + (def.fmt === "pct" ? a.toFixed(1) + " pts" : fmt[def.fmt](a));
};

function renderChangeLegend() {
  if (!state.changeCounts || state.activeDs !== ds()) return;
  const d = DIVERGING[currentTheme()], c = state.changeCounts, mag = state.magnitude;
  const f = (v) => fmtDelta(v).slice(1);
  const row = (k, text) => `<li><span class="swatch${k === 0 ? " dots" : ""}" style="background-color:${d[k]}" aria-hidden="true"></span>${text} <span class="count">(${c[k].toLocaleString()})</span></li>`;
  const items = [row(2, `Rose by more than ${f(mag)}`), row(1, `Rose by up to ${f(mag)}`),
    row(0, "No measurable change"), row(-1, `Fell by up to ${f(mag)}`), row(-2, `Fell by more than ${f(mag)}`)];
  if (c.none) items.push(`<li><span class="swatch" style="background:var(--nodata)" aria-hidden="true"></span>No comparable estimate <span class="count">(${c.none.toLocaleString()})</span></li>`);
  $("legend").innerHTML = items.join("");
  const def = measureDef();
  const dollars = def.dollars ? `2006–10 dollars raised to 2020 dollars (×${(changeOf(state.features[0]?.properties.GEOID ?? "").factor || 1).toFixed(4)}, R-CPI-U-RS). ` : "";
  const lines = state.level === "tract" ? "2006–10 values moved onto 2020 tract lines. " : "";
  $("dollar-note").textContent = `2006–10 to 2016–20. ${lines}${dollars}A change counts only if it clears the 90% significance test (Z ≥ ${Z90}); the rest is "no measurable change". The split between shades is the median significant change${
    { national: " across the U.S", loaded: " in the states loaded (national split arrives when every state is built)", state: ` in ${stateName(state.scope)}` }[state.magnitudeSource]}.${
    state.level === "county" ? " Counties whose boundaries changed (e.g. Bedford, VA) are not compared." : ""}`;
}

function renderLegend() {
  if (changing()) return renderChangeLegend();
  const r = ramp();
  const { low, none } = state.counts;
  const items = state.breaks.length ? r.map((c, i) =>
    `<li><span class="swatch" style="background:${c}" aria-hidden="true"></span>${["Lowest", "Low", "Middle", "High", "Highest"][i]} fifth: ${rangeLabel(i)}</li>`) : [];
  items.push(`<li><span class="swatch hatch" aria-hidden="true"></span>${low.toLocaleString()} low reliability</li>`);
  if (none) items.push(`<li><span class="swatch" style="background:var(--nodata)" aria-hidden="true"></span>${none.toLocaleString()} no estimate</li>`);
  $("legend").innerHTML = items.join("");
  const yr = M.vintages[state.vintage].dollars_year;
  const dollars = measureDef().fmt === "usd" ? `In ${yr} dollars, as published, not inflation-adjusted. ` : "";
  const moved = harmonized() ? "Moved onto 2020 tract lines in proportion to where people live (2020 block counts). " : "";
  $("dollar-note").textContent = `${moved}${dollars}${state.breakSource}`;
}

function displayName(id) {
  const n = state.names[id] || id;
  // National per-state levels: name the state, since "Tract 101" repeats.
  const perState = state.level !== "zcta" && (state.level !== "county" || state.active[0] !== US);
  if (national() && perState) return `${n}, ${BOXES[id.slice(0, 2)]?.abbr || ""}`;
  return n;
}

function tractRow(id) {
  if (changing()) {
    const c = state.changes?.get(id) ?? changeOf(id);
    const t = c.state === "none" ? null : c.state;
    return { id, name: displayName(id), r: state.cube.get(id), e: t ? c.d : null, m: t ? c.moe : null,
             cv: t && Number.isFinite(c.z) ? c.z : null, t, c };
  }
  const r = state.cube.get(id);
  const m = state.measure;
  const e = r?.[`${m}_e`], mo = r?.[`${m}_m`];
  const t = tier(e, mo);
  return { id, name: displayName(id), r, e: t ? e : null, m: t ? mo : null, cv: t ? cvOf(e, mo) : null, t };
}

const VERDICT = { up: "Rose", down: "Fell", nochange: "No measurable change" };

function renderChangeInspector() {
  const def = measureDef(), f = fmt[def.fmt];
  const x = tractRow(state.selected), c = x.c;
  $("inspector").innerHTML = `
    <p class="name">${esc(x.name)}</p>
    <dl>
      <dt>GEOID</dt><dd>${x.id}</dd>
      <dt>2006–10${def.dollars ? " (2020 $)" : ""}</dt><dd>${c.x1 == null ? "No estimate" : f(c.x1)}</dd>
      <dt>2016–20</dt><dd>${c.x2 == null ? "No estimate" : f(c.x2)}</dd>
      ${x.t ? `<dt>Change</dt><dd>${fmtDelta(c.d)}</dd>
      <dt>Margin (90%)</dt><dd>± ${fmtDelta(c.moe).slice(1)}</dd>
      <dt>Z</dt><dd>${Number.isFinite(c.z) ? c.z.toFixed(2) : "exact"}</dd>
      <dt>Verdict</dt><dd>${VERDICT[c.state]}</dd>` : `<dt>Verdict</dt><dd>${c.boundary ? "Boundary changed; not comparable" : "No comparable estimate"}</dd>`}
    </dl>`;
}

function renderInspector() {
  if (!state.selected) {
    $("inspector").innerHTML = `<p class="note">Hover or tap the map, or pick from the table.</p>`;
    return;
  }
  if (changing()) return renderChangeInspector();
  const def = measureDef(), f = fmt[def.fmt];
  const x = tractRow(state.selected);
  const fifth = x.t && x.t !== "low" && state.breaks.length ? ["lowest", "low", "middle", "high", "highest"][classOf(x.e)] + " fifth" : null;
  $("inspector").innerHTML = `
    <p class="name">${esc(x.name)}</p>
    <dl>
      <dt>GEOID</dt><dd>${x.id}</dd>
      <dt>${esc(def.label)}</dt><dd>${x.t ? f(x.e) : "No estimate"}</dd>
      ${x.t ? `<dt>Margin (90%)</dt><dd>± ${f(x.m)}</dd>
      <dt>CV</dt><dd>${x.cv == null ? "n/a" : x.cv.toFixed(1) + "%"}</dd>
      <dt>Reliability</dt><dd class="tier-${x.t}">${TIER_TEXT[x.t]}</dd>` : ""}
      ${fifth ? `<dt>Class</dt><dd>${fifth}</dd>` : ""}
      <dt>Population</dt><dd>${x.r ? fmt.count(x.r.total_population_e) : "n/a"}</dd>
    </dl>`;
}

function select(id) {
  if (state.selected === id) return;
  if (state.selected) map.setFeatureState({ source: "tracts", id: state.selected }, { sel: false });
  state.selected = id;
  if (id) map.setFeatureState({ source: "tracts", id }, { sel: true });
  renderInspector();
}

// ---------------------------------------------------------------- table

const TABLE_LIMIT = 2000;

function renderTable() {
  if (state.view !== "table") { state.tableStale = true; return; }
  state.tableStale = false;
  const def = measureDef(), f = fmt[def.fmt];
  const q = state.filter.trim().toLowerCase();
  let rows = [...state.cube.keys()].map(tractRow);
  if (q) rows = rows.filter((x) => x.name.toLowerCase().includes(q) || x.id.includes(q));
  const { key: sortKey, dir } = state.sort;
  rows.sort((a, b) => {
    const av = a[sortKey], bv = b[sortKey];
    if (av == null && bv == null) return a.id.localeCompare(b.id);
    if (av == null) return 1;               // no estimate always sorts last
    if (bv == null) return -1;
    return (typeof av === "string" ? av.localeCompare(bv) : av - bv) * dir || a.id.localeCompare(b.id);
  });
  const total = rows.length;
  const shown = rows.slice(0, TABLE_LIMIT);
  const hasGeo = new Set(state.features.map((x) => x.properties.GEOID));
  const ch = changing();
  const heads = ch ? ["Change", "Margin (90%)", "Z", "Verdict"] : ["Estimate", "Margin (90%)", "CV", "Reliability"];
  $("tracts").querySelectorAll("thead th").forEach((th, i) => {
    if (i >= 1 && i <= 4) (th.querySelector("button") || th).textContent = heads[i - 1];
  });
  $("tracts").querySelector("tbody").innerHTML = shown.map((x) => `
    <tr>
      <th scope="row"><span class="tract-name">${esc(x.name)}</span><span class="geoid">${x.id}</span></th>
      <td class="num">${x.t ? (ch ? fmtDelta(x.e) : f(x.e)) : ch ? "Not comparable" : "No estimate"}</td>
      <td class="num">${x.t ? "± " + (ch ? fmtDelta(x.m).slice(1) : f(x.m)) : ""}</td>
      <td class="num">${x.cv == null ? "" : ch ? x.cv.toFixed(2) : x.cv.toFixed(1) + "%"}</td>
      <td class="${x.t && !ch ? "tier-" + x.t : ""}">${x.t ? (ch ? VERDICT[x.t] : TIER_TEXT[x.t]) : ""}</td>
      <td>${hasGeo.has(x.id)
        ? `<button type="button" class="show" data-id="${x.id}" aria-label="Show ${esc(x.name)} on the map">Show on map</button>`
        : `<span class="note">No boundary</span>`}</td>
    </tr>`).join("");
  const lv = levelDef();
  const scopeText = national() && state.level !== "county"
    ? (state.active.length ? `${lv.plural} in ${state.active.map(stateName).join(", ")}` : `no ${lv.plural} loaded: zoom in on the map or pick a state`)
    : `${placeName()} ${lv.plural}`;
  const period = ch ? "change 2006–10 to 2016–20" : M.vintages[state.vintage].label;
  $("table-caption").textContent = `${def.label}, ${period}, ${scopeText}. ${total} rows.`;
  const capped = total > TABLE_LIMIT ? ` Showing the first ${TABLE_LIMIT.toLocaleString()}; search to narrow.` : "";
  $("table-count").textContent = (q ? `${total.toLocaleString()} of ${state.cube.size.toLocaleString()} match.` : `${total.toLocaleString()} ${scopeText}.`) + capped;
  for (const th of $("tracts").querySelectorAll("th[aria-sort]")) {
    const k = th.querySelector("button").dataset.sort;
    th.setAttribute("aria-sort", k === sortKey ? (dir > 0 ? "ascending" : "descending") : "none");
  }
}

function featureBBox(id) {
  if (!state.bbox[id]) {
    const f = state.features.find((x) => x.properties.GEOID === id);
    let w = 180, s = 90, e = -180, n = -90;
    const walk = (c) => typeof c[0] === "number"
      ? (w = Math.min(w, c[0]), e = Math.max(e, c[0]), s = Math.min(s, c[1]), n = Math.max(n, c[1]))
      : c.forEach(walk);
    walk(f.geometry.coordinates);
    state.bbox[id] = [[w, s], [e, n]];
  }
  return state.bbox[id];
}

function setView(v) {
  state.view = v;
  document.querySelector(".map-wrap").hidden = v !== "map";
  $("table-view").hidden = v !== "table";
  for (const r of document.querySelectorAll('input[name="view"]')) r.checked = r.value === v;
  if (v === "map") map.resize();
  if (v === "table" && state.tableStale) renderTable();
  syncAvailability();
}

function showOnMap(id) {
  setView("map");
  select(id);
  map.fitBounds(featureBBox(id), { padding: 60, maxZoom: 12, duration: reduceMotion.matches ? 0 : 600 });
  map.getCanvas().focus();
}

function flyToScope() {
  const b = national() ? US_BOUNDS : (([w, s, e, n]) => [[w, s], [e, n]])(BOXES[state.scope].bbox);
  map.fitBounds(b, { padding: 20, duration: reduceMotion.matches ? 0 : 500 });
}

// Deep links: #PA, #US (default).
function readHash() {
  const h = location.hash.slice(1).toUpperCase();
  const st = Object.keys(BOXES).find((k) => BOXES[k].abbr === h);
  return st && st in M.states ? st : US;
}
function writeHash() {
  const h = national() ? "" : `#${BOXES[state.scope].abbr}`;
  if (location.hash !== h) history.replaceState(null, "", h || location.pathname + location.search);
}

function setScope(st, { move = true } = {}) {
  state.scope = st;
  $("scope").value = st;
  // Keep the level (and change mode) if they exist here; otherwise fall back
  // to counties, then to a single period (review: a state with no 2010 data
  // used to leave Change checked and disabled over an empty map).
  if (changing() && !available(state.level, "change")) {
    if (available("county", "change")) state.level = "county";
    else { state.mode = "level"; $("period-note").textContent = `No 2006–10 comparison is built for ${placeName()} yet; showing ${M.vintages[state.vintage].label}.`; }
  }
  const v = changing() ? "change" : state.vintage;
  if (!available(state.level, v)) state.level = available("county", v) ? "county" : "tract";
  $("level").value = state.level;
  writeHash();
  if (move) flyToScope();
  // Viewport loading needs the camera to land first in the national view.
  if (move && national() && !reduceMotion.matches) map.once("moveend", () => reload().catch(fail));
  else reload().catch(fail);
}

// ---------------------------------------------------------------- wiring

function wire() {
  $("measure").innerHTML = M.measures.map((m) => `<option value="${m.id}">${esc(m.label)}</option>`).join("");
  $("measure").value = state.measure;
  $("measure").addEventListener("change", (ev) => { state.measure = ev.target.value; recolor(); });

  $("vintage-options").innerHTML = Object.entries(M.vintages).map(([id, v]) =>
    `<label><input type="radio" name="vintage" value="${id}" ${id === state.vintage ? "checked" : ""}><span>${esc(v.label)}</span></label>`).join("") +
    `<label><input type="radio" name="vintage" value="change"><span>Change</span></label>`;
  $("vintage").addEventListener("change", (ev) => {
    $("period-note").textContent = "";
    if (ev.target.value === "change") state.mode = "change";
    else { state.mode = "level"; state.vintage = ev.target.value; }
    reload().catch(fail);
  });

  $("on-new").addEventListener("change", (ev) => { state.onNew = ev.target.checked; reload().catch(fail); });

  $("level").innerHTML = Object.entries(M.levels).map(([id, l]) => `<option value="${id}">${esc(l.label)}</option>`).join("");
  $("level").value = state.level;
  $("level").addEventListener("change", (ev) => { state.level = ev.target.value; reload().catch(fail); });

  const built = Object.keys(M.states).sort((a, b) => stateName(a).localeCompare(stateName(b)));
  $("scope").innerHTML = `<option value="${US}">United States (all states)</option>` +
    built.map((st) => `<option value="${st}">${esc(stateName(st))}</option>`).join("");
  $("scope").addEventListener("change", (ev) => setScope(ev.target.value));
  $("scope-note").textContent = built.length < Object.keys(BOXES).length
    ? `${built.length} of ${Object.keys(BOXES).length} states built so far; the rest are in progress.` : "";
  $("scope-note").hidden = !$("scope-note").textContent;

  for (const r of document.querySelectorAll('input[name="view"]')) r.addEventListener("change", () => setView(r.value));
  $("filter").addEventListener("input", (ev) => { state.filter = ev.target.value; renderTable(); });
  $("tracts").querySelector("thead").addEventListener("click", (ev) => {
    const k = ev.target.closest("button")?.dataset.sort;
    if (!k) return;
    state.sort = { key: k, dir: state.sort.key === k ? -state.sort.dir : (k === "name" ? 1 : -1) };
    renderTable();
  });
  $("tracts").querySelector("tbody").addEventListener("click", (ev) => {
    const id = ev.target.closest("button.show")?.dataset.id;
    if (id) showOnMap(id);
  });
  document.querySelector(".skip").addEventListener("click", (ev) => {
    ev.preventDefault(); // the default jump would move focus off the search box
    setView("table");
    $("filter").focus();
  });

  // Ignore features from a previous dataset while new data is still swapping in.
  const pick = (e) => { const id = e.features[0]?.id; if (id && state.cube.has(id)) select(id); };
  map.on("mousemove", "tract-fill", pick);
  map.on("click", "tract-fill", pick);
  map.on("mouseenter", "tract-fill", () => (map.getCanvas().style.cursor = "crosshair"));
  map.on("mouseleave", "tract-fill", () => (map.getCanvas().style.cursor = ""));

  // National view: load the states that come into view, once the camera rests.
  let t;
  map.on("moveend", () => {
    if (!national() || state.level === "county") return syncAvailability();
    clearTimeout(t);
    t = setTimeout(() => reload({ keepSelection: true }).catch(fail), 150);
  });
  addEventListener("hashchange", () => { const st = readHash(); if (st !== state.scope) setScope(st); });
}

$("theme").addEventListener("click", () => {
  const next = currentTheme() === "dark" ? "light" : "dark";
  document.documentElement.dataset.theme = next;
  try { localStorage.setItem("strata-theme", next); } catch {}
  applyTheme();
});
try { const t = localStorage.getItem("strata-theme"); if (t) document.documentElement.dataset.theme = t; } catch {}
matchMedia("(prefers-color-scheme: dark)").addEventListener("change", applyTheme);
reduceMotion.addEventListener("change", () => {
  if (map.getLayer("tract-fill"))
    map.setPaintProperty("tract-fill", "fill-color-transition", { duration: reduceMotion.matches ? 0 : 180 });
});
syncThemeButton();

function fail(err) {
  console.error(err);
  $("status").textContent = "Error";
  $("inspector").innerHTML = `<p class="note">${esc(err.message)}. Build the data first: see app/README.md.</p>`;
}

const ready = Promise.all([getJSON("manifest.json"), new Promise((r) => map.on("load", r))]);
ready.then(async ([manifest]) => {
  M = manifest;
  BOXES = await getJSON(M.outlines.boxes);
  state.scope = readHash();
  if (!available(state.level, state.vintage)) state.level = available("county", state.vintage) ? "county" : "tract";
  wire();
  $("scope").value = state.scope;
  addLayers();
  applyTheme();
  if (!national()) map.jumpTo(map.cameraForBounds((([w, s, e, n]) => [[w, s], [e, n]])(BOXES[state.scope].bbox), { padding: 20 }));
  await reload();
  window.__strataReady = true;
}).catch(fail);
