// STRATA local preview. Reads the built cube (Parquet) and tract geometry from
// ../build/, joins them in the browser by GEOID via feature state (spec 03).
// Never calls a Census API.
import { parquetReadObjects } from "https://cdn.jsdelivr.net/npm/hyparquet@1.31.5/+esm";
import { compressors } from "https://cdn.jsdelivr.net/npm/hyparquet-compressors@1.1.2/+esm";

const DATA = new URL("../build/", import.meta.url);
const STATE = "51";

const VINTAGES = [
  { id: "2006-2010", label: "2006–10", dollars: "2010 dollars" },
  { id: "2016-2020", label: "2016–20", dollars: "2020 dollars" },
];

const MEASURES = [
  { id: "mean_household_income", label: "Mean household income", fmt: "usd" },
  { id: "mean_gross_rent", label: "Mean gross rent (cash renters)", fmt: "usd" },
  { id: "mean_home_value", label: "Mean home value", fmt: "usd" },
  { id: "pct_bachelors_plus", label: "Bachelor’s degree or higher, 25+", fmt: "pct" },
  { id: "pct_nh_white", label: "Non-Hispanic white", fmt: "pct" },
  { id: "total_population", label: "Total population", fmt: "count" },
  { id: "households", label: "Households", fmt: "count" },
];

// Warm half of the diverging ramp (spec 07): single-measure level maps.
// Lightest step sits clearly below --paper so the bottom quintile never reads as empty.
const RAMP = ["#E2C994", "#CDA460", "#B47B36", "#925722", "#6B3311"];

const fmt = {
  usd: (v) => "$" + Math.round(v).toLocaleString("en-US"),
  pct: (v) => v.toFixed(1) + "%",
  count: (v) => Math.round(v).toLocaleString("en-US"),
};

// spec 05: CV = SE / estimate × 100, SE = MOE / 1.645 (90% MOEs)
function tier(e, m) {
  if (e == null || m == null || Number.isNaN(e)) return null;
  if (e === 0) return m === 0 ? "high" : "low";
  const cv = (m / 1.645 / Math.abs(e)) * 100;
  return cv < 12 ? "high" : cv <= 40 ? "medium" : "low";
}
const cvOf = (e, m) => (e ? (m / 1.645 / Math.abs(e)) * 100 : null);

const state = {
  vintage: "2016-2020",
  measure: "mean_household_income",
  cubes: {}, // vintage -> Map(GEOID -> row)
  geo: {},   // vintage -> GeoJSON
  breaks: [],
  hover: null,
};

const $ = (id) => document.getElementById(id);
const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

async function loadCube(v) {
  if (!state.cubes[v]) {
    const url = new URL(`acs/${v}/tract/${STATE}.parquet`, DATA);
    const res = await fetch(url);
    if (!res.ok) throw new Error(`${url.pathname}: ${res.status}`);
    const rows = await parquetReadObjects({ file: await res.arrayBuffer(), compressors });
    state.cubes[v] = new Map(rows.map((r) => [r.GEOID, r]));
  }
  return state.cubes[v];
}

async function loadGeo(v) {
  if (!state.geo[v]) {
    const url = new URL(`geo/${v}/tract/${STATE}.geojson`, DATA);
    const res = await fetch(url);
    if (!res.ok) throw new Error(`${url.pathname}: ${res.status}`);
    state.geo[v] = await res.json();
  }
  return state.geo[v];
}

function quantileBreaks(values, k) {
  const s = values.slice().sort((a, b) => a - b);
  const out = [];
  for (let i = 1; i < k; i++) out.push(s[Math.floor((i / k) * (s.length - 1))]);
  return out;
}

// ---------------------------------------------------------------- map

const map = new maplibregl.Map({
  container: "map",
  style: { version: 8, sources: {}, layers: [
    { id: "bg", type: "background", paint: { "background-color": css("--paper") } },
  ] },
  bounds: [[-83.7, 36.5], [-75.2, 39.5]],
  fitBoundsOptions: { padding: 20 },
  attributionControl: { compact: true, customAttribution: "U.S. Census Bureau, ACS 5-year &amp; Cartographic Boundary files" },
  dragRotate: false,
  pitchWithRotate: false,
});
map.touchZoomRotate.disableRotation();
map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");

function hatchImage(color) {
  const n = 8, c = document.createElement("canvas");
  c.width = c.height = n;
  const g = c.getContext("2d");
  g.strokeStyle = color; g.lineWidth = 1; g.globalAlpha = 0.85;
  g.beginPath();
  for (let o = -n; o <= n; o += n) { g.moveTo(o, n); g.lineTo(o + n, 0); }
  g.stroke();
  return g.getImageData(0, 0, n, n);
}

function applyTheme() {
  if (!map.getLayer("bg")) return;
  map.setPaintProperty("bg", "background-color", css("--paper"));
  map.setPaintProperty("tract-line", "line-color", css("--rule"));
  map.setPaintProperty("tract-hover", "line-color", css("--ink"));
  map.setPaintProperty("tract-fill", "fill-color", fillColor());
  if (map.hasImage("hatch")) map.removeImage("hatch");
  map.addImage("hatch", hatchImage(css("--ink-3")));
}

function fillColor() {
  return ["match", ["feature-state", "cls"],
    0, RAMP[0], 1, RAMP[1], 2, RAMP[2], 3, RAMP[3], 4, RAMP[4],
    -2, css("--paper"),   // low reliability: uncolored ground under the hatch
    css("--nodata")];     // no estimate
}

function addLayers() {
  map.addSource("tracts", { type: "geojson", data: { type: "FeatureCollection", features: [] }, promoteId: "GEOID" });
  map.addImage("hatch", hatchImage(css("--ink-3")));
  map.addLayer({ id: "tract-fill", type: "fill", source: "tracts",
    paint: { "fill-color": fillColor(), "fill-color-transition": { duration: 180 } } });
  map.addLayer({ id: "tract-hatch", type: "fill", source: "tracts",
    paint: { "fill-pattern": "hatch",
             "fill-opacity": ["case", ["boolean", ["feature-state", "low"], false], 1, 0] } });
  map.addLayer({ id: "tract-line", type: "line", source: "tracts",
    paint: { "line-color": css("--rule"), "line-width": ["interpolate", ["linear"], ["zoom"], 6, 0.2, 11, 1] } });
  map.addLayer({ id: "tract-hover", type: "line", source: "tracts",
    paint: { "line-color": css("--ink"),
             "line-width": ["case", ["boolean", ["feature-state", "hover"], false], 2, 0] } });
}

// ---------------------------------------------------------------- render

async function setVintage(v) {
  state.vintage = v;
  renderVintageButtons();
  $("status").textContent = "Loading…";
  const [geo] = await Promise.all([loadGeo(v), loadCube(v)]);
  state.hover = null;
  map.getSource("tracts").setData(geo);
  recolor();
}

function recolor() {
  const t0 = performance.now();
  const cube = state.cubes[state.vintage];
  const m = state.measure;
  const vals = [];
  for (const r of cube.values()) {
    const e = r[`${m}_e`];
    if (e != null && !Number.isNaN(e) && tier(e, r[`${m}_m`]) !== "low") vals.push(e);
  }
  state.breaks = quantileBreaks(vals, RAMP.length);
  let low = 0, none = 0;
  for (const f of state.geo[state.vintage].features) {
    const id = f.properties.GEOID;
    const r = cube.get(id);
    const e = r?.[`${m}_e`], mo = r?.[`${m}_m`];
    const t = tier(e, mo);
    let cls = -1;
    if (t === null) none++;
    else if (t === "low") { low++; cls = -2; }
    else { cls = 0; while (cls < state.breaks.length && e > state.breaks[cls]) cls++; }
    map.setFeatureState({ source: "tracts", id }, { cls, low: t === "low" });
  }
  renderLegend(vals.length, low, none);
  const ms = performance.now() - t0;
  $("status").textContent = `${state.geo[state.vintage].features.length.toLocaleString()} tracts · ${ms.toFixed(0)} ms`;
  if (state.hover) inspect(state.hover);
}

function renderLegend(n, low, none) {
  const f = fmt[MEASURES.find((x) => x.id === state.measure).fmt];
  const b = state.breaks;
  const items = RAMP.map((c, i) => {
    const lo = i === 0 ? "≤ " + f(b[0]) : i === RAMP.length - 1 ? "> " + f(b[i - 1]) : `${f(b[i - 1])} – ${f(b[i])}`;
    return `<li><span class="swatch" style="background:${c}"></span>${lo}</li>`;
  });
  items.push(`<li><span class="swatch hatch"></span>${low.toLocaleString()} low reliability</li>`);
  if (none) items.push(`<li><span class="swatch" style="background:var(--nodata)"></span>${none.toLocaleString()} no estimate</li>`);
  $("legend").innerHTML = items.join("");
  const dollars = MEASURES.find((x) => x.id === state.measure).fmt === "usd";
  const vin = VINTAGES.find((x) => x.id === state.vintage);
  $("dollar-note").textContent = dollars
    ? `In ${vin.dollars}, as published — not inflation-adjusted. Quintiles of ${n.toLocaleString()} reliable tracts.`
    : `Quintiles of ${n.toLocaleString()} reliable tracts.`;
}

function inspect(id) {
  const r = state.cubes[state.vintage].get(id);
  const def = MEASURES.find((x) => x.id === state.measure);
  const f = fmt[def.fmt];
  const e = r?.[`${def.id}_e`], m = r?.[`${def.id}_m`];
  const t = tier(e, m);
  const cv = t ? cvOf(e, m) : null;
  const tierText = { high: "High", medium: "Medium — use with care", low: "Low — not colored" }[t];
  $("inspector").innerHTML = `
    <h2 class="eyebrow">Tract</h2>
    <dl>
      <dt>GEOID</dt><dd>${id}</dd>
      <dt>${def.label}</dt><dd>${t ? f(e) : "No estimate"}</dd>
      ${t ? `<dt>Margin (90%)</dt><dd>± ${f(m)}</dd>
      <dt>CV</dt><dd>${cv == null ? "—" : cv.toFixed(1) + "%"}</dd>
      <dt>Reliability</dt><dd class="tier-${t}">${tierText}</dd>` : ""}
      <dt>Population</dt><dd>${r ? fmt.count(r.total_population_e) : "—"}</dd>
    </dl>`;
}

function renderVintageButtons() {
  $("vintage").innerHTML = VINTAGES.map((v) =>
    `<button type="button" role="radio" aria-checked="${v.id === state.vintage}" data-v="${v.id}">${v.label}</button>`).join("");
}

// ---------------------------------------------------------------- wiring

$("measure").innerHTML = MEASURES.map((m) => `<option value="${m.id}">${m.label}</option>`).join("");
$("measure").addEventListener("change", (ev) => { state.measure = ev.target.value; recolor(); });
$("vintage").addEventListener("click", (ev) => {
  const v = ev.target.closest("button")?.dataset.v;
  if (v && v !== state.vintage) setVintage(v).catch(fail);
});

function setHover(id) {
  if (state.hover === id) return;
  if (state.hover) map.setFeatureState({ source: "tracts", id: state.hover }, { hover: false });
  state.hover = id;
  if (id) { map.setFeatureState({ source: "tracts", id }, { hover: true }); inspect(id); }
}
map.on("mousemove", "tract-fill", (e) => setHover(e.features[0]?.id));
map.on("click", "tract-fill", (e) => setHover(e.features[0]?.id));
map.on("mouseenter", "tract-fill", () => (map.getCanvas().style.cursor = "crosshair"));
map.on("mouseleave", "tract-fill", () => (map.getCanvas().style.cursor = ""));

function currentTheme() {
  const set = document.documentElement.dataset.theme;
  return set || (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
}
function syncThemeButton() { $("theme").textContent = currentTheme() === "dark" ? "Light" : "Dark"; }
$("theme").addEventListener("click", () => {
  const next = currentTheme() === "dark" ? "light" : "dark";
  document.documentElement.dataset.theme = next;
  try { localStorage.setItem("strata-theme", next); } catch {}
  syncThemeButton(); applyTheme();
});
try { const t = localStorage.getItem("strata-theme"); if (t) document.documentElement.dataset.theme = t; } catch {}
matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => { syncThemeButton(); applyTheme(); });
syncThemeButton();

function fail(err) {
  console.error(err);
  $("status").textContent = "Error";
  $("inspector").innerHTML = `<h2 class="eyebrow">Error</h2><p class="note">${err.message}.
    Build the data first: see app/README.md.</p>`;
}

renderVintageButtons();
map.on("load", () => {
  addLayers();
  applyTheme();
  setVintage(state.vintage).then(() => { window.__strataReady = true; }).catch(fail);
});
