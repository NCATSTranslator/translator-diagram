/*
  The entry point `node --test tests/web/` lands on.

  Node's test runner used to expand a directory argument into the test files
  inside it; newer versions resolve a bare positional as a module path
  instead, and a directory resolves to its `index.js`. Requiring the suites
  here makes the one command in tests/test_web_assets.py work on both: an
  older runner globs `*.test.js` and never looks at this file, a newer one
  loads this file and the requires register the same tests.

  Add a new suite to the list below as well as to the directory.
*/

require("./urlstate.test.js");
require("./sort.test.js");
require("./layout.test.js");
