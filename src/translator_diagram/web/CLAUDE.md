# src/translator_diagram/web/

The browser half of the dashboard: the CSS and JS that `CSS_FILES` and
`JS_FILES` in `dashboard.py` concatenate and inline into the generated page.
The repo-wide working agreements are in [../../../AGENTS.md](../../../AGENTS.md),
and the Python side — the payload this code reads, and which module builds
which part of it — is in [../CLAUDE.md](../CLAUDE.md).

## Looking at the page

`AGENTS.md` says to render the page and look before calling it fine, in both
views and both themes. This is how.

Either browser works. Chromium's headless shell runs from the command line
with no Python package; Firefox runs through Playwright's API, which also
handles the theme and the reduced motion itself (see *Firefox* below).
Playwright's bundled headless shell needs no install. From the repo root:

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
stubbing trick as the JS note below. Insert it straight after
`<meta charset="utf-8">`: the page writes no `<head>` tag (HTML implies it), so
a script that looks for `<head>` to insert after finds nothing.

**The stub must answer the reduced-motion query too.** `core.js` asks
`matchMedia("(prefers-reduced-motion: reduce)")` to decide whether the tiles
count up, and a stub that returns `matches: false` for every query but the
colour scheme switches the animation back on: four shots taken with the flag
above still showed tiles mid-count (`40`, `41`, `42`, `43` fetches of the
same 219). This one answers the colour scheme itself and hands every other
query to the real `matchMedia`, so the flag keeps working. Run it in the
build directory; it writes `light.html` and `dark.html` beside `index.html`:

```bash
for theme in light dark; do python3 - "$theme" <<'PY'
import sys
theme = sys.argv[1]
dark = "true" if theme == "dark" else "false"
stub = (
    '<meta charset="utf-8"><script>'
    "const realMatchMedia = window.matchMedia.bind(window);"
    "window.matchMedia = (q) => q.includes('prefers-color-scheme')"
    "  ? { matches: q.includes('dark') && " + dark + ", media: q,"
    "      addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {} }"
    "  : realMatchMedia(q);"
    "</script>"
)
page = open("index.html", encoding="utf-8").read()
assert page.count('<meta charset="utf-8">') == 1
open(f"{theme}.html", "w", encoding="utf-8").write(page.replace('<meta charset="utf-8">', stub, 1))
PY
done
```

Checked on 8b5d40d: both themes render, and the tiles read the final counts
in both.

**Firefox** needs two environment variables on macOS 27, and nothing else.
Without them every launch dies with `Could not find profile folder`, whatever
`-profile` names: macOS 27 denies a shell-launched process access to
`~/Library/Application Support/Firefox`, and Firefox reads that directory even
when given a profile elsewhere. Pointing `MOZ_APP_DATA` and
`MOZ_LOCAL_APP_DATA` at a directory under `data/` gives it app data of its
own. The diagnosis and the upstream fix (Firefox 158, after which the
variables can go) are in prcoder's
[firefox-runner README](https://github.com/gaurav/prcoder/blob/main/tools/firefox-runner/README.md).

Playwright's `color_scheme` and `reduced_motion` drive the page's own
`matchMedia` queries, so this needs neither the stub above nor a copy of
`index.html`. Serve the build as above, then:

```bash
cat > data/ff_shot.py <<'PY'
import os, sys
from pathlib import Path
from playwright.sync_api import sync_playwright
url, out, theme = sys.argv[1:4]
appdata = Path("data/firefox-appdata").resolve()
appdata.mkdir(parents=True, exist_ok=True)
env = {**os.environ, "MOZ_APP_DATA": str(appdata), "MOZ_LOCAL_APP_DATA": str(appdata)}
with sync_playwright() as p:
    browser = p.firefox.launch(env=env)
    page = browser.new_page(viewport={"width": 1700, "height": 1400},
                            reduced_motion="reduce", color_scheme=theme)
    page.goto(url)
    page.wait_for_timeout(1500)
    page.screenshot(path=out)
    browser.close()
PY
uv run --with playwright==1.64.0 python data/ff_shot.py \
  "http://localhost:8765/index.html?view=map" data/shots/map-dark.png dark
```

The Playwright version has to match a Firefox build in
`~/Library/Caches/ms-playwright/`: 1.64.0 wants `firefox-1555`, and
`uv run --with playwright==1.64.0 playwright install firefox` fetches it.
Checked on c6b97a8 with Firefox 157: Overview light and dark and Map dark
render, and the tiles read the final counts.

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

**The sticky header's offset is measured, not declared.** `--filters-height` is
set from the filter bar's real height on every render and on resize, because
the bar wraps to two lines at some widths and a hardcoded `top` hides the first
row underneath it.

**The theme cycle starts by moving away from the system**, not at light: the
page defaults to following the operating system, so `auto → light → dark`
would spend the first click repainting a light machine light and read as a
dead button. `nextTheme` therefore reads `prefers-color-scheme` to decide
which way to go first, and the one click that does not change the appearance
is the trip back to auto, which says so in the button's title.
