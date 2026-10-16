# Contributing

How to work in this repository, for people and coding agents alike.
[README.md](README.md) is how to use the commands; this file is how to change
them. Agents also read [AGENTS.md](AGENTS.md), which adds the few rules only an
agent needs and maps the per-directory notes.

**If you use Claude Code, use v2.1.281 or later.** There is deliberately no
`CLAUDE.md` here (AGENTS.md says why), and Claude Code reads `AGENTS.md` only
from v2.1.277, and in every session type only from v2.1.281. An older version
loads none of this repository's notes, including the rule not to read `.env`,
and nothing warns you.

## Setup, and the checks CI runs

```bash
uv sync                # first-time setup; creates .venv/
uv run pytest          # the test suite
uv run ruff check      # Python lint
uv run rumdl check .   # Markdown lint
```

All of these run on every pull request (`.github/workflows/ci.yml`).
`pages.yml`, which builds the dashboard, does not: it deploys from `main`, and
runs on a branch only when asked to, as README.md's *The components dashboard*
describes. The JS tests in `tests/web/` run under `node --test` from inside
`pytest`; without Node 18 or later on `PATH` they skip rather than fail, and CI
has one.

The commands, as you will run them while working:

```bash
uv run sync-components                               # -> data/sync/
uv run build-dashboard                               # -> data/dashboard/
uv run build-dashboard --include-private             # ignore config/privacy.yaml
uv run build-dashboard --watch                       # stays running; see below

uv run generate-diagram --input data/components.csv  # from a local CSV
uv run generate-diagram --google-sheet               # the real sheet
```

`sync-components` and `build-dashboard` are split because fetching is slow and
rate-limited while rendering is iterated on: one sync serves a hundred
rebuilds. Every other command here writes its output and exits;
`build-dashboard --watch` builds once and then keeps running, rebuilding
`data/dashboard/` each time a component file, the sync cache, `catalog/`,
`config/` or the code changes, until you stop it with Ctrl-C. Run it in a
terminal of its own, beside `python3 -m http.server`, and reload the tab to see
each rebuild. `--google-sheet` reaches the real sheet, so prefer a local CSV
when testing. The README has every flag.

## Before a first change

Read [docs/design.md](docs/design.md) for how the parts fit together, and
then, before simplifying anything, *Things that look wrong but aren't* in
[src/translator_diagram/AGENTS.md](src/translator_diagram/AGENTS.md). Most
entries there exist because someone already tried the obvious thing. The same
file has the module map and the rule about which module may import which,
which `tests/test_package_layout.py` enforces.

The per-directory `AGENTS.md` files are written for agents, but nothing in
them is agent-only: they are where this repository keeps the detail that only
matters inside one directory.

## Checking your work

- **After changing code, run `uv run pytest`.** Running
  `uv run generate-diagram` is often the right check too; write its output
  somewhere under `data/`. Whether the picture *reads* well — crossing edges,
  cramped clusters, a legend in an awkward place — cannot be judged from a
  diff, so say in the pull request what changed and let the reviewer look.
- **Look at the dashboard before saying it is fine.** Structural checks do not
  catch visual bugs: this page once passed 301 tests, `node --check` and a
  self-containment assertion while shipping a badge on 27 of 45 cells that
  drowned the table, a tile that counted 74 things where there were 41, and two
  environment columns unreachable at narrow widths. Render it and look, in
  **both views** (Overview and Map) and in light and dark. The recipe — which
  browser, frozen animations, forcing the theme, and which widths to measure
  rather than eyeball — is in
  [src/translator_diagram/web/AGENTS.md](src/translator_diagram/web/AGENTS.md),
  along with how to test the JS without a harness.
- **When a change should not alter the output, prove it.** Generate from a
  sample CSV before and after and compare: the `.dot`, `.json`, `.svg` and
  `.png` are all byte-identical for a change that only moves code. (A `.pdf`
  never is: it embeds a creation timestamp.) This is stronger than reading the
  diff, and it needs no aesthetic judgement.

  The dashboard works the same way: build from one `data/sync/` before and
  after, and `overview.json` and `index.html` are byte-identical. (`web/*.js`
  and `*.css` are inlined verbatim, comments included, so editing a comment
  there changes `index.html`; `diff` it to confirm only the comment moved.)
  `sync` itself cannot be compared across two live runs, because upstream
  answers change in between, so replay a recorded one with
  `tools/replay_sync.py` — its docstring has the recipe.

## Conventions

- **`data/` is gitignored scratch space.** Use it rather than `/tmp` for
  sample CSVs, cloned repositories, screenshots and anything else you write
  while working, and never commit anything from it.
- **The default branch is `main`**, and work happens on feature branches.
- **One test file per module**, and a test belongs to the module whose
  *decision* it pins, not to the function it happens to call — the module map
  says why.
- **Deliberate simplifications with a known ceiling are marked** with a
  `ponytail:` comment naming the ceiling and the upgrade path.
- **Record what didn't work.** An approach that was tried and failed goes in
  the commit message, or, if someone is likely to try it again, beside the
  code it would change or in the nearest `AGENTS.md`. That is what the *Things
  that look wrong but aren't* sections are.

## The catalog and config are data, not code

Everything under `catalog/` — the component files, `unknown.yaml`,
`flow-steps.yaml`, `owner-colors.csv` and their schemas — is edited by people
who know the platform and do not want to open a Python module, and it is kept
in that one directory so they never need to look outside it.
`config/privacy.yaml` is the same kind of file, but a publication decision
rather than curation. That is deliberate and worth protecting: when a change
could be made either in one of those files or in code, it belongs in the file.
Each is validated — by a schema, a test, or a hard error at build time — so a
wrong edit fails loudly rather than silently doing nothing. The curator's
guide is [catalog/README.md](catalog/README.md).

## What is not committed

`data/` is gitignored in its entirety, so no generated diagram, `.dot`, `.json`
or downloaded CSV is in the repository. That is currently load-bearing: this
repository and its GitHub Pages site are public, and what may be published
from the component sheet is still being decided — see
[issue #7](https://github.com/NCATSTranslator/translator-diagram/issues/7).
Don't commit generated artifacts without checking first.
