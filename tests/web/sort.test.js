/*
  The table's comparators, driven the way the table drives them.

  The rule these exist for: half the components have no date — they publish no
  GitHub releases and are in no SmartAPI record — and reversing a sort must not
  promote the rows we know least about. That is checked in *both* directions
  here, because it is the direction nobody looks at where it broke before.
*/

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const CORE = path.join(__dirname, "..", "..", "src", "translator_diagram", "web", "core.js");

globalThis.TD = {};
vm.runInThisContext(fs.readFileSync(CORE, "utf8"), { filename: "core.js" });
const TD = globalThis.TD;

/* A column, in the shape web/table.js builds them. */
const updatedColumn = {
  key: "updated",
  value: (row) => (row.last_updated || {}).date || "",
  compare: TD.sort.byDate,
};

const envColumn = (env) => ({
  key: `env-${env}`,
  value: (row) => (row.environments[env] || {}).released || "",
  rank: (row) => TD.sort.envRank(row, env),
  compare: TD.sort.byDate,
});

const dated = (id, date) => ({ id, last_updated: date ? { date } : null, environments: {} });

test("byDate orders ISO dates without leaning on the alphabet", () => {
  assert.equal(TD.sort.byDate("2026-01-02", "2026-01-10"), -1);
  assert.equal(TD.sort.byDate("2026-01-10", "2026-01-02"), 1);
  assert.equal(TD.sort.byDate("2026-01-02", "2026-01-02"), 0);
});

test("byText compares numerically inside names", () => {
  assert.ok(TD.sort.byText("step2", "step10") < 0);
  assert.equal(TD.sort.byText("ARAX", "arax"), 0);
});

test("blanks stay last in both directions", () => {
  const rows = [
    dated("nodate-a", null),
    dated("old", "2024-01-01"),
    dated("nodate-b", null),
    dated("new", "2026-08-01"),
  ];
  const asc = TD.sort.rows(rows, updatedColumn, "asc").map((row) => row.id);
  const desc = TD.sort.rows(rows, updatedColumn, "desc").map((row) => row.id);
  assert.deepEqual(asc, ["old", "new", "nodate-a", "nodate-b"]);
  assert.deepEqual(desc, ["new", "old", "nodate-a", "nodate-b"]);
});

test("sorting reads a copy and leaves the payload's own order alone", () => {
  const rows = [dated("b", "2026-01-01"), dated("a", "2020-01-01")];
  const sorted = TD.sort.rows(rows, updatedColumn, "asc");
  assert.deepEqual(rows.map((row) => row.id), ["b", "a"]);
  assert.deepEqual(sorted.map((row) => row.id), ["a", "b"]);
  assert.notEqual(sorted, rows);
});

test("with no column the copy is the payload's order", () => {
  const rows = [dated("b", null), dated("a", null)];
  assert.deepEqual(TD.sort.rows(rows, null, "asc").map((row) => row.id), ["b", "a"]);
});

test("the sort is stable, so ties fall back to stage order", () => {
  const rows = ["one", "two", "three"].map((id) => dated(id, "2026-01-01"));
  assert.deepEqual(TD.sort.rows(rows, updatedColumn, "desc").map((row) => row.id),
    ["one", "two", "three"]);
});

test("envRank tiers a dated release, then an undated one, then nothing", () => {
  const row = {
    environments: {
      prod: { deployed: true, released: "2026-01-01" },
      test: { deployed: true },
      ci: { deployed: false },
      dev: {},
    },
  };
  assert.equal(TD.sort.envRank(row, "prod"), 0);
  assert.equal(TD.sort.envRank(row, "test"), 1);
  assert.equal(TD.sort.envRank(row, "ci"), 2);
  assert.equal(TD.sort.envRank(row, "dev"), 2);
  assert.equal(TD.sort.envRank({ environments: {} }, "prod"), 2);
});

test("the tiers hold before the direction flip", () => {
  const rows = [
    { id: "undated", environments: { prod: { deployed: true } } },
    { id: "gone", environments: { prod: { deployed: false } } },
    { id: "old", environments: { prod: { deployed: true, released: "2024-01-01" } } },
    { id: "new", environments: { prod: { deployed: true, released: "2026-06-01" } } },
  ];
  const column = envColumn("prod");
  assert.deepEqual(TD.sort.rows(rows, column, "asc").map((row) => row.id),
    ["old", "new", "undated", "gone"]);
  assert.deepEqual(TD.sort.rows(rows, column, "desc").map((row) => row.id),
    ["new", "old", "undated", "gone"]);
});
