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
| [`owner-colors.csv`](owner-colors.csv) | Each owning team's colour; [`owner-colors.md`](owner-colors.md) has the rules for choosing one |
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
   colour by the rules in `owner-colors.md`.
4. If the component claims an identifier listed in `unknown.yaml`, delete that
   entry (see [Promotion](#unknownyaml) below).

## Rules the tests enforce

- The filename stem equals `id`, and ids are unique case-insensitively.
- Every id in `connections.gets_results_from` or `connections.calls` has a
  file. That is why `docmetadata-api` has one: `ui` calls it.
- Every `owner` appears in `owner-colors.csv`.
- `hosted_at`, each environment's `location`, and `layer` take one of the
  values listed in `schema/component.schema.json` (`$defs/host` for the first
  two). A new host or layer is added there in the same change as the first
  component that uses it, so a misspelling fails rather than quietly becoming
  a new one.
- `endpoints` values and `examples` paths are relative paths, never URLs.
- No component has more than three `examples`.
- A `summary` is one line of at most 160 characters, and a `description` is a
  `|` block rather than `>`.
- No file writes a `diagram:` flag at its default, which keeps that block
  absent rather than a copy of `ubiquitous: false` in every file.
- A `third_party` block names its `software`, and its `url`, if any, is
  http(s).
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

**Recording `status` vouches for its `version`.** A /status body has no
shared schema, so the dashboard reads a plain `version` key from it as the
software's own version, ahead of any `*_version` key, and badges it `status`.
Before you record one, look at the body: if its bare `version` is a TRAPI,
Biolink or data release instead, the cell would show that as the software,
so say so in an issue rather than recording the endpoint. The same body's
`babel_version` and `biolink_model.tag` are read as the data the deployment
runs on, and drawn as pills under its version; the Biolink tag is checked
against biolink-model's tags, so a body that reports a branch (`master`)
earns the component a finding until it reports the release it loaded.

**Environments are recorded only where SmartAPI cannot supply them.** For a
registered component the block should be *absent*, and a fetcher fills it in.
The unit is the environment, not the component: registration is manual and
routinely partial, so a component can be registered for prod and say nothing
about the ci and test it is also deployed to. `answer-appraiser` is the live
example — its record lists production only — so its `environments:` block
carries the two SmartAPI does not cover and leaves prod to the fetcher.

**An infores can bring a SmartAPI record with it.** Where a file records no
`identifiers.smartapi`, the one registry record that claims its `infores` is
attached as though it had been recorded, deployments and all; where several
claim it, none is. That is usually what you want, and it is why a stale
registration matters: `nodenorm-redis` has its infores commented out until its
record stops listing a host it no longer runs on.

**`summary`, `description` and `notes` answer different questions.**

- `summary` — *what is this?* One line, plain text, that makes sense on its
  own: the Component view shows it under the component's name. "Contains ARAX,
  ARAGORN and BTE" is not a summary; it needs the name beside it.
- `description` — *what does it do, and where is it going?* As long as it
  needs, in a small Markdown subset: paragraphs, `code`, `-` lists and
  `[links](https://…)`. Write it with `|` rather than `>`, because `>` folds
  the line breaks a list needs. Write it only where the component's own
  documentation does not already say it well; otherwise link that under
  `documentation` instead of copying it here.
- `notes` — *why does our record of it look like this?* Why a field is null,
  overridden or unusual, and what a reader needs to make sense of a cell.
  Plain text. An explanation only a curator needs goes in a YAML comment
  beside the field it explains, as the `endpoints:` comments do.

[`components/docmetadata-api.yaml`](components/docmetadata-api.yaml) has all
three. All three are published, so keep them to public information.

**Software we deploy but did not write is a component too, marked
`third_party`.** Jaeger is upstream code on our chart, and a MongoDB or Redis
a service reads is a pod we run. Each gets a file when it is deployed on its
own — its own chart or ITRB app, so a version per environment to show — or is
shared by more than one component, like the Elasticsearch behind `nodenorm-es`
and `nameres-es`, which has no single service file to live in. A datastore
bundled as a dependency inside its service's own chart is not a component:
mention it in the service's `description`. The block says whose code it is:

```yaml
third_party:
  software: Jaeger                      # the upstream project's name
  url: https://www.jaegertracing.io/    # its home page; optional
```

Absent means Translator-written; `null` means checked, our own code. The rest
of the file is filled like any component's: `owner` is the team that runs it,
`refactor_status` is required, `component_type` is absent (it is not a
registered API service), and the upstream repository goes under
`repositories` with `role: related`. A datastore takes its service's `layer`,
is listed in `flow-steps.yaml` right after that service, and takes `part_of`
only where the service has one; the service lists it under `connections.calls`.
Its `summary` says what the software does for us — "third-party" is the
field's job now, not the summary's. [`components/jaeger.yaml`](components/jaeger.yaml)
is the live example; `omnicorp-redis` in `unknown.yaml` is the kind of
thing the rule decides.

A maintainer can still count a separately deployed datastore as part of its
service, when it exists only for that service and they ship together. Its
chart then goes on the service's `identifiers.helm_chart` with the others, and
a comment there says why. `nodenorm-redis` is the example: its seven Redis
databases are their own chart, `redis-r3-external`, recorded beside the web
server and the loader.

**Examples are for trying a component, not testing it.** `examples` holds
up to three GET requests someone could make to see what a component does,
each a `description` and a `path` relative to every environment's base URL,
the same convention as `endpoints`. [`components/docmetadata-api.yaml`](components/docmetadata-api.yaml)
is the live example. Three is the cap because a longer list is a test suite,
and those belong in the Test Harness. A TRAPI component's SmartAPI record
already points at its test data, so don't copy that here. Most files have no
examples yet; absent means not recorded, and nothing runs them yet — that is
[#57](https://github.com/NCATSTranslator/translator-diagram/issues/57).

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
  `status: retired` and nobody investigates it twice.

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
| `operation` | A processing step reporting under its own service name, not a component | `component`, the service it is a step of | Only by becoming `retired`. It stays so nobody attributes it |
| `out-of-scope` | We know what it is, and it is not something this repo records as a component: part of a legacy or adjacent stack, or not the kind of identifier its section lists | `evidence`, saying why | `not-recorded`, if the component sheet gains a row for it; `retired`, if it stops running |
| `retired` | Someone confirmed it stopped running | | Nothing. It stays so nobody investigates it twice |

Three distinctions do most of the work:

- **`unattributed` versus `needs-decision`.** The question is whether more
  looking would settle it. `shepherd-server` is understood from its traces,
  and what is missing is a decision about whether the shared Shepherd server
  is its own component. A chart whose `Chart.yaml` is the unedited
  `helm create` default is `unattributed` until someone looks inside it.
- **`needs-decision` versus `out-of-scope`.** `out-of-scope` is itself a
  decision, and one nobody expects to revisit. If a maintainer could
  reasonably want a component file for it, it is `needs-decision`.
- **`out-of-scope` versus `retired`.** A legacy chart that is still
  deployed is `out-of-scope`, not retired. `retired` means someone
  confirmed it stopped running, so something that has not started running
  yet, such as a component still in development, is never `retired`.

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
