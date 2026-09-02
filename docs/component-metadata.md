# Component metadata: a proposal

**Status:** proposal, for discussion. Nothing here is wired into the diagram
generator yet — `loading.py` still reads the Google Sheet.

## The problem

The single source of truth today is a world-readable Google Sheet. It works,
and it is about to stop working. The live export has 21 columns, seven of
which nothing reads, and every new kind of link we want to record — the
OpenAPI document, the Helm chart, the wiki page, the four deployment
environments — makes it wider. Recording all of that in the sheet would turn
this repo into a second copy of information that already exists somewhere
else, and second copies go stale.

That is not a prediction. While this proposal was being written the sheet
gained two more columns, `GitHub Repo` and `Helm chart`, and one of them
immediately needed two values in a single cell —
`ui-fe|github.com/NCATSTranslator/ui-be`. The pressure is real and it is
already being answered one column at a time.

[Issue #7](https://github.com/NCATSTranslator/translator-diagram/issues/7)
names the trap: *"We don't want this repo to become another documentation
source that could go out of date."*

## What this repo is actually for

**Establishing identifiers.** Translator components are named independently in
at least six places, and no two of those names can be computed from each
other. Name Lookup is:

| Naming space | Name |
|---|---|
| GitHub repository | `NCATSTranslator/NameResolution` |
| Helm chart | `name-lookup` |
| Information Resource | `infores:sri-name-resolver` |
| Deployment hostname | `name-lookup.ci.transltr.io` |
| Translator-All wiki | `Name-Resolution-Service` |
| OpenTelemetry service | `Nameres`, and also `infores:sri-name-resolver` |

Nothing upstream reconciles those. Until something does, we cannot say "ARS
gets its results from Shepherd-ARAX" in a way a machine can follow, because
there is no agreed handle for either end of that sentence.

So the job this repo takes on is small and specific: **give every component
one identifier, map it to its name in every other naming space, and record the
data flow between those identifiers.** The diagram is what we build from that.
Everything else — descriptions, versions, deployment URLs, resource
requirements — we *point at* rather than copy.

## What lives here, and what does not

**Here**, because nothing else records it:

- the component id, and its name in each other naming space;
- who owns the component;
- the data flow: what it gets results from, and what it calls;
- where it sits: its refactor status, its layer, the subsystem it is part of,
  and where it runs;
- how it should be drawn, in the rare case that needs saying at all.

**Pointed at**, because somewhere upstream is already authoritative:

| Wanted | Authoritative source |
|---|---|
| Description, API version, TRAPI version, team | OpenAPI `info.x-translator` |
| Deployment URLs per environment | SmartAPI `servers[].x-maturity` |
| Software version, data release, liveness | the component's `/status` |
| Container image, resources, data downloads | Helm `values.yaml` |
| Prose documentation | the repo, the wiki, the tech docs site |
| Knowledge level, agent type, consumers | the infores catalog |
| Which services actually call which | the OpenTelemetry collectors |

[`metadata-sources.md`](metadata-sources.md) records what each of those
actually offers today, and where each one falls short.

## The format

One file per component, `components/<id>.yaml`. The filename stem **is** the
id — a test enforces it. Each team edits its own file, `git log` gives
per-component history, and a future `CODEOWNERS` can route review.

YAML rather than TOML because every neighbour in this ecosystem is YAML — the
infores catalog, SmartAPI specs, Helm charts, mkdocs, GitHub Actions — and
because the data is nested and list-heavy in ways TOML renders awkwardly.
Both support comments, so that was not the deciding factor.

`schema/component.schema.json` is the authoritative field list.
`components/name-lookup.yaml` is the worked example; here it is in full:

```yaml
id: name-lookup
name: Name Lookup (NameRes)
owner: DOGSLED
component_type: Utility          # the x-translator `component` vocabulary
refactor_status: Continues into Refactor
layer: Shared services           # the band the diagram draws as a row
hosted_at: ITRB

identifiers:                     # this component's name everywhere else
  infores: infores:sri-name-resolver
  smartapi: "9995fed757acd034ef099dbb483c4c82"
  helm_chart: name-lookup
  translator_all_wiki: Name-Resolution-Service
  otel_services:                 # a list: components report under several
    - Nameres
    - infores:sri-name-resolver

itrb:                            # two coordinates, so not an identifier
  app: name-lookup
  group: SRI-Ranking

connections:                     # the data flow, recorded by hand
  gets_results_from: []
  calls: [jaeger]
  externals: []

repositories:
  - url: https://github.com/NCATSTranslator/NameResolution
    role: source                 # source | helm-chart | deployment | data | related
    visibility: public
  - url: https://github.com/helxplatform/translator-devops/tree/develop/helm/name-lookup
    role: helm-chart
    visibility: public

documentation:
  - url: https://github.com/NCATSTranslator/Translator-All/wiki/Name-Resolution-Service
    kind: wiki                   # wiki | technical-documentation | api-docs | readme | other

endpoints:                       # paths relative to an environment's base URL
  openapi: openapi.json
  status: status?full=true
  docs: docs
```

There is no `diagram:` block, and there is none in any of the 26 files. It
holds `ubiquitous` and `hide` — the two fields that really are about the
picture rather than the component — and both default to `false`, which is what
every component is. The block appears the first time one of them is `true`.

### `unknown.yaml`

Not every identifier we find belongs to a component we know about. The 41
OpenTelemetry service names reporting to the three collectors include seven
that are Shepherd *operations* rather than components, twelve that belong to
components with no file yet, and three we cannot place.

Those go in [`unknown.yaml`](../unknown.yaml) rather than being dropped, with
the evidence for whatever we do believe. Entries leave it in one of two ways:

- **promoted** — we learn which component it belongs to, so the identifier
  moves into that component's file (or gets a new component file) and the
  entry is deleted;
- **retired** — someone confirms it is out of use, so it stays with
  `status: not-in-use` and nobody investigates it twice.

`tests/test_components.py` enforces the part that would otherwise rot: no
identifier may be claimed by a component *and* sit in `unknown.yaml`, no two
components may claim the same one, and a `not-recorded` entry naming a
component that now has a file fails until it is promoted.

The same file takes other kinds of unattributed identifier as they turn up —
`urls:` is already in the schema.

### Conventions

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
ghost-node rendering exists for exactly that case. `docmetadata-api` has a
file only because `ui` calls it.

**An empty list is a claim; a default flag is not.** `gets_results_from: []`
says this component was checked and gets results from nothing, which is the
absent-versus-`null` rule applied to a list — so `connections:` keeps its
empty lists. The block and all three of its lists are *required*, which is the
one place this format does not let absence stand for "not recorded yet": the
dashboard renders the empty list as a claim, and a reader cannot tell an
unanswered question from an answered one. A `diagram:` flag at its default
says only what the schema already says, so it is not written at all, and the
block goes with it once it is empty. The distinction is why one block is full
of `[]` and the other is usually missing.

**Public information only.** Every URL in this repo is already publicly
reachable; the transltr.io endpoints are all discoverable through SmartAPI. A
private repository may be *linked* (`visibility: private`), but nothing inside
it may be copied here, and no fetcher may read it. That rule is what keeps
this repo publishable without a per-field review.

## Open questions

These are the parts worth arguing about before anyone fills in 96 files.

**1. Is the kebab-case id the right identifier? — decided, for now: yes.**
It is readable, it is what the sheet already uses, and every reference in
these files already resolves through it. The cost is that it is *our*
invention, so we maintain it. Two alternatives are unambiguous and externally
maintained, and both are worth revisiting before we scale past 26 files:

- the **GitHub repository** (`NCATSTranslator/NameResolution`) — universal,
  every component has one, easy to look up. But some components map to several
  repos (`ui` is `ui-fe` plus `ui-be`) and several map to one
  (`shepherd-arax`, `shepherd-aragorn` and `shepherd-bte` all live in
  `BioPack-team/shepherd`), so it is not one-to-one.
- the **URL slug** (`name-lookup`, `nodenorm-es`) — matches what operators
  actually type, and is close to the ITRB app name. But it is per-environment
  and it changes when a service moves host.

We could also adopt `infores:` outright, but it does not cover us: several
components here (`dogpark-tier-0`, `dingo-ingest`, `shepherd`'s siblings
partially) have no infores, and the catalog mixes upstream data sources in
with Translator software with no field distinguishing the two.

Nothing is lost by deciding this later: `identifiers` already records the
GitHub repository and the ITRB app name, so a switch is a rename plus a
reference rewrite, not a re-survey. What would be lost is doing it *twice* —
so the question wants an answer before the remaining 70 components get
files.

**2. Should Helm charts become a required metadata source?** Today
`Chart.yaml` is boilerplate — see [`metadata-sources.md`](metadata-sources.md)
— so we cannot pull identity from it. But `values.yaml` already carries
resource requests, storage sizes and data-download URLs that exist nowhere
else, and the chart is the one artifact every deployed component must have.
If we want to *require* components to declare basic metadata, the chart is a
plausible place to require it. The counter-argument is coverage: only 5 of the
26 components here have a chart in the public `translator-devops` repo, and
SmartAPI and GitHub already cover far more.

**3. Should the OpenTelemetry call graph check the recorded data flow?**
The collectors observe which service actually called which, which is the same
question `gets_results_from` and `calls` answer by hand. Comparing the two
would catch both a stale edge and a dependency nobody declared. It is not
free: service names are a naming space of their own, async work distorts span
parentage, and a trace only shows edges that were exercised.

**4. Is `diagram:` the right nesting? — decided: no, and it has been split.**
The argument for it was that grouping the drawing-only fields keeps it obvious
which describe the component and which describe the picture. The block did not
hold to that: of its nine fields only `ubiquitous` and `hide` were about the
picture. The refactor status, the layer, the subsystem and the host are what
the component *is*, and the data flow is one of the four jobs this repo
exists to do — so filing it under drawing was backwards.

They are now top-level fields, `connections:` and a `diagram:` block holding
the two flags that earned it. That block is absent from all 26 files, because
both flags default to `false` and every component is. The eight files whose
`identifiers:` block turned out to hold nothing but `itrb_app` and
`itrb_group` are why ITRB moved out at the same time: a group is not a name
for a component, it is a namespace around an application.

**5. How much should be pulled versus pinned?** A fetched value is always
current and sometimes unavailable; a pinned value is always available and
sometimes wrong. This proposal pulls everything it can and pins nothing, on
the grounds that a wrong answer is worse than a missing one.

## How this replaces the sheet

Not in this pull request. The order after it:

1. A fetcher reads `components/*.yaml`, queries SmartAPI once, fetches each
   `openapi` and `status` endpoint, and writes an enriched `components.json`
   into the gitignored `data/`. It caches, and a component being down never
   fails the diagram.
2. `loading.py` reads YAML instead of CSV, and `--google-sheet` retires. A
   one-way `--export-csv` keeps a spreadsheet view available for anyone who
   wants one.
3. [Issue #6](https://github.com/NCATSTranslator/translator-diagram/issues/6)
   — reconciling against the list ITRB sends — joins on `itrb.app` and
   `itrb.group`.
