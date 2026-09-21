# translator-diagram

Two commands over the Translator platform's components, in one package under
`src/translator_diagram/`: `generate-diagram` renders Graphviz pictures from a
Google Sheet CSV, and `build-dashboard` renders a self-contained HTML page from
`components/*.yaml`. [README.md](README.md) is the user-facing documentation and
the faster way in.

This file is what applies to every session. The detail that only matters once
you are in a particular directory lives beside that directory, so it is read
when it is relevant rather than every time:

| Where | What is in it |
|---|---|
| [`src/translator_diagram/CLAUDE.md`](src/translator_diagram/CLAUDE.md) | The module map, the import rules, the data model, "I want to change X → open this", and two sections of decisions that look wrong and aren't. **Read it before changing any module.** |
| [`components/CLAUDE.md`](components/CLAUDE.md) | What a `components/<id>.yaml` must contain and which rules the tests enforce on it |
| [`docs/component-metadata.md`](docs/component-metadata.md) | Why that file format looks the way it does |
| [`docs/metadata-sources.md`](docs/metadata-sources.md) | What each upstream source actually offers, surveyed |
| [`docs/owner-colours.md`](docs/owner-colours.md) | The four constraints on a new team colour |
| [`FUTURE.md`](FUTURE.md) | Ideas with their costs worked out |

**Read first:** *Working agreements* below. Then, before simplifying anything in
the code, *Things that look wrong but aren't* in
[`src/translator_diagram/CLAUDE.md`](src/translator_diagram/CLAUDE.md) — most
entries are there because someone already tried the obvious thing.

## Working agreements

- **After changing code, run `uv run pytest`.** Running
  `uv run generate-diagram` yourself is fine and often the right check — write
  its output somewhere under `data/`. What you cannot do from a diff is judge
  whether the picture *reads* well: crossing edges, cramped clusters, a legend
  in an awkward place. That is the operator's call, so report what changed and
  let them look rather than declaring the result good.
- **Look at the dashboard before saying it is fine.** Structural checks do not
  catch visual bugs: this page once passed 301 tests, `node --check` and a
  self-containment assertion while shipping a badge on 27 of 45 cells that
  drowned the table, a tile that counted 74 things where there were 41, and two
  environment columns unreachable at narrow widths. Render it and look, in
  **both views** (Overview and Map) and in light and dark.

  **Use Chromium, not Firefox.** Headless Firefox does not start on current
  macOS — every invocation dies with `Could not find profile folder`, whatever
  you pass for `--profile`, including a directory that demonstrably exists
  ([gaurav/prcoder#61](https://github.com/gaurav/prcoder/issues/61)). The
  recipe here used to be Firefox; it is kept only as the reason not to try it
  again. Playwright's bundled headless shell needs no install:

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

  **`--force-prefers-reduced-motion` is not optional.** The stat tiles count
  up on load, and a screenshot without it catches them mid-animation: the page
  reads `3 components · 6 deployments` when there are 24 and 51. That is
  indistinguishable from the tile-counting bug listed above, so a naive shot
  invents a bug that is not there. Freeze the animation, then check the tiles
  against what `build-dashboard` printed.

  **Forcing the theme needs a `matchMedia` stub, not a flag.** Chromium's
  `--force-dark-mode` does not move the page's `prefers-color-scheme`, and the
  shots come back byte-identical. The page resolves its theme through
  `matchMedia("(prefers-color-scheme: dark)")` (`web/app.js`), so copy
  `index.html` beside itself — relative paths must still resolve — and inject a
  script before the bootstrap that returns a fixed `matches` for that query.
  This is the same stubbing trick as the JS note below.

  Shoot it narrow (`--window-size=760,1100`) and at the widths *between* the
  breakpoints. Measured across 1000–1600px, `div.tablewrap` overflows only
  between about **1490 and 1535px** — 30px over at 1500, 10px at 1520, clean
  at 1480 and 1540 — where a column returns before there is room for it. The
  page root never overflows at any width, and the wrap scrolls, so nothing is
  unreachable; issue #31 describes the wider 1100–1500px version of this,
  most of which is now gone. At 760px the PROD column is likewise clipped but
  reachable. None of this is visible in a screenshot: measure `scrollWidth`
  against `clientWidth` at several widths instead of judging by eye.

  Serve the build over HTTP rather than opening `file://`: Map export and
  other features are blocked on a `file://` origin, and the copies the theme
  stub needs are simpler to reach over a server anyway.

  Whether the result *reads* well is still the operator's call: report what you
  saw and let them look.
- **JS with judgement in it can be tested, even with no JS harness here.** Slice
  the block out of `web/table.js` or `web/core.js`, stub `document`/`localStorage`/
  `matchMedia`, and run it under `node` from the scratchpad — that is how the
  theme cycle was checked against both system preferences, and how the sort
  comparators were driven over the real `overview.json` to prove undated rows
  stay last in *both* directions. Layout and URL-state units live in
  `tests/web/` and run under `node --test` via `tests/test_web_assets.py`.
- **When a change should not alter the output, prove it.** Generate from a
  sample CSV before and after and compare — the `.dot`, `.json`, `.svg` and
  `.png` are all byte-identical for a change that only moves code. (A `.pdf`
  never is: it embeds a creation timestamp.) This is stronger than reading the
  diff, and it does not need an aesthetic judgement.
- **`data/` is gitignored scratch space. Use it instead of `/tmp`** for
  temporary files, sample CSVs, cloned repos, or anything else you need to
  write while working. Never commit anything from it.
- **Do not read `.env`** — it holds the real Google Sheet ID. If you need to
  work against another local checkout of a Translator repo, `git clone` it into
  `data/` rather than reading the working copy, so you can't pick up its
  secrets.
- Default branch is `main`; work happens on feature branches.
- Deliberate simplifications with a known ceiling are marked with a
  `ponytail:` comment naming the ceiling and the upgrade path.

## Quick start

```bash
uv sync                                              # first-time setup
uv run pytest                                        # after every change
uv run ruff check                                    # Python lint, gated in CI
uv run rumdl check .                                 # Markdown lint, gated in CI

uv run sync-components                               # -> data/sync/
uv run build-dashboard                               # -> data/dashboard/
uv run build-dashboard --include-private             # ignore config/privacy.yaml

uv run generate-diagram --google-sheet               # most common
uv run generate-diagram --input data/components.csv  # from a local CSV
```

`sync-components` and `build-dashboard` are split because fetching is slow and
rate-limited while rendering is iterated on — one sync serves a hundred
rebuilds. `--google-sheet` reaches the real sheet, so prefer a local CSV when
testing. Both commands must stay easy for a human to run: run them yourself when
it helps. The README has the full flag list.

## The four config files are data, not code

`config/owner-colors.csv`, `config/flow-steps.yaml`, `config/privacy.yaml` and
`components/*.yaml` are edited by people who know the platform and do not want
to open a Python module. That is deliberate and worth protecting: when a change
could be made either in one of those files or in code, it belongs in the file.
Each is validated — by a schema, a test, or a hard error at build time — so a
wrong edit fails loudly rather than silently doing nothing.

## What is not committed

`data/` is gitignored in its entirety, so no generated diagram, `.dot`, `.json`
or downloaded CSV is in the repo. That is currently load-bearing: this repo and
its future GitHub Pages site are public, and what may be published from the
component sheet is still being decided — see
[issue #7](https://github.com/NCATSTranslator/translator-diagram/issues/7).
Don't commit generated artifacts without checking first.
