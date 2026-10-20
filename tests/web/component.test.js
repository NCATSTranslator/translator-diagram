/*
  The Component view's pure parts: the one-line blurb under a component's
  name, the third-party text, the catalog edges, the picker's groups, the
  catalog file's address, and the whole page rendered as a string over a
  fixture.

  Rendering the page needs table.js, whose environment cell is the matrix's
  first row, and so core.js before both; TD.ui's glyphs and tooltip are
  stubbed because only the DOM half uses them. What still has no test is the
  DOM itself (#22): the picker's change, the click handler, focus.
*/

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const WEB = path.join(__dirname, "..", "..", "src", "translator_diagram", "web");

globalThis.TD = {};
vm.runInThisContext(fs.readFileSync(path.join(WEB, "core.js"), "utf8"), { filename: "core.js" });
globalThis.TD.ui = { CHEVRON: "", CARET_UP: "", CARET_DOWN: "", tooltip: { bind() {}, hide() {} } };
for (const file of ["table.js", "component.js"]) {
  vm.runInThisContext(fs.readFileSync(path.join(WEB, file), "utf8"), { filename: file });
}
const { blurbFor, thirdPartyText } = globalThis.TD.component;

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

// The TD component.js captured, taken at load (see index.js): deployedIn reads
// its ENVS, and a test body runs after a later suite has replaced the global.
const VIEW_TD = globalThis.TD;
const {
  catalogNeighbours, catalogUrls, deployedIn, docLabel, fieldState, pageHtml, pickerGroups,
  recordedSection, schemaFields, updatedHtml,
} = VIEW_TD.component;
const SCHEMA = JSON.parse(fs.readFileSync(
  path.join(__dirname, "..", "..", "catalog", "schema", "component.schema.json"), "utf8"));

test("catalog edges run with the data: into a consumer, out of what it consumes", () => {
  // Backwards once, and each list showed the other's components.
  const edges = [
    { from: "kp", to: "ars" }, { from: "ars", to: "ui" }, null, { from: "x", to: "y" },
  ];
  assert.deepEqual(catalogNeighbours(edges, "ars"), { consumes: ["kp"], consumedBy: ["ui"] });
  assert.deepEqual(catalogNeighbours(edges, "nobody"), { consumes: [], consumedBy: [] });
});

test("deployedIn names the environments running a release, from the cells", () => {
  VIEW_TD.ENVS = ["ci", "test", "prod"];
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

test("the last-updated note escapes its date, label and tag once", (t) => {
  // Escaped twice, an `&` showed as `&amp;` on the page (#87).
  const saved = VIEW_TD.DATA;
  t.after(() => { VIEW_TD.DATA = saved; });
  VIEW_TD.DATA = { updated_labels: { release: "Release & tag" } };
  const html = updatedHtml({ last_updated: { source: "release", tag: "v1<2", date: "2026<01" } });
  assert.match(html, /^2026&lt;01 <span class="cv-note">Release &amp; tag · v1&lt;2<\/span>$/);
  // A source with no label falls back to itself, and is escaped the same way.
  const fallback = updatedHtml({ last_updated: { source: "a&b" } });
  assert.match(fallback, /<span class="cv-note">a&amp;b<\/span>/);
  assert.doesNotMatch(html + fallback, /&amp;(amp|lt);/);
});

test("a component's catalog file is named by its id", () => {
  const urls = catalogUrls("arax");
  assert.equal(urls.view,
    "https://github.com/NCATSTranslator/translator-diagram/blob/main/catalog/components/arax.yaml");
  assert.equal(urls.edit,
    "https://github.com/NCATSTranslator/translator-diagram/edit/main/catalog/components/arax.yaml");
});

test("the picker groups components by stage, in the payload's order", () => {
  const groups = pickerGroups([
    { id: "a", step_label: "Step 1", step_title: "Front door" },
    { id: "b", step_label: "Step 1", step_title: "Front door" },
    { id: "c", step_label: "Step 2", step_title: "ARAs" },
    // The unplaced band's label is its title; it is said once.
    { id: "d", step_label: "Not yet placed", step_title: "Not yet placed" },
    { id: "e" },
  ]);
  assert.deepEqual(groups.map((g) => [g.label, g.rows.map((r) => r.id)]), [
    ["Step 1: Front door", ["a", "b"]],
    ["Step 2: ARAs", ["c"]],
    ["Not yet placed", ["d"]],
    ["", ["e"]],
  ]);
});

/* Every section of the page, over a row that fills most of them, renders
   without falling back to its "could not be rendered" line, and the matrix
   carries every document a fact was read from. */
const FULL = {
  id: "arax", name: "ARAX", owner: "CATRAX", step_label: "Step 2", step_title: "ARAs",
  summary: "An autonomous relay agent.", repository: "https://github.com/RTXteam/RTX",
  infores: "infores:arax", smartapi: "abc",
  smartapi_record: {
    registry_url: "https://smart-api.info/ui/abc", title: "ARAX", trapi: { version: "1.5" },
    servers: [{ maturity: "production", url: "https://arax.transltr.io/api/arax/v1.4" }],
    status: { uptime_status: "pass" }, meta: { source_url: "https://example.org/arax.yaml" },
  },
  releases_detail: [{ tag: "v1.6.2", url: "https://github.com/RTXteam/RTX/releases/tag/v1.6.2" }],
  helm_charts: [{ chart: "arax", source_url: "https://github.com/helxplatform/translator-devops" }],
  connections: { calls: ["ars"] },
  findings: [{ key: "no-chart", severity: "warning", about: "row", text: "hosted at ITRB with no chart" }],
  environments: {
    ci: { deployed: true, version: "1.6.2", version_source: "openapi",
      url: "https://arax.ci.transltr.io", openapi_url: "https://arax.ci.transltr.io/openapi.json",
      status_url: "https://arax.ci.transltr.io/status", trapi: "1.5", reachable: true,
      trapi_operations: ["lookup"], babel: "2025sep1", babel_source: "status",
      findings: [{ key: "document-error", severity: "severe", about: "reach", text: "answers HTTP 500" }] },
    prod: { deployed: false, reason: "no such host", reason_key: "no-such-host" },
  },
};

test("the page renders every section of a full row", (t) => {
  const saved = { DATA: VIEW_TD.DATA, state: VIEW_TD.state };
  t.after(() => { VIEW_TD.DATA = saved.DATA; VIEW_TD.state = saved.state; });
  VIEW_TD.boot({ rows: [FULL, { id: "ars", name: "ARS" }], environments: ["ci", "prod"] });
  VIEW_TD.state = { ...VIEW_TD.url.defaults(), view: "component", sel: "arax" };
  VIEW_TD.table.ensureColumns();
  const html = pageHtml("arax");
  assert.doesNotMatch(html, /could not be rendered/);
  for (const id of ["findings", "environments", "overview", "smartapi", "releases", "helm", "connections", "recorded"]) {
    assert.match(html, new RegExp(`id="cv-${id}"`), `no ${id} section`);
  }
  // Findings first, worst first, each saying where it was found.
  assert.ok(html.indexOf('id="cv-findings"') < html.indexOf('id="cv-environments"'));
  assert.match(html, /<h3 class="cv-fsev severe">severe<\/h3><ul class="cv-findings"><li>[^]*?<span\s+class="cv-fenv">ci<\/span><span>answers HTTP 500<\/span><\/li><\/ul><h3 class="cv-fsev warning">warning<\/h3>[^]*?<span\s+class="cv-fenv">component<\/span><span>hosted at ITRB with no chart<\/span>/);
  // The environment matrix carries the data pill and the glyph like the table.
  assert.match(html, /<span class="ax">Babel<\/span> 2025sep1/);
  assert.match(html, /class="dot down" data-tip="findings" data-id="arax" data-env="ci" data-about="reach" data-sev="all"/);
  assert.match(html, /<th scope="col">ci<\/th><th scope="col">prod<\/th>/);
  for (const url of ["https://arax.ci.transltr.io/openapi.json", "https://arax.ci.transltr.io/status",
    "https://smart-api.info/ui/abc", "catalog/components/arax.yaml"]) {
    assert.ok(html.includes(url), `no link to ${url}`);
  }
  assert.match(html, /<option value="arax" selected>ARAX<\/option>/);
});

test("an unknown or empty selection shows the picker and says why", (t) => {
  const saved = VIEW_TD.DATA;
  t.after(() => { VIEW_TD.DATA = saved; });
  VIEW_TD.boot({ rows: [FULL], environments: ["ci", "prod"] });
  assert.match(pageHtml("nope"), /No component has the id nope/);
  assert.match(pageHtml(""), /Choose a component above/);
  assert.match(pageHtml(""), /<option value="" selected disabled>/);
});

test("a component with nothing to report says so in its Findings section", (t) => {
  const saved = { DATA: VIEW_TD.DATA, state: VIEW_TD.state };
  t.after(() => { VIEW_TD.DATA = saved.DATA; VIEW_TD.state = saved.state; });
  VIEW_TD.boot({ rows: [{ id: "ars", name: "ARS", environments: {} }], environments: ["ci"] });
  VIEW_TD.state = { ...VIEW_TD.url.defaults(), view: "component", sel: "ars" };
  VIEW_TD.table.ensureColumns();
  assert.match(pageHtml("ars"), /id="cv-findings"[^]*?No findings: nothing this build checked disagrees/);
});

/* --- Recorded (from #51, 811826b) ------------------------------------------ */

const RECORDED = {
  id: "svc", name: "Service", owner: "Team", refactor_status: "Continues into Refactor",
  identifiers: { infores: "infores:svc", smartapi: "abc" },
  connections: { gets_results_from: ["other"], calls: ["third"], externals: [] },
  endpoints: { openapi: "openapi.json", status: null, extra: "x" },
  repositories: [{ url: "https://github.com/org/svc", role: "source", visibility: "public" }],
  environments: { ci: { url: "https://svc.ci.transltr.io/", location: "ITRB" } },
};

test("the schema flattens to one row per field, nested blocks one level deep", (t) => {
  const saved = VIEW_TD.ENVS;
  t.after(() => { VIEW_TD.ENVS = saved; });
  VIEW_TD.ENVS = ["dev", "ci", "test", "prod"];
  const fields = schemaFields(SCHEMA, RECORDED);
  const labels = fields.map((f) => f.label);
  for (const expected of ["id", "identifiers.infores", "itrb.app", "connections.calls",
    "endpoints.openapi", "environments.prod", "diagram.hide", "notes", "repositories"]) {
    assert.ok(labels.includes(expected), expected);
  }
  // A key the file has under a block the schema leaves open (endpoints).
  assert.ok(labels.includes("endpoints.extra"));
  // No block appears as a row of its own beside its keys.
  assert.ok(!labels.includes("identifiers"));
  assert.ok(!labels.includes("environments"));
  assert.equal(fields.find((f) => f.label === "id").required, true);
  assert.equal(fields.find((f) => f.label === "notes").required, false);
  // Schema order, so the page reads like the file.
  assert.ok(labels.indexOf("id") < labels.indexOf("identifiers.infores"));
  assert.ok(labels.indexOf("identifiers.infores") < labels.indexOf("notes"));
});

test("absent, null and empty are three different states", () => {
  assert.equal(fieldState(RECORDED, ["id"]).state, "recorded");
  assert.equal(fieldState(RECORDED, ["endpoints", "status"]).state, "none");
  assert.equal(fieldState(RECORDED, ["connections", "externals"]).state, "none");
  assert.equal(fieldState(RECORDED, ["description"]).state, "absent");
  assert.equal(fieldState(RECORDED, ["environments", "prod"]).state, "absent");
  assert.equal(fieldState(RECORDED, ["environments", "ci"]).state, "recorded");
});

test("the Recorded section counts, marks and links", (t) => {
  const saved = VIEW_TD.DATA;
  t.after(() => { VIEW_TD.DATA = saved; });
  VIEW_TD.boot({ rows: [], environments: ["ci", "prod"], component_schema: SCHEMA });
  const html = recordedSection({ id: "svc", recorded: RECORDED });
  for (const cls of ["cv-f-absent", "cv-f-none", "cv-f-recorded"]) assert.match(html, new RegExp(cls));
  assert.match(html, /\d+ of \d+ fields recorded/);
  assert.match(html, /not recorded/);
  assert.match(html, /checked: none/);
  assert.match(html, /catalog\/components\/svc\.yaml/);
  // Values render, URLs as links.
  assert.match(html, /href="https:\/\/github\.com\/org\/svc"/);
  assert.match(recordedSection({ id: "svc" }), /did not carry the component file/);
});

