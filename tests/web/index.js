/*
  The entry point `node --test tests/web/` lands on.

  Node's test runner used to expand a directory argument into the test files
  inside it; newer versions resolve a bare positional as a module path
  instead, and a directory resolves to its `index.js`. Requiring the suites
  here makes the one command in tests/test_web_assets.py work on both: an
  older runner globs `*.test.js` and never looks at this file, a newer one
  loads this file and the requires register the same tests.

  Loaded this way, every suite shares one globalThis, and several start by
  replacing globalThis.TD. So a suite takes what it tests out of TD when it
  loads, not inside a test body: by the time the tests run, a later suite
  has swapped TD for its own. A runner that globs the directory gives each
  file its own process and never shows the difference -- Node 26 does, the
  ubuntu-latest runner's node does not, so a lazy `TD.x` in a test body
  passes locally and fails in CI.

  Add a new suite to the list below as well as to the directory.
  TestTheSuiteListMatchesTheDirectory in tests/test_web_assets.py fails
  until you do, in either direction.
*/

require("./urlstate.test.js");
require("./sort.test.js");
require("./row.test.js");
require("./smartapi.test.js");
require("./fmt.test.js");
require("./table.test.js");
require("./layout.test.js");
require("./map.test.js");
require("./prose.test.js");
require("./component.test.js");
require("./namespace.test.js");
