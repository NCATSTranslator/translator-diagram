/*
  TD.fmt.prose, the Markdown subset a component's `description` is written in.

  The text comes from catalog files anyone can send a pull request to, and it
  lands in the page as HTML, so most of what is checked here is what it must
  *not* do: run markup, link anywhere but the web, or eat text it does not
  understand.
*/

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const CORE = path.join(__dirname, "..", "..", "src", "translator_diagram", "web", "core.js");

globalThis.TD = globalThis.TD || {};
vm.runInThisContext(fs.readFileSync(CORE, "utf8"), { filename: "core.js" });
const { prose } = globalThis.TD.fmt;

test("markup in the text is escaped, not run", () => {
  assert.equal(
    prose('<script>alert("x")</script> & more'),
    "<p>&lt;script&gt;alert(&quot;x&quot;)&lt;/script&gt; &amp; more</p>",
  );
});

test("blank lines separate paragraphs, and single line breaks join", () => {
  assert.equal(prose("One\nline.\n\nTwo."), "<p>One line.</p><p>Two.</p>");
  // A line holding only spaces still separates, as it does in Markdown.
  assert.equal(prose("One.\n  \nTwo."), "<p>One.</p><p>Two.</p>");
  assert.equal(prose(""), "");
  assert.equal(prose(null), "");
});

test("a block starting with '- ' is a list, and other lines continue an item", () => {
  assert.equal(
    prose("- first\n- second item\n  wrapped\n\nAfter."),
    "<ul><li>first</li><li>second item wrapped</li></ul><p>After.</p>",
  );
});

test("code spans are escaped inside", () => {
  assert.equal(
    prose("Call `GET /x?a=1&b=<2>` first."),
    "<p>Call <code>GET /x?a=1&amp;b=&lt;2&gt;</code> first.</p>",
  );
});

test("an http(s) link becomes a link that opens in its own tab", () => {
  assert.equal(
    prose("See [the README](https://github.com/a/b?x=1&y=2)."),
    '<p>See <a href="https://github.com/a/b?x=1&amp;y=2" target="_blank" '
      + 'rel="noopener">the README</a>.</p>',
  );
});

test("any other link is shown as its text and goes nowhere", () => {
  for (const url of ["javascript:alert%281%29", "data:text/html,x", "/relative", "README.md"]) {
    assert.equal(prose(`[click](${url})`), "<p>click</p>", url);
  }
});

test("unclosed markup is left as it was written", () => {
  assert.equal(prose("a `b c"), "<p>a `b c</p>");
  assert.equal(prose("[text](https://x"), "<p>[text](https://x</p>");
  assert.equal(prose("[text] (https://x)"), "<p>[text] (https://x)</p>");
});
