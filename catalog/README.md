# The component catalog

Everything a curator of the Translator component records edits is in this
directory, and you should not need to look anywhere else. The dashboard is
built from these files; the code that reads them is not something you need to
open.

| File | What it holds |
|---|---|
| [`components/<id>.yaml`](components/) | One file per component: who owns it, its name in each naming space, what it calls, where it runs |
| [`unknown.yaml`](unknown.yaml) | Identifiers seen in the platform that no component file claims yet, and what we know about each |
| [`flow-steps.yaml`](flow-steps.yaml) | The dashboard's stages, in page order, and which components sit in each |
| [`owner-colors.csv`](owner-colors.csv) | Each owning team's colour; [`owner-colours.md`](owner-colours.md) has the rules for choosing one |
| [`schema/`](schema/) | The field reference for `components/*.yaml` and `unknown.yaml`. Editors that understand `yaml-language-server` pick it up from each file's header |

Every file here is checked by the test suite, so a wrong edit fails loudly
rather than silently doing nothing. After any change, run from the repository
root:

```bash
uv run pytest
```

## Adding a component

1. Write `components/<id>.yaml`. The filename stem is the id, in kebab-case.
   [`components/name-lookup.yaml`](components/name-lookup.yaml) is the worked
   example, and
   [`schema/component.schema.json`](schema/component.schema.json) describes
   every field.
2. Place the id in a stage in `flow-steps.yaml`, or under `unplaced` if it
   genuinely belongs to none yet.
3. If its owner is a new team, add a row to `owner-colors.csv`, choosing the
   colour by the rules in `owner-colours.md`.
4. If the component claims an identifier listed in `unknown.yaml`, delete that
   entry (see [Promotion](#unknownyaml) below).

## Rules the tests enforce

- The filename stem equals `id`, and ids are unique case-insensitively.
- Every id in `connections.gets_results_from` or `connections.calls` has a
  file. That is why `docmetadata-api` has one: `ui` calls it.
- Every `owner` appears in `owner-colors.csv`.
- `endpoints` values are relative paths, never URLs.
- No file writes a `diagram:` flag at its default, which keeps that block
  absent rather than 26 copies of `ubiquitous: false`.
- Every component is either in a stage or listed under `unplaced` in
  `flow-steps.yaml`.
- No identifier is claimed by two components, or by a component *and*
  `unknown.yaml`.

`diagram.ubiquitous: true` marks cross-cutting infrastructure (jaeger today)
that the Map view draws beside each caller instead of as one central node.
`diagram.hide: true` removes a component from the Map only; it stays in the
Overview table (ploverdb today).

## Conventions

**Absent means "not recorded yet". Explicit `null` means "checked, there is
none."** The sheet already needs this distinction — it writes `NA` in the
`OpenAPI URL` column for components that genuinely have no OpenAPI document.
Collapsing the two would send a fetcher back to the same dead ends forever.

**Endpoints are relative paths, not URLs.** One line covers all four
environments instead of four near-identical absolute URLs per endpoint kind.
Where an environment does not follow the shared pattern, it carries its own
`endpoints:` block. `node-annotator` is the live example and the reason the
override exists: ci and test serve `webapp/openapi.json`, prod serves
`openapi.json`, and ci and test are the intended convention going forward — so
the override records the exception rather than the rule.

**Environments are recorded only where SmartAPI cannot supply them.** For a
registered component the block should be *absent*, and a fetcher fills it in.
The unit is the environment, not the component: registration is manual and
routinely partial, so a component can be registered for prod and say nothing
about the ci and test it is also deployed to. `answer-appraiser` is the live
example — its record lists production only — so its `environments:` block
carries the two SmartAPI does not cover and leaves prod to the fetcher.

**A `~` prefix marks a planned relationship**, unchanged from the sheet:
`calls: [~jaeger]` is an edge we intend but have not built, and renders red.
Note that a bare `~` is YAML `null`; the schema requires at least one
character after it, so a stray tilde fails validation rather than becoming a
silent null in the middle of a list.

**The file set is closed under references.** Every id in
`connections.gets_results_from` or `connections.calls` must have a file, even
when the component itself is filtered out of the diagram — the generator's
ghost-node rendering exists for exactly that case.

**An empty list is a claim; a default flag is not.** `gets_results_from: []`
says this component was checked and gets results from nothing, which is the
absent-versus-`null` rule applied to a list — so `connections:` keeps its
empty lists. A `diagram:` flag at its default says only what the schema
already says, so it is not written at all, and the block goes with it once it
is empty. The distinction is why one block is full of `[]` and the other is
usually missing.

**Public information only.** Every URL in this repo is already publicly
reachable; the transltr.io endpoints are all discoverable through SmartAPI. A
private repository may be *linked* (`visibility: private`), but nothing inside
it may be copied here, and no fetcher may read it. That rule is what keeps
this repo publishable without a per-field review.

**Quote ISO dates.** YAML parses a bare `2026-08-31` into a date, which is not
a JSON Schema string, and the failure message points at the schema rather than
the quoting.

## `unknown.yaml`

Identifiers we find but cannot yet attribute to a component file — today,
OpenTelemetry service names and Helm chart directories — go in `unknown.yaml`
rather than being dropped, with the evidence for whatever we do believe.
Entries leave it in one of two ways:

- **promoted** — we learn which component it belongs to, so the identifier
  moves into that component's file (or gets a new component file) and the
  entry is deleted;
- **retired** — someone confirms it is out of use, so it stays with
  `status: not-in-use` and nobody investigates it twice.

Never delete an entry to make a test pass: an entry is removed only when its
identifier moves into a component file.

Every entry has a `status`, which says how much we know and what would move it
on. The schema holds a one-line version of this table and rejects any other
value.

| `status` | Means | Must also have | Leaves by |
|---|---|---|---|
| `unattributed` | We do not know what this is, or which component it belongs to | | Finding out, then taking whichever status fits |
| `not-recorded` | It belongs to a component the sheet lists, which has no file yet | `component`, the sheet row's id | Promotion, when the file is written. A test fails once the file exists and the entry is still here |
| `needs-decision` | We know what it is, but where it is recorded is a maintainer's call — including whether a service the sheet does not list should become a component | `note`, saying what the decision is | `not-recorded`, promotion or `out-of-scope`, once someone decides |
| `operation` | A processing step reporting under its own service name, not a component | `component`, the service it is a step of | Only by becoming `not-in-use`. It stays so nobody attributes it |
| `out-of-scope` | We know what it is, and it is not something this repo records as a component: part of a legacy or adjacent stack, or not the kind of identifier its section lists | `evidence`, saying why | `not-recorded`, if the component sheet gains a row for it; `not-in-use`, if it stops running |
| `not-in-use` | Confirmed retired | | Nothing. It stays so nobody investigates it twice |

Three distinctions do most of the work:

- **`unattributed` versus `needs-decision`.** The question is whether more
  looking would settle it. `shepherd-server` is understood from its traces,
  and what is missing is a decision about whether the shared Shepherd server
  is its own component. A chart whose `Chart.yaml` is the unedited
  `helm create` default is `unattributed` until someone looks inside it.
- **`needs-decision` versus `out-of-scope`.** `out-of-scope` is itself a
  decision, and one nobody expects to revisit. If a maintainer could
  reasonably want a component file for it, it is `needs-decision`.
- **`out-of-scope` versus `not-in-use`.** A legacy chart that is still
  deployed is `out-of-scope`, not retired. `not-in-use` means someone
  confirmed it stopped running.

`component` means slightly different things by section. On an OTel service it
names the component the service belongs to. On a Helm chart it names the
component the chart *deploys*, and one component may deploy several charts,
since `identifiers.helm_chart` accepts a list. On an `unattributed` entry it is
at most a guess, to be read alongside `evidence`.

To find a chart's sheet row, compare the chart directory with the sheet's
`ITRB App Name` column rather than its `Helm chart` column. For an
ITRB-hosted row the app name is the chart directory, and `Helm chart` is
filled on only two rows.

The file takes other kinds of unattributed identifier as they turn up — a
new top-level key in the schema for each kind; `urls:` is already there.
