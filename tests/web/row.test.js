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
const { boot, row, cell } = globalThis.TD;

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

/* --- TD.cell: one model of an environment cell ----------------------------- */

const LIVE = {
  id: "svc", smartapi_record: { registry_url: "https://smart-api.info/ui/abc" },
  helm_charts: [{ source_url: "https://github.com/x/devops/tree/develop/helm/svc" }],
  otel_presence: [{ service: "Svc", seen_in: ["ci"] }],
  environments: {
    ci: { deployed: true, version: "1.2.0", version_source: "openapi", reachable: true,
          url: "https://svc.ci.transltr.io/", openapi_url: "https://svc.ci.transltr.io/openapi.json",
          status_url: "https://svc.ci.transltr.io/status",
          trapi: "1.6.0", trapi_source: "openapi", data_release: "babel 2025sep1",
          babel: "2025sep1", babel_source: "status", babel_url: "https://example.org/babel/2025sep1",
          biolink: "v4.4.3", biolink_source: "status", biolink_declared: "4.4.2",
          findings: [{ key: "biolink-mismatch", severity: "moderate", about: "biolink",
            text: "loads Biolink v4.4.3 but its API document declares 4.4.2" }],
          document: "version", http_status: 200, root_status: 200, paths_count: 5,
          trapi_operations: ["lookup", "overlay"], asyncquery: false,
          recent_queries: { count: 1200, p50_ms: 10.5, p95_ms: 80 } },
    test: { deployed: true, version: "1.1.0", version_source: "smartapi", reachable: false,
            url: "https://svc.test.transltr.io/", drift: ["version", "trapi"], unregistered: true },
    prod: { deployed: false, reason: "no such host", reason_key: "no-such-host" },
  },
};

test("a live cell links its version to the document it was read from", () => {
  boot({ source_labels: { openapi: "OpenAPI" } });
  const m = cell(LIVE, "ci");
  assert.equal(m.deployed, true);
  assert.equal(m.version, "1.2.0");
  assert.equal(m.live, true);
  assert.equal(m.href, "https://svc.ci.transltr.io/openapi.json");
  assert.equal(m.sourceLabel, "OpenAPI");
  assert.equal(m.sourceWord, "its API document");
  assert.equal(m.sourceShort, "API");
  assert.equal(m.reach, "up");
  assert.deepEqual(m.drift, []);
  assert.equal(m.dataRelease, "babel 2025sep1");
  // The data axes, in the payload's order, each linking to the document
  // that names it, else to the document its source was read from.
  assert.deepEqual(m.data, [
    { axis: "babel", label: "Babel", version: "2025sep1", source: "status",
      href: "https://example.org/babel/2025sep1", drift: false },
    { axis: "biolink", label: "Biolink", version: "v4.4.3", source: "status",
      href: "https://svc.ci.transltr.io/status", drift: false },
  ]);
  assert.deepEqual(m.findings.map((f) => f.key), ["biolink-mismatch"]);
  assert.deepEqual(m.facts.map((f) => f.label), [
    "TRAPI", "Babel", "Biolink", "Host", "API document", "Root URL", "Paths",
    "Operations", "Async query", "Recent queries", "Telemetry",
  ]);
  // Every fact explains where it comes from, for the (?) beside its label.
  assert.ok(m.facts.every((f) => typeof f.about === "string" && f.about.length > 20));
  const byLabel = Object.fromEntries(m.facts.map((f) => [f.label, f]));
  assert.equal(byLabel.Host.value, "svc.ci.transltr.io");
  assert.equal(byLabel.Host.href, "https://svc.ci.transltr.io/");
  assert.equal(byLabel["API document"].note, "HTTP 200");
  assert.equal(byLabel.Operations.value, "2");
  assert.equal(byLabel["Async query"].value, "no");
  assert.equal(byLabel["Recent queries"].value, "1,200 queries · p50 10.5 ms · p95 80 ms");
  assert.equal(byLabel.Telemetry.value, "Svc");
});

test("the axes come from the payload, and an absent one is not drawn", () => {
  boot({ data_axes: { graph: "Translator Graph", babel: "Babel" } });
  const m = cell({ environments: { ci: { deployed: true, babel: "x", drift: ["babel"] } } }, "ci");
  assert.deepEqual(m.data.map((d) => [d.axis, d.drift]), [["babel", true]]);
  assert.equal(m.facts.find((f) => f.label === "Babel").value, "x");
});

test("findings are drawn as one glyph per severity at an anchor, and listed worst first", () => {
  boot({});
  const findings = [
    { key: "a", severity: "warning", about: "version", text: "w1" },
    { key: "b", severity: "severe", about: "version", text: "s1" },
    { key: "c", severity: "warning", about: "version", text: "w2" },
    { key: "d", severity: "moderate", about: "reach", text: "m1" },
  ];
  const html = TD.findings.marks(findings, { id: "svc", env: "ci", about: "version" });
  const buttons = [...html.matchAll(/class="fg (\w+)"[^>]*aria-label="([^"]+)"/g)].map((m) => [m[1], m[2]]);
  assert.deepEqual(buttons, [["severe", "1 severe finding"], ["warning", "2 warning findings"]]);
  assert.match(html, /data-tip="findings" data-id="svc" data-env="ci" data-about="version" data-sev="severe"/);
  assert.equal(TD.findings.marks(findings, { id: "svc", env: "ci", about: "babel" }), "");
  assert.deepEqual(TD.findings.at(findings, "version", "warning").map((f) => f.text), ["w1", "w2"]);
  const row = { findings: [{ key: "r", severity: "moderate", about: "row", text: "row-level" }],
    environments: { ci: { deployed: true, findings: findings.slice(0, 1) } } };
  assert.deepEqual(TD.findings.all(row, ["ci", "prod"]).map((f) => [f.env, f.text]),
    [["", "row-level"], ["ci", "w1"]]);
  assert.deepEqual(TD.findings.all({}, ["ci"]), []);
});

test("a registry-copied cell is not live, links to the record, and carries its flags", () => {
  boot({});
  const m = cell(LIVE, "test");
  assert.equal(m.live, false);
  assert.equal(m.href, "https://smart-api.info/ui/abc");
  assert.equal(m.reach, "down");
  assert.deepEqual(m.drift, ["version", "trapi"]);
  assert.deepEqual(m.flags, { inferred: false, unregistered: true });
  // Telemetry was seen in ci only.
  assert.ok(!m.facts.some((f) => f.label === "Telemetry"));
});

test("an undeployed cell says why, and whether the absence is a known one", () => {
  boot({});
  const prod = cell(LIVE, "prod");
  assert.equal(prod.deployed, false);
  assert.equal(prod.reason, "no such host");
  assert.equal(prod.reasonKey, "no-such-host");
  assert.equal(prod.knownAbsent, true);
  assert.deepEqual(prod.facts, []);
  const gap = cell({ environments: { dev: { deployed: false, reason: "no address on file", reason_key: "no-host" } } }, "dev");
  assert.equal(gap.knownAbsent, false);
});

test("a missing environment, or a missing row, is an undeployed cell with no facts", () => {
  boot({});
  for (const m of [cell(LIVE, "dev"), cell({}, "ci"), cell(null, "ci")]) {
    assert.equal(m.deployed, false);
    assert.equal(m.version, "");
    assert.equal(m.href, "");
    assert.deepEqual(m.facts, []);
  }
});

test("a helm-sourced version links to the chart, and a non-http host never links", () => {
  boot({});
  const row = { helm_charts: [{ source_url: "https://github.com/x/devops/tree/develop/helm/svc" }],
    environments: { dev: { deployed: true, version: "2.0", version_source: "helm", url: "ftp://evil.example/" } } };
  const m = cell(row, "dev");
  assert.equal(m.href, "https://github.com/x/devops/tree/develop/helm/svc");
  assert.equal(m.facts.find((f) => f.label === "Host").href, "");
});
