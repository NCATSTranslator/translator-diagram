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
`?view=map` selects the Map view.

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
stay last in *both* directions. Layout and URL-state units live in
`tests/web/` and run under `node --test` via `tests/test_web_assets.py`.

## Things that look wrong but aren't

**This is not a module system.** The files are concatenated in `JS_FILES`
order into one shared scope. A name declared with `const` in two files is a
syntax error only when the bundle is checked — which is why
`tests/test_web_assets.py` concatenates before `node --check`, and why
`tests/web/` runs under `node --test`.

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
