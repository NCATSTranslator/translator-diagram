"""web/ is the browser half, checked without a browser: every file parses,
the concatenation the page ships parses, and dashboard.py's file lists equal
the directory (an orphan in web/ is a file nobody inlines; a name in the
tuples with no file dies on resources.files).
"""

import re
import shutil
import subprocess
from pathlib import Path

import pytest

from translator_diagram.dashboard import CSS_FILES, JS_FILES, _assets

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "src" / "translator_diagram" / "web"
WEB_TESTS = ROOT / "tests" / "web"


@pytest.fixture(scope="module")
def node():
    """The `node` binary, or a skip naming why -- not a failure, since a
    missing interpreter says nothing about whether the JS itself is right."""
    path = shutil.which("node")
    if path is None:
        pytest.skip("node is not on PATH; the JS checks need it, and CI runners have one")
    version = subprocess.run(
        [path, "--version"], capture_output=True, text=True, check=True
    ).stdout.strip()
    major = int(re.match(r"v(\d+)", version).group(1))
    if major < 18:
        pytest.skip(f"node {version} is older than the 18 the JS checks need")
    return path


class TestEveryScriptParses:
    """`node --check` is a syntax check, not a type check or a linter -- but
    it needs no browser and it is what catches the SyntaxError a stray brace
    or a merge conflict leaves behind."""

    @pytest.mark.parametrize("path", sorted(WEB.glob("*.js")), ids=lambda p: p.name)
    def test_node_check(self, node, path):
        result = subprocess.run(
            [node, "--check", str(path)], capture_output=True, text=True, check=False
        )
        assert result.returncode == 0, result.stderr

    def test_the_concatenation_parses(self, node, tmp_path):
        """Each file parses alone; the page ships them as one shared scope, so
        a name declared with `const` in two files is a SyntaxError only here
        -- which is the whole reason this test exists beside the one above."""
        bundle = tmp_path / "bundle.js"
        bundle.write_text(_assets(JS_FILES), encoding="utf-8")
        result = subprocess.run(
            [node, "--check", str(bundle)], capture_output=True, text=True, check=False
        )
        assert result.returncode == 0, result.stderr


class TestTheFileListsMatchTheDirectory:
    """CSS_FILES and JS_FILES are the inlining order, not the directory
    listing -- so this checks the *set* matches, which fails with a readable
    diff whether the mismatch is an orphan file or a missing one."""

    def test_no_orphan_css(self):
        assert {p.name for p in WEB.glob("*.css")} == set(CSS_FILES)

    def test_no_orphan_js(self):
        assert {p.name for p in WEB.glob("*.js")} == set(JS_FILES)


class TestTheSuiteListMatchesTheDirectory:
    """`tests/web/index.js` requires each suite by name, and its own comment
    says to keep the list and the directory in step. Nothing checked that it
    was: an older `node --test` globs the directory and never opens index.js,
    a newer one loads index.js and runs only what it requires, so a suite
    missing from the list passes on one runner and is silently skipped on the
    other -- exactly the orphan-vs-missing split
    TestTheFileListsMatchTheDirectory catches for web/.

    Needs no `node`, so it still runs where the two subprocess checks skip.
    """

    def test_no_orphan_suite(self):
        listed = set(re.findall(
            r"""require\(\s*["']\./([^"']+)["']\s*\)""",
            (WEB_TESTS / "index.js").read_text(),
        ))
        assert listed == {p.name for p in WEB_TESTS.glob("*.test.js")}


class TestTheJsUnitTests:
    def test_node_test_runner(self, node):
        """node's built-in test runner, over the suites in tests/web/.

        The directory is committed, so an empty one is a checkout that has
        lost its JS units rather than a state to skip past -- which is what
        this did until the suites landed, and would have gone on doing
        silently if they were ever deleted."""
        suites = sorted(p.name for p in WEB_TESTS.glob("*.test.js"))
        assert suites, f"no *.test.js in {WEB_TESTS}: the JS units are gone"
        result = subprocess.run(
            [node, "--test", "tests/web/"], cwd=ROOT, capture_output=True, text=True, check=False
        )
        assert result.returncode == 0, result.stdout + result.stderr
