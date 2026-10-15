/*
  core.js's clock-dependent formatting, the theme cycle, and the page's own
  summary of the payload: pure once the clock and the system preference are
  arguments, which is what makes "a future timestamp says today" and "the
  first click moves away from the system" testable at all.
*/

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const CORE = path.join(__dirname, "..", "..", "src", "translator_diagram", "web", "core.js");

globalThis.TD = {};
vm.runInThisContext(fs.readFileSync(CORE, "utf8"), { filename: "core.js" });
const { fmt, theme, summary } = globalThis.TD;

const NOW = Date.parse("2026-10-15T12:00:00Z");
const ago = (ms) => new Date(NOW - ms).toISOString();
const DAY = 86400000;

test("relativeAge clamps the first day, and a clock ahead of GitHub's, to today", () => {
  assert.equal(fmt.relativeAge(ago(3 * 3600000), NOW), "today");
  assert.equal(fmt.relativeAge(ago(-3 * 3600000), NOW), "today");
});

test("relativeAge counts days, then weeks, then months, then years", () => {
  assert.match(fmt.relativeAge(ago(10 * DAY), NOW), /10.*day/);
  assert.match(fmt.relativeAge(ago(21 * DAY), NOW), /3.*week/);
  assert.match(fmt.relativeAge(ago(200 * DAY), NOW), /month/);
  assert.match(fmt.relativeAge(ago(800 * DAY), NOW), /2.*year/);
  assert.equal(fmt.relativeAge("not a date", NOW), "");
});

test("since has a finer bottom end than relativeAge, and hands off to it", () => {
  assert.equal(fmt.since(ago(60000), NOW), "just now");
  assert.match(fmt.since(ago(30 * 60000), NOW), /30.*minute/);
  assert.match(fmt.since(ago(3 * 3600000), NOW), /3.*hour/);
  assert.match(fmt.since(ago(5 * DAY), NOW), /5.*day/);
});

test("the theme cycle starts by moving away from the system", () => {
  // On a light machine: auto → dark → light → auto. On a dark one: auto →
  // light → dark → auto. The one click that changes nothing visible is the
  // trip back to auto.
  assert.equal(theme.next("auto", false), "dark");
  assert.equal(theme.next("dark", false), "light");
  assert.equal(theme.next("light", false), "auto");
  assert.equal(theme.next("auto", true), "light");
  assert.equal(theme.next("light", true), "dark");
  assert.equal(theme.next("dark", true), "auto");
});

test("the deployments tile counts deployed cells, not rows or environments", () => {
  const rows = [
    { environments: { ci: { deployed: true }, prod: { deployed: true }, dev: { deployed: false } } },
    { environments: { prod: { deployed: true } } },
    { environments: {} },
    {},
  ];
  assert.equal(summary.deployments(rows, ["dev", "ci", "test", "prod"]), 3);
  assert.equal(summary.deployments(rows, ["dev"]), 0);
  assert.equal(summary.deployments(undefined, ["prod"]), 0);
});

test("the finding sentence names each source by the payload's label", () => {
  const html = summary.finding({
    source_tally: { openapi: 26, smartapi: 13, none: 11 },
    source_labels: { openapi: "OpenAPI document", smartapi: "SmartAPI" },
    unregistered_count: 3,
  });
  assert.match(html, /^Of 50 deployments, <strong>26<\/strong> from OpenAPI document, <strong>13<\/strong> from SmartAPI, and <strong>11<\/strong> from nothing at all\./);
  assert.match(html, /<strong>3<\/strong> of them are absent/);
});

test("the finding sentence says when nothing was found at all", () => {
  assert.match(summary.finding({}), /No deployments were found/);
  assert.doesNotMatch(summary.finding({ source_tally: { helm: 2 } }), /absent/);
});
