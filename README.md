# translator-diagram

Two views of the
[NCATS Biomedical Data Translator](https://ncats.nih.gov/research/research-activities/translator)
platform, built from the same set of components:

- **The dashboard** — a single self-contained HTML page with one row per
  component, showing which version each environment is running, where that
  version was read from, and where the environments disagree.
- **The diagram** — Graphviz pictures of how data flows between components and
  which services call each other.

They are two commands over two sources that are converging: the dashboard reads
`catalog/components/*.yaml`, which are committed here; the diagram still reads a
Google Sheet. Merging them is
[issue #19](https://github.com/NCATSTranslator/translator-diagram/issues/19).

The platform comprises many components maintained by different teams, and both
views exist to make the whole thing visible at once — to people inside the
project who need to see how the pieces fit together, to performance work that
needs a map of where the bottlenecks might be (usefully combined with our
OpenTelemetry data), and to people outside the project trying to understand how
Translator works.

## Start here

Requires Python ≥ 3.11 and [uv](https://docs.astral.sh/uv/) — and for the
dashboard, nothing else. No credentials, no Graphviz, no spreadsheet access:

```bash
uv sync                    # first-time setup; creates .venv/
uv run sync-components     # follow what catalog/components/*.yaml points at -> data/sync/
uv run build-dashboard     # compile that into a page      -> data/dashboard/
python3 -m http.server 8765 --directory data/dashboard
# then open http://localhost:8765/ (Ctrl-C stops the server)
```

That takes about ten seconds of network time and reaches only public services.
Everything it fetches is cached under `data/`, which is gitignored, so nothing
you run can dirty the repository.

The page inlines its own data, so `open data/dashboard/index.html` works
without a server too, but browsers block map export, clipboard copy and some
other features from `file://`.

### The diagram needs two more things

The [Graphviz](https://graphviz.org/) system package (`brew install graphviz`,
or `apt-get install graphviz`), and read access to the Google Sheet the
component list still lives in — copy [`env.default`](env.default) to `.env` and
fill in `GOOGLE_SHEET_ID`.

```bash
uv run generate-diagram --google-sheet          # download the sheet, then render
uv run generate-diagram                         # use the cached data/components.csv
uv run generate-diagram --all                   # include non-refactor components
uv run generate-diagram --google-sheet --format pdf
uv run generate-diagram --google-sheet --layer-column Tier
```

The default view filters to components active in the current refactor
("Continues into Refactor" and "New in Refactor"), so the picture stays focused
on what is currently relevant.

## Where things live

| If you want to | Look at |
|---|---|
| add or change a component, or investigate an unattributed identifier | [`catalog/`](catalog/), whose [README](catalog/README.md) is the curator's guide |
| change what a component records | `catalog/components/<id>.yaml`, and [`catalog/schema/component.schema.json`](catalog/schema/component.schema.json) for the field reference |
| change the dashboard's row order or its stage descriptions | [`catalog/flow-steps.yaml`](catalog/flow-steps.yaml) |
| change a team's colour | [`catalog/owner-colors.csv`](catalog/owner-colors.csv), with the four constraints in [`catalog/owner-colors.md`](catalog/owner-colors.md) |
| change what a published dashboard withholds | [`config/privacy.yaml`](config/privacy.yaml) |
| change the code | `src/translator_diagram/`, with the module map in [`src/translator_diagram/AGENTS.md`](src/translator_diagram/AGENTS.md) |
| see how the parts fit together | [`docs/design.md`](docs/design.md) |
| know why something is the way it is | [CONTRIBUTING.md](CONTRIBUTING.md) for how to work here, [`src/translator_diagram/AGENTS.md`](src/translator_diagram/AGENTS.md) for the code and [`web/AGENTS.md`](src/translator_diagram/web/AGENTS.md) for the page — particularly *Things that look wrong but aren't* |
| see what is planned | the [issue tracker](https://github.com/NCATSTranslator/translator-diagram/issues) and [`FUTURE.md`](FUTURE.md) |

The first four are data files, editable by anyone who knows the platform
without opening a Python module. That is deliberate, and worth keeping.

## Input data

### Google Sheet

The canonical source of truth is a world-readable Google Sheet. Its ID is
stored in `.env` (gitignored; never committed). Copy [`env.default`](env.default)
to `.env` and fill it in:

```dotenv
GOOGLE_SHEET_ID=<paste the sheet ID here>
```

Run with `--google-sheet` to download the latest CSV export into `data/` and
use it immediately. The downloaded file is also gitignored.

The `.env` in the working directory, or the nearest one above it, is the one
that is read — so run the tool from your checkout, or set `GOOGLE_SHEET_ID` in
the environment.

### CSV format

The sheet must have an `id` column; everything else is optional (order does
not matter, and unknown columns are ignored). A CSV with no `id` column at all
is an error rather than an empty diagram — that is what pointing `--sheet-gid`
at the wrong tab looks like.

| Column | Description |
|---|---|
| `id` | Unique machine-readable identifier (kebab-case preferred) |
| `Name` | Human-readable display name shown in the diagram |
| `Owner` | Team that owns the component; controls node colour |
| `URL` | Link to the component's repo or docs; makes the node clickable in SVG output. Must be `http://` or `https://` — anything else is dropped with a warning |
| `Component in ITRB` | ITRB category (informational only) |
| `Refactor status` | Lifecycle status — see filtering below |
| `Gets results from` | Comma-separated IDs this component receives data from |
| `Calls` | Comma-separated IDs this component makes optional API calls to |
| `Externals` | Entities outside the diagram — `<Name` feeds in, `>Name` receives out. A name with neither prefix has no direction to draw and is dropped with a warning |
| `Part of` | Groups this component into a named cluster box |
| `Hosted at` | Deployment location; `ITRB` is the default and shown as nothing |
| `Ubiquitous` | `TRUE` to render this component as a per-caller clone (see below) |
| `Hide` | `TRUE` to suppress the component entirely: not as a ghost node, and not in `components.json` either |
| `Notes` | Free-text notes; shown as an SVG hover tooltip, not in the diagram |

IDs are matched case-insensitively; a case mismatch is a warning. An unknown
ID, a duplicate ID, and two things that would end up sharing one SVG id (see
[SVG output and links](#svg-output-and-links)) are hard errors that stop the
run.

#### Planned (not-yet-implemented) relationships

Prefix any ID in `Gets results from` or `Calls` with `~` to mark it as
planned but not yet implemented:

```text
Gets results from: nodenorm-es, ~new-service
Calls: ars, ~future-api
```

Planned edges render in red; implemented edges render in black.

#### Ubiquitous components

Cross-cutting infrastructure that nearly every component depends on
(telemetry, name resolution, logging…) creates long converging edges in
the diagram that obscure the real data-flow structure. Marking such a
component `TRUE` in the `Ubiquitous` column renders it as a small copy
next to each caller instead of as a single central node — the underlying
data stays normalised, only the visual layout duplicates. Jaeger (OTel)
is the canonical example.

## Output files

All outputs go to `data/` (gitignored) by default.

| File | Always? | Description |
|---|---|---|
| `data/diagram.png` | yes | Main shareable diagram |
| `data/diagram.dot` | yes | Graphviz source — useful for debugging or tweaking |
| `data/components.json` | yes | Every parsed component except the hidden ones (all statuses, not status-filtered) |
| `data/diagram_owners.png` | default | Owner-colour legend |
| `data/diagram_legend.png` | default | Edge-style legend |
| `data/diagram.pdf` | `--format pdf` | Vector format for presentations |
| `data/diagram.svg` | `--format svg` | Vector format for web embedding |
| `data/diagram_<layer>.png` | `--layer-column` | One sub-figure per distinct column value |
| `data/diagram_<layer>.dot` | `--layer-column` | Graphviz source for each sub-figure |

The two legend files are written separately by default; `--no-split-legends`
embeds them in the main diagram instead.

`<layer>` is the layer's value with punctuation folded to `_`. Two values that
fold to the same stem (`Tier 1` and `Tier-1`) would overwrite each other, so
the second gets a `_2` suffix and a warning.

## Component metadata files

Everything a curator edits is under [`catalog/`](catalog/), and
[`catalog/README.md`](catalog/README.md) is the guide to it: how to add a
component, the rules the tests enforce, and what each `unknown.yaml` status
means.

`catalog/components/<id>.yaml` records one file per component: what it is
(owner, refactor status, layer, where it runs), its identifier in each of the naming
spaces Translator uses (GitHub repo, Helm chart, infores CURIE, wiki page),
ITRB's own `app` and `group`, links to its repositories and documentation, and
the `connections:` edges between components.
[`catalog/schema/component.schema.json`](catalog/schema/component.schema.json)
is the field reference; `tests/test_component_files.py` validates every file
against it, and `tests/test_components.py` covers the parser.

These files are the dashboard's only input, and they are committed — which is
why the dashboard needs no credentials to run.

[`catalog/unknown.yaml`](catalog/unknown.yaml) is the holding pen for
identifiers seen in the platform that no component file claims yet —
currently OpenTelemetry service names and Helm chart directories. Entries
leave it by being promoted into a component file or confirmed out of use.

**The dashboard reads these files; the diagram does not.**
`build-dashboard` follows their pointers, but `generate-diagram` still loads
the sheet CSV — switching it over is
[issue #19](https://github.com/NCATSTranslator/translator-diagram/issues/19).
The case for the format is in
[`docs/component-metadata.md`](docs/component-metadata.md); the survey of what
each upstream source actually offers is in
[`docs/metadata-sources.md`](docs/metadata-sources.md), and
[`docs/examples/name-lookup-enriched.yaml`](docs/examples/name-lookup-enriched.yaml)
shows what a fetcher builds from one of them.

## The components dashboard

A single self-contained HTML page with three views over the same payload:

- **Overview** — one row per component, in stages (data coming in at the top,
  the people who use it at the bottom), with a cell per environment tinted by
  its state: the same version as the rest of the row, a different one, up
  with no version to read, down, or nothing on file. The version links to the
  document it was read from, and the data release it has loaded (`babel
  2025sep1`) sits under it.
- **Map** — an interactive SVG diagram of which component connects to what,
  laid out in the same stages, with pan/zoom, hover highlighting and SVG/PNG
  export.
- **Component** — one component on a page of its own, chosen from a picker:
  its environments side by side, one row per fact with a link to every
  document a fact was read from, then its overview, SmartAPI registration,
  releases, Helm chart and connections, and its catalog file field by field
  against the schema, marked recorded, "checked: none" or "not recorded".

Click a component's name in the table, or a node on the map, to open its
Component page; Back returns to where you were. Click anywhere else on a row,
or its chevron, to expand it inline for a side-by-side environment read
without leaving the table: one line per fact, each with a (?) that says where
its values come from, the component's releases under its repository, and,
under its name, what it gets results from, provides them to, calls and is
called by, each opening that component's page. (Below 800px wide that column
holds the labels instead, and the connections are on the Component page.) A
legend beside the filters says what the cell colours mean.

```bash
uv run sync-components     # follow the pointers, cache into data/sync/
uv run build-dashboard     # compile           into data/dashboard/
python3 -m http.server 8765 --directory data/dashboard   # http://localhost:8765/

# Without a server, minus map export and other features browsers block from
# file://:
open data/dashboard/index.html

# Rebuild on every edit to the catalog, config, sync cache or code (Ctrl-C
# stops it). Reload the tab by hand; a new sync is still a separate step.
uv run build-dashboard --watch

# Everything, including what a published build withholds. Local use only.
uv run build-dashboard --include-private
```

The two steps are split because fetching is slow and rendering is iterated on:
one sync serves any number of rebuilds. `sync-components` re-fetches only what
is older than `--max-age` (15 minutes by default); `--force` ignores the cache.
A service being down is recorded rather than fatal, so the run still succeeds
and the page shows what was reachable.

It exists to test whether the metadata in `catalog/` is worth keeping. Two
things it reports are the answer:

- **Where each version came from.** A version is read from the live OpenAPI
  document where possible, then `/status`, then the registered SmartAPI copy,
  then the Helm chart — and each cell says which, so "is OpenAPI a good enough
  source?" has a number rather than an opinion. Both live sources come before
  the registry, because a registration is a copy somebody filed by hand.
- **Which environments disagree.** A version in the minority for its component
  is tinted amber and marked ≠, so drift between dev, ci, test and prod is
  visible without reading every cell. A version copied from the registry or
  the chart rather than read from the running service is a dashed pill, so
  four identical copies do not read as four services agreeing.
- **Where it is registered, and what needs a look.** The SmartAPI column says
  what to do about each registration, worst problem first: `record not found`
  (the catalog has an id the registry does not), `probe failing`, `ci not
  listed` (deployed somewhere the record leaves out), `not probed` (the
  registry skipped every path, usually for want of example requests), and
  then `registered`, `not registered` or `not an API` (`smartapi: null` in
  the component file). Any further problems and when the record last changed
  sit under it, and the tooltip has the detail, including the probe's failing
  lines. Sorting the column lists the problems first, banded by kind. The
  Repository column dates the newest GitHub release; an open row lists every
  release under it, each tag linking to its notes, the ones running somewhere
  on the row filled in.
- **Why a cell is empty.** Every cell with no version says what happened
  instead, in a few words: `no such host`, `no API document found`,
  `serves a web page, not an API document`, `SmartAPI lists no prod server`,
  `not a hosted service`. The distinctions matter — a host that does not
  resolve, one that is up and publishes no version, and one nobody has
  recorded a URL for are three different things, and an empty cell said all
  three at once. Every deployment is contacted at its own URL for this, so
  "reachable" means a host answered rather than a document parsed.
- **How much of the platform.** The "checked N minutes ago" note at the top
  right opens a panel of shares rather than counts: deployments reachable,
  with a version read, listed in their SmartAPI record; components with a
  record, running the same version everywhere — each as "n of N" with a link
  that filters the table to the rest. Under them, where versions came from
  and how many services report to OpenTelemetry per environment.

To see a branch's page the way the published build will be — built on a
GitHub runner, with `config/privacy.yaml` applied — run the Pages workflow on
the branch and download what it builds. On any branch but `main` it deploys
nothing. The run list is narrowed to manual runs and the newest one, because
older runs on the same branch can still hold a `dashboard` artifact built from
an earlier commit:

```bash
gh workflow run pages.yml --ref my-branch
sleep 5   # the new run takes a moment to be listed
id=$(gh run list --workflow pages.yml --branch my-branch \
       --event workflow_dispatch --limit 1 --json databaseId --jq '.[0].databaseId')
gh run watch "$id" --exit-status
gh run download "$id" --name dashboard --dir data/pages-preview
```

### What a published build leaves out

`build-dashboard` withholds what [`config/privacy.yaml`](config/privacy.yaml)
names — today the tracing console, the internal test rig, and the container
image tags that would turn the version grid into a CVE-matching inventory.
`--include-private` builds the full picture for local use. Helm chart
`appVersion` and other chart metadata stay in the published build; only image
tags are redacted.

Redaction is the default so that a forgotten flag costs information rather than
publishing it, and the file is data rather than code so that the people who
know which systems are sensitive can edit it without opening a Python module.
An entry that matches nothing is an error: withholding *nothing* is the failure
worth guarding against, so renaming a component without updating the policy
stops the build.

This is about reach rather than secrecy. Everything the page shows is read from
public services and this repository is public, so the policy hides nothing from
someone who looks — it keeps a few things off an indexed page. See
[issue #7](https://github.com/NCATSTranslator/translator-diagram/issues/7) for
the public/private split this anticipates.

Release lists and repository metadata come from the GitHub API, which allows
60 calls an hour to an unauthenticated address. A full sync spends about 46,
so a second `--force` sync within the hour runs short. Set `GITHUB_TOKEN` in
`.env` (see [`env.default`](env.default)) or in the environment for a limit of
5000; with `gh` logged in, `GITHUB_TOKEN=$(gh auth token) uv run
sync-components` does it without a file. The token is sent to `api.github.com`
and to nothing else, and a throttled fetch costs some release tags, not the
run.

**Every column sorts.** Click a header to sort by it, click again to reverse,
and a third click returns to stage order — which is also what the ✕ beside
the order name in the filter bar does, and the only way back when a narrow
window has hidden the column you sorted on. The order is always named there,
and it travels in the URL with the filters. In stage order the rows are banded by
stage — each band naming what that stage is for — sorting by owner bands
them by owner instead, and sorting by SmartAPI bands them by what the
registration needs, problems first in both directions.

The stages, their order, and the components in each are
[`catalog/flow-steps.yaml`](catalog/flow-steps.yaml), edited by hand. The
recorded dependency edges are too sparse to order twenty-six components: with
nothing recording that the UI calls Name Lookup, a computed order put Name
Lookup up beside the data sources. A written order is more honest than a
plausible-looking one derived from data that is missing.

**Dates.** The Repository column dates a component's newest GitHub release
and the SmartAPI column its registration's last change; about half the
components have neither, because they publish no releases and are in no
registry. Nothing here dates a *deployment* — see [`FUTURE.md`](FUTURE.md)
for the closest available proxy. The environment columns sort by the age of
the release running in that environment, which is the sharpest version of the
same question: prod is on `0.6.1`, released 2024-10-04.

**The page opens on every component.** The `Show` dropdown narrows it:
`Environments disagree` (the rows with the most to say), `Any version known`,
`No version known` — the list of gaps in the metadata, worth reading as a
to-do list — and the three complements the sync panel links to, `Not
reachable`, `Absent from SmartAPI record` and `No SmartAPI record`. The count
beside the filters always says how many of the total are showing.

Filters live in the URL, so a filtered view can be pasted to someone else and
arrives as you saw it. Output goes to the gitignored `data/`: `index.html`,
which inlines its own data and so works straight from disk, and
`overview.json`, the same payload as a file for anything that wants to consume
it.

### What travels in the URL

| Parameter | Meaning |
|---|---|
| `view` | `overview` (the default), `map` or `component` |
| `q` | the search box |
| `owner` | a comma-separated list of owners |
| `versions` | the `Show` view: `all`, `differ`, `known`, `none`, `unreachable`, `unregistered` or `no-smartapi` |
| `sort`, `dir` | the sorted column (`name`, `owner`, `repo`, `smartapi` or `env-<env>`) and `asc` or `desc`; absent means stage order |
| `expand` | the ids of the rows expanded inline |
| `sel` | the component looked at: the Component view's subject, the table's highlighted row and the map's ringed node. A `tab` from an older link is ignored |
| `edges` | on the map, which edge kinds are shown |

Only what differs from the default is written, so a shared link says what the
sender changed and nothing else.

**Map controls:** `f` fits the diagram, `+`/`-` zoom, arrow keys pan when the
map has focus, `Esc` clears selection. Edge kinds can be toggled in the legend.
SVG and PNG export buttons are in the toolbar; serve over `http://` if your
browser blocks downloads from `file://`.

## Diagram conventions

### Node colours (by Owner)

Owner-to-colour mappings live in
[`catalog/owner-colors.csv`](catalog/owner-colors.csv) (two columns: `owner`,
`color`). Edit that file to add a new owner, re-order the legend, or change a
colour — no Python edit required.

The tool looks for that file in the working directory or any directory above
it, and falls back to the copy the wheel carries, so an installed
`generate-diagram` has colours wherever it runs. That copy is the same file:
the build maps it in, rather than the repository holding a second one.
`--owner-colors PATH` overrides both.

New owners not listed there receive fallback colours automatically.

### Node border weight

- **Bold border** — component is "New in Refactor"
- **Normal border** — component "Continues into Refactor"

### Edge types

| Style | Meaning |
|---|---|
| Solid black arrow B → A | B provides results to A ("Gets results from") |
| Solid red arrow B → A | Same, but planned / not yet implemented |
| Dashed black arrow A → B | A makes an optional API call to B ("Calls") |
| Dashed red arrow A → B | Same, but planned / not yet implemented |

Where a solid edge already connects two nodes, a dashed edge in the same
direction is suppressed — otherwise `--concentrate` would merge the two and
lose the solid style. For the same reason, listing an ID both plainly and with
a `~` prefix in one cell (`Calls: foo, ~foo`) draws only the implemented edge.

### Special nodes

Entries in the `Externals` column become nodes for things outside the diagram's
scope, filled amber so they stand out against the component colours:

- **Sources** (`<Name`, cylinder) — entry points, e.g. the upstream data stores
  that feed into `kgx-storage-pipeline`
- **Sinks** (`>Name`, double-border oval) — exit points, e.g. the human
  end-consumer who receives results from the UI

### Ghost nodes

Components that are referenced by an active component but are themselves
outside the current filter (e.g. "Removed after Refactor") appear as gray
dashed boxes labelled `(excluded)`. This keeps cross-boundary edges visible
without cluttering the main diagram.

## SVG output and links

In SVG output every component node carries:

- an `<a xlink:href>` wrapper when the row has a `URL`, so the node is a
  clickable link to that component's repo or docs — no JavaScript needed;
- a hover tooltip with the owner, refactor status and notes;
- a stable `id`, so a web page can address nodes directly from
  `components.json`. XML IDs can't contain spaces or slashes or start with a
  digit, so it is a sanitised form of the component's `id` (`ARS 2.0` becomes
  `ars_2_0`), and `components.json` carries the ids verbatim as `node_ids`.
  That is a *list*: a ubiquitous component has no node of its own, only one
  clone per caller (`ars__log`, `ara__log`), and a component nothing
  references has none at all. Two things that would end up sharing one id —
  including a component whose id collides with a clone, an external entity, or
  the `a_`-prefixed wrapper graphviz puts around a linked node — are a
  validation error.

These attributes are inert in PNG output. They exist to support the planned
interactive GitHub Pages view of this diagram — see below.

## All CLI options

Run `uv run generate-diagram --help` for the authoritative list.

```text
uv run generate-diagram [OPTIONS]

  --input FILE                     Local CSV file  [default: data/components.csv]
  --google-sheet                   Download CSV from Google Sheet (reads
                                   GOOGLE_SHEET_ID from .env in the current
                                   directory or above) instead of --input
  --sheet-gid INTEGER              Google Sheet tab GID (0 = first tab)  [default: 0]
  --output-dir DIRECTORY           Directory for output files  [default: data]
  --output-name TEXT               Base filename for outputs  [default: diagram]
  --refactor-status TEXT           Comma-separated Refactor status values to include
                                   [default: "Continues into Refactor,New in Refactor"]
  --all                            Include all components regardless of Refactor status
  --format [pdf|svg]               Additional output format beyond PNG (PNG is
                                   always produced; can be repeated)
  --direction [LR|TB]              Graphviz layout direction  [default: TB]
  --concentrate/--no-concentrate   Merge partially-parallel edges  [default: off]
  --split-legends/--no-split-legends
                                   Write the legends as separate PNGs rather than
                                   embedding them  [default: split-legends]
  --owner-colors FILE              Owner-colour CSV to use instead of
                                   catalog/owner-colors.csv
  --layer-column TEXT              Column to drive per-layer sub-figures, with
                                   in-layer nodes bold-bordered and their
                                   neighbours from other layers at normal
                                   weight. In the current sheet this column is
                                   named `Tier`.
  --help                           Show this message and exit.
```

## Repository layout

```text
translator-diagram/
├── src/translator_diagram/
│   │                       # shared by both stacks
│   ├── files.py            # Finding a hand-edited file from any directory; reading JSON and YAML
│   ├── colors.py           # Owner colours and the palette
│   ├── components.py       # Reads catalog/components/<id>.yaml
│   ├── privacy.py          # What a published dashboard withholds
│   │                       # the diagram
│   ├── model.py            # Component, index_by_id (one sheet row)
│   ├── naming.py           # SVG ids and output filename stems
│   ├── loading.py          # CSV parsing and the Google Sheet download
│   ├── validation.py       # Reference and id checks
│   ├── render.py           # The diagram and the per-layer sub-figures
│   ├── legend.py           # The two legends
│   ├── export.py           # components.json
│   ├── cli.py              # generate-diagram
│   │                       # the dashboard
│   ├── deployments.py      # Where each component runs: recorded, registered, derived
│   ├── charts.py           # Which component each Helm chart belongs to
│   ├── fetch.py            # One URL into one file: fetch_to, probe_to
│   ├── sync.py             # Fetches what the component files point at
│   ├── flow.py             # Data-flow depths, and the stage-order check
│   ├── synced_data.py      # Reads the sync cache; where the 200 gate lives
│   ├── payload_details.py  # Pure shapers over the cache and component files
│   ├── stages.py           # The bands, from catalog/flow-steps.yaml
│   ├── cells.py            # The version-source chain, one cell at a time
│   ├── rows.py             # One row per component: drift, dates, releases
│   ├── dashboard.py        # The payload, the graph views, the rendered page
│   ├── dashboard_cli.py    # sync-components and build-dashboard
│   ├── web/                # The page's CSS and JS, inlined into it
│   │   └── AGENTS.md       # How to look at the page, and its non-obvious decisions
│   └── AGENTS.md           # The module map and the non-obvious decisions
├── catalog/                # Everything a curator edits, by hand
│   ├── components/         # One YAML file per component
│   ├── unknown.yaml        # Identifiers no component file claims yet
│   ├── flow-steps.yaml     # The dashboard's stages, in page order
│   ├── owner-colors.csv    # Owner → fill colour
│   ├── owner-colors.md     # The rules for choosing a new colour
│   ├── schema/             # JSON Schema for components/*.yaml and unknown.yaml
│   ├── README.md           # The curator's guide to all of the above
│   └── AGENTS.md           # Agent notes for this directory
├── config/
│   └── privacy.yaml        # What a published build leaves out
├── docs/                   # The design, the metadata case and its research
├── tests/                  # One test file per module
├── tools/                  # replay_sync.py: sync() offline, from a recorded cache;
│                           # make_favicon.py: renders web/favicon.ico
├── .github/workflows/      # ci.yml (tests and lints), pages.yml (build + deploy)
├── pyproject.toml          # uv/hatchling project metadata and dependencies
├── uv.lock                 # Pinned dependency versions
├── env.default             # Template for .env: the sheet ID, a GitHub token
├── FUTURE.md               # Ideas with their costs worked out
├── CONTRIBUTING.md         # How to work here: checks, conventions
├── AGENTS.md               # What only an agent needs, and where the rest is
└── data/                   # Gitignored — every input and output goes here
    ├── sync/               # Cached upstream responses + manifest.json
    ├── dashboard/          # index.html and overview.json
    ├── components.csv      # Downloaded from the Google Sheet
    └── diagram.png         # Rendered diagram (plus .dot, .json, .svg, .pdf)
```

## Status and next steps

Both commands work. The dashboard is also published: `.github/workflows/ci.yml`
runs the tests and lints on every pull request, and
`.github/workflows/pages.yml` builds and deploys the page from `main` — on a
push, a nightly schedule, or a manual run — and, run by hand on any other
branch, builds it as a downloadable artifact without deploying. A published
build applies [`config/privacy.yaml`](config/privacy.yaml) and carries
`noindex`.

What is *not* built is the interactive view of the **diagram** — a static page
over the generated SVG and `components.json`. That is
[issue #10](https://github.com/NCATSTranslator/translator-diagram/issues/10),
and it waits on
[issue #7](https://github.com/NCATSTranslator/translator-diagram/issues/7):
this repository and its Pages site are public, so publishing a rendered diagram
publishes the component names, owners, statuses and dependency edges it
contains. Until that is settled nothing generated is committed, and `data/`
stays gitignored.

Worth knowing while it is being decided: the SVG carries more than the picture
shows. Every node's hover tooltip embeds its owner, refactor status and
`Notes`, and `components.json` carries every parsed column of every non-hidden
row — so "publish the diagram but not the details" means stripping tooltips and
JSON keys, not just labels.

## Possible future improvements

The [issue tracker](https://github.com/NCATSTranslator/translator-diagram/issues)
is the live list. Ideas that started here:

- [Report dependency cycles during validation](https://github.com/NCATSTranslator/translator-diagram/issues/11)
  — the validator catches unknown and duplicate IDs, but not a loop.
- [Diff two runs and report what changed](https://github.com/NCATSTranslator/translator-diagram/issues/12)
  — e.g. before and after a sprint.
- [Use the `Component in ITRB` column](https://github.com/NCATSTranslator/translator-diagram/issues/6)
  — it is parsed into `Component.itrb` and nothing reads it.
- **Multiple sheet tabs.** `--sheet-gid` already handles non-default tabs, so an
  `--all-tabs` mode could merge or overlay several views. Not filed as an issue:
  whether it is worth anything depends on how the sheet ends up structured,
  which is part of #7.

## Contributing

[CONTRIBUTING.md](CONTRIBUTING.md) is how to work here: the setup and the
checks CI runs (`uv run pytest`, `ruff check`, `rumdl check .`), how to check
a change to the diagram or the page, and the conventions. Read
[`docs/design.md`](docs/design.md) and the module map in
[`src/translator_diagram/AGENTS.md`](src/translator_diagram/AGENTS.md) before
a first change.

Changes reach `main` only through a pull request approved by a code owner.
[`.github/CODEOWNERS`](.github/CODEOWNERS) lists them: gaurav maintains the
whole repository, and anyone who wants responsibility for part of the code is
welcome to add themselves for that path.

## Licence

[MIT](LICENSE).
