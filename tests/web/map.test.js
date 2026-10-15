const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const ROOT = path.join(__dirname, "..", "..");
const MAP = path.join(ROOT, "src", "translator_diagram", "web", "map.js");

globalThis.TD = { fmt: { esc: String } };
vm.runInThisContext(fs.readFileSync(MAP, "utf8"), { filename: "map.js" });
const { nodeNameLimit } = TD.map;

test("a map node name reserves the measured category width and an 8px gap", () => {
  assert.equal(nodeNameLimit(188, 12), 146);
  assert.equal(nodeNameLimit(188, 0), 166);
});

test("an unexpectedly wide category cannot consume the whole node name", () => {
  assert.equal(nodeNameLimit(188, 999), 24);
});

// Taken at load, like nodeNameLimit above: by the time a test body runs, a
// later suite has swapped globalThis.TD, and ENVS must land on the TD map.js
// captured (see index.js).
const MAP_TD = globalThis.TD;
const { kindOf, versionOf, reachability, buckets } = MAP_TD.map;

test("an edge is one kind, and cross-cutting wins over planned", () => {
  assert.equal(kindOf({ kind: "calls", planned: true, crosscutting: true }), "crosscutting");
  assert.equal(kindOf({ kind: "calls", planned: true }), "planned");
  assert.equal(kindOf({ kind: "calls" }), "calls");
  assert.equal(kindOf({ kind: "results" }), "results");
  assert.equal(kindOf({ kind: "external_in" }), "externals");
  assert.equal(kindOf({ kind: "catalog" }), "catalog");
});

test("a node shows prod's version, else the furthest environment that reports one", () => {
  MAP_TD.ENVS = ["dev", "ci", "test", "prod"];
  const cell = (version) => ({ deployed: true, version });
  assert.equal(versionOf({ environments: { ci: cell("1.0"), prod: cell("2.0") } }), "2.0");
  assert.equal(versionOf({ environments: { dev: cell("1.0"), test: cell("1.5"), prod: { deployed: true } } }), "1.5");
  assert.equal(versionOf({ environments: { prod: { deployed: false, version: "9" } } }), "");
  assert.equal(versionOf({}), "");
});

test("one unreachable environment outranks three reachable ones", () => {
  MAP_TD.ENVS = ["ci", "test", "prod"];
  const r = (reachable) => ({ deployed: true, reachable });
  assert.equal(reachability({ environments: { ci: r(true), test: r(true), prod: r(false) } }), "bad");
  assert.equal(reachability({ environments: { ci: r(true) } }), "ok");
  assert.equal(reachability({ environments: { ci: { deployed: false, reachable: false } } }), "");
  assert.equal(reachability({ environments: { ci: { deployed: true } } }), "");
});

test("a node's edges sort into the four directions and the externals, by name", () => {
  const edges = [
    { kind: "results", from: "kp-b", to: "ars" },
    { kind: "results", from: "kp-a", to: "ars", planned: true },
    { kind: "results", from: "ars", to: "ui" },
    { kind: "calls", from: "ars", to: "appraiser" },
    { kind: "calls", from: "sdk", to: "ars" },
    { kind: "external_in", from: "Researcher", to: "ars" },
    { kind: "external_out", from: "ars", to: "Sink" },
    { kind: "external_in", from: "Other", to: "ui" },   // not this node's
  ];
  const found = buckets("ars", edges, (id) => id.toUpperCase());
  assert.deepEqual(found.from, [{ name: "KP-A", planned: true }, { name: "KP-B", planned: false }]);
  assert.deepEqual(found.to, [{ name: "UI", planned: false }]);
  assert.deepEqual(found.calls, [{ name: "APPRAISER", planned: false }]);
  assert.deepEqual(found.calledBy, [{ name: "SDK", planned: false }]);
  assert.deepEqual(found.extIn, [{ name: "Researcher", planned: false }]);
  assert.deepEqual(found.extOut, [{ name: "Sink", planned: false }]);
});
