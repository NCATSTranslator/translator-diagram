/*
  The seven files in web/ as the page runs them: concatenated in JS_FILES
  order, sharing nothing but the one global `TD`.

  Each file is its own function scope and publishes what the others use on
  TD, so two files cannot collide over a name. What can still go wrong is
  that each file trusts TD to hold what it reads, and nothing checks it:

  - a file that reads TD.x while it loads needs the file defining TD.x to be
    earlier in JS_FILES. Reorder the tuple, or move a read to top level, and
    the page dies on load with a TypeError;
  - a misspelled TD.fmt.escc is `undefined`, and the call fails only when
    that line runs in a browser.

  ES modules would catch both, and were not adopted for it: the page must
  open from file://, where `import` across files is blocked, so modules mean
  a bundler and a Node toolchain inside a build that otherwise needs only
  Python (see "This is not a module system" in web/CLAUDE.md). This suite
  gets the same two checks by running the real files instead.

  It loads them into a context of its own, with an inert stand-in for each
  browser global and a minimal payload for app.js to boot on. TD there is a
  Proxy that records which file defined each name and which names a file read
  before anything had defined them. Its own context also keeps it out of the
  globalThis.TD the other suites share (see index.js).

  A browser global that loading reaches and BROWSER_GLOBALS lacks fails
  "every file loads" as "X is not defined". Add it below, unless it is a
  typo.
*/

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const ROOT = path.join(__dirname, "..", "..");
const WEB = path.join(ROOT, "src", "translator_diagram", "web");

/* The order is dashboard.py's, read from its source so there is one list. */
function jsFiles() {
  const source = fs.readFileSync(path.join(ROOT, "src", "translator_diagram", "dashboard.py"), "utf8");
  const tuple = source.match(/^JS_FILES = \(([\s\S]*?)\)/m);
  assert.ok(tuple, "JS_FILES not found in dashboard.py: this suite reads its order from there");
  return [...tuple[1].matchAll(/"([^"]+\.js)"/g)].map((m) => m[1]);
}

/* Callable, constructible, every property another one; it reads as "null"
   and iterates as empty, so the page's setup code runs to the end against it
   and changes nothing. */
function inert() {
  return new Proxy(function () {}, {
    get(_, key) {
      if (key === Symbol.toPrimitive) return () => "null";
      if (key === Symbol.iterator) return function* () {};
      if (key === "then") return undefined;
      return inert();
    },
    set: () => true,
    apply: () => inert(),
    construct: () => inert(),
  });
}

/* Only what loading reaches, plus `document` below. The page uses many more,
   but inside handlers that never fire here, and a longer list would only
   hide a misspelled global in the code that does run. */
const BROWSER_GLOBALS = [
  "location", "addEventListener", "matchMedia", "queueMicrotask", "clearTimeout",
];

const PAYLOAD = JSON.stringify({ rows: [] });

const ORDER = jsFiles();
const definedBy = new Map();   // TD name -> the file that first defined it
const earlyReads = [];         // { file, name }: read while nothing had defined it
const loadErrors = [];         // { file, error }
let loading = null;

const TD = new Proxy({}, {
  get(target, key) {
    if (typeof key === "string" && !(key in target)) earlyReads.push({ file: loading, name: key });
    return target[key];
  },
  set(target, key, value) {
    if (typeof key === "string" && !definedBy.has(key)) definedBy.set(key, loading);
    target[key] = value;
    return true;
  },
});

const context = { TD, console, URLSearchParams };
for (const name of BROWSER_GLOBALS) context[name] = inert();
context.document = new Proxy(inert(), {
  get(target, key) {
    if (key === "getElementById") {
      return (id) => (id === "payload" ? { textContent: PAYLOAD } : inert());
    }
    return target[key];
  },
});
vm.createContext(context);

for (const file of ORDER) {
  loading = file;
  try {
    vm.runInContext(fs.readFileSync(path.join(WEB, file), "utf8"), context, { filename: file });
  } catch (error) {
    loadErrors.push({ file, error });
  }
}
loading = null;
const loaded = { ...context.TD };

/* Payload and URL state: their keys are data, not code, so TD.DATA.rows and
   TD.state.view are not checked against anything. */
const DATA_NAMESPACES = new Set(["DATA", "ENVS", "state"]);

test("JS_FILES names every script in web/", () => {
  const onDisk = fs.readdirSync(WEB).filter((name) => name.endsWith(".js")).sort();
  assert.deepEqual([...ORDER].sort(), onDisk);
});

test("every file loads, in JS_FILES order", () => {
  const failures = loadErrors.map(({ file, error }) => `${file}: ${error.message}`);
  assert.deepEqual(failures, []);
});

test("no file reads a TD name before an earlier file defines it", () => {
  // `const map = (TD.map = TD.map || {})` reads TD.map before defining it,
  // and is fine: that is the file defining its own name.
  const failures = earlyReads
    .filter(({ file, name }) => definedBy.get(name) !== file)
    .map(({ file, name }) => {
      const owner = definedBy.get(name);
      return owner
        ? `${file} reads TD.${name} while it loads, but ${owner} defines it and comes later in JS_FILES`
        : `${file} reads TD.${name} while it loads, and no file defines it`;
    });
  assert.deepEqual([...new Set(failures)], []);
});

test("every TD.x and TD.x.y in web/ names something a file defines", () => {
  assert.ok(Object.keys(loaded).length > 0, "nothing was defined on TD: this test checks nothing");
  const failures = [];
  for (const file of ORDER) {
    const source = fs.readFileSync(path.join(WEB, file), "utf8");
    for (const match of source.matchAll(/\bTD\.([A-Za-z_$][\w$]*)(?:\.([A-Za-z_$][\w$]*))?/g)) {
      const [text, name, member] = match;
      const line = source.slice(0, match.index).split("\n").length;
      const namespace = loaded[name];
      if (!(name in loaded)) {
        failures.push(`${file}:${line} ${text}: no file defines TD.${name}`);
      } else if (member && !DATA_NAMESPACES.has(name) && namespace && typeof namespace === "object"
                 && !(member in namespace)) {
        failures.push(`${file}:${line} ${text}: TD.${name} has no ${member}`);
      }
    }
  }
  assert.deepEqual(failures, []);
});
