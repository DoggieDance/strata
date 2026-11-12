// STRATA local preview. Reads the built cubes (Parquet) and geometry from
// ../build/, joins them in the browser by GEOID via feature state (spec 03).
// Never calls a Census API.
//
// Accessibility: every value on the map is also in the table view (search,
// sort, "Show on map"), so nothing depends on seeing color or using a mouse.
import { parquetReadObjects } from "https://cdn.jsdelivr.net/npm/hyparquet@1.31.5/+esm";
import { compressors } from "https://cdn.jsdelivr.net/npm/hyparquet-compressors@1.1.2/+esm";

const DATA = new URL("../build/", import.meta.url);
const STATE = "51";

const VINTAGES = [
  { id: "2006-2010", label: "2006–10", dollars: "2010 dollars" },
  { id: "2016-2020", label: "2016–20", dollars: "2020 dollars" },
];

// Census-published geographies. Values are Census's own estimates for each,
// not sums of tracts. ZCTAs exist from the 2011-15 release on, so not 2006-10.
const LEVELS = [
  { id: "tract", label: "Census tracts", noun: "tract", plural: "tracts", vintages: ["2006-2010", "2016-2020"] },
  { id: "county", label: "Counties & independent cities", noun: "county or city", plural: "counties and cities", vintages: ["2006-2010", "2016-2020"] },
  { id: "place", label: "Towns & places", noun: "place", plural: "places", vintages: ["2006-2010", "2016-2020"],
    note: "Places are incorporated towns and cities plus census-designated places. They cover only part of the state; blank ground is outside any place." },
  { id: "zcta", label: "ZIP codes", noun: "ZIP code area", plural: "ZIP code areas", vintages: ["2016-2020"],
    note: "ZIP Code Tabulation Areas: Census's area version of USPS ZIP codes, as defined in 2010 (the 2016–20 survey still uses those). Not published for 2006–10." },
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

// Warm half of the diverging ramp (spec 07), lowest to highest. One hue family
// stepping in lightness, so it reads under every common color-vision deficiency.
// Paper: dark ink rises out of light ground. Vellum: the same hues run dim to
// bright, so high values never sink into the dark ground (darkest step 2.2:1,
// brightest 12:1 against --paper).
const RAMPS = {
  light: ["#E2C994", "#CDA460", "#B47B36", "#925722", "#6B3311"],
  dark: ["#6B4423", "#8F5E2C", "#B47B36", "#D4A25E", "#EBCB93"],
};

const reduceMotion = matchMedia("(prefers-reduced-motion: reduce)");

const fmt = {
  usd: (v) => "$" + Math.round(v).toLocaleString("en-US"),
  pct: (v) => v.toFixed(1) + "%",
  count: (v) => Math.round(v).toLocaleString("en-US"),
};

// spec 05: CV = SE / estimate × 100, SE = MOE / 1.645 (90% MOEs)
function tier(e, m) {
  if (e == null || m == null || Number.isNaN(e)) return null;
  if (e === 0) return m === 0 ? "high" : "low";
  // Tier on the CV as displayed (one decimal), so "12.0%" never reads as High.
  const cv = Math.round((m / 1.645 / Math.abs(e)) * 1000) / 10;
  return cv < 12 ? "high" : cv <= 40 ? "medium" : "low";
}
const cvOf = (e, m) => (e ? (m / 1.645 / Math.abs(e)) * 100 : null);
const TIER_TEXT = { high: "High", medium: "Medium, use with care", low: "Low, not colored" };

const state = {
  vintage: "2016-2020",
  level: "tract",
  measure: "mean_household_income",
  view: "map",
  cubes: {}, geo: {}, names: {}, bbox: {},
  breaks: [],
  selected: null,
  sort: { key: "name", dir: 1 },
  filter: "",
};

const $ = (id) => document.getElementById(id);
const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
const measureDef = () => MEASURES.find((x) => x.id === state.measure);
const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

async function getJSON(path) {
  const url = new URL(path, DATA);
  const res = await fetch(url);
  if (!res.ok) throw new Error(`${url.pathname}: ${res.status}`);
  return res.json();
}

const key = () => `${state.vintage}/${state.level}`;
const levelDef = () => LEVELS.find((x) => x.id === state.level);

async function loadData() {
  const k = key();
  if (!state.cubes[k]) {
    const url = new URL(`acs/${k}/${STATE}.parquet`, DATA);
    const res = await fetch(url);
    if (!res.ok) throw new Error(`${url.pathname}: ${res.status}`);
    const rows = await parquetReadObjects({ file: await res.arrayBuffer(), compressors });
    state.cubes[k] = new Map(rows.map((r) => [r.GEOID, r]));
  }
  if (!state.geo[k]) state.geo[k] = await getJSON(`geo/${k}/${STATE}.geojson`);
  if (!state.names[k]) state.names[k] = await getJSON(`geo/${k}/${STATE}.names.json`).catch(() => ({}));
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
  const dark = currentTheme() === "dark";
  $("theme").setAttribute("aria-pressed", String(dark));
  $("theme").textContent = "Dark theme";
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

function fillColor() {
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
  map.setPaintProperty("tract-sel-casing", "line-color", css("--paper"));
  map.setPaintProperty("tract-sel", "line-color", css("--accent"));
  map.setPaintProperty("tract-fill", "fill-color", fillColor());
  if (map.hasImage("hatch")) map.removeImage("hatch");
  map.addImage("hatch", hatchImage(css("--ink-2")));
  if (state.breaks.length) renderLegend();
}

function addLayers() {
  map.addSource("tracts", { type: "geojson", data: { type: "FeatureCollection", features: [] }, promoteId: "GEOID" });
  map.addImage("hatch", hatchImage(css("--ink-2")));
  map.addLayer({ id: "tract-fill", type: "fill", source: "tracts",
    paint: { "fill-color": fillColor(), "fill-color-transition": { duration: reduceMotion.matches ? 0 : 180 } } });
  map.addLayer({ id: "tract-hatch", type: "fill", source: "tracts",
    paint: { "fill-pattern": "hatch",
             "fill-opacity": ["case", ["boolean", ["feature-state", "low"], false], 1, 0] } });
  map.addLayer({ id: "tract-line", type: "line", source: "tracts",
    paint: { "line-color": css("--rule"), "line-width": ["interpolate", ["linear"], ["zoom"], 6, 0.2, 11, 1] } });
  // Selection: accent line on a paper casing, visible on every ramp step in both themes.
  map.addLayer({ id: "tract-sel-casing", type: "line", source: "tracts",
    paint: { "line-color": css("--paper"),
             "line-width": ["case", ["boolean", ["feature-state", "sel"], false], 6, 0] } });
  map.addLayer({ id: "tract-sel", type: "line", source: "tracts",
    paint: { "line-color": css("--accent"),
             "line-width": ["case", ["boolean", ["feature-state", "sel"], false], 3, 0] } });
}

// ---------------------------------------------------------------- render

async function reload() {
  const k = key();
  $("status").textContent = "Loading…";
  syncAvailability();
  await loadData();
  if (key() !== k) return; // a newer switch happened while loading; it will render
  if (state.selected) map.setFeatureState({ source: "tracts", id: state.selected }, { sel: false });
  state.selected = null;
  state.bbox = {};
  map.getSource("tracts").setData(state.geo[key()]);
  map.setPaintProperty("tract-line", "line-width", lineWidth());
  recolor();
  renderInspector();
  renderLabels();
}

function lineWidth() {
  const big = state.level === "county" ? 1.4 : state.level === "tract" ? 0 : 0.5;
  return ["interpolate", ["linear"], ["zoom"], 6, 0.2 + big * 0.5, 11, 1 + big];
}

// A level Census did not publish for a vintage cannot be picked with it.
function syncAvailability() {
  const lv = levelDef();
  for (const o of $("level").options) {
    const def = LEVELS.find((x) => x.id === o.value);
    o.disabled = !def.vintages.includes(state.vintage);
    o.textContent = def.label + (o.disabled ? " (2016–20 only)" : "");
  }
  for (const r of document.querySelectorAll('input[name="vintage"]')) {
    r.disabled = !lv.vintages.includes(r.value);
    r.closest("label").title = r.disabled ? `Census published no ${lv.plural} for this period` : "";
  }
  $("level-note").textContent = lv.note || "";
  $("level-note").hidden = !lv.note;
}

function renderLabels() {
  const lv = levelDef();
  const cap = (s) => s[0].toUpperCase() + s.slice(1);
  $("inspector-title").textContent = `Selected ${lv.noun}`;
  $("filter-label").textContent = `Find a ${lv.noun}`;
  $("name-col").textContent = cap(lv.noun);
  $("map").setAttribute("aria-label", `Map of Virginia ${lv.plural}. Arrow keys pan, plus and minus zoom. Every value is also in the table view.`);
}

function recolor() {
  const t0 = performance.now();
  const cube = state.cubes[key()];
  const m = state.measure;
  const vals = [];
  for (const r of cube.values()) {
    const e = r[`${m}_e`];
    if (e != null && !Number.isNaN(e) && tier(e, r[`${m}_m`]) !== "low") vals.push(e);
  }
  state.breaks = quantileBreaks(vals, 5);
  state.reliable = vals.length;
  let low = 0, none = 0;
  for (const f of state.geo[key()].features) {
    const id = f.properties.GEOID;
    const r = cube.get(id);
    const e = r?.[`${m}_e`];
    const t = tier(e, r?.[`${m}_m`]);
    let cls = -1;
    if (t === null) none++;
    else if (t === "low") { low++; cls = -2; }
    else cls = classOf(e);
    map.setFeatureState({ source: "tracts", id }, { cls, low: t === "low" });
  }
  state.counts = { low, none };
  renderLegend();
  const ms = performance.now() - t0;
  $("status").textContent = `${state.geo[key()].features.length.toLocaleString()} ${levelDef().plural} · ${ms.toFixed(0)} ms`;
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

function renderLegend() {
  const r = ramp();
  const { low, none } = state.counts;
  const items = r.map((c, i) =>
    `<li><span class="swatch" style="background:${c}" aria-hidden="true"></span>${["Lowest", "Low", "Middle", "High", "Highest"][i]} fifth: ${rangeLabel(i)}</li>`);
  items.push(`<li><span class="swatch hatch" aria-hidden="true"></span>${low.toLocaleString()} low reliability</li>`);
  if (none) items.push(`<li><span class="swatch" style="background:var(--nodata)" aria-hidden="true"></span>${none.toLocaleString()} no estimate</li>`);
  $("legend").innerHTML = items.join("");
  const vin = VINTAGES.find((x) => x.id === state.vintage);
  const dollars = measureDef().fmt === "usd"
    ? `In ${vin.dollars}, as published, not inflation-adjusted. ` : "";
  $("dollar-note").textContent = `${dollars}Fifths (quintiles) of ${state.reliable.toLocaleString()} reliable ${levelDef().plural}.`;
}

function tractRow(id) {
  const r = state.cubes[key()].get(id);
  const m = state.measure;
  const e = r?.[`${m}_e`], mo = r?.[`${m}_m`];
  const t = tier(e, mo);
  return { id, name: state.names[key()][id] || id, r, e: t ? e : null, m: t ? mo : null,
           cv: t ? cvOf(e, mo) : null, t };
}

function renderInspector() {
  if (!state.selected) {
    $("inspector").innerHTML = `<p class="note">Hover or tap the map, or pick from the table.</p>`;
    return;
  }
  const def = measureDef(), f = fmt[def.fmt];
  const x = tractRow(state.selected);
  const fifth = x.t && x.t !== "low" ? ["lowest", "low", "middle", "high", "highest"][classOf(x.e)] + " fifth" : null;
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

function renderTable() {
  const def = measureDef(), f = fmt[def.fmt];
  const vin = VINTAGES.find((x) => x.id === state.vintage);
  const q = state.filter.trim().toLowerCase();
  let rows = [...state.cubes[key()].keys()].map(tractRow);
  if (q) rows = rows.filter((x) => x.name.toLowerCase().includes(q) || x.id.includes(q));
  const { key: sortKey, dir } = state.sort;
  rows.sort((a, b) => {
    const av = a[sortKey], bv = b[sortKey];
    if (av == null && bv == null) return a.id.localeCompare(b.id);
    if (av == null) return 1;               // no estimate always sorts last
    if (bv == null) return -1;
    return (typeof av === "string" ? av.localeCompare(bv) : av - bv) * dir || a.id.localeCompare(b.id);
  });
  const hasGeo = new Set(state.geo[key()].features.map((x) => x.properties.GEOID));
  $("tracts").querySelector("tbody").innerHTML = rows.map((x) => `
    <tr>
      <th scope="row"><span class="tract-name">${esc(x.name)}</span><span class="geoid">${x.id}</span></th>
      <td class="num">${x.t ? f(x.e) : "No estimate"}</td>
      <td class="num">${x.t ? "± " + f(x.m) : ""}</td>
      <td class="num">${x.cv == null ? "" : x.cv.toFixed(1) + "%"}</td>
      <td class="${x.t ? "tier-" + x.t : ""}">${x.t ? TIER_TEXT[x.t] : ""}</td>
      <td>${hasGeo.has(x.id)
        ? `<button type="button" class="show" data-id="${x.id}" aria-label="Show ${esc(x.name)} on the map">Show on map</button>`
        : `<span class="note">No boundary</span>`}</td>
    </tr>`).join("");
  $("table-caption").textContent = `${def.label}, ${vin.label}, Virginia ${levelDef().plural}. ${rows.length} rows.`;
  $("table-count").textContent = q ? `${rows.length.toLocaleString()} of ${state.cubes[key()].size.toLocaleString()} ${levelDef().plural} match.` : `${rows.length.toLocaleString()} ${levelDef().plural}.`;
  for (const th of $("tracts").querySelectorAll("th[aria-sort]")) {
    const k = th.querySelector("button").dataset.sort;
    th.setAttribute("aria-sort", k === sortKey ? (dir > 0 ? "ascending" : "descending") : "none");
  }
}

function featureBBox(id) {
  if (!state.bbox[id]) {
    const f = state.geo[key()].features.find((x) => x.properties.GEOID === id);
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
  $("map").hidden = v !== "map";
  $("table-view").hidden = v !== "table";
  for (const r of document.querySelectorAll('input[name="view"]')) r.checked = r.value === v;
  if (v === "map") map.resize();
}

function showOnMap(id) {
  setView("map");
  select(id);
  map.fitBounds(featureBBox(id), { padding: 60, maxZoom: 12, duration: reduceMotion.matches ? 0 : 600 });
  map.getCanvas().focus();
}

// ---------------------------------------------------------------- wiring

$("measure").innerHTML = MEASURES.map((m) => `<option value="${m.id}">${m.label}</option>`).join("");
$("measure").addEventListener("change", (ev) => { state.measure = ev.target.value; recolor(); });

$("vintage-options").innerHTML = VINTAGES.map((v) =>
  `<label><input type="radio" name="vintage" value="${v.id}" ${v.id === state.vintage ? "checked" : ""}><span>${v.label}</span></label>`).join("");
$("vintage").addEventListener("change", (ev) => { state.vintage = ev.target.value; reload().catch(fail); });

$("level").innerHTML = LEVELS.map((l) => `<option value="${l.id}">${l.label}</option>`).join("");
$("level").addEventListener("change", (ev) => { state.level = ev.target.value; reload().catch(fail); });

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

// Ignore features from the previous level while new data is still swapping in.
const pick = (e) => { const id = e.features[0]?.id; if (id && state.cubes[key()]?.has(id)) select(id); };
map.on("mousemove", "tract-fill", pick);
map.on("click", "tract-fill", pick);
map.on("mouseenter", "tract-fill", () => (map.getCanvas().style.cursor = "crosshair"));
map.on("mouseleave", "tract-fill", () => (map.getCanvas().style.cursor = ""));

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

map.on("load", () => {
  addLayers();
  applyTheme();
  reload().then(() => { window.__strataReady = true; }).catch(fail);
});
