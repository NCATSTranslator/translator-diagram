# translator-diagram

Two commands over the Translator platform's components, in one package under
`src/translator_diagram/`: `generate-diagram` renders Graphviz pictures from a
Google Sheet CSV, and `build-dashboard` renders a self-contained HTML page from
`catalog/components/*.yaml`. [README.md](README.md) is the user-facing
documentation and the faster way in.

**These notes are `AGENTS.md` files, and there is no `CLAUDE.md` on
purpose.** Claude Code reads `AGENTS.md` natively from v2.1.277, and in
every session type from v2.1.281, the version `CONTRIBUTING.md` asks for,
but only where there is no `CLAUDE.md` or `CLAUDE.local.md`: one in the
working directory or above it switches it to reading `CLAUDE.md` files alone,
and one in a subdirectory hides that directory's `AGENTS.md`. Either way
these notes drop out silently, so put new ones in the nearest `AGENTS.md`.
`tests/test_agent_files.py` fails on either file anywhere in the checkout, a
gitignored personal `CLAUDE.local.md` included.

This file is what applies to every session. The detail that only matters once
you are in a particular directory lives beside that directory, so it is read
when it is relevant rather than every time:

| Where | What is in it |
|---|---|
| [`docs/design.md`](docs/design.md) | How the parts fit together: the two stacks, sync versus build, which source wins, where redaction sits. The map to everything below |
| [`src/translator_diagram/AGENTS.md`](src/translator_diagram/AGENTS.md) | The module map, the import rules, the data model, "I want to change X → open this", and two sections of decisions that look wrong and aren't. **Read it before changing any module.** |
| [`src/translator_diagram/web/AGENTS.md`](src/translator_diagram/web/AGENTS.md) | The browser half: how to screenshot and measure the page, how to test its JS, and the browser-side decisions that look wrong and aren't |
| [`catalog/AGENTS.md`](catalog/AGENTS.md), [`catalog/README.md`](catalog/README.md) | Everything a curator edits. The README is the guide: what a component file must contain, what each `unknown.yaml` status means, and which rules the tests enforce |
| [`docs/component-metadata.md`](docs/component-metadata.md) | Why that file format looks the way it does |
| [`docs/metadata-sources.md`](docs/metadata-sources.md) | What each upstream source actually offers, surveyed |
| [`catalog/owner-colors.md`](catalog/owner-colors.md) | The four constraints on a new team colour |
| [`docs/Security.md`](docs/Security.md) | What the published page must not leak, what the build must not become, and the checklist for a change that adds a field, source or fetch |
| [`FUTURE.md`](FUTURE.md) | Ideas with their costs worked out |

**Read first:** [CONTRIBUTING.md](CONTRIBUTING.md), which is how to work in
this repository and applies to agents as much as to people: the setup, the
checks CI runs, how to check your work, and the conventions. Claude Code loads
it through the import below; any other agent should read it before a first
change. Then *What only an agent needs* below, and, before simplifying
anything in the code, *Things that look wrong but aren't* in
[`src/translator_diagram/AGENTS.md`](src/translator_diagram/AGENTS.md) — most
entries are there because someone already tried the obvious thing.

@CONTRIBUTING.md

## What only an agent needs

- **Do not read `.env`** — it holds the real Google Sheet ID. If you need to
  work against another local checkout of a Translator repo, `git clone` it into
  `data/` rather than reading the working copy, so you can't pick up its
  secrets.
- **Report what you saw; don't call a picture or a page good.** Render and
  look as *Checking your work* in `CONTRIBUTING.md` says, then say what
  changed and what you saw: whether it *reads* well is the operator's call.
- **The commands are a person's tools first.** You will run
  `generate-diagram`, `sync-components` and `build-dashboard` as checks, but
  they must stay easy to run by hand.
