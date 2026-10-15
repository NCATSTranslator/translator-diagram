/*
  TD.row: what every view says about a row the same way. The table, the
  drawer and the map each used to carry a copy of these; one copy, tested.
*/

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const CORE = path.join(__dirname, "..", "..", "src", "translator_diagram", "web", "core.js");

globalThis.TD = {};
vm.runInThisContext(fs.readFileSync(CORE, "utf8"), { filename: "core.js" });
const { boot, row } = globalThis.TD;

test("byId finds a row by id, and null for an id nothing has", () => {
  boot({ rows: [{ id: "ars", name: "ARS" }, { id: "arax", name: "ARAX" }] });
  assert.equal(row.byId("arax").name, "ARAX");
  assert.equal(row.byId("nope"), null);
});

test("byId follows the payload, not the first one it saw", () => {
  boot({ rows: [{ id: "a" }] });
  assert.ok(row.byId("a"));
  boot({ rows: [{ id: "b" }] });
  assert.equal(row.byId("a"), null);
  assert.ok(row.byId("b"));
});

test("a repository label is the owner/name of a GitHub URL, else the text", () => {
  assert.equal(row.repoLabel("https://github.com/NCATSTranslator/ARS"), "NCATSTranslator/ARS");
  assert.equal(row.repoLabel("https://example.org/x"), "https://example.org/x");
  assert.equal(row.repoLabel(null), "");
});

test("the last-updated label comes from the payload, falling back to the key", () => {
  boot({ updated_labels: { release: "GitHub release" } });
  assert.equal(row.updatedLabel({ source: "release" }), "GitHub release");
  assert.equal(row.updatedLabel({ source: "registry" }), "registry");
});

test("an external's arrow points the way the data flows", () => {
  assert.equal(row.arrow("in"), "◀");
  assert.equal(row.arrow("out"), "▶");
});

test("reachability has three states, and never contacted is not down", () => {
  assert.equal(row.reach({ reachable: true }), "up");
  assert.equal(row.reach({ reachable: false }), "down");
  assert.equal(row.reach({ reachable: null }), "");
  assert.equal(row.reach({}), "");
  assert.equal(row.reach(undefined), "");
});

test("an owner label carries the coin and the escaped name", () => {
  boot({ owner_styles: {} });
  const html = row.ownerLabel("A&B");
  assert.ok(html.startsWith('<span class="ownercell"><span class="coin"'));
  assert.ok(html.endsWith("<span>A&amp;B</span></span>"));
});
