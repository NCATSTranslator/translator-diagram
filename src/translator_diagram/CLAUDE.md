# src/translator_diagram/

The code for both commands. Repo-wide working agreements — how to check your work,
what only a human can judge, `data/` as scratch space — are in
[../../AGENTS.md](../../AGENTS.md). This file is the module map and the decisions
that are not visible from the line you are changing.

| Section | What it answers |
|---|---|
| [Package layout](#package-layout-srctranslator_diagram) | Which module holds what, and which may import which |
| [Data model](#data-model) | CSV column → `Component` field |
| [Common change patterns](#common-change-patterns) | "I want to change X" → the file to open |
| [What the dashboard refuses to claim](#what-the-dashboard-refuses-to-claim) | Correctness rules that were each a bug first |
| [Things that look wrong but aren't](#things-that-look-wrong-but-arent) | Decisions with a reason that is not visible locally |
| [Special features](#special-features) | Ubiquitous clones, the SVG id namespace, ghost nodes |

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
| `privacy.py` | `Policy`, `load_policy`, `apply`, `verify` — what a published build withholds |
| `dashboard.py` | The version-source chain, drift detection, and the rendered page. Returns plain dicts; no CLI, no network |
| `dashboard_cli.py` | `sync-components` and `build-dashboard` |
| `web/dashboard.css`, `web/dashboard.js` | The browser half of the dashboard, inlined into the generated page |

`web/` holds what the browser gets and nothing else — it was `data/`, which
collided with the gitignored `/data/` scratch space at the root. The packaged
fallback copy of `owner-colors.csv` sits at the package root instead: a colour
table the diagram generator reads is not a web file.

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
privacy → dashboard
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

## Common change patterns

**Change the dashboard's row order, or what a band says** →
`config/flow-steps.yaml`. It lists the stages in page order, each with a title,
a description and the components it holds, shown in the order it lists them.
Prose about the platform, and the order it is read in, belong where the people
who know both can edit them — same reasoning as `config/owner-colors.csv`.

**That file is the order**, not labels on a computed one. It began as the
latter, and the computed order was wrong in ways the edges cannot fix: only 13
of 26 components appear in a results edge at all, so Name Lookup sorted up
beside the data sources. `flow.py` still computes depths — `isolated` draws the
left bar and `build-dashboard` reports it — but nothing derives the page order
from them, and `flow_steps` was deleted rather than left as a second answer.

A component no stage names lands in a trailing band, and
`tests/test_flow_steps.py` fails until it is placed or named under `unplaced` —
the same contract as `unknown.yaml`. The file is required, found by the same
upward walk `load_owner_colors` and `load_policy` use, and `build-dashboard`
fails without it. `in_stage_order` *does* still fall back to `in_flow_order`
with no bands, and that fallback is exactly why a missing file is refused: a
build run from outside a checkout would otherwise publish the derived order the
file exists to replace, and look finished doing it.

**Change owner node colours** → edit `config/owner-colors.csv`. No code
change. Row order is legend order. Keeping this a data file is deliberate:
project managers change colours without touching Python. Don't move it into a
constant. There is one copy: the wheel build maps this file to
`translator_diagram/owner-colors.csv`, which is where an install with no
checkout to read falls back to, so nothing has to be kept in step by hand. In
a source checkout that packaged path does not exist and nothing needs it,
because `config/` is right there. See `load_owner_colors` for the resolution
 order and `[tool.hatch.build.targets.wheel.force-include]` for the mapping.

The four rules constraining a new owner colour — which hues are reserved, the
contrast floor, the luminance line, and the fact that the palette is full — are
in [`docs/owner-colours.md`](../../docs/owner-colours.md), where somebody
choosing a colour will find them.

Generating that copy at build time is the obvious simplification and it does
not work: hatchling's `force-include` reaches the wheel but not an editable
install, so `uv sync` would leave every developer — and CI — without the
fallback wheel users get.

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
data-model table above, and the CSV-format table in the README.

**Add a new CLI flag** → an `@click.option` above `main` in `cli.py`, plus the
matching parameter in the `main` signature, plus the options block in the
README (it is a hand-maintained paraphrase of `--help`, not generated).

**Add a column to the dashboard** → `build_cell` or `build_rows` in
`dashboard.py` for the value, then **one entry in the `COLUMNS` table** in
`web/dashboard.js`, and `web/dashboard.css` if it needs a style. That entry
owns the header, the body cell, the `drop-*` class that hides both at narrow
widths, the sort value and the column count the empty row's colspan needs —
they used to be written out separately, which is how a header ends up hidden
without its column. The payload written to `overview.json` is a contract a
scheduled job would publish, so adding a key is safe and renaming one is not.
The payload keys are independent of the YAML keys they happen to be spelled
like: `layer` and `refactor_status` moved out of `diagram:` in the component
files without the payload changing at all, because `build_rows` writes those
names as string literals. Rename a YAML key freely; renaming a payload key
breaks `web/dashboard.js`.

`type` and `layer` are the exception in the other direction: the page no
longer shows either — neither told a reader anything the stage bands and the
owner chip do not — so both are payload keys with no column, no filter and no
query-string parameter. They stay in `overview.json` because it is a contract
and dropping a key from it is the change that breaks a consumer.

**Change what the published page withholds** → `config/privacy.yaml`. No code
change: it lists whole components to drop and row or per-environment fields to
empty, each with a reason. `build-dashboard` applies it by default and
`--include-private` skips it, which is the safe way round — a forgotten flag
costs information rather than publishing it, and
`.github/workflows/pages.yml` passes no flag at all so it cannot be edited into
a full build.

An entry that matches nothing is a hard error. Withholding *nothing* is the
one failure this file must not have, so renaming a component without updating
the policy stops the build instead of quietly publishing the row. For the same
reason `build-dashboard` calls `privacy.verify` on the finished payload before
writing it: `apply` removes, `verify` re-reads the serialised result and looks
for what should be gone, which catches a field added later that carries a
withheld id somewhere `apply` never looks. It looks for the id as a whole
word, bounded by anything that is not a letter or a digit — a substring search
would fail every published build the day someone withholds a component called
`ars` or `ui`, naming a leak that is not there, and the only way to clear a
false alarm is to stop running the check.

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

## What the dashboard refuses to claim

Each of these is a rule with a test behind it, and each was a bug first. They
are collected because the failure mode they share is silence: the page keeps
rendering, and says something that is not true.

- **A version it did not fetch.** `sync` writes a body only on a 200 and leaves
  the previous one where it is, so `SyncedData` reads an OpenAPI or `/status`
  body only when this run's manifest entry for that path is a 200 with no
  error. Otherwise a component whose prod had gone away kept reporting the
  version it last served, with `reachable: true` beside its own 404. Release
  lists and Helm charts are deliberately *not* gated: neither says anything
  about what is running now, and dropping a cached release list because GitHub
  rate-limited the run would lose real information.
- **A data release as a software version.** `/status` has no Translator-wide
  schema, so the version is the first `*_version` key — with `babel_version`,
  `biolink_version`, `biolink_model_version` and `trapi_version` excluded, or a
  body that lists Biolink first would have that badged as its software.
- **An odd one out where there is none.** A tie in a version split marks *every*
  reporting environment. `Counter.most_common` breaks ties by insertion order,
  which here is column order, so two-against-two used to tint whichever pair sat
  further right.
- **A derived host it has not confirmed.** `_confirm_derived` believes a guessed
  hostname only if the document it returns reports the component's own
  `infores`; without a recorded infores the candidate is dropped, because an
  unverifiable guess is worth less than a gap. A host that answers 200 with
  something else has its body deleted rather than cached. A rejection this run
  also outranks an older confirmation — otherwise one success published a
  deployment for good.
- **A hostname chosen by the alphabet.** Where a component's known URLs span two
  `transltr.io` stems, the derived host uses the commonest stem, earliest on the
  ladder among equals.
- **Fewer release chips than it has.** The "newest three" cut counts chips kept,
  not entries seen, or two draft releases spend two of the three places.
- **Attempts it did not record.** Every probe reaches `report.fetches`,
  including the ones that fail, which is why the Fetches tile counts more than
  the endpoints — the manifest promises every attempt.
- **A leak that is not one.** `privacy.verify` matches a withheld id bounded by
  non-alphanumerics. As a substring it would abort every published build the day
  someone withholds `ars` or `ui`, and a false alarm nobody can clear ends with
  the check switched off.

Two more of the same family live in the code because they are local: a
malformed OpenTelemetry answer costs its tile rather than the run, and a
registry or guessed host answering unexpected JSON is caught rather than
raising through `sync`.

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

**The privacy filter is about reach, not secrecy.** Everything the dashboard
shows is read from public services, this repository is public, and
`config/privacy.yaml` names what it withholds and why — so it hides nothing
from anyone who looks. What it does is keep a handful of things off an indexed
page that arrives without being asked for. The corollary matters more than the
filter: because nothing here comes from the private spreadsheet any more, a
genuine leak would be a secret already being served by a public API, and the
fix for that is upstream, at that API. Redacting it here would only make it
harder to notice. So treat a finding as "review it and revert" rather than as
an emergency, and do not let the filter become the reason nobody looks at what
the sources are publishing.

**A published build is the local build minus rows, not a different page.**
`privacy.apply` runs inside `build_payload` *after* `build_rows`, so
`flow_depths` and `isolated` still see every component and the rows that
survive keep their depths, steps and left bars. Filtering the component list
before building the rows would let a withheld component move everything else,
and the two builds would disagree about the shape of the platform rather than
about how much of it is shown. It also runs *before* `source_tally` and
`unregistered_count`, which are computed from `rows` — that is what stops a
tile counting things the table does not show.

**A stage whose components are all withheld disappears entirely.** Bands are
rendered from the rows in them, so the Engineering stage — `jaeger` and
`test-harness`, the only two in it — is absent from a published build rather
than showing as an empty header. Step numbers come from the stage's position
in `config/flow-steps.yaml`, so the others are not renumbered; a published page
runs 1–8 and skips 9.

**The dashboard opens on every component**, having once opened on
`Environments disagree` — which showed 7 rows of 24 and hid the platform to
make a point about drift, so someone looking up one component found it missing
from a page that never said it was filtered. Drift is still the first thing the
page says, in the finding above the table. The four views (`all`, `differ`,
`known`, `none`) live in `VERSION_VIEWS` in `web/dashboard.js`, listed in that
order so the default reads first, with `DEFAULT_VIEW` naming it. `differ` means
any of the three tinted axes, not versions alone. It replaced a "Drift only"
toggle rather than joining it: two controls that select the same rows cannot be
told apart by a reader.

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
