# src/translator_diagram/web/

The browser half of the dashboard: the CSS and JS that `CSS_FILES` and
`JS_FILES` in `dashboard.py` concatenate and inline into the generated page.
How to work in this repository is in
[../../../CONTRIBUTING.md](../../../CONTRIBUTING.md), and the Python side —
the payload this code reads, and which module builds which part of it — is in
[../AGENTS.md](../AGENTS.md).

## Looking at the page

`CONTRIBUTING.md` says to render the page and look before calling it fine, in
every view and both themes. This is how.

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

**`--force-prefers-reduced-motion` is not optional.** The map's nodes
stagger in and a view switch crossfades, and a screenshot without it catches
either mid-animation, which is indistinguishable from a rendering bug. (The
stat tiles that used to count up on load, and once invented a tile-counting
bug in exactly this way, are gone.)

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
`matchMedia("(prefers-reduced-motion: reduce)")` through `TD.motion.enabled`,
and a stub that returns `matches: false` for every query but the colour
scheme switches every animation back on (four shots taken with the flag above
once showed the then-tiles mid-count). This one answers the colour scheme
itself and hands every other query to the real `matchMedia`, so the flag
keeps working. Run it in the build directory; it writes `light.html` and
`dark.html` beside `index.html`:

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

Checked on 8b5d40d: both themes render.

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
render.

Shoot it narrow (`--window-size=760,1100`) and at the widths *between* the
breakpoints. Measured at fourteen widths from 760 to 1700px on the redrawn
table, `div.tablewrap` never overflows from 1000px up (`scrollWidth` equals
`clientWidth` at every step) with every row collapsed; at 900px and below
the environment columns run past the window and the wrap scrolls, so nothing
is unreachable. With every row open it holds too, measured at nine widths from
1000 to 1700px; three rules in `table.css` keep it so, each written where it
applies: the Owner column's labels wrap between 800 and 1150px, a host label
longer than its column may break inside itself there, and a long connection
name wraps inside its button. Each was a measured overflow first. The
earlier table overflowed between about 1490 and 1535px (issue #31) because a
wide-window rule widened the environment columns and the names and
repository slugs could not wrap; both are gone. The overflow is not visible
in a screenshot: measure `scrollWidth` against `clientWidth` at several
widths instead of judging by eye. At 760px the Map's EDGES legend still sits
over the Translator UI / Node Annotator row.

Serve the build over HTTP rather than opening `file://`: Map export and other
features are blocked on a `file://` origin, and the copies the theme stub
needs are simpler to reach over a server anyway.

**A change that should not move a pixel can be proved, not judged.** The
headless shell's screenshots are deterministic here: the same build, the same
flags and the same `--window-size` give byte-identical PNGs run after run, so
a refactor of the JS or CSS is checked the way `CONTRIBUTING.md` checks a
Python one — shoot before and after from one `data/sync/` snapshot and `cmp`
the files. Shoot every surface the change can reach: every view, both
themes, a narrow width, the Component view on a component with data in every
section (`?view=component&sel=arax`, scrolled down as well: the page is
taller than any window), and an expanded row (`?expand=<id>`).
The ten commits of #86 that only moved code (fd0c9c3–f6e7321) were each
checked this way; a differing PNG means something moved, and `--dump-dom` on
the two builds, diffed, says what. One pixel block is allowed to differ: the
sync note in the top bar says "N minutes ago" against the reader's clock,
so two shots minutes apart differ there and nowhere else. PIL's
`ImageChops.difference(a, b).getbbox()` names the box; a box confined to
the top bar's right end is the clock.

**To shoot a tooltip, hover it synthetically.** The headless shell's window is
never focused, so `element.focus()` fires no `focusin` and the tooltip stays
hidden; `dispatchEvent(new MouseEvent("mouseover", { bubbles: true }))` on
the element does open it. Pick the *visible* element: an expanded row writes
its label and (?) into every non-environment cell and shows one, so
`querySelector` finds a hidden copy with a zero-size box and the tooltip
lands at the top-left corner. Filter by `offsetParent`. And do not scroll
first: the page hides the tooltip on any scroll, so size the window to hold
the row instead. Run such loops under `bash`: in `zsh`, a loop variable
named `path` overwrites `PATH`.

Whether the result *reads* well is still the operator's call: report what you
saw and let them look.

## Testing JS with judgement in it

There is no JS harness here, and that has not stopped anything being tested.
The rule is that judgement is a pure function and the DOM is a thin layer over
it: the filter, the band grouping, the detail-field pruning and the cell
rendering in `table.js`, the edge kind, node version, reachability and tooltip
buckets in `map.js`, the catalog edge direction, the picker's groups, the
Recorded section and the whole page as a string in `component.js`, and the
cell model, the sync panel's figures, the theme cycle and
the clock formatting in `core.js` are all exported and driven under `node
--test` from `tests/web/`, which `tests/test_web_assets.py` runs. Anything
that needs a clock or the system preference takes it as an argument
(`relativeAge(iso, now)`, `TD.theme.next(choice, systemDark)`), so "a future
timestamp says today" is a test rather than a stub. What is still untested is
the DOM itself — the Component view's picker and click handling, the row
expansion animation — which issue #22 tracks. `TD.row` is where a fact about
a row is said once for every view.

## Things that look wrong but aren't

**This is not a module system, on purpose.** The files are concatenated in
`JS_FILES` order into one `<script>`. Each wraps its body in its own
`(() => { … })()`, so a `const` in one file cannot collide with one in
another; the only shared name is `TD`, which each file publishes its half of
the page on (`TD.fmt`, `TD.table`, `TD.map`, …) and reads the others' from.

The CSS has no such scope: `CSS_FILES` are concatenated into one stylesheet,
so a class name in `table.css` shares one namespace with `controls.css` and
the rest. Search `web/*.css` for a class before using it. A `.seg` in the
SmartAPI cell once picked up the segmented control's flex layout and
swallowed the space in "changed 5 months ago".

ES modules were considered and not adopted. The page has to open from
`file://`, where `import` across files is blocked, so modules would mean a
bundler and a Node toolchain inside a build that otherwise needs only Python,
in `build-dashboard` and in the Pages workflow alike. That belongs to the
whole-repository decision in issue #45, not to this directory. What modules
would have bought — load order made explicit, and a misspelled import caught
before a browser runs it — `tests/web/namespace.test.js` checks instead: it
runs the files in `JS_FILES` order and fails if a file reads a `TD` name
while loading before an earlier file defines it, or if any `TD.x` or `TD.x.y`
in the source names nothing. So moving a file in `JS_FILES` is safe exactly
when that suite passes.

**The page opens on every component**, having once opened on
`Environments disagree` — which showed 7 rows of 24 and hid the platform to
make a point about drift, so someone looking up one component found it missing
from a page that never said it was filtered. Drift is still the first thing the
page says, in the sync panel's shares. The views (`all`, `differ`, `known`,
`none`, `unreachable`, `unregistered`, `no-smartapi`) live in `SHOW_VIEWS` in
`table.js`, listed in that order so the default reads first, with
`DEFAULT_VIEW` naming it. `differ` means any of the three tinted axes, not
versions alone. It replaced a "Drift only" toggle rather than joining it: two
controls that select the same rows cannot be told apart by a reader. The last
three are the complements of the sync panel's shares, which link to them.

**The table is a tinted board, and it was chosen over two others.** Three
directions were mocked up over the real payload and compared side by side: a
ruled ledger on the page's own tokens, this status matrix, and a GitHub-styled
table. The matrix won because the four environment columns are what a reader
comes to compare, and a tint per state lets them be read without reading
every cell; the GitHub mockup's rounded pills and underlined links were kept
because they parse faster than hairline rectangles. The mockups were deleted
once the choice was made (the commit that deleted them says why), and their
shared cell model moved into `core.js` as `TD.cell`. Two rules in the tint:
a lone deployment is not tinted "same", because it agrees with nobody; and an
absence the page is sure of (no such host, no server listed, not a hosted
service) is left white, while "no address on file" — the page's own gap — is
grey.

**The expanded row's label sits beside the environments, not in the first
column.** It is written into every non-environment cell and CSS shows the
rightmost one still on screen (`td.dk-smartapi .dkl` and the ladder under it
in `table.css`). The first-column
label was tried in #90 and read as detached from the numbers it named; the
ladder is more rules, and the right answer.

**An expanded row's connections are decided in JS, at render time.** They
fill the Component column of the detail rows, which is empty above 800px
because the labels sit in the rightmost non-environment column (the ladder).
They are one cell with a `rowspan`, and a rowspan cannot be undone in CSS:
hiding that cell at 800px, where the Component column becomes the label
column, would move every later row's cells one column left. So
`detailRowsHtml` takes `narrow` as an argument, `isNarrow` reads `NARROW` in
`table.js`, a `change` listener on it redraws the open rows, and the 800px
there and in the ladder must change together. The rows the cell spans start
at Owner, so `tr.detail.spanned` stops that cell being sticky or drawing the
group spine. The grouping is `TD.row.connections`, which the Component view
reads too.

**A component's name in the table is not a link.** A click on it opens the
row, like a click anywhere else on the row, because the open row is where the
connections are and it is the better first click. The page is behind the
arrow at the cell's right edge, which sits in the same place on every row so
the arrows read as a column without costing one, and behind a labelled button
at the top of the open row. A new column for it would have had to take width
from the environment columns.

**A component has a view of its own, not a drawer beside the table.** The
440px side drawer this replaced could not fit its six tabs on one row, could
not show two environments side by side, and needed its own column ladder in
the table CSS so the table would not run under it. The Component view shows
every section at once, at full width, and the table no longer shares the
window. It is a view of the one page, `?view=component&sel=<id>`, and not a
separate HTML file per component: #51 weighed that and turned it down,
because each file would inline the payload again and `privacy.verify` would
have to cover every copy.

**The view reuses `sel` rather than a key of its own.** #51 used
`component=<id>` because `sel` then meant "the drawer is open"; with the
drawer gone, one key for "the component being looked at" lets the table's
highlighted row, the map's ring and the Component view's subject follow each
other, and Show on map is just a change of `view`. `TD.navigate`, unlike
`TD.commit`, pushes a history entry, and records the picked component on the
entry it leaves, so Back lands on the row highlighted rather than on the
table as it was before the click.

**The picker is a native `<select>`.** Twenty-seven components in stage
groups, found by typing: the browser's own control does type-to-find, the
keyboard and a phone's picker, and `TD.ui.listbox` would have had to be
taught all three.

**The SmartAPI column says what to do, not whether a record exists.** It
used to print "registered" for every record and draw the registry's
`uptime_status` as green for `pass` and red for anything else, so the three
shepherds, whose paths the registry skipped (`unknown`), looked as broken as
RTX/ARAX's failing probe, and Retriever and PloverDB, whose recorded ids match
no Translator-tagged record, read "not registered". `TD.smartapi.status`
(`core.js`) now names one state per row, worst first, and the cell, the
column's sort and its tooltip all read it, so they cannot disagree. Only
`pass` is green. The cell's date is the record's own `meta.last_updated`, not
`last_updated`: that one is the newer of the release and the registration,
and showing it only when the registry won hid the registry date from every
component with a newer release, and the release date from the Repository
column of every component whose registration was newer.

**Environment columns sort by the age of the release running there**, not by
version string: comparing `2.10.2` against `1.0` across two different
components means nothing. Cells rank in tiers — running a release we can date,
running something no release names, not deployed — and the tiers hold in both
directions.

**The theme cycle starts by moving away from the system**, not at light: the
page defaults to following the operating system, so `auto → light → dark`
would spend the first click repainting a light machine light and read as a
dead button. `TD.theme.next` (core.js) therefore takes the system preference
to decide which way to go first, and the one click that does not change the
appearance is the trip back to auto, which says so in the button's title.
