/*
  The drawer's one-line blurb under a component's name, and the name of the
  third-party software a component deploys.

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
const { blurbFor, thirdPartyText } = globalThis.TD.drawer;

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

test("third-party software is named from its block, and only then", () => {
  assert.equal(thirdPartyText({ third_party: { software: "Jaeger", url: "https://x/" } }), "Jaeger");
  // The url is optional; the name is what the header and the map show.
  assert.equal(thirdPartyText({ third_party: { software: "MongoDB" } }), "MongoDB");
});

test("our own code has no third-party text", () => {
  assert.equal(thirdPartyText({ third_party: null }), "");
  assert.equal(thirdPartyText({}), "");
  assert.equal(thirdPartyText({ third_party: { software: "" } }), "");
  assert.equal(thirdPartyText(undefined), "");
});

// The TD drawer.js captured, taken at load (see index.js): deployedIn reads
// its ENVS, and a test body runs after a later suite has replaced the global.
const DRAWER_TD = globalThis.TD;
const { catalogNeighbours, deployedIn, docLabel, probeEvidence, updatedHtml } = DRAWER_TD.drawer;

test("catalog edges run with the data: into a consumer, out of what it consumes", () => {
  // Backwards once, and each list showed the other's components.
  const edges = [
    { from: "kp", to: "ars" }, { from: "ars", to: "ui" }, null, { from: "x", to: "y" },
  ];
  assert.deepEqual(catalogNeighbours(edges, "ars"), { consumes: ["kp"], consumedBy: ["ui"] });
  assert.deepEqual(catalogNeighbours(edges, "nobody"), { consumes: [], consumedBy: [] });
});

test("deployedIn names the environments running a release, from the cells", () => {
  DRAWER_TD.ENVS = ["ci", "test", "prod"];
  const row = { environments: {
    ci: { deployed: true, release_tag: "v2" },
    test: { deployed: true, release_tag: "v1" },
    prod: { deployed: false, release_tag: "v2" },
  } };
  assert.deepEqual(deployedIn(row, { tag: "v2" }), ["ci"]);
  // The Python side's flag with no cell naming the tag: deployed, but where
  // is unknown. Neither flag nor cell: not deployed.
  assert.deepEqual(deployedIn(row, { tag: "v3", deployed: true }), []);
  assert.equal(deployedIn(row, { tag: "v3" }), null);
});

test("a documentation label is the host and the page, not just github.com", () => {
  assert.equal(docLabel("https://github.com/NCATSTranslator/ARS/wiki/Home"), "github.com / Home");
  assert.equal(docLabel("https://example.org/docs/a%20b"), "example.org / a b");
  assert.equal(docLabel("https://example.org/"), "example.org");
});

test("the dot sits on the row that is the actual evidence", () => {
  assert.deepEqual(probeEvidence({ http_status: 404, root_status: 200, reachable: true }), { row: "http", status: 404 });
  assert.deepEqual(probeEvidence({ root_status: 200, reachable: true }), { row: "root", status: 200 });
  assert.deepEqual(probeEvidence({ reachable: false }), { row: "reachable", status: null });
  assert.deepEqual(probeEvidence({}), { row: null, status: null });
});

test("the last-updated note escapes its label and tag once", () => {
  // Escaped twice, an `&` showed as `&amp;` on the page (#87).
  DRAWER_TD.DATA = { updated_labels: { release: "Release & tag" } };
  const html = updatedHtml({ last_updated: { source: "release", tag: "v1<2", date: "2026-01-02" } });
  assert.match(html, /<span class="dw-note">Release &amp; tag · v1&lt;2<\/span>/);
  assert.doesNotMatch(html, /&amp;(amp|lt);/);
});
