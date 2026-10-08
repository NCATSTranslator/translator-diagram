/*
  The drawer's one-line blurb under a component's name.

  drawer.js is otherwise uncovered (#22): it builds DOM and listens on the
  document, so only its pure helpers are reachable from node. Loading it needs
  core.js first, because it reads TD.fmt when it loads, and two stubs for the
  listeners it registers at load; its boot microtask finds no TD.state and
  returns.
*/

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const WEB = path.join(__dirname, "..", "..", "src", "translator_diagram", "web");

globalThis.TD = {};
globalThis.document = globalThis.document || { addEventListener() {} };
globalThis.addEventListener = globalThis.addEventListener || (() => {});
for (const file of ["core.js", "drawer.js"]) {
  vm.runInThisContext(fs.readFileSync(path.join(WEB, file), "utf8"), { filename: file });
}
const { blurbFor } = globalThis.TD.drawer;

const repo = { repository_meta: { description: "Code from a previous collaborator" } };

test("the catalog's summary wins over the repository's GitHub description", () => {
  assert.equal(blurbFor({ ...repo, summary: "Looks up PubMed metadata." }), "Looks up PubMed metadata.");
});

test("without a summary, the repository's description is the blurb", () => {
  assert.equal(blurbFor(repo), "Code from a previous collaborator");
  // An empty summary is no summary, not a reason to show nothing.
  assert.equal(blurbFor({ ...repo, summary: "" }), "Code from a previous collaborator");
  assert.equal(blurbFor({ ...repo, summary: null }), "Code from a previous collaborator");
});

test("with neither there is no blurb, and a missing block is not an error", () => {
  assert.equal(blurbFor({}), "");
  assert.equal(blurbFor({ repository_meta: null }), "");
  assert.equal(blurbFor(undefined), "");
});
