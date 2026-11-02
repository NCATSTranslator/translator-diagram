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

test("the figures are shares with honest denominators, each naming a view", () => {
  const live = (version, extra) => ({ deployed: true, version, version_source: "openapi", reachable: true, ...extra });
  const data = {
    environments: ["ci", "prod"],
    synced_at: "2026-10-15T10:00:00Z",
    sync_counts: { attempted: 10, succeeded: 8, failed: 2 },
    source_tally: { openapi: 3, none: 1 },
    otel_service_total: 5, otel_service_counts: { ci: 3, prod: 2 },
    rows: [
      // Registered, reachable everywhere, agreeing.
      { id: "a", smartapi: "x", smartapi_record: { id: "x" },
        environments: { ci: live("1.0"), prod: live("1.0") } },
      // Unregistered in prod, prod down, versions differ; nothing probed in ci.
      { id: "b", smartapi: "y", smartapi_record: { id: "y" },
        environments: { ci: { deployed: true, version: "2.0", version_source: "openapi", reachable: null, drift: ["version"] },
                        prod: { deployed: true, reachable: false, unregistered: true, drift: ["version"] } } },
      // No record at all, no version anywhere.
      { id: "c", environments: { ci: { deployed: false, reason: "no address on file" } } },
    ],
  };
  const f = summary.figures(data);
  assert.equal(f.syncedAt, data.synced_at);
  assert.deepEqual(f.checks, { attempted: 10, succeeded: 8, failed: 2 });
  const byView = Object.fromEntries(f.shares.map((s) => [s.view, [s.n, s.of]]));
  // 3 probed (b.ci was not), 2 up.
  assert.deepEqual(byView.unreachable, [2, 3]);
  // 4 deployed, 3 with a version.
  assert.deepEqual(byView.none, [3, 4]);
  // 4 deployed cells on rows with a recorded id, one of them unregistered.
  assert.deepEqual(byView.unregistered, [3, 4]);
  assert.deepEqual(byView["no-smartapi"], [2, 3]);
  assert.deepEqual(byView.differ, [2, 3]);
  assert.deepEqual(f.otel, { total: 5, perEnv: [["ci", 3], ["prod", 2]] });
  assert.deepEqual(f.sources, ["3 from its API document", "1 from nowhere"]);
});

test("the axes strip lists each release seen, in version order, with where it is", () => {
  const on = (babel, extra) => ({ deployed: true, version: "1", babel, babel_source: "status", ...extra });
  const data = {
    environments: ["dev", "ci", "test", "prod"],
    data_axes: { babel: "Babel", biolink: "Biolink", graph: "Translator Graph" },
    rows: [
      { id: "nn", environments: { ci: on("2025sep1"), test: on("2025sep1"), prod: { deployed: false } } },
      { id: "nr", environments: { ci: on("2025sep1", { biolink: "master" }), prod: on("2025sep1", { biolink: "master" }) } },
      { id: "redis", environments: { dev: on("2026jul22", { biolink: "v4.4.3" }) } },
      { id: "gandalf", environments: { dev: { deployed: true, version: "1", biolink: "4.4.2", biolink_source: "openapi" } } },
    ],
  };
  const strip = summary.axes(data);
  // No cell carries a graph release, so the axis is not a line.
  assert.deepEqual(strip.map((a) => a.label), ["Babel", "Biolink"]);
  assert.deepEqual(strip[0].versions, [
    { version: "2025sep1", envs: [{ env: "ci", ids: ["nn", "nr"] }, { env: "test", ids: ["nn"] }, { env: "prod", ids: ["nr"] }] },
    { version: "2026jul22", envs: [{ env: "dev", ids: ["redis"] }] },
  ]);
  assert.deepEqual(strip[1].versions.map((v) => v.version), ["4.4.2", "master", "v4.4.3"]);
  assert.deepEqual(summary.axes({ rows: [] }), []);
});

test("the figures leave out a share with nothing to count", () => {
  const f = summary.figures({ rows: [] });
  assert.deepEqual(f.shares, []);
  assert.deepEqual(f.checks, { attempted: 0, succeeded: 0, failed: 0 });
});
