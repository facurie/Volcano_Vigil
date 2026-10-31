import { test } from "node:test";
import assert from "node:assert/strict";
import { age, bearing, destination, feet, localDate, localTime, number, plusMinus, ticks, zone } from "../../vigil/web/static/js/lib.js";

test("local time shifts by the volcano's offset, never the browser's zone", () => {
  assert.equal(localTime("2026-10-17T14:55:05Z", -10), "04:55");
  assert.equal(localTime("2026-10-17T14:55:05Z", -10, true), "04:55:05");
  assert.equal(localTime("2026-10-17T05:00:00Z", -10), "19:00");
  assert.equal(localDate("2026-10-17T05:00:00Z", -10), "2026-10-16");
  assert.equal(localTime("2026-10-17T14:55:05Z", 0), "14:55");
});

test("a time without its zone is refused", () => {
  assert.throws(() => localTime("2026-10-17T14:55:05", -10));
});

test("zones read like the bulletins'", () => {
  assert.equal(zone(-10), "UTC−10");
  assert.equal(zone(0), "UTC");
  assert.equal(zone(5.5), "UTC+5.5");
});

test("numbers and uncertainties print as the English bulletins print them", () => {
  assert.equal(number(6963.7), "6,964");
  assert.equal(number(3.25, 1), "3.3");
  assert.equal(plusMinus(6963.7, 419.4, "m"), "6,964 ± 419 m");
  assert.equal(plusMinus(224.44, 2.1, "deg"), "224.4° ± 2.1°");
  assert.equal(plusMinus(20215368, 1409392, "m2"), "20.2 ± 1.4 km²");
  assert.equal(feet(7620), 25000);
});

test("ages are relative to the scene's clock", () => {
  assert.equal(age("2026-10-17T14:59:40Z", "2026-10-17T15:00:00Z"), "just now");
  assert.equal(age("2026-10-17T14:48:00Z", "2026-10-17T15:00:00Z"), "12 min ago");
  assert.equal(age("2026-10-17T12:00:00Z", "2026-10-17T15:00:00Z"), "3 h ago");
  assert.equal(age("2026-10-14T15:00:00Z", "2026-10-17T15:00:00Z"), "3 d ago");
});

test("the replay's ticks match vigil.replay.ticks", () => {
  assert.deepEqual(ticks("2026-10-17T13:00:00Z", "2026-10-17T13:12:00Z", 5),
    ["2026-10-17T13:05:00Z", "2026-10-17T13:10:00Z", "2026-10-17T13:12:00Z"]);
});

test("a destination and a bearing on the sphere agree", () => {
  const [lat, lon] = destination(19.40496, -155.29022, 90, 1000);
  assert.ok(Math.abs(lat - 19.40496) < 1e-4);
  assert.ok(Math.abs(lon - -155.280685) < 2e-5);
  const [north] = destination(19.40496, -155.29022, 0, 1000);
  assert.ok(Math.abs(north - 19.413953) < 2e-5);
  const there = destination(19.492709, -155.385281, 137, 5000);
  assert.ok(Math.abs(bearing(19.492709, -155.385281, there[0], there[1]) - 137) < 0.01);
});
