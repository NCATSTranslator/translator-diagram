# Design

How the parts of this repository fit together, and the few decisions that cut
across all of them. It is a map: each section says what is true and links to
where the detail and the reasons live, so that this file stays short enough to
keep accurate. What is still undecided is in [`FUTURE.md`](../FUTURE.md), not
here.

## The shape of it

```text
Google Sheet ──CSV──▶ generate-diagram ──▶ data/diagram.{dot,svg,png,json}
                                            (retires with #19)

catalog/components/*.yaml ─┐
                           ▼
SmartAPI, OpenAPI, ──▶ sync-components ──▶ data/sync/
/status, GitHub,         (network,          raw bodies + manifest.json
Helm, OTel, infores       no judgement)        │
                                               ▼
config/privacy.yaml ──────────────▶ build-dashboard ──▶ data/dashboard/
catalog/flow-steps.yaml             (judgement,          index.html
catalog/owner-colors.csv             no network)         overview.json
                                                            │
                                         pages.yml, from main
                                                            ▼
                                                     GitHub Pages
```

Three commands, two inputs, one published page. Everything they write goes
under the gitignored `data/`; nothing generated is committed, because what may
be published from the component list is still being decided
([#7](https://github.com/NCATSTranslator/translator-diagram/issues/7)).

## Two stacks over the same components

`generate-diagram` reads the Google Sheet and draws a Graphviz picture.
`sync-components` and `build-dashboard` read `catalog/components/*.yaml` and
render an HTML page. They describe the same components but not the same data.
`model.py` parses a sheet row and `components.py` parses a YAML file, and
neither imports the other; the two stacks meet only at `colors.py`, so a team
is the same colour in both.

That split is temporary and known. The component files are meant to replace
the sheet as the diagram's input too. The steps are in
[`FUTURE.md`](../FUTURE.md#retire-the-sheet-as-an-input), and until #19 lands
the diagram and the dashboard can disagree. The import rules that keep the
stacks apart, and `tests/test_package_layout.py` that enforces them, are in
the [module map](../src/translator_diagram/AGENTS.md#package-layout-srctranslator_diagram).

## The catalog records identity; everything else is pointed at

A component file records only what nothing upstream records: one id, its name
in every other naming space, its owner, where it sits, and the data flow
between components. Versions, descriptions, deployment URLs and resource
requirements are *pointed at*, never copied, because a second copy goes stale.
[`component-metadata.md`](component-metadata.md) makes that case and records
the decisions behind the format; [`metadata-sources.md`](metadata-sources.md)
surveys what each upstream source actually offers.

Everything a curator edits is in `catalog/`, and stays there so they never
need to open a Python module. When a change could go in one of those files or
in code, it goes in the file. Each file is validated by a schema, a test or a
hard error at build time, so a wrong edit fails loudly. The curator's guide is
[`catalog/README.md`](../catalog/README.md).

## Sync and build are separate on purpose

Fetching is slow and rate-limited; rendering is iterated on. So one sync
serves many builds, and the line between them is also a line between kinds of
code:

- **`sync-components` fetches and does not judge.** It follows every pointer,
  writes each raw body under `data/sync/`, and records *every* attempt, failed
  ones included, in `manifest.json`. A service being down is data, not an
  error: the run still succeeds, because "was this reachable just now" is the
  question the page exists to answer. It runs in two waves, because the
  registry and the chart index (wave one) say what the per-endpoint and
  per-chart fetches (wave two) should be.
- **`build-dashboard` judges and does not fetch.** Every decision about what a
  version is, which source wins, or why a cell is empty is made from the cache,
  so all of it is testable from a fixture directory with no network.
  `tools/replay_sync.py` replays a recorded sync offline, for comparing a
  change before and after.

## Where a fact comes from, and which wins

The page's main promise is that it never shows a fact it did not fetch, and it
always says which source a fact came from. Four orderings carry that:

| Question | Order, best first | Where |
|---|---|---|
| Where is it deployed? | recorded in the file › registered in SmartAPI › derived from the ITRB hostname convention | `deployments.merge_deployments` |
| Is a derived host real? | only if the document it serves reports the component's own `infores` | `sync._confirm_derived` |
| What version is running? | OpenAPI `info` › `/status` › SmartAPI › Helm, badged with which | `cells.build_cell`, `SOURCE_LABELS` |
| Does a cached body count? | only if *this* run fetched it with a 200 | `SyncedData` |

A cell with no version says why, from one vocabulary (`CELL_REASONS`), so "we
never asked" and "we asked and nothing is there" look different. Edges work
the same way: the recorded `connections:` are what this repository claims, and
the infores catalog's dataflow is shown beside them, drawn differently, so it
never reads as ours. Each of these rules was a bug first. The list, with the
bug behind each, is
[*What the dashboard refuses to claim*](../src/translator_diagram/AGENTS.md#what-the-dashboard-refuses-to-claim).

## Inside a build

A build is one pass, top to bottom. Steps 1–3 are `build_payload` in
`dashboard.py`; step 4 is `build-dashboard` itself:

1. **Rows.** `SyncedData` reads the cache, `cells` resolves each environment's
   cell, and `rows` assembles one row per component, in the stage order from
   `catalog/flow-steps.yaml` (hand-written, not computed).
2. **Redaction.** `privacy.apply` drops what `config/privacy.yaml` withholds.
3. **Everything counted or drawn from the rows.** The tiles, the stages, and
   the map's edges are built from the rows that survived, so none of them can
   mention a withheld component.
4. **Verification.** `build-dashboard` reads the finished payload back with
   `privacy.verify` before writing anything, rather than trusting step 2 to
   have reached every place a name could appear. It also refuses to write a
   page with no deployments at all.

The position of step 2 is the design. Rows are built from every component, so
a published build is the local build *minus rows*: the same order and the same
depths, with nothing renumbered or moved. The counts come after it, so a tile
can never count more than the table shows.

## Publishing

Redaction is the default. `build-dashboard` withholds unless given
`--include-private`, and the publishing workflow passes no flag, so it cannot
be edited into publishing a full build by leaving one out. The filter is about
*reach*, not secrecy: everything on the page comes from public services, so it
keeps a few facts off an indexed page rather than hiding them. A real secret
on the page would be one a public API is already serving, and the fix belongs
there. The reasoning is in `privacy.py`'s docstring.

`pages.yml` builds the page on every pull request as a downloadable artifact,
and deploys only from `main`, the nightly schedule, or a deliberate manual
run. Its comments say why a pull request never deploys.

## The page

`index.html` is self-contained. The CSS and JS under `src/translator_diagram/web/`
are concatenated in a fixed order and inlined, and the payload is embedded, so
the file works from `file://` with no server. The same payload is written
beside it as `overview.json`, the machine-readable contract. The two views,
Overview (the version table) and Map (the same components laid out by stage,
with their connections), read one payload, and the detail drawer serves both.

The JS is split by subject, and each file's pure helpers are tested under
`node --test` from `tests/web/`. How to render the page, measure it and look
at it, and the browser-side decisions, are in
[`web/AGENTS.md`](../src/translator_diagram/web/AGENTS.md).

## Where the rest is

| To find | Read |
|---|---|
| How to use the commands, and what the page shows | [`README.md`](../README.md) |
| How to work in this repository | [`CONTRIBUTING.md`](../CONTRIBUTING.md), and [`AGENTS.md`](../AGENTS.md) for what only an agent needs |
| Which module holds what, and which may import which | [`src/translator_diagram/AGENTS.md`](../src/translator_diagram/AGENTS.md) |
| Decisions that look wrong but aren't | the same file, *Things that look wrong but aren't* |
| What a component file contains | [`catalog/README.md`](../catalog/README.md) and its schema |
| Why the format looks the way it does | [`component-metadata.md`](component-metadata.md) |
| What each upstream source offers | [`metadata-sources.md`](metadata-sources.md) |
| What is not done yet | [`FUTURE.md`](../FUTURE.md) and the issue tracker |
