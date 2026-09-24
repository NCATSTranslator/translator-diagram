# src/translator_diagram/web/

The browser half of the dashboard: the CSS and JS that `CSS_FILES` and
`JS_FILES` in `dashboard.py` concatenate and inline into the generated page.
The repo-wide working agreements are in [../../../AGENTS.md](../../../AGENTS.md),
and the Python side — the payload this code reads, and which module builds
which part of it — is in [../CLAUDE.md](../CLAUDE.md).

## Looking at the page

`AGENTS.md` says to render the page and look before calling it fine, in both
views and both themes. This is how.

**Use Chromium, not Firefox.** Headless Firefox does not start on current
macOS — every invocation dies with `Could not find profile folder`, whatever
you pass for `--profile`, including a directory that demonstrably exists
([gaurav/prcoder#61](https://github.com/gaurav/prcoder/issues/61)). The
recipe here used to be Firefox; it is kept only as the reason not to try it
again. Playwright's bundled headless shell needs no install. From the repo
root:

```bash
uv run build-dashboard
CHROME=~/Library/Caches/ms-playwright/chromium_headless_shell-*/*/chrome-headless-shell
cd data/dashboard && python3 -m http.server 8765 &   # see file:// note below
$CHROME --headless --disable-gpu --hide-scrollbars \
  --force-prefers-reduced-motion --virtual-time-budget=8000 \
  --screenshot="$PWD/data/shots/overview.png" --window-size=1700,1400 \
  --user-data-dir="$PWD/data/cp1" "http://localhost:8765/index.html"
```

Each run needs its **own `--user-data-dir`**, or concurrent shots collide.
`?view=map` selects the Map view and `?component=<id>` a component page, which
is its own scroller: to screenshot the whole page rather than the first
viewport, either use Playwright's `fullPage` after setting the scroller and
its ancestors to `overflow: visible; height: auto`, or shoot at a tall
`--window-size`.

**For behaviour rather than pixels — Back and forward, the drawer opening,
Show on map — drive the page with Playwright.** A global `playwright` is
installed (`npm ls -g playwright`); a script can `import { chromium } from
"playwright"` after `npm link playwright` in a scratch directory under
`data/`, and must pass `executablePath` pointing at the headless shell above,
because the global package expects a newer browser build than the one
cached. Collect `console.error` and `pageerror` in the script: a renderer
that throws on one absent field is caught by its own try/catch and reported
there, not by a screenshot.

**`--force-prefers-reduced-motion` is not optional.** The stat tiles count up
on load, and a screenshot without it catches them mid-animation: the page
reads `3 components · 6 deployments` when there are 24 and 51. That is
indistinguishable from a real tile-counting bug — the page once shipped one
that counted 74 things where there were 41 — so a naive shot invents a bug
that is not there. Freeze the animation, then check the tiles against what
`build-dashboard` printed.

**Forcing the theme needs a `matchMedia` stub, not a flag.** Chromium's
`--force-dark-mode` does not move the page's `prefers-color-scheme`, and the
shots come back byte-identical. The page resolves its theme through
`matchMedia("(prefers-color-scheme: dark)")` (`app.js`), so copy `index.html`
beside itself — relative paths must still resolve — and inject a script before
the bootstrap that returns a fixed `matches` for that query. This is the same
stubbing trick as the JS note below.

Shoot it narrow (`--window-size=760,1100`) and at the widths *between* the
breakpoints. Measured across 1000–1600px, `div.tablewrap` overflows only
between about **1490 and 1535px** — 30px over at 1500, 10px at 1520, clean at
1480 and 1540 — where a column returns before there is room for it. The page
root never overflows at any width, and the wrap scrolls, so nothing is
unreachable; issue #31 describes the wider 1100–1500px version of this, most
of which is now gone. At 760px the PROD column is likewise clipped but
reachable. None of this is visible in a screenshot: measure `scrollWidth`
against `clientWidth` at several widths instead of judging by eye.

Serve the build over HTTP rather than opening `file://`: Map export and other
features are blocked on a `file://` origin, and the copies the theme stub
needs are simpler to reach over a server anyway.

Whether the result *reads* well is still the operator's call: report what you
saw and let them look.

## Testing JS with judgement in it

There is no JS harness here, and that has not stopped anything being tested.
Slice the block out of `table.js` or `core.js`, stub `document`/`localStorage`/
`matchMedia`, and run it under `node` from the scratchpad — that is how the
theme cycle was checked against both system preferences, and how the sort
comparators were driven over the real `overview.json` to prove undated rows
stay last in *both* directions. Layout, URL-state, detail-renderer and
component-page units live in `tests/web/` and run under `node --test` via
`tests/test_web_assets.py`.

**`detail.js` and `component.js` touch no `document` at definition time**,
the same rule `layout.js` and `map.js` follow, and it is what lets
`tests/web/detail.test.js` load them under node and render every panel over
a fixture row, an empty row and every row of the real build. Keep it that
way: a `document.addEventListener` at the top level of either file breaks
the suite, and the two glyphs they read off `TD.ui` are stubbed before
`core.js` runs. `drawer.js` and `app.js` are the files allowed to touch the
page at load.

## Things that look wrong but aren't

**This is not a module system.** The files are concatenated in `JS_FILES`
order into one shared scope. A name declared with `const` in two files is a
syntax error only when the bundle is checked — which is why
`tests/test_web_assets.py` concatenates before `node --check`, and why
`tests/web/` runs under `node --test`. The order carries meaning: `detail.js`
defines `TD.detail`, which `drawer.js` and `component.js` read at definition
time, and `app.js` calls all three, so it is last.

**The drawer and the component page render the same functions.** `detail.js`
holds the header and the six panel renderers; `drawer.js` is the chrome
around them (a side panel, tabs, focus) and `component.js` is the other
chrome (a full-width column, sections, a sticky nav). A fact that appears in
one and not the other is a bug in the chrome, not a second renderer to write.
The `dw-` class prefix predates the page and is the shared detail vocabulary
(`detail.css`); it was kept rather than renamed across five hundred lines.

**`component` is its own URL key, not a reuse of `sel`.** `sel` means "the
drawer is open on this row" to the table, the map and the drawer's own boot,
which opens on any `sel` that names a row; a page addressed by `sel` would
have had the drawer open over it. `?component=<id>` names the view as well as
the row, so `view=` is not written beside it, and neither are the filters,
sort or drawer state — they stay in memory so the crumb back lands where the
reader left, but a link to one component must not carry the sender's search
box. A reload on the page loses them, which is the accepted cost.

**`app.js` is the only popstate listener, and the only file that pushes.**
`TD.navigate` pushes a history entry for a change of view or a component
page; `TD.commit` replaces, for filters, sort and drawer state, so Back
leaves a view rather than undoing a keystroke. The drawer once had its own
popstate listener, which was a second render and an ordering dependency on
`JS_FILES`; it now exposes `sync` and `close` for `app.js` to call. Entering
the component view closes the drawer, because `data-drawer="open"` is what
gives the page 440px of right padding and shifts the column breakpoints.

**The component page scrolls itself.** `html` and `body` are
`overflow: hidden` and `.page` is a flex column, so the page's `.cp-scroll` is
the scroller — the same arrangement as `.tablewrap` — and its sticky section
nav resolves against it. The browser's own fragment navigation therefore
finds a section and moves nothing, which is why the nav's anchors are
scrolled by hand and the `#c-<id>` fragment is dropped when the view is not
the table.

**The Recorded section prints a row for an absent value.** Everywhere else on
the page a missing fact is left out, on the rule that a drawer printing a
dash for each of forty keys is a form rather than a reading surface. That
section is the one place whose purpose is the gaps, and it draws every field
the schema allows, in schema order, with three states rather than two:
*absent* (not recorded yet), *null or empty* (checked, there is none) and
*recorded*. The distinction is the one `docs/component-metadata.md` builds the
format on, and this is where it is finally visible.

**The page opens on every component**, having once opened on
`Environments disagree` — which showed 7 rows of 24 and hid the platform to
make a point about drift, so someone looking up one component found it missing
from a page that never said it was filtered. Drift is still the first thing the
page says, in the finding above the table. The four views (`all`, `differ`,
`known`, `none`) live in `VERSION_VIEWS` in `table.js`, listed in that order so
the default reads first, with `DEFAULT_VIEW` naming it. `differ` means any of
the three tinted axes, not versions alone. It replaced a "Drift only" toggle
rather than joining it: two controls that select the same rows cannot be told
apart by a reader.

**Environment columns sort by the age of the release running there**, not by
version string: comparing `2.10.2` against `1.0` across two different
components means nothing. Cells rank in tiers — running a release we can date,
running something no release names, not deployed — and the tiers hold in both
directions.

**The theme cycle starts by moving away from the system**, not at light: the
page defaults to following the operating system, so `auto → light → dark`
would spend the first click repainting a light machine light and read as a
dead button. `nextTheme` therefore reads `prefers-color-scheme` to decide
which way to go first, and the one click that does not change the appearance
is the trip back to auto, which says so in the button's title.
