/*
  TD.smartapi.status: what the SmartAPI column says about a registration,
  worst problem first. The table's cell, its sort and its tooltip all read
  this one answer, so the states and their order are pinned here.
*/

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const CORE = path.join(__dirname, "..", "..", "src", "translator_diagram", "web", "core.js");

globalThis.TD = {};
vm.runInThisContext(fs.readFileSync(CORE, "utf8"), { filename: "core.js" });
const { boot, smartapi } = globalThis.TD;

const record = (status, extra) => ({
  id: "abc", registry_url: "https://smart-api.info/ui/abc",
  status, meta: { last_updated: "2026-05-24T00:00:00+00:00" }, ...extra,
});
const deployed = (extra) => ({ deployed: true, version: "1.0", ...extra });

test("a record whose probe passes and lists every deployment is registered, with a green dot", () => {
  boot({ environments: ["ci", "prod"] });
  const got = smartapi.status({ smartapi: "abc", smartapi_record: record({ uptime_status: "pass" }),
    environments: { ci: deployed(), prod: deployed() } });
  assert.equal(got.key, "ok");
  assert.equal(got.word, "registered");
  assert.equal(got.dot, "up");
  assert.equal(got.href, "https://smart-api.info/ui/abc");
  assert.equal(got.changed, "2026-05-24T00:00:00+00:00");
});

test("a record the registry has not probed is registered, but not green", () => {
  boot({ environments: ["prod"] });
  const got = smartapi.status({ smartapi_record: { id: "abc", registry_url: "https://smart-api.info/ui/abc" } });
  assert.equal(got.key, "ok");
  assert.equal(got.dot, null);
  assert.equal(got.changed, "");
  assert.deepEqual(got.failures, []);
});

test("unknown is grey, not red: the registry skipped the paths, nothing failed", () => {
  boot({ environments: ["prod"] });
  const got = smartapi.status({ smartapi_record: record({ uptime_status: "unknown",
    uptime_msg: ["🟠 /query: (skipped) Missing Required Params/Body"] }) });
  assert.equal(got.key, "unprobed");
  assert.equal(got.dot, "");
  assert.match(got.problems[0].note, /no example requests/);
});

test("a failing probe outranks a missing environment, which outranks no probe", () => {
  boot({ environments: ["ci", "test", "prod"] });
  const environments = { ci: deployed({ unregistered: true }), test: deployed({ unregistered: true }), prod: deployed() };
  const failing = smartapi.status({ environments, smartapi_record: record({ uptime_status: "fail",
    uptime_msg: ["🟢 200: (/ok) All good!", "🔴 /get: (400) Invalid request."] }) });
  assert.equal(failing.key, "failing");
  assert.equal(failing.dot, "down");
  assert.deepEqual(failing.problems.map((p) => p.key), ["failing", "unlisted"]);
  assert.deepEqual(failing.failures, ["🔴 /get: (400) Invalid request."]);
  const shepherd = smartapi.status({ environments, smartapi_record: record({ uptime_status: "unknown" }) });
  assert.equal(shepherd.key, "unlisted");
  assert.equal(shepherd.word, "ci, test not listed");
  assert.equal(shepherd.dot, "warn");
  assert.deepEqual(shepherd.problems.map((p) => p.key), ["unlisted", "unprobed"]);
});

test("an id the catalog records but the registry does not have is not 'not registered'", () => {
  boot({ environments: ["prod"] });
  const got = smartapi.status({ smartapi: "7a12feb2fbd8fe4af532a77ee19b7800", smartapi_record: null });
  assert.equal(got.key, "missing");
  assert.equal(got.word, "record not found");
  assert.equal(got.href, "https://smart-api.info/ui/7a12feb2fbd8fe4af532a77ee19b7800");
});

test("no record: candidates, then an explicit null in the catalog, then not registered", () => {
  boot({ environments: ["prod"] });
  assert.equal(smartapi.status({ smartapi_candidates: [{}, {}] }).word, "2 possible records");
  const checked = smartapi.status({ recorded: { identifiers: { smartapi: null } } });
  assert.equal(checked.key, "n/a");
  assert.equal(checked.word, "not an API");
  const none = smartapi.status({ recorded: { identifiers: {} } });
  assert.equal(none.key, "none");
  assert.equal(none.dot, null);
  assert.equal(none.href, "");
});

test("the rank is the order of the states, worst first", () => {
  assert.deepEqual(Object.keys(smartapi.STATES),
    ["missing", "failing", "unlisted", "unprobed", "candidates", "none", "ok", "n/a"]);
  boot({ environments: ["prod"] });
  const ranks = [
    { smartapi: "abc" },
    { smartapi_record: record({ uptime_status: "fail" }) },
    { smartapi_record: record({ uptime_status: "pass" }) },
    { recorded: { identifiers: { smartapi: null } } },
  ].map((row) => smartapi.status(row).rank);
  assert.deepEqual(ranks, [...ranks].sort((a, b) => a - b));
});
