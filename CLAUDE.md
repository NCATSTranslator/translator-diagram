# translator-components-diagram

Generates Graphviz dependency diagrams for Translator platform components from a Google Sheet CSV.

> **Note for Claude:** After making code changes, do not run `uv run generate-diagram` yourself — the user will run it. Only run `uv run pytest` to check for test failures.

## Quick start

```bash
# Download from Google Sheet and render (most common)
uv run generate-diagram --google-sheet

# From a local CSV
uv run generate-diagram --input data/components.csv

# Include all components (not just active refactor statuses)
uv run generate-diagram --google-sheet --all

# Left-to-right layout, PDF output
uv run generate-diagram --google-sheet --direction LR --format pdf

# Run tests
uv run pytest
```

## Script layout (`generate_diagram.py`)

| Lines | What's there |
|-------|-------------|
| 17–36 | Global constants: `DEFAULT_STATUSES`, `FALLBACK_COLORS`, color constants for planned/ghost/external nodes |
| 39–61 | `ColorAssigner` — maps owners to fill colors, falls back to rotating palette |
| 63–69 | `text_color_for` — picks black/white text for contrast against a fill hex |
| 72–103 | `Component` dataclass — one CSV row after parsing |
| 106–154 | CSV parsing utilities: `_parse_bool`, `parse_id_list`, `parse_externals` |
| 157–213 | Data loading: `load_owner_colors`, `load_components`, `index_by_id` |
| 216–258 | `validate` — duplicate ID detection, unknown reference checking |
| 261–284 | `write_json` — serializes all components to `components.json` |
| 290–711 | Graph construction: `_compute_*`, `_add_*`, `build_graph` (see table below) |
| 714–891 | CLI: `@click.option` decorators + `main` |

### Graph construction helpers (290–711)

| Function | Lines | Purpose |
|----------|-------|---------|
| `_compute_active_set` | 290–296 | IDs to render based on refactor status filter |
| `_compute_ghost_ids` | 299–316 | IDs of excluded-but-referenced components (shown dimmed) |
| `_emit_component_node` | 319–341 | Renders one component node (used for primary nodes and ubiquitous clones) |
| `_compute_groups` | 343–355 | Groups nodes by `Part of` label |
| `_add_active_nodes` | 358–372 | Emits all non-grouped, non-ubiquitous active nodes |
| `_add_ghost_nodes` | 375–394 | Emits dimmed nodes for excluded-but-referenced components |
| `_add_group_clusters` | 397–440 | Wraps `Part of` groups in labeled dotted-border subgraphs |
| `_add_edges` | 443–500 | Emits all dependency edges (solid/dashed, implemented/planned) |
| `_ext_node_id` | 503–506 | Stable node ID from an external-entity name |
| `_add_external_nodes_and_edges` | 509–568 | Emits external source/sink nodes from the `Externals` column |
| `_owner_legend_html` | 571–593 | Builds HTML-table label for the owner-color legend |
| `_add_legend` | 596–658 | Assembles the full legend (owner swatches + edge style examples) |
| `build_graph` | 661–711 | Top-level assembler — calls all the above in order |

## Data model

CSV column → `Component` field:

| CSV column | Field | Notes |
|-----------|-------|-------|
| `id` | `id` | Unique identifier; case-insensitive for references |
| `Name` | `name` | Display name; falls back to `id` if blank |
| `Owner` | `owner` | Defaults to `"None"` if blank |
| `Component in ITRB` | `itrb` | Informational only |
| `Refactor status` | `refactor_status` | Drives active-set filtering |
| `Gets results from` | `depends_on` / `depends_on_planned` | Comma-separated IDs; `~` prefix = planned |
| `Calls` | `uses` / `uses_planned` | Comma-separated IDs; `~` prefix = planned |
| `Notes` | `notes` | Informational only |
| `Ubiquitous` | `ubiquitous` | TRUE/yes/1 → render as per-caller clones |
| `Hide` | `hide` | TRUE/yes/1 → suppress entirely (not even as ghost) |
| `Part of` | `part_of` | Groups node into a named cluster subgraph |
| `Hosted at` | `hosted_at` | Deployment location; `ITRB` is default (no label shown); others get a third label line, e.g. `Hosted at: RENCI 🌐` |
| `Externals` | `externals` | `<Source` = data in, `>Sink` = data out |

## Common change patterns

**Change owner node colors** → edit `owner-colors.csv` (no code change). Row order = legend order.

**Change ghost/external node colors** → constants `GHOST_FILL_COLOR`, `GHOST_BORDER_COLOR`, `GHOST_FONT_COLOR`, `EXTERNAL_FILL_COLOR` at lines 31–36.

**Change planned-edge color** → `PLANNED_EDGE_COLOR` constant at line 30.

**Change active refactor statuses** → `DEFAULT_STATUSES` list at line 17.

**Change node label format** → `_emit_component_node` (line 319). Active node labels are `display_name\nid` plus an optional third line for non-ITRB hosts. Emoji mapping lives in `HOSTED_AT_EMOJI` at line ~37.

**Change node shape or border style** → `_emit_component_node` (line 319) for active nodes; `_add_ghost_nodes` (line 375) for ghost nodes. The `is_new` bold border is set at line 339.

**Change edge styles** (solid/dashed/color) → `_add_edges` (line 443). Each of the four dependency lists (`depends_on`, `depends_on_planned`, `uses`, `uses_planned`) has its own `dot.edge(...)` call (lines 483–500).

**Change external node shapes** → `_add_external_nodes_and_edges` (line 509). Sources use `shape="cylinder"`, sinks use `shape="oval", peripheries="2"`.

**Change graph layout settings** (dpi, ranksep, splines) → `build_graph` `graph_attr` dict at line 673.

**Add a new CSV column** → three places:
1. `load_components` (line 175) — read from `row`
2. `Component` dataclass (line 72) — add the field
3. `write_json` (line 261) — add to the export dict

**Add a new CLI flag** → add `@click.option` before `main` (line 714) and add the parameter to the `main` signature.

**Change the legend** → `_add_legend` (line 596) for structure; `_owner_legend_html` (line 571) for the owner-color table HTML.

## Special features

**Ubiquitous components** (e.g. telemetry, logging): Set `Ubiquitous=TRUE` in the CSV. Instead of one central node, a per-caller clone is emitted inline next to each caller. No central node is created. Logic lives in `edge_target()` inside `_add_edges` (line 457). These components are excluded from `_add_active_nodes` and `_compute_ghost_ids`.

**Ghost nodes**: When an active component references one that is filtered out (wrong refactor status), the excluded component appears dimmed with `(excluded)` in its label. Computed by `_compute_ghost_ids` (line 299).

**Planned edges** (`~id` in `Gets results from` or `Calls`): Parsed as `depends_on_planned` / `uses_planned` by `parse_id_list` (line 111). Rendered in red in `_add_edges` (lines 488–500). Solid red for "Gets results from", dashed red for "Calls".

**`--concentrate` flag**: Merges partially-parallel edges. Off by default because it can visually blend solid and dashed edges between nearby nodes.

**Google Sheet download**: Checks `Content-Type: text/csv` to catch the case where a private/missing sheet returns an HTML login page instead of CSV (line 826).
