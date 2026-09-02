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
| [`docs/public-private-split.md`](docs/public-private-split.md) | The private-repository design for issue #7: the border, the refresh workflow, the go-private runbook |
| [`content/README.md`](content/README.md) | What the generated `content/` tree holds and how to rebuild it |
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
  environment columns unreachable at narrow widths. Render it and look —
  headless Firefox needs no extra tooling, and its own profile because yours is
  probably already running:

  ```bash
  uv run build-dashboard
  MOZ_NO_REMOTE=1 /Applications/Firefox.app/Contents/MacOS/firefox \
    --headless --new-instance --profile /tmp/ffprofile \
    --screenshot /tmp/dash.png --window-size=1700,1400 \
    "file://$PWD/data/dashboard/index.html"
  ```

  Shoot it narrow (`--window-size=760,1000`) and at the widths *between* the
  breakpoints — the table is wider than the window between about 1100 and
  1500px, which is where the sticky header and the band descriptions go wrong.
  Whether the result *reads* well is still the operator's call: report what you
  saw and let them look.

  A headless profile follows the system theme, so on a dark machine every
  screenshot is dark and half the palette goes unchecked. A second profile with
  one pref shoots the other theme (use `1` for dark on a light machine):

  ```bash
  mkdir -p /tmp/fflight && echo 'user_pref("ui.systemUsesDarkTheme", 0);' > /tmp/fflight/user.js
  ```

- **JS with judgement in it can be tested, even with no JS harness here.** Slice
  the block out of `web/dashboard.js`, stub `document`/`localStorage`/
  `matchMedia`, and run it under `node` from the scratchpad — that is how the
  theme cycle was checked against both system preferences, and how the sort
  comparators were driven over the real `overview.json` to prove undated rows
  stay last in *both* directions. Throwaway scripts, not fixtures: nothing in
  CI runs JS beyond `node --check`.
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
uv run build-content --diagram                       # -> content/, nothing withheld

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

## What is committed, and what is not

`data/` is gitignored in its entirety, so no downloaded CSV, sync cache or
dashboard build is in the repo. `content/` is the one generated tree that
*is* committed, on purpose: it is what people with repository access read,
and `tests/test_content.py` fails when its static half is behind
`components/`. After editing a component file, run `uv run build-content`
and commit the result with the edit. Never edit anything under `content/`
by hand except its README.

The repo is public today, so the `private:` blocks in `components/` hold the
placeholder `PRIVATE` and nothing real. Do not put a real private value
anywhere in this repository until it is private — see
[`docs/public-private-split.md`](docs/public-private-split.md) and
[issue #7](https://github.com/NCATSTranslator/translator-diagram/issues/7).
