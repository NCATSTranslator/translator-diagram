const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const ROOT = path.join(__dirname, "..", "..");
const MAP = path.join(ROOT, "src", "translator_diagram", "web", "map.js");

globalThis.TD = { fmt: { esc: String } };
vm.runInThisContext(fs.readFileSync(MAP, "utf8"), { filename: "map.js" });

test("a map node name reserves the measured category width and an 8px gap", () => {
  assert.equal(TD.map.nodeNameLimit(188, 12), 146);
  assert.equal(TD.map.nodeNameLimit(188, 0), 166);
});

test("an unexpectedly wide category cannot consume the whole node name", () => {
  assert.equal(TD.map.nodeNameLimit(188, 999), 24);
});
