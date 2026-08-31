# translator-diagram

Generates Graphviz dependency diagrams for Translator platform components from
a Google Sheet CSV. Single Python module, `generate_diagram.py`, at the repo
root. See [README.md](README.md) for user-facing documentation.

## Working agreements

- **After changing code, run `uv run pytest`. Do _not_ run
  `uv run generate-diagram` yourself** — Gaurav runs it and eyeballs the output.
  Rendering is a visual judgement, not something to verify from a diff.
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
uv run pytest                                        # the only thing you should run

# For reference — these must be easy for humans to run, but coding agents can run them when useful:
uv run generate-diagram --google-sheet               # most common
uv run generate-diagram --input data/components.csv  # from a local CSV
uv run generate-diagram --google-sheet --all         # no refactor-status filter
uv run generate-diagram --google-sheet --layer-column Tier
```

## Script layout (`generate_diagram.py`)

Roughly in file order. No line numbers here on purpose — they rot within a
commit or two. `grep -n '^def '` finds any of these instantly.

| Section | What's there |
|---|---|
| Constants | `DEFAULT_STATUSES`, `FALLBACK_COLORS`, `HOSTED_AT_EMOJI`, and the ghost / external colour constants |
| `ColorAssigner` | Maps owners to fill colours, falling back to a rotating palette |
| `text_color_for` | Picks black or white label text for contrast against a fill hex (Rec. 709 luminance) |
| `Component` | Dataclass — one CSV row after parsing |
| `_parse_bool`, `parse_id_list`, `parse_externals` | CSV cell parsing |
| `load_owner_colors`, `load_components`, `index_by_id` | Data loading |
| `validate` | Duplicate-ID, unknown-reference and SVG-id-collision checking |
| `write_json` | Serialises every non-hidden component to `components.json` |
| Graph construction | `_compute_*`, `_emit_*`, `_add_*`, `build_graph` — see below |
| `main` | The `click` CLI: one `@click.option` per flag, then the run sequence |

### Graph construction

| Function | Purpose |
|---|---|
| `_compute_active_set` | IDs to render, per the refactor-status filter |
| `_compute_ghost_ids` | Excluded-but-referenced IDs, rendered dimmed |
| `_node_tooltip` | SVG hover text (owner, status, notes) |
| `_emit_component_node` | Renders one component node — used for both primary nodes and ubiquitous clones |
| `_compute_groups` | Groups node IDs by their `Part of` label |
| `_add_active_nodes` | Emits all non-grouped, non-ubiquitous active nodes |
| `_add_ghost_nodes` | Emits dimmed nodes for excluded-but-referenced components |
| `_add_group_clusters` | Wraps `Part of` groups in labelled dotted-border subgraphs |
| `_add_edges` | Emits all dependency edges; also emits ubiquitous clones via its inner `edge_target` |
| `_add_external_nodes_and_edges` | External source/sink nodes from the `Externals` column |
| `_svg_id`, `_unique_svg_id`, `_clone_svg_id`, `external_svg_ids`, `_svg_node_ids` | XML-ID-safe handles for SVG `id` attributes and cluster names — see the SVG id namespace below |
| `_owner_legend_html`, `_add_owner_cluster`, `_add_edge_cluster`, `_add_legend` | The embedded legend (`--no-split-legends`) |
| `_build_owners_graph`, `_build_edge_legend_graph` | The standalone legend PNGs (the default) |
| `build_graph` | Top-level assembler — calls all the above in order |
| `_layer_filename`, `_layer_filenames`, `build_layer_subgraph` | Per-layer sub-figures (`--layer-column`) |

## Data model

CSV column → `Component` field:

| CSV column | Field | Notes |
|---|---|---|
| `id` | `id` | Unique identifier; references to it are case-insensitive |
| `Name` | `name` | Display name; falls back to `id` if blank |
| `Owner` | `owner` | Defaults to `"None"` if blank |
| `URL` | `url` | Becomes the graphviz `URL` node attribute — a real link in SVG output. `_valid_url` drops anything that isn't `http(s)` |
| `Component in ITRB` | `itrb` | Informational only; not currently rendered |
| `Refactor status` | `refactor_status` | Drives active-set filtering |
| `Gets results from` | `depends_on` / `depends_on_planned` | Comma-separated IDs; `~` prefix = planned |
| `Calls` | `uses` / `uses_planned` | Comma-separated IDs; `~` prefix = planned |
| `Notes` | `notes` | Not in the diagram; surfaces as an SVG tooltip |
| `Ubiquitous` | `ubiquitous` | TRUE/yes/y/1 → render as per-caller clones |
| `Hide` | `hide` | TRUE/yes/y/1 → suppress entirely: not even as a ghost, and not in `components.json` either |
| `Part of` | `part_of` | Groups the node into a named cluster subgraph |
| `Hosted at` | `hosted_at` | `ITRB` is the default and shows nothing; others get a third label line, e.g. `Hosted at: RENCI 🌐` |
| `Externals` | `externals` | `<Source` = data in, `>Sink` = data out |
| *(`--layer-column`)* | `layer` | Whichever column that flag names. In the current sheet it is `Tier`, not `Layer`. |

Every column but `id` is optional at parse time — `load_components` uses
`row.get(...)` throughout, so an older sheet export missing a column yields
empty values rather than a `KeyError`. Keep it that way. `id` is the one
exception: without that column every row parses as id-less, and the run used
to end with an empty diagram at exit 0, which is what the wrong `--sheet-gid`
produces. A missing `id` column, and a file whose rows are all id-less, are
`ClickException`s.

## Common change patterns

**Change owner node colours** → edit `owner-colors.csv`. No code change. Row
order is legend order. Keeping this a data file is deliberate: project managers
change colours without touching Python. Don't move it into a constant.

**Change ghost or external node colours** → the `GHOST_*` / `EXTERNAL_FILL_COLOR`
constants near the top of the module.

**Change which statuses count as active** → `DEFAULT_STATUSES`.

**Change node label format** → `_emit_component_node`. Labels are
`display_name\nid`, plus a third line for non-ITRB hosts; the emoji map is
`HOSTED_AT_EMOJI`.

**Change node shape or border style** → `_emit_component_node` for active
nodes, `_add_ghost_nodes` for ghosts. The bold "New in Refactor" border is the
`penwidth` argument in `_emit_component_node`.

**Change edge styles** → `_add_edges`. Each of the four dependency lists
(`depends_on`, `depends_on_planned`, `uses`, `uses_planned`) has its own
`dot.edge(...)` call.

**Change graph layout** (dpi, ranksep, splines) → the `graph_attr` dict in
`build_graph`.

**Add a new CSV column** → five places: the `Component` dataclass,
`load_components`, `write_json`, the table above, and the CSV-format table in
the README.

**Add a new CLI flag** → an `@click.option` above `main`, plus the matching
parameter in the `main` signature, plus the options block in the README (it is
a hand-maintained paraphrase of `--help`, not generated).

**Add anything that lands in the SVG with an id** → route it through the
namespace: give it an id shape that cannot collide (see below), and claim it
in `validate` so a collision is caught at parse time rather than in a
browser.

## Things that look wrong but aren't

**`--concentrate` defaults to off.** It merges partially-parallel edges, which
looks tidier but can visually blend a solid edge with a dashed one between
nearby nodes, losing the distinction the diagram exists to show.

**Dashed edges are suppressed where a solid edge already exists** between the
same two nodes in the same direction, for the same reason.

**`newrank="true"`** in `build_graph` is required for `rank=same` to work
across cluster boundaries — the legend clusters rely on it.

**`utf-8-sig`** when reading CSVs strips the BOM an Excel resave prepends.
Without it the first header parses as `"﻿id"` and everything downstream
KeyErrors.

**The Google Sheet download checks `Content-Type: text/csv`.** A private or
missing sheet returns a *200* with an HTML login page, which would otherwise be
saved as `components.csv` and fail confusingly much later.

**Components are sorted by lowercase `id`** in `load_components` so the `.dot`
and `.json` output is stable when someone reorders rows in the sheet.

**Planned edges are red**, hardcoded as `color="red"` at two sites in
`_add_edges` and two more in `build_layer_subgraph`. An earlier
`PLANNED_EDGE_COLOR` constant (soft indigo) was defined but never referenced,
and has been deleted — red is what ships and what the README documents.

**There are two suppression sets, and they are not interchangeable.**
`solid_edges` suppresses a dashed edge that duplicates a solid one in the same
direction; `dashed_edges` suppresses a planned (red) "Calls" edge when an
implemented one already covers the pair, mirroring how `depends_on` outranks
`depends_on_planned`. Recording a dashed edge in `solid_edges` drops the wrong
edge — a real bug `build_layer_subgraph` used to have. `_add_edges` and
`build_layer_subgraph` must stay in step on both.

## Special features

**Ubiquitous components** (telemetry, logging, name resolution): set
`Ubiquitous=TRUE`. Instead of one central node with long converging edges, a
clone is emitted next to each caller with a synthetic id from `_clone_svg_id`.
No central node exists, so these are skipped by `_add_active_nodes` and
`_compute_ghost_ids`; the logic is in `edge_target()` inside `_add_edges`. A
ubiquitous component therefore has *no* node bearing its own id, which is why
`components.json` gives every row a `node_ids` list rather than one id.

**The SVG id namespace has four families**, and no two members of it may
claim the same id — a duplicate XML id makes `getElementById` return whichever
graphviz emitted first. The families are component nodes (`_svg_id`), the
per-caller clones of ubiquitous components (`_clone_svg_id`), external
entities (`external_svg_ids`), and the `a_`-prefixed `<g>` graphviz wraps
around every node carrying a tooltip or a URL — which here is all of them.
Clone and external ids use a `__` joiner, which `_svg_id` can never produce
because it collapses runs of punctuation to a single `_`; that keeps them off
component ids by construction. `validate` then folds all four families into
one dict and hard-errors on any remaining collision, so `Foo` plus `A Foo`
(whose id is `Foo`'s wrapper id) fails the run rather than silently rebinding
a node.

**Ghost nodes**: an active component referencing a filtered-out one makes that
component appear dimmed and labelled `(excluded)`, so cross-boundary edges stay
visible. See `_compute_ghost_ids`.

**SVG attributes**: `_emit_component_node` sets `id` (stable per-node handle),
`tooltip`, and `URL`/`target` when the row has a URL. Graphviz turns `URL` into
an `<a xlink:href>` wrapper in SVG output. These are inert in PNG. They exist
for the planned GitHub Pages view — a static page over the generated SVG and
`components.json`, no build step. Don't port this tool to JavaScript to serve
that view; the browser needs the generated DOT, not the generator.

## What is not committed

`data/` is gitignored in its entirety, so no generated diagram, `.dot`, `.json`
or downloaded CSV is in the repo. That is currently load-bearing: this repo and
its future GitHub Pages site are public, and what may be published from the
component sheet has not been decided yet. Don't commit generated artifacts
without checking first.
