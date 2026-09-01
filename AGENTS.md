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
- **Look at the dashboard before saying it is fine.** Structural checks do not
  catch visual bugs: this page once passed 301 tests, `node --check`, a
  self-containment assertion and a payload-consistency check while shipping a
  badge on 27 of 45 cells that drowned the table, a tile that counted 74 things
  where there were 41, and two environment columns unreachable at narrow
  widths. Render it and look — Firefox does this with no extra tooling, and
  needs its own profile because yours is probably already running:

  ```bash
  uv run build-dashboard
  MOZ_NO_REMOTE=1 /Applications/Firefox.app/Contents/MacOS/firefox \
    --headless --new-instance --profile /tmp/ffprofile \
    --screenshot /tmp/dash.png --window-size=1700,1400 \
    "file://$PWD/data/dashboard/index.html"
  ```

  Shoot it narrow (`--window-size=760,1000`) too; the column-dropping rules
  only misbehave there. Whether the result *reads* well is still the
  operator's call — report what you saw and let them look.
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

# The dashboard: fetch, then render. Split because fetching is slow and
# rendering is iterated on — one sync serves a hundred rebuilds.
uv run sync-components                               # -> data/sync/
uv run build-dashboard                               # -> data/dashboard/

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

The dashboard is a second, parallel stack over the same components:

| Module | What's there |
|---|---|
| `components.py` | `ComponentFile` (one `components/<id>.yaml`), `endpoint_url_in`, `merge_deployments`, `deployments_from_smartapi`, `github_repo`, `DEFAULT_ENDPOINT_PATHS` |
| `flow.py` | `flow_depths`, `in_flow_order`, `isolated` — ordering components from the data sources to the user |
| `sync.py` | The fetchers and the manifest. Takes an injected `Fetcher`, so tests never reach the network |
| `dashboard.py` | The version-source chain, drift detection, and the rendered page. Returns plain dicts; no CLI, no network |
| `dashboard_cli.py` | `sync-components` and `build-dashboard` |
| `data/dashboard.css`, `data/dashboard.js` | Inlined into the generated page |

**Imports run one way**, and a new one must not break it:

```text
# the diagram
model → naming → {validation, export, render}
colors → {render, legend}
legend → render
cli → everything above

# the dashboard
components → {flow, sync, dashboard}
flow → dashboard
colors → dashboard
dashboard_cli → everything above
```

Nothing imports either CLI. The palette constants live in `colors.py` rather
than `render.py` for exactly this reason: `render` and `legend` both need
`EXTERNAL_FILL_COLOR`, and putting it in `render` would make them import each
other.

**The two halves meet only at `colors`.** `model.py` parses a sheet row and
`components.py` parses a YAML file; they describe the same components but not
the same data, and neither imports the other. Merging them is what issue #19
is for — doing it early would mean one of the two losing fields it needs.

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

## components/ — the component metadata files

`components/<id>.yaml` holds one file per component, validated against
`schema/component.schema.json` by `tests/test_component_files.py` and parsed
by `components.py` (whose own tests are `tests/test_components.py`).

**The dashboard reads them; the diagram does not.** `sync`, `flow` and
`dashboard` are built on them, while `loading.py` still parses the sheet CSV.
The two stacks meet only at `colors`, and merging them is issue #19. The
rationale for the format is in `docs/component-metadata.md`, the upstream
survey in `docs/metadata-sources.md`.

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

`pyyaml` is a **runtime** dependency because the dashboard reads
`components/*.yaml` at run time. `jsonschema` stays **dev-only**: nothing but
the tests validates those files, and a schema library in the runtime
dependency set would suggest otherwise.

## Common change patterns

**Change what a dashboard band says** → edit `config/flow-steps.yaml`. Titles
and descriptions for the steps of the data-flow order, and prose about the
platform belongs where the people who know the platform can edit it — same
reasoning as `config/owner-colors.csv`.

Entries are matched by **the components a step contains**, not by position: a
step is "these components, together", and one new dependency edge renumbers
everything below it. So prose can never attach to the wrong rows; what it can
do is stop matching, in which case the band falls back to naming its layers and
`tests/test_flow_steps.py` fails until someone rewrites it. That test is the
whole point of the arrangement — verified by adding an edge and watching it
fire, not by reading it. The file is optional: delete it and every band is
named after its layers.

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

**Add a column to the dashboard** → `build_cell` or `build_rows` in
`dashboard.py` for the value, then **one entry in the `COLUMNS` table** in
`data/dashboard.js`, and `data/dashboard.css` if it needs a style. That entry
owns the header, the body cell, the `drop-*` class that hides both at narrow
widths, the sort value and the column count the empty row's colspan needs —
they used to be written out separately, which is how a header ends up hidden
without its column. The payload written to `overview.json` is a contract a
scheduled job would publish, so adding a key is safe and renaming one is not.

**Add a new upstream source** → a fetch in `sync.py` and a tier in the
version-source chain in `dashboard.build_cell`. Order that chain by how close
the source is to what is actually running: a live endpoint, then a manual
registration, then a chart describing what should have been deployed. Whatever
you add must appear in `SOURCE_LABELS` so the badge names it — a version whose
provenance is invisible is the thing the dashboard exists to avoid.

**Touch anything that calls the GitHub API** → it is the one host here with a
budget: 60 calls an hour per address unauthenticated, 5000 with a
`GITHUB_TOKEN` in the environment, which `_headers` sends to api.github.com and
nowhere else. Release lists are keyed by repository rather than by component so
the three shepherds cost one call, and a throttled 403 is reported by name at
the end of wave one — a silent one reads as "this repository has no releases",
which is a different and wrong finding. Nothing here fails the run: the
dashboard shows fewer tags, and the next sync picks them up.

**Only a `source` repository whose URL names a whole repository gets releases.**
`github_repo` rejects `.../translator-devops/tree/develop/helm/<chart>`, which
is what every `helm-chart` entry looks like: those releases belong to the
devops repository and labelling them as a component's would be worse than
showing none.

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

**Half the rows have no date.** `Last updated` is null for 13 of 26
components — they publish no GitHub releases and are in no SmartAPI record, and
those are the only two date sources we fetch. They sort to the bottom in *both*
directions, deliberately: reversing a sort must not promote the rows we know
least about. `FUTURE.md` records what it would cost to fill them in.

**A cached `data/sync/` body can predate a change to the URL that fetched it.**
`fetch_to` judges freshness by the destination's mtime, so adding a field to
`SMARTAPI_QUERY` used to leave a perfectly fresh `smartapi.json` that answered
the older question. `sync` now carries the previous manifest's path-to-URL map
and re-fetches anything whose URL moved. If you add a fetcher, give it a stable
destination path and let that map do the work.

**Environment columns sort by the age of the release running there**, not by
version string: comparing `2.10.2` against `1.0` across two different
components means nothing. Cells rank in tiers — running a release we can date,
running something no release names, not deployed — and the tiers hold in both
directions.

**The sticky header's offset is measured, not declared.** `--filters-height` is
set from the filter bar's real height on every render and on resize, because
the bar wraps to two lines at some widths and a hardcoded `top` hides the first
row underneath it.

**The dashboard opens filtered**, on `Environments disagree`, so it shows 7 of
26 rows rather than everything. The count beside the filters says so, and
`All components` is one selection away. It replaced a "Drift only" toggle
rather than joining it: two controls that select the same rows cannot be told
apart by a reader, and the four views (`differ`, `known`, `none`, `all`) live
in `VERSION_VIEWS` in `data/dashboard.js` with the default in `DEFAULT_VIEW`.
`differ` means any of the three tinted axes, not versions alone — a component
whose TRAPI version drifts while its software version does not is exactly as
interesting.

**The theme cycle starts by moving away from the system**, not at light: the
page defaults to following the operating system, so `auto → light → dark`
would spend the first click repainting a light machine light and read as a
dead button. `nextTheme` therefore reads `prefers-color-scheme` to decide
which way to go first, and the one click that does not change the appearance
is the trip back to auto, which says so in the button's title.

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
