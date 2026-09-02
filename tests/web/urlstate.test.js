/*
  web/core.js under node, with no browser and no stubs.

  This is the half of the page that has judgement in it — which query
  parameters survive a paste into Slack, which ones a hostile URL cannot smuggle
  in — and it is testable precisely because core.js touches no DOM. Run by
  `node --test tests/web/`, which tests/test_web_assets.py invokes.
*/

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const CORE = path.join(__dirname, "..", "..", "src", "translator_diagram", "web", "core.js");

globalThis.TD = {};
vm.runInThisContext(fs.readFileSync(CORE, "utf8"), { filename: "core.js" });
const TD = globalThis.TD;

const defaults = () => TD.url.defaults();

test("an empty query gives every default", () => {
  const state = TD.url.parse("");
  assert.deepEqual(state, {
    view: "overview", q: "", owner: [], versions: "all", sort: "", dir: "asc",
    expand: [], sel: "", tab: "", edges: [],
  });
});

test("defaults serialise to nothing at all", () => {
  assert.equal(TD.url.serialize(defaults()), "");
});

test("only what differs from the default is written", () => {
  const state = { ...defaults(), versions: "differ" };
  assert.equal(TD.url.serialize(state), "versions=differ");
});

test("every field round-trips", () => {
  const state = {
    view: "map",
    q: "arax",
    owner: ["Core Components WG", "DINGO"],
    versions: "differ",
    sort: "env-prod",
    dir: "desc",
    expand: ["arax", "ars"],
    sel: "arax",
    tab: "environments",
    edges: ["calls", "catalog"],
  };
  assert.deepEqual(TD.url.parse(TD.url.serialize(state)), state);
});

test("a leading question mark is accepted", () => {
  assert.equal(TD.url.parse("?versions=none").versions, "none");
});

test("commas stay readable in a shared link", () => {
  const query = TD.url.serialize({ ...defaults(), expand: ["a", "b"] });
  assert.equal(query, "expand=a,b");
});

test("an unknown versions view falls back to the default", () => {
  assert.equal(TD.url.parse("versions=nonsense").versions, "all");
  assert.equal(TD.url.parse("versions=").versions, "all");
});

test("an unknown sort column falls back to no sort", () => {
  assert.equal(TD.url.parse("sort=owner").sort, "owner");
  assert.equal(TD.url.parse("sort=env-prod").sort, "env-prod");
  assert.equal(TD.url.parse("sort=env-nowhere").sort, "");
  assert.equal(TD.url.parse("sort=drop%20table").sort, "");
});

test("an unknown view falls back", () => {
  assert.equal(TD.url.parse("view=diagram").view, "overview");
});

test("the sort vocabulary follows the payload's environments", () => {
  const state = TD.url.parse("sort=env-staging", {
    ...TD.url.vocabulary(), sorts: ["name", "env-staging"],
  });
  assert.equal(state.sort, "env-staging");
});

/* There is one row style now. Both spellings of the control that used to
   choose between two are still accepted so that a link someone shared before
   it went away opens on the table rather than on an error -- they are simply
   read and dropped, and never written back. */
test("density and details are accepted and ignored", () => {
  for (const query of ["density=compact", "density=comfortable", "details=0", "details=1"]) {
    const state = TD.url.parse(query);
    assert.ok(!("density" in state), `${query} left a density on the state`);
    assert.equal(TD.url.serialize(state), "", `${query} was written back`);
  }
  // The rest of a shared link still survives beside them.
  const state = TD.url.parse("density=compact&versions=differ&expand=arax");
  assert.equal(state.versions, "differ");
  assert.deepEqual(state.expand, ["arax"]);
  assert.equal(TD.url.serialize(state), "versions=differ&expand=arax");
});

test("q is truncated rather than trusted", () => {
  const long = "x".repeat(500);
  assert.equal(TD.url.parse(`q=${long}`).q.length, 200);
  assert.equal(TD.url.serialize({ ...defaults(), q: long }).length, "q=".length + 200);
});

test("owner is a capped comma list, deduplicated", () => {
  assert.deepEqual(TD.url.parse("owner=DINGO,DINGO,%20UI%20").owner, ["DINGO", "UI"]);
  assert.deepEqual(TD.url.parse("owner=").owner, []);
  const many = TD.url.parse(`owner=${"a".repeat(60)},${"b".repeat(60)}`).owner;
  assert.equal(many.join(",").length, 100);
});

test("an unknown edge kind is dropped, the known ones kept", () => {
  assert.deepEqual(TD.url.parse("edges=calls,teleport,catalog").edges, ["calls", "catalog"]);
});

test("dir is written only beside a column, and never survives alone", () => {
  assert.equal(TD.url.serialize({ ...defaults(), dir: "desc" }), "");
  assert.equal(TD.url.parse("dir=desc").dir, "asc");
  // Both, always, when there is a column: the first click's direction differs
  // per column, so "asc" is not a default a reader of the URL could infer.
  assert.equal(TD.url.serialize({ ...defaults(), sort: "updated" }), "sort=updated&dir=asc");
});

test("a query with everything default but whitespace stays empty", () => {
  assert.equal(TD.url.serialize({ ...defaults(), q: "   " }), "");
});
