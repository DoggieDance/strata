// Index builder, on screen (spec 04): the Philadelphia preset draws, its
// contributions add up to the score shown, the link reopens the same index,
// and the engine's refusals reach the reader as words, not a blank map.
//
//   node tests/browser/index_builder.mjs http://127.0.0.1:8765/app/
// Needs playwright-core and a Chromium (CHROME env var). Exit code 1 on any failure.
import { chromium } from "playwright-core";

const APP = process.argv[2] || "http://127.0.0.1:8765/app/";
let failed = 0;
const check = (ok, what) => { console.log(`${ok ? "ok  " : "FAIL"} ${what}`); if (!ok) failed++; };
const num = (t) => Number(t.replace(/[−–]/g, "-").replace(/[^\d.-]/g, ""));

const b = await chromium.launch({ executablePath: process.env.CHROME, args: ["--use-angle=swiftshader", "--enable-unsafe-swiftshader"] });
for (const scheme of ["light", "dark"]) {
  const p = await b.newPage({ viewport: { width: 1300, height: 1000 }, colorScheme: scheme, reducedMotion: "reduce" });
  const errors = [];
  p.on("pageerror", (e) => errors.push(e.message));
  await p.goto(`${APP}#PA`);
  await p.waitForFunction(() => window.__strataReady, null, { timeout: 60000 });
  await p.check("#index-on");
  await p.selectOption("#ix-preset", "philly");
  await p.waitForFunction(() => (window.__strataIx || 0) >= 1 && document.querySelector("#ix-measures li[data-id=pct_nh_white]"), null, { timeout: 120000 });
  await p.waitForTimeout(500);
  check(await p.locator("#ix-measures li").count() === 5, `${scheme}: preset has the study's five measures`);
  check(!(await p.isVisible("#ix-error")), `${scheme}: no engine error`);
  check(new URL(p.url()).searchParams.has("index"), `${scheme}: the spec is in the URL`);
  const changed = await p.inputValue("#to").catch(() => "");
  const note = await p.textContent("#period-note");
  check(changed === "2016-2020" || /not on change/.test(note), `${scheme}: change mode, or the fallback is stated (${note || "change"})`);

  await p.check('input[name="view"][value="table"]', { force: true });
  await p.fill("#filter", "Philadelphia County");
  await p.waitForTimeout(400);
  await p.click("#tracts tbody tr button.show");
  await p.waitForTimeout(800);
  const score = num((await p.locator("#inspector dd").nth(1).textContent()).split("±")[0]);
  const parts = await p.locator("#inspector .contrib .v").allTextContents();
  const sum = parts.map(num).reduce((a, x) => a + x, 0);
  check(parts.length === 5 && Math.abs(sum - score) <= 0.03, `${scheme}: contributions (${parts.join(" ")}) add to the score ${score}`);

  // Reopen from the link: same spec, same score for the same tract.
  const q = await b.newPage({ viewport: { width: 1300, height: 1000 }, colorScheme: scheme, reducedMotion: "reduce" });
  q.on("pageerror", (e) => errors.push(e.message));
  await q.goto(p.url());
  await q.waitForFunction(() => window.__strataReady && (window.__strataIx || 0) >= 1, null, { timeout: 120000 });
  check(await q.locator("#ix-measures li").count() === 5, `${scheme}: the link reopens all five measures`);
  check((await q.textContent("#legend")) === (await p.textContent("#legend")), `${scheme}: the link reopens the same breaks`);

  // A refusal is shown as text. In change mode logging a change is refused; in
  // a single period, unscaled dollars and percents together are refused.
  await q.selectOption('#ix-measures li[data-id="mean_gross_rent"] [data-key="normalize"]', "none");
  await q.selectOption('#ix-measures li[data-id="pct_nh_white"] [data-key="normalize"]', "none");
  await q.waitForTimeout(800);
  check(/differing units/.test(await q.textContent("#ix-error")), `${scheme}: unscaled measures of differing units are refused on screen`);
  check(errors.length === 0, `${scheme}: no page errors ${errors.join("; ")}`);
}
await b.close();
console.log(failed ? `${failed} failed` : "all passed");
process.exit(failed ? 1 : 0);
