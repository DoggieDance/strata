// Label gate, on screen: for each measure with a published Census equivalent,
// pick it in the real app, find a sampled tract or county in the table view,
// and check that (1) the menu shows the label the manifest gives that measure
// and (2) the number on screen equals Census's published figure.
//
//   node tests/browser/labels.mjs http://127.0.0.1:8765/app/
// Needs playwright-core and a Chromium (CHROME env var). Exit code 1 on any mismatch.
import { chromium } from "playwright-core";
import fs from "fs";
import path from "path";

const APP = process.argv[2] || "http://127.0.0.1:8765/app/";
const ROOT = process.env.STRATA_ROOT || path.resolve(path.dirname(new URL(import.meta.url).pathname), "../..");
const REG = JSON.parse(fs.readFileSync(`${ROOT}/registry/published_equivalents.json`, "utf8")).equivalents;
const ABBR = { "51": "VA", "42": "PA", "06": "CA" };
const NULL = new Set(["", "-", "N", "(X)", "**", "***", "null", "*****"]);

function fixtures(vintage) {
  const f = `${ROOT}/tests/fixtures/published_equivalents_${vintage}.csv`;
  if (!fs.existsSync(f)) return [];
  const [head, ...lines] = fs.readFileSync(f, "utf8").trim().split(/\r?\n/);
  const cols = head.split(",");
  return lines.map((l) => Object.fromEntries(l.split(",").map((v, i) => [cols[i], v])));
}

function published(eq, vals) {
  const nums = eq.variables.map((v) => vals[v]);
  if (nums.some((x) => x === undefined || NULL.has(x))) return null;
  const n = nums.map((x) => Number(x.replace(/,/g, "")));
  if (eq.op === "each") return { want: n[0], tol: eq.variables[0].endsWith("PE") ? 0.05 : 0.5 };
  if (eq.op === "sum") return { want: n.reduce((a, b) => a + b, 0), tol: 0.05 * n.length };
  return { want: 100 - n[0], tol: 0.05 };
}

const parseShown = (t) => Number(t.replace(/[$,%\s]/g, ""));

const b = await chromium.launch({ executablePath: process.env.CHROME, args: ["--use-angle=swiftshader", "--enable-unsafe-swiftshader"] });
const p = await b.newPage({ viewport: { width: 1300, height: 900 }, reducedMotion: "reduce" });
p.on("pageerror", (e) => console.log("PAGEERROR", e.message));
let checked = 0, failed = 0, compared = 0; // compared: checks against a published number
const VINTAGES = ["2006-2010", "2011-2015", "2015-2019", "2016-2020", "2020-2024"];
for (const vintage of VINTAGES) {
  const rows = fixtures(vintage);
  const byGeo = {};
  for (const r of rows) (byGeo[`${r.level}|${r.GEOID}`] ??= {})[r.variable] = r.value;
  // Two geographies per state and level keep the run short; the pytest gate covers all.
  const picks = Object.keys(byGeo).filter((k, i, a) => a.filter((x) => x.slice(0, x.indexOf("|") + 3) === k.slice(0, k.indexOf("|") + 3)).indexOf(k) < 2);
  for (const key of picks) {
    const [level, geoid] = key.split("|");
    await p.goto(`${APP}#${ABBR[geoid.slice(0, 2)]}`);
    await p.waitForFunction(() => window.__strataReady, null, { timeout: 60000 });
    await p.selectOption("#level", level); await p.waitForTimeout(800);
    // One period, then the period from the dropdown (the app's "Show" and "Period" controls).
    await p.check('input[name="mode"][value="level"]', { force: true });
    await p.selectOption("#vintage", vintage); await p.waitForTimeout(1500);
    await p.check('input[name="view"][value="table"]', { force: true });
    await p.fill("#filter", geoid); await p.waitForTimeout(300);
    const manifest = await p.evaluate(() => fetch(new URL("../build/manifest.json", location.href)).then((r) => r.json()));
    for (const [measure, d] of Object.entries(REG)) {
      if (!d[vintage]) continue;
      const def = manifest.measures.find((m) => m.id === measure);
      if (!def || !(def.vintages || [vintage]).includes(vintage)) continue;
      const pub = published(d[vintage], byGeo[key]);
      await p.selectOption("#measure", measure); await p.waitForTimeout(250);
      const shownLabel = await p.evaluate(() => { const s = document.getElementById("measure"); return s.options[s.selectedIndex].textContent; });
      const cell = await p.evaluate((g) => {
        const row = [...document.querySelectorAll("#tracts tbody tr")].find((tr) => tr.querySelector(".geoid")?.textContent === g);
        return row ? row.querySelectorAll("td")[0].textContent.trim() : null;
      }, geoid);
      checked++;
      const problems = [];
      if (shownLabel !== def.label) problems.push(`menu shows "${shownLabel}", manifest says "${def.label}"`);
      if (await p.evaluate(() => document.getElementById("measure").selectedOptions[0].disabled)) problems.push("measure is disabled for a period that has it");
      if (cell === null) problems.push("row not in table");
      else if (pub === null) { if (cell !== "No estimate") problems.push(`Census suppresses it, app shows ${cell}`); }
      else {
        compared++;
        const shown = parseShown(cell);
        // The app rounds percents to 0.1 and dollars/counts to 1.
        const extra = def.fmt === "pct" ? 0.05 : 0.5;
        if (!(Math.abs(shown - pub.want) <= pub.tol + extra + 1e-9)) problems.push(`app shows ${cell}, Census publishes ${pub.want} (${d[vintage].labels.join(" + ")})`);
      }
      if (problems.length) { failed++; console.log(`FAIL ${vintage} ${level} ${geoid} ${measure}: ${problems.join("; ")}`); }
    }
    console.log(`ok   ${vintage} ${level} ${geoid}`);
  }
}
console.log(`${checked} on-screen checks, ${compared} against a published number, ${failed} failed`);
await b.close();
// A run that never compared a number checked nothing (the CRLF bug, 2026-11-17).
if (compared < checked / 2) console.log("FAIL fewer than half the checks compared a published number: the fixtures were not read");
process.exit(failed || compared < checked / 2 ? 1 : 0);
