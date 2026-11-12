import test from "node:test";
import assert from "node:assert/strict";
import { change, changeClass, magnitudeBreak, se, Z90 } from "../../app/engine/change.js";

const close = (a, b, eps = 1e-9) => assert.ok(Math.abs(a - b) < eps, `${a} != ${b}`);

test("SE is MOE over 1.645", () => close(se(16.45), 10));

test("significant rise", () => {
  // d = 120 - 100 = 20; SE = sqrt(5^2 + 5^2) = 7.07; Z = 2.83
  const c = change(100, 5 * Z90, 120, 5 * Z90);
  assert.equal(c.state, "up");
  close(c.z, 20 / Math.hypot(5, 5));
  close(c.moe, Math.hypot(5, 5) * Z90);
});

test("a difference inside the noise is no measurable change, not a direction", () => {
  const c = change(100, 20, 105, 20); // Z = 5 / (sqrt(2)*12.16) = 0.29
  assert.equal(c.state, "nochange");
  assert.equal(changeClass(c, 1), 0);
});

test("deflation scales the earlier estimate and its MOE", () => {
  // $50,000 in 2010 dollars x 1.1906 = $59,530 in 2020 dollars; later $59,000 is a real decline only if outside noise
  const f = 380.75541666666663 / 319.8;
  const c = change(50000, 1000, 59000, 1000, { factor: f });
  close(c.d, 59000 - 50000 * f, 1e-6);
  close(c.moe, Math.hypot(1000 * f, 1000), 1e-9);
  assert.equal(c.state, "nochange"); // -530 against an MOE of ~1555
  const nominal = change(50000, 1000, 59000, 1000);
  assert.equal(nominal.state, "up"); // without deflation the same data looks like a rise
});

test("missing input yields no state", () => {
  assert.equal(change(null, 1, 2, 1).state, "none");
  assert.equal(change(1, NaN, 2, 1).state, "none");
  assert.equal(changeClass(change(null, 1, 2, 1), 1), null);
});

test("zero-MOE controlled counts compare exactly", () => {
  assert.equal(change(10, 0, 10, 0).state, "nochange");
  assert.equal(change(10, 0, 11, 0).state, "up");
});

test("classes split significant changes at the median magnitude", () => {
  const cs = [change(0, 0, 1, 0), change(0, 0, 3, 0), change(0, 0, -10, 0), change(5, 50, 6, 50)];
  const b = magnitudeBreak(cs); // |d| of significant: 1, 3, 10 -> median 3
  assert.equal(b, 3);
  assert.deepEqual(cs.map((c) => changeClass(c, b)), [1, 1, -2, 0]);
});
