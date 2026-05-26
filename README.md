# Translator Components Diagram

A Python CLI tool that reads a spreadsheet of Translator platform components,
validates their dependency declarations, and produces Graphviz diagrams showing
how data flows through the system and which services call each other.

## Purpose

The Translator platform comprises many components maintained by different teams.
This tool makes the overall architecture visible by turning a human-maintained
Google Sheet into a shareable diagram. The default view filters to components
that are active in the current refactor ("Continues into Refactor" and
"New in Refactor"), so the diagram stays focused on what is currently relevant.

## Quick start

Requires Python ≥ 3.11 and [uv](https://docs.astral.sh/uv/).
The [Graphviz](https://graphviz.org/) system package must also be installed
(`brew install graphviz` on macOS).

```bash
cd translator-components-diagram
uv sync                          # first-time setup; creates .venv/

# Download latest data from the Google Sheet and regenerate
uv run generate_diagram.py --google-sheet

# Use a locally cached CSV instead
uv run generate_diagram.py

# Include all components, not just the refactor-active ones
uv run generate_diagram.py --all

# Also produce a PDF (useful for presentations)
uv run generate_diagram.py --google-sheet --format pdf
```

## Input data

### Google Sheet

The canonical source of truth is a world-readable Google Sheet. Its ID is
stored in `.env` (gitignored; never committed):

```
# translator-components-diagram/.env
GOOGLE_SHEET_ID=<paste the sheet ID here>
```

Run with `--google-sheet` to download the latest CSV export into `data/` and
use it immediately. The downloaded file is also gitignored.

### CSV format

The sheet must have these columns (order does not matter):

| Column | Description |
|---|---|
| `id` | Unique machine-readable identifier (kebab-case preferred) |
| `Name` | Human-readable display name shown in the diagram |
| `Owner` | Team that owns the component; controls node colour |
| `Component in ITRB` | ITRB category (informational only) |
| `Refactor status` | Lifecycle status — see filtering below |
| `Gets results from` | Comma-separated IDs this component receives data from |
| `Calls` | Comma-separated IDs this component makes optional API calls to |
| `Notes` | Free-text notes (not used by the tool) |

#### Planned (not-yet-implemented) relationships

Prefix any ID in `Gets results from` or `Calls` with `~` to mark it as
planned but not yet implemented:

```
Gets results from: nodenorm-es, ~new-service
Calls: ars, ~future-api
```

Planned edges render in gray; implemented edges render in black.

## Output files

All outputs go to `data/` (gitignored) by default.

| File | Always? | Description |
|---|---|---|
| `data/diagram.png` | yes | Main shareable diagram |
| `data/diagram.dot` | yes | Graphviz source — useful for debugging or tweaking |
| `data/components.json` | yes | All components parsed (all statuses, not filtered) |
| `data/diagram.pdf` | `--format pdf` | Vector format for presentations |
| `data/diagram.svg` | `--format svg` | Vector format for web embedding |

> The `.dot` and `.json` files are intended to eventually be committed to the
> repo so people can inspect the data without running the tool.

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
| Indigo dashed arrow B → A | Same, but planned / not yet implemented |
| Dotted black arrow A → B | A makes an optional API call to B ("Calls") |
| Indigo dotted arrow A → B | Same, but planned / not yet implemented |

Planned-edge indigo is distinct from the gray used for ghost-node borders,
so the two encodings don't blur together visually.

### Special nodes

- **External data sources** (cylinder, gray) — entry point; represents all
  upstream data stores that feed into `kgx-storage-pipeline`
- **User** (double-border oval, gray) — exit point; the human end-consumer
  who receives results from the UI

### Ghost nodes

Components that are referenced by an active component but are themselves
outside the current filter (e.g. "Removed after Refactor") appear as gray
dashed boxes labelled `(excluded)`. This keeps cross-boundary edges visible
without cluttering the main diagram.

## All CLI options

```
uv run generate_diagram.py [OPTIONS]

  --input PATH              Local CSV file  [default: data/components.csv]
  --google-sheet            Download CSV from Google Sheet (reads GOOGLE_SHEET_ID
                            from .env) instead of using --input
  --sheet-gid INTEGER       Google Sheet tab GID (0 = first tab)  [default: 0]
  --output-dir PATH         Directory for output files  [default: data]
  --output-name TEXT        Base filename for outputs  [default: diagram]
  --refactor-status TEXT    Comma-separated Refactor status values to include
                            [default: "Continues into Refactor,New in Refactor"]
  --all                     Include all components regardless of Refactor status
  --format [pdf|svg]        Additional output format beyond PNG (PNG is
                            always produced; can be repeated)
  --direction [LR|TB]       Graphviz layout direction  [default: TB]
  --help                    Show this message and exit.
```

## Repository layout

```
translator-components-diagram/
├── generate_diagram.py   # The tool
├── owner-colors.csv      # Owner → fill colour mapping (edit me)
├── tests/                # pytest suite for the pure functions
├── pyproject.toml        # uv/hatchling project metadata and dependencies
├── uv.lock               # Pinned dependency versions
├── .env                  # GOOGLE_SHEET_ID — gitignored, fill in locally
├── README.md             # This file
└── data/                 # Gitignored — all inputs and outputs go here
    ├── components.csv    # Downloaded from Google Sheet
    ├── components.json   # Parsed component data (all statuses)
    ├── diagram.dot       # Graphviz source
    └── diagram.png       # Rendered diagram
```

## Possible future improvements

- **Commit `.dot` and `.json` to Git** — move these outputs outside `data/` so
  they are version-controlled and reviewable without running the tool.
- **Interactive SVG or HTML output** — embed tooltips (owner, notes, status)
  using Graphviz's `tooltip` attribute or a post-processing step with a library
  like `d3-graphviz`.
- **Grouping / filtering by ITRB category** — the `Component in ITRB` column
  is loaded but not currently used; it could drive an alternative colour scheme
  or a `--group-by itrb` flag.
- **Cycle detection** — the validator checks for unknown IDs but does not yet
  detect dependency cycles, which would be a useful integrity check.
- **Multiple sheet tabs** — `--sheet-gid` already supports non-default tabs;
  a `--all-tabs` mode could merge or overlay multiple views.
- **Diff mode** — compare two runs of the tool (e.g. before and after a sprint)
  and highlight added, removed, or changed components and edges.
