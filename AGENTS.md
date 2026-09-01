# translator-diagram

Generates Graphviz dependency diagrams for Translator platform components from
a Google Sheet CSV. The tool is the `translator_diagram` package under `src/`.
See [README.md](README.md) for user-facing documentation.

## Working agreements

- **After changing code, run `uv run pytest`.** Running
  `uv run generate-diagram` yourself is fine and often the right check — write
  its output somewhere under `data/`. What you cannot do from a diff is judge
  whether the picture *reads* well: crossing edges, cramped clusters, a legend
  in an awkward place. That is the operator's call, so report what changed and
  let them look rather than declaring the result good.
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

# These must stay easy for a human to run; run them yourself when it helps.
# --google-sheet reaches the real sheet, so prefer a local CSV for testing.
uv run generate-diagram --google-sheet               # most common
uv run generate-diagram --input data/components.csv  # from a local CSV
uv run generate-diagram --google-sheet --all         # no refactor-status filter
uv run generate-diagram --google-sheet --layer-column Tier
```

## Package layout (`src/translator_diagram/`)

One module per subject, and one test file per module. No line numbers here on
purpose — they rot within a commit or two.

| Module | What's there |
|---|---|
| `model.py` | `Component` (one CSV row after parsing) and `index_by_id` |
| `naming.py` | Every name the tool hands out: `_svg_id`, `_clone_svg_id`, `_unique_svg_id`, `external_svg_ids`, `_svg_node_ids`, and the `_layer_filename*` output stems |
| `colors.py` | `ColorAssigner`, `text_color_for`, `load_owner_colors`, and the palette constants — `FALLBACK_COLORS`, `GHOST_*`, `EXTERNAL_FILL_COLOR` |
| `loading.py` | `_parse_bool`, `parse_id_list`, `parse_externals`, `_valid_url`, `load_components`, and `download_sheet_csv` for `--google-sheet` |
| `validation.py` | `validate` — duplicate IDs, unknown references, SVG id collisions |
| `render.py` | `build_graph`, `build_layer_subgraph`, and the `_compute_*` / `_emit_*` / `_add_*` helpers below |
| `legend.py` | The owner and edge-style legends, embedded (`--no-split-legends`) or standalone |
| `export.py` | `write_json` — every non-hidden component, into `components.json` |
| `cli.py` | The `click` command: one `@click.option` per flag, then the run sequence |

**Imports run one way**, and a new one must not break it:

```text
model → naming → {validation, export, render}
colors → {render, legend}
legend → render
cli → everything
```

Nothing imports `cli`. The palette constants live in `colors.py` rather than
`render.py` for exactly this reason: `render` and `legend` both need
`EXTERNAL_FILL_COLOR`, and putting it in `render` would make them import each
other.

`tests/test_package_layout.py` enforces it, so a wrong-direction import fails
CI rather than sitting there working. Widening its `ALLOWED` map to silence a
failure will not help: a separate assertion checks the map itself is acyclic.
Move the shared code down the graph instead, the way the palette constants
went.

**`build_graph` and `build_layer_subgraph` share `render.py` on purpose.** They
duplicate the edge-suppression rules, drift between them has already caused a
real bug (see the two suppression sets, below), and a file boundary would make
the next drift easier to miss. Deduplicating them is worth doing; splitting
them without deduplicating them is not.

### Inside render.py

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
| `build_graph` | Top-level assembler — calls all the above in order |
| `build_layer_subgraph` | One per-layer sub-figure (`--layer-column`) |

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

## components/ — the metadata proposal

`components/<id>.yaml` holds one file per component, validated by
`schema/component.schema.json` and `tests/test_components.py`. **Nothing in
`src/` reads them**: `loading.py` still parses the sheet CSV, and the import
graph above is unchanged. They exist to be argued about — the rationale is in
`docs/component-metadata.md` and the upstream survey in
`docs/metadata-sources.md`.

Rules the tests enforce, so a change that breaks one fails CI rather than
sitting there wrong: the filename stem equals `id`; ids are unique
case-insensitively; every id in `connections.gets_results_from`/`calls` has a
file (which is why `docmetadata-api` has one — `ui` calls it); every `owner`
appears in `config/owner-colors.csv`; `endpoints` values are relative paths,
never URLs; and no file writes a `diagram:` flag at its default, which is what
keeps that block absent rather than 26 copies of `ubiquitous: false`.

`unknown.yaml` collects identifiers observed in the platform that no
component file claims — today, the OpenTelemetry service names that could not
be attributed. Do not delete an entry to make a test pass: an entry is removed
only when its identifier moves into a component file. The tests enforce that
no identifier is claimed twice, and that a `not-recorded` entry whose
component now has a file fails until it is promoted.

Quote ISO dates in that file. YAML parses a bare `2026-08-31` into a
`datetime.date`, which is not a JSON Schema string, and the failure message
points at the schema rather than the quoting.

`pyyaml` and `jsonschema` are **dev-only** dependencies on purpose. Moving
them to `[project.dependencies]` is the signal that `loading.py` has actually
switched over — don't do it before then.

## Common change patterns

**Change owner node colours** → edit `config/owner-colors.csv`. No code
change. Row order is legend order. Keeping this a data file is deliberate:
project managers change colours without touching Python. Don't move it into a
constant. `src/translator_diagram/data/owner-colors.csv` is the copy shipped
with the package for installs that have no checkout to read; a test fails if
the two diverge, so edit `config/` and copy it across. See `load_owner_colors`
for the resolution order.

Generating the packaged copy from `config/` at build time is the obvious way to
drop one of them, and it does not work: hatchling's `force-include` reaches the
wheel but not an editable install, so `uv sync` would leave every developer
without the fallback that wheel users have — and CI, which installs editable,
would never exercise it. Two files and a test is the cheaper trade.

**Change ghost or external node colours** → the `GHOST_*` /
`EXTERNAL_FILL_COLOR` constants in `colors.py`.

**Change which statuses count as active** → `DEFAULT_STATUSES` in `cli.py`.

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

**Add a new CSV column** → five places: the `Component` dataclass in
`model.py`, `load_components` in `loading.py`, `write_json` in `export.py`, the
data-model table below, and the CSV-format table in the README.

**Add a new CLI flag** → an `@click.option` above `main` in `cli.py`, plus the
matching parameter in the `main` signature, plus the options block in the
README (it is a hand-maintained paraphrase of `--help`, not generated).

**Add anything that lands in the SVG with an id** → route it through
`naming.py`: give it an id shape that cannot collide (see below), and claim it
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
`_add_edges` and two more in `build_layer_subgraph`, both in `render.py`. An earlier
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
entities (`external_svg_ids`) — all in `naming.py` — and the `a_`-prefixed
`<g>` graphviz wraps around every node carrying a tooltip or a URL, which here
is all of them.
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
for the planned GitHub Pages view ([#10](https://github.com/NCATSTranslator/translator-diagram/issues/10))
— a static page over the generated SVG and `components.json`, no build step.
Don't port this tool to JavaScript to serve that view; the browser needs the
generated DOT, not the generator.

## What is not committed

`data/` is gitignored in its entirety, so no generated diagram, `.dot`, `.json`
or downloaded CSV is in the repo. That is currently load-bearing: this repo and
its future GitHub Pages site are public, and what may be published from the
component sheet is still being decided — see
[issue #7](https://github.com/NCATSTranslator/translator-diagram/issues/7).
Don't commit generated artifacts without checking first.
