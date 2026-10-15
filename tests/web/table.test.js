/*
  table.js's judgement, driven without a document: which rows a filter
  keeps, what a header click does to the sort, which bands are drawn, which
  detail fields survive, and what an environment cell says. The file reads
  TD.fmt and TD.sort when it loads, so core.js comes first; TD.ui's two
  glyphs are stubbed because the cells inline them.
*/

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const WEB = path.join(__dirname, "..", "..", "src", "translator_diagram", "web");

globalThis.TD = {};
vm.runInThisContext(fs.readFileSync(path.join(WEB, "core.js"), "utf8"), { filename: "core.js" });
globalThis.TD.ui = { CHEVRON: "", CARET_UP: "", tooltip: { bind() {}, hide() {} } };
vm.runInThisContext(fs.readFileSync(path.join(WEB, "table.js"), "utf8"), { filename: "table.js" });
const TD = globalThis.TD;
const { table } = TD;

const cell = (version, extra) => ({ deployed: true, version, ...extra });
const ROWS = [
  { id: "ars", name: "ARS", owner: "NCATS", step: 1, step_label: "Step 1", step_title: "Front door",
    environments: { ci: cell("1.0"), prod: cell("1.0") } },
  { id: "arax", name: "ARAX", owner: "CATRAX", step: 2, step_label: "Step 2", step_title: "ARAs",
    environments: { ci: cell("2.1", { drift: ["version"] }), prod: cell("2.0", { trapi: "1.5" }) } },
  { id: "ui", name: "UI", owner: "UI", step: 3, step_label: "Step 3", step_title: "Front end",
    environments: { prod: { deployed: true, reachable: true, reason: "no version endpoint to read", reason_key: "no-endpoint" } } },
];

function reset(patch) {
  TD.boot({ rows: ROWS, environments: ["ci", "prod"] });
  TD.state = { ...TD.url.defaults(), ...(patch || {}) };
  table.ensureColumns();
}

test("the search forgets a version when its environment leaves the payload", () => {
  reset({ q: "2.1" });
  assert.deepEqual(table.visibleRows().map((row) => row.id), ["arax"]);
  // The same row objects, booted without ci: the cached search text must not
  // still carry ci's version.
  TD.boot({ rows: ROWS, environments: ["prod"] });
  assert.deepEqual(table.visibleRows(), []);
});

test("the search matches ids, names and versions, case-insensitively", () => {
  reset({ q: "ARA" });
  assert.deepEqual(table.visibleRows().map((row) => row.id), ["arax"]);
  reset({ q: "2.0" });
  assert.deepEqual(table.visibleRows().map((row) => row.id), ["arax"]);
  reset({ q: "" });
  assert.equal(table.visibleRows().length, 3);
});

test("the owner filter and the version views narrow the rows", () => {
  reset({ owner: ["UI", "NCATS"] });
  assert.deepEqual(table.visibleRows().map((row) => row.id), ["ars", "ui"]);
  reset({ versions: "differ" });
  assert.deepEqual(table.visibleRows().map((row) => row.id), ["arax"]);
  reset({ versions: "none" });
  assert.deepEqual(table.visibleRows().map((row) => row.id), ["ui"]);
});

test("a header click cycles preferred direction, the other, then home", () => {
  reset();
  const owner = table.COLUMNS.find((column) => column.key === "owner");
  assert.deepEqual(table.nextSort({ sort: "", dir: "asc" }, owner), { sort: "owner", dir: "asc" });
  assert.deepEqual(table.nextSort({ sort: "owner", dir: "asc" }, owner), { dir: "desc" });
  assert.deepEqual(table.nextSort({ sort: "owner", dir: "desc" }, owner), { sort: "", dir: "asc" });
  // A column that prefers descending starts there.
  const desc = { key: "x", prefer: "desc" };
  assert.deepEqual(table.nextSort({ sort: "", dir: "asc" }, desc), { sort: "x", dir: "desc" });
  assert.deepEqual(table.nextSort({ sort: "x", dir: "desc" }, desc), { dir: "asc" });
});

test("stage order draws a band per step present, and never an empty one", () => {
  reset();
  const html = table.bodyHtml(table.visibleRows().filter((row) => row.id !== "arax"));
  const bands = [...html.matchAll(/class="band" data-step="([^"]+)"/g)].map((m) => m[1]);
  assert.deepEqual(bands, ["Step 1", "Step 3"]);
  assert.match(html, /Front door/);
  assert.doesNotMatch(html, /ARAs/);
});

test("a sort by date draws no bands, and no rows draws the empty message", () => {
  reset({ sort: "updated", dir: "asc" });
  assert.doesNotMatch(table.bodyHtml(table.visibleRows()), /class="band"/);
  assert.match(table.bodyHtml([]), /No components match these filters/);
});

test("an expanded row shows only the fields some environment answered", () => {
  reset();
  const arax = table.detailRowsHtml(ROWS[1], "Step 2", true);
  assert.match(arax, /TRAPI/);
  assert.doesNotMatch(arax, /Biolink/);
  const ars = table.detailRowsHtml(ROWS[0], "Step 1", true);
  assert.match(ars, /Nothing else is recorded/);
});

test("an environment cell says why it has no version, and marks drift", () => {
  reset();
  assert.match(table.envCell(ROWS[2], "prod"), /no version endpoint to read/);
  assert.match(table.envCell(ROWS[2], "prod"), /dot up/);
  assert.match(table.envCell(ROWS[2], "ci"), /class="env absent"/);
  const drifting = table.envCell(ROWS[1], "ci");
  assert.match(drifting, /class="env drift"/);
  assert.match(drifting, /aria-label="disagrees with the row"/);
  assert.doesNotMatch(table.envCell(ROWS[1], "prod"), /drift/);
});
