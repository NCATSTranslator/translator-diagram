/*
  web/detail.js under node: the six panel renderers and the header, driven
  over a row with everything in it, a row with nothing in it, and — when a
  build is lying about — every row of the real overview.json.

  The contract under test is the one the file comment states: every value is
  optional, so no renderer may throw on an absent block, and a fact is shown
  with its provenance. Both the drawer and the component page render through
  these functions, which is why they are tested here rather than through
  either surface.
*/

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const ROOT = path.join(__dirname, "..", "..");
const WEB = path.join(ROOT, "src", "translator_diagram", "web");

/* The same lookup layout.test.js uses: the private build first, since it has
   every component in it, then the published one. Neither present is fine. */
function realPayload() {
  const candidates = [
    path.join(ROOT, "data", "dashboard-private", "overview.json"),
    path.join(ROOT, "data", "dashboard", "overview.json"),
  ];
  for (const file of candidates) {
    try {
      const data = JSON.parse(fs.readFileSync(file, "utf8"));
      if (Array.isArray(data.rows) && data.rows.length) return { file, data };
    } catch { /* not built, or half-written by a build running right now */ }
  }
  return null;
}

// controls.js is not loaded (it builds elements); the two glyphs detail.js
// reads off it are stubbed before core.js runs, which keeps `TD` as the same
// object core.js then extends.
globalThis.TD = { ui: { CHEVRON: "<svg/>", CARET_DOWN: "<svg/>" } };
for (const name of ["core.js", "detail.js", "component.js"]) {
  vm.runInThisContext(fs.readFileSync(path.join(WEB, name), "utf8"), { filename: name });
}
const TD = globalThis.TD;

const FULL = {
  id: "svc",
  name: "Service",
  owner: "Team",
  refactor_status: "Continues into Refactor",
  hosted_at: "ITRB",
  component_type: "Utility",
  layer: "Shared services",
  step_label: "Step 3",
  step_title: "Middle",
  step_description: "where it sits",
  infores: "infores:svc",
  smartapi: "abc",
  chart_names: ["svc"],
  otel_services: ["Svc", "svc-worker"],
  otel_presence: [{ service: "Svc", seen_in: ["ci", "prod"] }],
  translator_all_wiki: "Service",
  itrb: { app: "svc", group: "SRI" },
  repository: "https://github.com/org/svc",
  repositories: [{ url: "https://github.com/org/svc", role: "source", visibility: "public" }],
  docs: [{ url: "https://example.org/docs/svc", kind: "technical-documentation" }],
  endpoints: { openapi: "openapi.json", status: null },
  last_updated: { at: "2026-09-01T00:00:00Z", date: "2026-09-01", source: "release", tag: "v1.2.0" },
  uptime: "pass",
  notes: "A note.",
  externals: [{ direction: "out", name: "User" }],
  connections: {
    gets_results_from: ["other"], calls: ["third"],
    planned_gets_results_from: [], planned_calls: ["fourth"],
  },
  releases_detail: [
    { tag: "v1.2.0", name: "One point two", url: "https://github.com/org/svc/releases/v1.2.0",
      published: "2026-09-01", prerelease: false, author: "someone", body_excerpt: "Fixes.", deployed: true },
  ],
  helm_status: "recorded",
  helm_charts: [{ chart: "svc", chart_version: "0.1.0", app_version: "1.2.0", description: "the chart",
    source_url: "https://github.com/helxplatform/translator-devops/tree/develop/helm/svc",
    services: [{ name: "web", replicas: 2, requests: { cpu: "500m", memory: "1Gi" } }],
    storage: [], dependencies: [], ingress_hosts: [] }],
  smartapi_record: { id: "abc", registry_url: "https://smart-api.info/ui/abc", title: "Service API",
    version: "1.2.0", team: ["Team"], component: "Utility", infores: "infores:svc",
    trapi: { version: "1.5.0", asyncquery: true, operations: ["lookup"] },
    servers: [{ url: "https://svc.transltr.io", maturity: "production" }],
    status: { uptime_status: "pass" }, meta: {}, tags: ["translator"], matched_by: "id" },
  repository_meta: { description: "Does a thing.", default_branch: "main", pushed_at: "2026-09-01T00:00:00Z",
    license: "MIT", topics: ["ncats-translator"], open_issues: 3, stars: 4 },
  catalog: { status: "released", knowledge_level: "knowledge_assertion", agent_type: "manual_agent" },
  derived_rejected: [{ env: "dev", url: "https://svc.dev.transltr.io/" }],
  environments: {
    dev: { deployed: false, reason: "not in registry for dev" },
    ci: { deployed: true, url: "https://svc.ci.transltr.io/", version: "1.2.0", version_source: "openapi",
      http_status: 200, reachable: true, trapi: "1.5.0", trapi_source: "openapi", release_tag: "v1.2.0",
      released: "2026-09-01", paths_count: 5, drift: [] },
    test: { deployed: true, url: "https://svc.test.transltr.io/", version: "1.1.0", version_source: "smartapi",
      root_status: 200, reachable: true, drift: ["version"], unregistered: true },
    prod: { deployed: true, url: "https://svc.transltr.io/", version: null, version_source: null,
      reason: "up · document has no version", document: "no-version", reachable: true },
  },
};

const OTHER = { id: "other", name: "Other", owner: "Team", connections: { calls: ["svc"] }, environments: {} };
const THIRD = { id: "third", name: "Third", owner: "Team", connections: {}, environments: {} };
const EMPTY = { id: "bare" };

const SCHEMA = JSON.parse(fs.readFileSync(path.join(ROOT, "schema", "component.schema.json"), "utf8"));

FULL.recorded = {
  id: "svc", name: "Service", owner: "Team", refactor_status: "Continues into Refactor",
  identifiers: { infores: "infores:svc", smartapi: "abc" },
  connections: { gets_results_from: ["other"], calls: ["third"], externals: [] },
  endpoints: { openapi: "openapi.json", status: null, extra: "x" },
  repositories: [{ url: "https://github.com/org/svc", role: "source", visibility: "public" }],
  environments: { ci: { url: "https://svc.ci.transltr.io/", location: "ITRB" } },
};

const PAYLOAD = {
  environments: ["dev", "ci", "test", "prod"],
  owner_styles: {},
  updated_labels: { release: "release", registry: "registry" },
  catalog_edges: [{ from: "other", to: "svc", kind: "catalog" }],
  component_schema: SCHEMA,
  unknown: [
    { kind: "otel_services", name: "svc-legacy", status: "not-recorded", component: "svc" },
    { kind: "otel_services", name: "mystery", status: "unattributed", component: null },
  ],
  redacted: { components: 2, fields: [], environment_fields: [], mentions: 0 },
  repo_url: "https://github.com/org/repo",
  rows: [FULL, OTHER, THIRD, EMPTY],
};
TD.boot(PAYLOAD);

const PANEL_IDS = ["overview", "environments", "releases", "helm", "smartapi", "connections"];

test("the tab list and the panel table agree", () => {
  assert.deepEqual(TD.detail.TABS.map((tab) => tab.id), PANEL_IDS);
  assert.deepEqual(Object.keys(TD.detail.panels).sort(), PANEL_IDS.slice().sort());
  assert.equal(TD.detail.DEFAULT_TAB, "overview");
});

test("every panel renders a full row and names what it shows", () => {
  const html = Object.fromEntries(PANEL_IDS.map((id) => [id, TD.detail.panels[id](FULL)]));
  for (const id of PANEL_IDS) assert.equal(typeof html[id], "string", id);
  assert.match(html.overview, /infores:svc/);
  assert.match(html.overview, /Step 3/);
  assert.match(html.environments, /1\.2\.0/);
  // A drifting version says so in words, not only in colour.
  assert.match(html.environments, /disagrees with the rest of this row: version/);
  // A cell with no version carries the payload's own reason.
  assert.match(html.environments, /document has no version/);
  assert.match(html.environments, /not in registry for dev/);
  assert.match(html.releases, /v1\.2\.0/);
  assert.match(html.helm, /0\.1\.0/);
  assert.match(html.smartapi, /Service API/);
  assert.match(html.connections, /Gets results from/);
  assert.match(html.connections, /Called by/);
  // The catalog's edge is shown as the catalog's, beside the recorded graph.
  assert.match(html.connections, /Catalog says/);
});

test("a fact is never shown without its provenance", () => {
  const env = TD.detail.panels.environments(FULL);
  assert.match(env, /data-src="openapi"/);
  assert.match(env, /absent from the SmartAPI record/);
  assert.match(env, /root path, not its document/);
  assert.match(env, /a conventional hostname that did not confirm/);
  const overview = TD.detail.panels.overview(FULL);
  assert.match(overview, /from SmartAPI, whole record/);
});

test("every panel survives a row with nothing in it", () => {
  for (const id of PANEL_IDS) {
    const html = TD.detail.panels[id](EMPTY);
    assert.equal(typeof html, "string", id);
  }
  assert.match(TD.detail.panels.smartapi(EMPTY), /Not registered in SmartAPI/);
  assert.match(TD.detail.panels.connections(EMPTY), /None recorded/);
});

test("the header carries a close button only when asked", () => {
  const plain = TD.detail.header(FULL);
  const closable = TD.detail.header(FULL, { close: true });
  assert.doesNotMatch(plain, /dw-close/);
  assert.match(closable, /dw-close/);
  assert.match(plain, /Service/);
  assert.match(plain, /Does a thing\./);
  assert.match(plain, /Continues into Refactor · ITRB · Utility · Shared services/);
});

test("the header's links are the external ones the row records", () => {
  const links = TD.detail.links(FULL);
  assert.match(links, /Repository/);
  assert.match(links, /SmartAPI registry/);
  assert.match(links, /Helm chart/);
  assert.match(links, /Wiki/);
  assert.equal(TD.detail.links(EMPTY), "");
});

test("values are escaped on the way out", () => {
  const nasty = { id: "x", name: "<img src=x onerror=alert(1)>", owner: "T", notes: "<b>bold</b>" };
  const html = TD.detail.header(nasty) + TD.detail.panels.overview(nasty);
  assert.doesNotMatch(html, /<img/);
  assert.doesNotMatch(html, /<b>/);
  assert.match(html, /&lt;img/);
});

const real = realPayload();
test(`every panel renders every row of ${real ? path.relative(ROOT, real.file) : "(no build present)"}`,
  { skip: !real }, () => {
    TD.boot(real.data);
    for (const row of real.data.rows) {
      for (const id of PANEL_IDS) {
        const html = TD.detail.panels[id](row);
        assert.equal(typeof html, "string", `${row.id} ${id}`);
      }
      assert.equal(typeof TD.detail.header(row), "string", row.id);
    }
    TD.boot(PAYLOAD);
  });

/* The drawer's per-environment list and the page's matrix are two layouts of
   `envFields`, so what one shows the other must show. */
test("envFields is empty for an environment with no deployment", () => {
  assert.deepEqual(TD.detail.envFields(FULL, "dev"), []);
  assert.deepEqual(TD.detail.envFields(EMPTY, "prod"), []);
});

test("the environments panel is envFields laid out per environment", () => {
  const panel = TD.detail.panels.environments(FULL);
  for (const field of TD.detail.envFields(FULL, "ci")) {
    if (field.html) assert.match(panel, new RegExp(`<dt>${field.label}</dt>`), field.label);
  }
  // Version is `always`: the environment with no version still gets the row.
  const prod = TD.detail.envFields(FULL, "prod").find((f) => f.label === "Version");
  assert.equal(prod.always, true);
});

test("the matrix has a column per environment and a row per fact any of them reports", () => {
  const html = TD.detail.envMatrix(FULL);
  for (const env of ["dev", "ci", "test", "prod"]) assert.match(html, new RegExp(`<th>${env}</th>`));
  const labels = new Set();
  for (const env of ["ci", "test", "prod"]) {
    for (const f of TD.detail.envFields(FULL, env)) if (f.html) labels.add(f.label);
  }
  for (const label of labels) {
    const hits = html.split(`<th scope="row">${label}</th>`).length - 1;
    assert.equal(hits, 1, `${label} appears ${hits} times`);
  }
  // The undeployed environment's reason is in the caption row, not lost.
  assert.match(html, /not in registry for dev/);
  // An environment with nothing to say on a row gets a dash, not a blank.
  assert.match(html, /<span class="dash">—<\/span>/);
  // The probed-not-confirmed hosts travel with the matrix.
  assert.match(html, /Probed, not confirmed/);
});

test("the matrix over a row with nothing deployed still names every environment", () => {
  const html = TD.detail.envMatrix(EMPTY);
  for (const env of ["dev", "ci", "test", "prod"]) assert.match(html, new RegExp(`<th>${env}</th>`));
  assert.match(html, /Not deployed\./);
});

/* --- The component page (component.js) ---------------------------------- */

test("the schema flattens to one row per field, nested blocks one level deep", () => {
  const fields = TD.component.schemaFields(SCHEMA, FULL.recorded);
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
  const r = FULL.recorded;
  assert.equal(TD.component.fieldState(r, ["id"]).state, "recorded");
  assert.equal(TD.component.fieldState(r, ["endpoints", "status"]).state, "none");
  assert.equal(TD.component.fieldState(r, ["connections", "externals"]).state, "none");
  assert.equal(TD.component.fieldState(r, ["description"]).state, "absent");
  assert.equal(TD.component.fieldState(r, ["environments", "prod"]).state, "absent");
  assert.equal(TD.component.fieldState(r, ["environments", "ci"]).state, "recorded");
});

test("the Recorded section counts, marks and links", () => {
  const html = TD.component.recordedSection(FULL);
  assert.match(html, /cp-f-absent/);
  assert.match(html, /cp-f-none/);
  assert.match(html, /cp-f-recorded/);
  assert.match(html, /of \d+ fields recorded/);
  assert.match(html, /not recorded/);
  assert.match(html, /checked: none/);
  assert.match(html, /components\/svc\.yaml/);
  // Values render, URLs as links, and are escaped.
  assert.match(html, /href="https:\/\/github\.com\/org\/svc"/);
  assert.equal(TD.component.recordedSection(EMPTY), TD.detail.helpers.muted("This build did not carry the component file."));
});

test("the page has every section and the file links", () => {
  const html = TD.component.page(FULL);
  for (const id of ["identity", "environments", "releases", "helm", "smartapi", "connections", "recorded"]) {
    assert.match(html, new RegExp(`<section class="cp-sec" id="${id}"`), id);
  }
  assert.match(html, /<h1>Service<\/h1>/);
  assert.match(html, /https:\/\/github\.com\/org\/repo\/blob\/main\/components\/svc\.yaml/);
  assert.match(html, /https:\/\/github\.com\/org\/repo\/edit\/main\/components\/svc\.yaml/);
  assert.match(html, /data-copy="svc"/);
  assert.match(html, /data-map="svc"/);
  assert.doesNotMatch(html, /dw-close/);
});

test("an unknown id resolves case-insensitively or not at all", () => {
  assert.equal(TD.component.resolve("SVC").id, "svc");
  assert.equal(TD.component.resolve("nope"), null);
  assert.equal(TD.component.resolve(""), null);
});

test("near matches reach through every naming space a row carries", () => {
  const ids = (q) => TD.component.nearMatches(q).map((r) => r.id);
  assert.deepEqual(ids("svc-worker"), ["svc"]);      // an OTel service name
  assert.deepEqual(ids("infores:svc"), ["svc"]);     // the infores CURIE
  assert.deepEqual(ids("abc"), ["svc"]);             // the SmartAPI id
  assert.deepEqual(ids("serv"), ["svc"]);            // part of the name
  assert.deepEqual(ids("zzz"), []);
});

test("the not-found page offers what it knows and names no withheld component", () => {
  const html = TD.component.notFound("svc-legacy");
  assert.match(html, /No component with the id/);
  assert.match(html, /Seen in the platform/);
  assert.match(html, /not-recorded/);
  // The entry's component resolves, so it is a link to the page.
  assert.match(html, /data-go="svc"/);
  assert.match(html, /leaves out 2 components/);
  assert.match(html, /components\/ on GitHub/);
  const nothing = TD.component.notFound("<script>x</script>");
  assert.doesNotMatch(nothing, /<script>/);
  assert.match(nothing, /&lt;script&gt;/);
  assert.doesNotMatch(nothing, /Did you mean/);
});
