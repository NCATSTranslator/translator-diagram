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
stored in `.env` (gitignored; never committed). Copy [`env.default`](env.default)
to `.env` and fill it in:

```
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
| `data/diagram_<layer>.dot` | `--layer-column` | Graphviz source for each sub-figure |

The two legend files are written separately by default; `--no-split-legends`
embeds them in the main diagram instead.

`<layer>` is the layer's value with punctuation folded to `_`. Two values that
fold to the same stem (`Tier 1` and `Tier-1`) would overwrite each other, so
the second gets a `_2` suffix and a warning.

## Diagram conventions

### Node colours (by Owner)

Owner-to-colour mappings live in
[`config/owner-colors.csv`](config/owner-colors.csv) (two columns: `owner`,
`color`). Edit that file to add a new owner, re-order the legend, or change a
colour — no Python edit required.

The tool looks for that file in the working directory, and falls back to the
copy shipped inside the package, so an installed `generate-diagram` has colours
wherever it runs. `--owner-colors PATH` overrides both.

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
                                   config/owner-colors.csv
  --layer-column TEXT              Column to drive per-layer sub-figures, with
                                   in-layer nodes bold-bordered and their
                                   neighbours from other layers at normal
                                   weight. In the current sheet this column is
                                   named `Tier`.
  --help                           Show this message and exit.
```

## Repository layout

```
translator-diagram/
├── src/translator_diagram/   # The tool
│   ├── model.py          # Component, index_by_id
│   ├── naming.py         # SVG ids and output filename stems
│   ├── colors.py         # Owner colours and the palette
│   ├── loading.py        # CSV parsing and the Google Sheet download
│   ├── validation.py     # Reference and id checks
│   ├── render.py         # The diagram and the per-layer sub-figures
│   ├── legend.py         # The two legends
│   ├── export.py         # components.json
│   ├── cli.py            # The command line
│   └── data/             # owner-colors.csv, shipped with the package
├── config/
│   └── owner-colors.csv  # Owner → fill colour mapping (edit me)
├── tests/                # One test file per module
├── pyproject.toml        # uv/hatchling project metadata and dependencies
├── uv.lock               # Pinned dependency versions
├── env.default           # Template for .env
├── .env                  # GOOGLE_SHEET_ID — gitignored, fill in locally
├── AGENTS.md             # Orientation for coding agents
├── README.md             # This file
└── data/                 # Gitignored — all inputs and outputs go here
    ├── components.csv    # Downloaded from Google Sheet
    ├── components.json   # Parsed component data (all statuses, minus hidden rows)
    ├── diagram.dot       # Graphviz source
    └── diagram.png       # Rendered diagram
```

## Status and next steps

This is a work in progress. The tool itself works; what is not yet built is the
public-facing view — a single static page over the generated SVG and
`components.json`, deployed from a scheduled GitHub Actions run. That is
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

```bash
uv sync            # first-time setup
uv run pytest      # the test suite
uv run ruff check  # Python lint
uv run rumdl check # Markdown lint
```

All four run in CI on every pull request. The source is one module per subject
under `src/translator_diagram/`, and `tests/` has one file per module — a
change to `loading.py` belongs in `tests/test_loading.py`.
[AGENTS.md](AGENTS.md) has the module map, the rule about which module may
import which, and the non-obvious decisions worth knowing before changing
rendering.

## Licence

[MIT](LICENSE).
