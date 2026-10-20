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
    smartapi_record: { id: "abc" }, repository: "https://github.com/x/ars",
    releases_detail: [{ tag: "v1.0", url: "https://github.com/x/ars/releases/tag/v1.0", deployed: true }],
    environments: { ci: cell("1.0"), prod: cell("1.0", { reachable: false }) } },
  { id: "arax", name: "ARAX", owner: "CATRAX", step: 2, step_label: "Step 2", step_title: "ARAs",
    smartapi_record: { id: "def" },
    environments: {
      ci: cell("2.1", { drift: ["version"], unregistered: true,
        findings: [{ key: "unregistered", severity: "warning", about: "version", text: "deployed, but absent" }] }),
      prod: cell("2.0", { trapi: "1.5" }) } },
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
  reset({ versions: "unreachable" });
  assert.deepEqual(table.visibleRows().map((row) => row.id), ["ars"]);
  reset({ versions: "unregistered" });
  assert.deepEqual(table.visibleRows().map((row) => row.id), ["arax"]);
  reset({ versions: "no-smartapi" });
  assert.deepEqual(table.visibleRows().map((row) => row.id), ["ui"]);
  reset({ versions: "findings" });
  assert.deepEqual(table.visibleRows().map((row) => row.id), ["arax"]);
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
  reset({ sort: "smartapi", dir: "asc" });
  assert.doesNotMatch(table.bodyHtml(table.visibleRows()), /class="band"/);
  assert.match(table.bodyHtml([]), /No components match these filters/);
});

test("an expanded row shows only the fields some environment answered", () => {
  reset();
  const arax = table.detailRowsHtml(ROWS[1], "Step 2");
  assert.match(arax, /TRAPI/);
  assert.doesNotMatch(arax, /Biolink/);
  // The label is written into every non-environment cell, each with its
  // column's drop class, so CSS can show the one beside the first environment.
  assert.match(arax, /class="dk dk-smartapi drop-sm"/);
  assert.match(arax, /class="dk dk-name "/);
  // And a (?) that says where the row comes from.
  assert.match(arax, /class="help" data-tip="fact" data-id="arax"\s+data-fact="TRAPI"/);
  const ars = table.detailRowsHtml(ROWS[0], "Step 1");
  assert.match(ars, /Nothing else is recorded/);
  // Releases are not a detail row: they sit in the Repository cell, for CSS
  // to show once the row is open.
  assert.doesNotMatch(ars, /v1\.0/);
  assert.match(table.bodyHtml([ROWS[0]]), /class="rels"><a class="rel deployed"[^>]*>v1\.0</);
});

test("a cell's state follows the model: known absences are white, a lone deployment is not green", () => {
  reset();
  const state = (m, peers = 2) => table.cellState({ deployed: false, knownAbsent: false, reach: "", version: "", drift: [], ...m }, peers);
  assert.equal(state({ knownAbsent: true }), "none");
  assert.equal(state({}), "off");
  assert.equal(state({ deployed: true, reach: "down", version: "1.0" }), "down");
  assert.equal(state({ deployed: true, reach: "up" }), "nov");
  assert.equal(state({ deployed: true, version: "1.0", drift: ["version"] }), "diff");
  assert.equal(state({ deployed: true, version: "1.0" }), "same");
  assert.equal(state({ deployed: true, version: "1.0" }, 1), "one");
});

test("the repository and SmartAPI cells carry their dates and the registry's probe", () => {
  reset();
  const row = {
    ...ROWS[0],
    last_updated: { at: "2026-10-01T00:00:00Z", date: "2026-10-01", source: "release", tag: "v1.0" },
    smartapi_record: { id: "abc", registry_url: "https://smart-api.info/ui/abc", status: { uptime_status: "fail" } },
  };
  const html = table.bodyHtml([row]);
  assert.match(html, /class="repo drop-md"><a[^>]*href="https:\/\/github\.com\/x\/ars"/);
  assert.match(html, /class="l2" data-tip="upd" data-id="ars"><span class="age">[^<]+<\/span> · v1\.0/);
  assert.match(html, /class="sapi drop-sm"><span class="dot down" aria-label="registry probe: fail"><\/span><a[^>]*href="https:\/\/smart-api\.info\/ui\/abc"[^>]*>registered/);
  // Registered, but the date came from the registry: it goes under "registered".
  const registry = { ...row, last_updated: { ...row.last_updated, source: "registry", tag: null } };
  assert.match(table.bodyHtml([registry]), /registered<\/a><span class="l2" data-tip="upd" data-id="ars">changed/);
  // No record: say so, or count the candidates.
  assert.match(table.bodyHtml([{ ...ROWS[0], smartapi_record: null }]), /not registered/);
  assert.match(table.bodyHtml([{ ...ROWS[0], smartapi_record: null, smartapi_candidates: [{}, {}] }]), /2 possible records/);
});

test("an environment cell says why it has no version, and marks drift", () => {
  reset();
  assert.match(table.envCell(ROWS[2], "prod"), /no version endpoint to read/);
  assert.match(table.envCell(ROWS[2], "prod"), /dot up/);
  assert.match(table.envCell(ROWS[2], "ci"), /class="env absent"/);
  // A lone deployment agrees with nobody, so it is not tinted "same".
  assert.match(table.envCell(ROWS[2], "prod"), /class="env nov"/);
  assert.match(table.envCell(ROWS[0], "ci"), /class="env same"/);
  const drifting = table.envCell(ROWS[1], "ci");
  assert.match(drifting, /class="env drift diff/);
  assert.match(drifting, /≠/);
  assert.match(drifting, /aria-label="disagrees with the row"/);
  assert.doesNotMatch(table.envCell(ROWS[1], "prod"), /drift/);
});

test("a cell draws the data it runs on as pills, each with its own ≠ and glyphs", () => {
  reset();
  const row = { id: "nn", name: "NodeNorm", environments: {
    ci: cell("1.0", { version_source: "status", status_url: "https://nn.ci/status",
      babel: "2026jul22", babel_source: "status", babel_url: "https://babel/2026jul22",
      biolink: "v4.4.3", biolink_source: "status", drift: ["babel"],
      findings: [{ key: "biolink-mismatch", severity: "moderate", about: "biolink", text: "loads v4.4.3, declares 4.4.2" }] }),
    prod: cell("1.0", { babel: "2025sep1", babel_source: "status", biolink: "v4.4.3", drift: ["babel"] }),
  } };
  const ci = table.envCell(row, "ci");
  assert.match(ci, /class="env drift diff"/);
  // The version pill agrees with the row, so it carries no ≠ and no status.
  assert.match(ci, /<a class="v" href="https:\/\/nn.ci\/status"[^>]*>1\.0<\/a><\/span>/);
  // Babel differs: its border says so; Biolink's says a finding, and carries its glyph.
  assert.match(ci, /<a class="v data warn" href="https:\/\/babel\/2026jul22"[^>]*><span class="ax">Babel<\/span> 2026jul22<\/a><span class="neq"[^>]*on Babel">≠<\/span>/);
  assert.match(ci, /<a class="v data warn" [^>]*><span class="ax">Biolink<\/span> v4\.4\.3<\/a><button type="button" class="fg moderate" data-tip="findings" data-id="nn" data-env="ci" data-about="biolink"/);
  // The old captions are gone: a finding is a glyph, not a word in the cell.
  const arax = table.envCell(ROWS[1], "ci");
  assert.doesNotMatch(arax, /not in SmartAPI|inferred/);
  assert.match(arax, /class="v copied warn">2\.1<\/span><span class="neq"[^>]*on version">≠<\/span><button type="button" class="fg warning"[^>]*data-about="version"/);
  // A down cell does not redden a version it copied from the registry.
  assert.match(table.envCell(ROWS[0], "prod"), /<span class="dot down" aria-label="not reachable"><\/span><span class="v copied">1\.0<\/span>/);
  // A cell with no version still shows what data it has loaded.
  const nov = table.envCell({ id: "x", environments: { ci: { deployed: true, reachable: true,
    reason: "API document has no version", reason_key: "no-version-in-document", babel: "2025sep1" } } }, "ci");
  assert.match(nov, /class="why">API document has no version<\/span><span class="dataline">/);
  assert.match(nov, /<span class="ax">Babel<\/span> 2025sep1/);
});

test("findings about the host are the dot itself, with every severity in its tooltip", () => {
  reset();
  const findings = [
    { key: "unverified-host", severity: "warning", about: "reach", text: "unconfirmed" },
    { key: "document-error", severity: "severe", about: "reach", text: "HTTP 500" },
  ];
  const row = { id: "svc", environments: {
    ci: cell("1.0", { reachable: true, version_source: "status", findings }),
    prod: { deployed: false, reason: "a host answers, unconfirmed", reason_key: "unverified-host",
      findings: findings.slice(0, 1) },
  } };
  const ci = table.envCell(row, "ci");
  // Red for the severe finding although the host answered; no glyph after it.
  assert.match(ci, /<span class="envline"><button type="button" class="dot down" data-tip="findings" data-id="svc" data-env="ci" data-about="reach" data-sev="all" aria-label="reachable; 2 findings"><\/button><span class="v">1\.0/);
  assert.doesNotMatch(ci, /class="fg (severe|warning)"/);
  // An undeployed cell whose conventional address answered gets an amber dot before its reason.
  assert.match(table.envCell(row, "prod"), /<button type="button" class="dot warn"[^>]*aria-label="not checked; 1 finding"><\/button><span class="why">a host answers, unconfirmed/);
  TD.boot({ rows: [row], environments: ["ci", "prod"] });
  const tip = table.tipHtml({ dataset: { tip: "findings", id: "svc", env: "ci", about: "reach", sev: "all" } });
  assert.match(tip, /<div class="title">host · svc · ci<\/div><div>reachable<\/div><ul class="fl"><li><span class="fg severe"[^>]*>✕<\/span> HTTP 500<\/li><li><span class="fg warning"[^>]*>◆<\/span> unconfirmed<\/li><\/ul>/);
});

test("row-level findings sit after the name, and the tooltip lists one anchor's findings", () => {
  reset();
  const row = { ...ROWS[0], findings: [
    { key: "no-chart", severity: "warning", about: "row", text: "no chart" },
    { key: "otel-missing", severity: "warning", about: "row", text: "ghost unseen" }] };
  const html = table.bodyHtml([row]);
  assert.match(html, /data-open="ars">ARS<\/button><button type="button" class="fg warning" data-tip="findings" data-id="ars" data-env="" data-about="row" data-sev="warning" aria-label="2 warning findings">/);
  TD.boot({ rows: [row], environments: ["ci", "prod"] });
  const tip = table.tipHtml({ dataset: { tip: "findings", id: "ars", env: "", about: "row", sev: "warning" } });
  assert.match(tip, /<div class="title">warning · ars<\/div><ul class="fl"><li>no chart<\/li><li>ghost unseen<\/li><\/ul>/);
  assert.equal(table.tipHtml({ dataset: { tip: "findings", id: "ars", env: "", about: "row", sev: "severe" } }), "");
});
