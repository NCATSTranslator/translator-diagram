# translator-diagram

Diagrams describing the overall architecture of the
[NCATS Biomedical Data Translator](https://ncats.nih.gov/research/research-activities/translator).

A Python CLI tool reads a spreadsheet of Translator platform components,
validates their dependency declarations, and produces Graphviz diagrams showing
how data flows through the system and which services call each other.

## Purpose

The Translator platform comprises many components maintained by different teams.
This tool makes the overall architecture visible by turning a human-maintained
Google Sheet into a shareable diagram. The default view filters to components
that are active in the current refactor ("Continues into Refactor" and
"New in Refactor"), so the diagram stays focused on what is currently relevant.

It is meant to serve three audiences at once: everyone inside the project who
needs to see how the pieces fit together, performance work that needs a map of
where the bottlenecks might be (usefully combined with our OpenTelemetry data),
and people outside the project trying to understand how Translator works.

## Quick start

Requires Python ≥ 3.11 and [uv](https://docs.astral.sh/uv/).
The [Graphviz](https://graphviz.org/) system package must also be installed
(`brew install graphviz` on macOS, `apt-get install graphviz` on Debian/Ubuntu).

```bash
uv sync                          # first-time setup; creates .venv/

# Download latest data from the Google Sheet and regenerate
uv run generate-diagram --google-sheet

# Use a locally cached CSV instead
uv run generate-diagram

# Include all components, not just the refactor-active ones
uv run generate-diagram --all

# Also produce a PDF (useful for presentations)
uv run generate-diagram --google-sheet --format pdf

# One sub-figure per tier, plus the main diagram
uv run generate-diagram --google-sheet --layer-column Tier
```

## Input data

### Google Sheet

The canonical source of truth is a world-readable Google Sheet. Its ID is
stored in `.env` at the repository root (gitignored; never committed). Copy
[`env.default`](env.default) to `.env` and fill it in:

```
GOOGLE_SHEET_ID=<paste the sheet ID here>
```

Run with `--google-sheet` to download the latest CSV export into `data/` and
use it immediately. The downloaded file is also gitignored.

### CSV format

The sheet must have these columns (order does not matter; unknown columns are
ignored, and any column may be absent):

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
| `Externals` | Entities outside the diagram — `<Name` feeds in, `>Name` receives out |
| `Part of` | Groups this component into a named cluster box |
| `Hosted at` | Deployment location; `ITRB` is the default and shown as nothing |
| `Ubiquitous` | `TRUE` to render this component as a per-caller clone (see below) |
| `Hide` | `TRUE` to suppress the component entirely: not as a ghost node, and not in `components.json` either |
| `Notes` | Free-text notes; shown as an SVG hover tooltip, not in the diagram |

IDs are matched case-insensitively; a case mismatch is a warning, an unknown ID
or a duplicate ID is a hard error that stops the run.

#### Planned (not-yet-implemented) relationships

Prefix any ID in `Gets results from` or `Calls` with `~` to mark it as
planned but not yet implemented:

```
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

The two legend files are written separately by default; `--no-split-legends`
embeds them in the main diagram instead.

## Diagram conventions

### Node colours (by Owner)

Owner-to-colour mappings live in [`owner-colors.csv`](owner-colors.csv)
(two columns: `owner`, `color`). Edit that file to add a new owner,
re-order the legend, or change a colour — no Python edit required.

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

```
uv run generate-diagram [OPTIONS]

  --input FILE                     Local CSV file  [default: data/components.csv]
  --google-sheet                   Download CSV from Google Sheet (reads
                                   GOOGLE_SHEET_ID from .env) instead of --input
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
  --layer-column TEXT              Column to drive per-layer sub-figures. In the
                                   current sheet this column is named `Tier`.
  --help                           Show this message and exit.
```

## Repository layout

```
translator-diagram/
├── generate_diagram.py   # The tool
├── owner-colors.csv      # Owner → fill colour mapping (edit me)
├── tests/                # pytest suite for the pure functions
├── pyproject.toml        # uv/hatchling project metadata and dependencies
├── uv.lock               # Pinned dependency versions
├── env.default           # Template for .env
├── .env                  # GOOGLE_SHEET_ID — gitignored, fill in locally
├── AGENTS.md             # Orientation for coding agents
├── README.md             # This file
└── data/                 # Gitignored — all inputs and outputs go here
    ├── components.csv    # Downloaded from Google Sheet
    ├── components.json   # Parsed component data (all statuses)
    ├── diagram.dot       # Graphviz source
    └── diagram.png       # Rendered diagram
```

## Status and next steps

This is a work in progress. The tool itself works; what is not yet built is the
public-facing view.

**Next: an interactive GitHub Pages view.** The plan is a single static HTML
page that embeds the generated SVG and drives a detail panel from
`components.json` — no build step, no bundler. The generator already emits
everything that needs: per-node links, tooltips and stable ids. A GitHub
Actions workflow will regenerate from the sheet on a schedule and deploy.

**Open question, to settle before that ships:** this repository and its Pages
site are public, so publishing a rendered diagram publishes the component
names, owners, statuses and dependency edges it contains. That needs a
deliberate decision — publish everything, gate it behind an opt-in `Public`
column in the sheet, or strip the free-text fields. Until then nothing
generated is committed; `data/` stays gitignored.

Note that the SVG carries more than the picture shows: every node's hover
tooltip embeds its owner, refactor status and `Notes`, and `components.json`
carries every parsed column of every non-hidden row. "Strip the free-text fields" therefore means
stripping tooltips and JSON keys, not just labels.

## Possible future improvements

- **Grouping / filtering by ITRB category** — the `Component in ITRB` column
  is loaded but not currently used; it could drive an alternative colour scheme
  or a `--group-by itrb` flag.
- **Cycle detection** — the validator checks for unknown IDs but does not yet
  detect dependency cycles, which would be a useful integrity check.
- **Multiple sheet tabs** — `--sheet-gid` already supports non-default tabs;
  a `--all-tabs` mode could merge or overlay multiple views.
- **Diff mode** — compare two runs of the tool (e.g. before and after a sprint)
  and highlight added, removed, or changed components and edges.

## Licence

[MIT](LICENSE).
