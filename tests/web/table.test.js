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
    environments: { ci: cell("2.1", { drift: ["version"], unregistered: true }), prod: cell("2.0", { trapi: "1.5" }) } },
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
  reset({ sort: "env-prod", dir: "asc" });
  assert.doesNotMatch(table.bodyHtml(table.visibleRows()), /class="band"/);
  assert.match(table.bodyHtml([]), /No components match these filters/);
});

test("a SmartAPI sort puts the problems first in both directions, banded by state", () => {
  for (const dir of ["asc", "desc"]) {
    reset({ sort: "smartapi", dir });
    const column = table.COLUMNS.find((entry) => entry.key === "smartapi");
    const ids = TD.sort.rows(table.visibleRows(), column, dir).map((row) => row.id);
    // arax has an environment its record leaves out; ars has a clean record;
    // ui has none at all.
    assert.deepEqual(ids, ["arax", "ui", "ars"]);
    const html = table.bodyHtml(TD.sort.rows(table.visibleRows(), column, dir));
    const bands = [...html.matchAll(/class="band" data-step="([^"]+)"/g)].map((m) => m[1]);
    assert.deepEqual(bands, ["Deployments missing from the record", "Not registered", "Registered"]);
  }
});

test("an expanded row shows only the fields some environment answered", () => {
  reset();
  const arax = table.detailRowsHtml(ROWS[1], "Step 2");
  assert.match(arax, /TRAPI/);
  assert.doesNotMatch(arax, /Biolink/);
  // The label is written into every non-environment cell, each with its
  // column's drop class, so CSS can show the one beside the first environment.
  // At narrow widths that includes the Component column.
  assert.match(arax, /class="dk dk-smartapi drop-sm"/);
  assert.doesNotMatch(arax, /class="dk dk-name "/);
  assert.match(table.detailRowsHtml(ROWS[1], "Step 2", { narrow: true }), /class="dk dk-name "/);
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

test("the repository and SmartAPI cells each carry their own date, whichever is newer", () => {
  reset();
  const row = {
    ...ROWS[0],
    // The registration changed after the release: last_updated is the
    // registry's, and the release date must stay under the repository anyway.
    last_updated: { at: "2026-10-02T00:00:00Z", date: "2026-10-02", source: "registry", tag: null },
    releases_detail: [{ tag: "v1.0", published: "2026-10-01", url: "https://github.com/x/ars/releases/tag/v1.0" }],
    smartapi_record: { id: "abc", registry_url: "https://smart-api.info/ui/abc",
      status: { uptime_status: "fail" }, meta: { last_updated: "2026-10-02T00:00:00Z" } },
  };
  const html = table.bodyHtml([row]);
  assert.match(html, /class="repo drop-md"><a[^>]*href="https:\/\/github\.com\/x\/ars"/);
  assert.match(html, /class="l2" data-tip="rel" data-id="ars" data-tag="v1\.0"><span class="age">[^<]+<\/span> · v1\.0/);
  assert.match(html, /class="sapi drop-sm" data-tip="sapi" data-id="ars"><span class="sapil"><span class="dot down" aria-label="Registry probe failing"><\/span><span class="sapiw"><a[^>]*href="https:\/\/smart-api\.info\/ui\/abc"[^>]*>probe failing<\/a><\/span><span class="l2">changed <span class="age">/);
  // A release newer than the registration leaves the registry date in place.
  const released = { ...row, last_updated: { at: "2026-10-03T00:00:00Z", date: "2026-10-03", source: "release", tag: "v1.0" } };
  assert.match(table.bodyHtml([released]), /class="sapi[\s\S]*changed <span class="age">/);
  // No record: say so, or count the candidates, with no dot but the gutter kept.
  assert.match(table.bodyHtml([{ ...ROWS[0], smartapi_record: null }]),
    /<span class="sapil"><span class="sapiw"><span class="why">not registered<\/span>/);
  assert.match(table.bodyHtml([{ ...ROWS[0], smartapi_record: null, smartapi_candidates: [{}, {}] }]), /2 possible records/);
});

test("the SmartAPI tooltip names the state, each problem and the failing probe lines", () => {
  const row = { ...ROWS[1], smartapi: "def", smartapi_record: { id: "def",
    status: { uptime_status: "fail", uptime_ts: "2026-10-21T07:00:00Z",
      uptime_msg: ["🟢 200: (/ok) All good!", "🔴 /get: (400) Invalid <request>."] } } };
  TD.boot({ rows: [row], environments: ["ci", "prod"] });
  const html = table.tipHtml({ dataset: { tip: "sapi", id: "arax" } });
  assert.match(html, /SmartAPI · Registry probe failing/);
  assert.match(html, /<dt>probed<\/dt><dd>2026-10-21<\/dd>/);
  assert.match(html, /ci, but the record lists no server there/);
  assert.match(html, /🔴 \/get: \(400\) Invalid &lt;request&gt;\./);
  assert.doesNotMatch(html, /All good/);
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

test("an expanded row's Component column holds the connections, in one cell spanning the detail", () => {
  const rows = [
    { ...ROWS[0], connections: { gets_results_from: ["arax"], calls: ["ui"], planned_calls: ["nope"] } },
    { ...ROWS[1], connections: {},
      environments: { ...ROWS[1].environments, prod: cell("2.0", { trapi: "1.5", biolink: "4.2", location: "ITRB" }) } },
    ROWS[2],
    { ...ROWS[2], id: "lone", name: "Lone" },
  ];
  TD.boot({ rows, environments: ["ci", "prod"] });
  TD.state = { ...TD.url.defaults() };
  table.ensureColumns();
  const html = table.detailRowsHtml(rows[1], "Step 2");
  const trs = html.match(/<tr /g).length;
  // One cell, in the first row, spanning every detail row; the rest start at
  // Owner, marked so CSS does not make that cell sticky or draw the spine on it.
  assert.equal(trs, 3);
  assert.match(html, new RegExp(`^<tr class="detail grp detail-first"[^>]*><td class="dk-conn" rowspan="${trs}">`));
  assert.equal((html.match(/class="dk-conn"/g) || []).length, 1);
  assert.equal((html.match(/class="detail grp[^"]*spanned"/g) || []).length, trs - 1);
  // arax is what ars gets results from, so ars is what arax provides them to.
  assert.match(html, /<span class="cgl">Provides results to<\/span><button type="button" class="conn" data-open="ars"/);
  assert.doesNotMatch(html, /Gets results from/);
  // ars's own: an unknown id keeps its id as its name, and planned is marked.
  const ars = table.detailRowsHtml(rows[0], "Step 1");
  assert.match(ars, /Gets results from<\/span><button[^>]*data-open="arax"[^>]*>.*ARAX<\/button>/s);
  assert.match(ars, /class="conn planned" data-open="nope" title="Open nope \(planned, not yet implemented\)">nope</);
  // Nothing recorded either way says so.
  assert.match(table.detailRowsHtml(rows[3], "Step 3"), /No connections recorded/);
  assert.match(table.detailRowsHtml(rows[2], "Step 3"), /Called by<\/span><button[^>]*data-open="ars"/);
  // Narrow: today's rows, no connections, every row with its own label cell.
  const narrow = table.detailRowsHtml(rows[1], "Step 2", { narrow: true });
  assert.doesNotMatch(narrow, /dk-conn|spanned/);
  assert.equal((narrow.match(/class="dk dk-name "/g) || []).length, trs);
});

test("a detail label keeps its last word with its (?), so a narrow column never strands the (?)", () => {
  reset();
  const html = table.detailRowsHtml({ ...ROWS[1], environments: { prod: cell("2.0", { asyncquery: true }) } }, "Step 2");
  assert.match(html, /<span class="dkl">Async <span class="dkw">query<button type="button" class="help"/);
});
