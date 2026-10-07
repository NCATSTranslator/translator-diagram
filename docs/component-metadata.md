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

One file per component, `catalog/components/<id>.yaml`. The filename stem
**is** the id — a test enforces it. Each team edits its own file, `git log` gives
per-component history, and a future `CODEOWNERS` can route review. They
sit in their own subdirectory of `catalog/`, beside everything else a curator
edits, so that every `*.yaml` in it is exactly one component and nothing that
reads them needs an exception.

YAML rather than TOML because every neighbour in this ecosystem is YAML — the
infores catalog, SmartAPI specs, Helm charts, mkdocs, GitHub Actions — and
because the data is nested and list-heavy in ways TOML renders awkwardly.
Both support comments, so that was not the deciding factor.

`catalog/schema/component.schema.json` is the authoritative field list.
`catalog/components/name-lookup.yaml` is the worked example; here it is in full:

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

There is no `diagram:` block, and most files have none. It holds `ubiquitous`
and `hide` — the two fields that really are about the picture rather than the
component — and both default to `false`, which is what most components are.
The block appears only in a file where one of them is `true`.

There is no `examples:` block yet either. It holds up to three GET requests
someone could make to try the component, as paths relative to each
environment's base URL like `endpoints`; `docmetadata-api` is the first file
with one, and what the field is for is in
[`catalog/README.md`](../catalog/README.md#conventions).

### `unknown.yaml`

Not every identifier we find belongs to a component we know about. The 41
OpenTelemetry service names reporting to the three collectors include seven
that are Shepherd *operations* rather than components, twelve that belong to
components with no file yet, two that wait on a maintainer's decision, and one
we cannot place. The Helm chart index has the same problem with more entries.

Those go in [`catalog/unknown.yaml`](../catalog/unknown.yaml) rather than
being dropped, with the evidence for whatever we do believe, so the next
person does not have to rediscover them. One file rather than one per entry,
because an unattributed entry has no component id to name a file after, and a
single list is what a test can check for an identifier claimed twice — which
is what stops a retired entry from quietly coming back.

What each `status` means and how an entry leaves it is in
[`catalog/README.md`](../catalog/README.md#unknownyaml), beside the file.

### Conventions

The rules a component file follows — absent versus `null`, relative
endpoints and examples, environments only where SmartAPI cannot supply them,
the `~` prefix, a file set closed under references, and public information
only — are in [`catalog/README.md`](../catalog/README.md#conventions), each
with its reason, so that a curator finds them without leaving that directory.

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
the two flags that earned it. That block is absent from most files, because
both flags default to `false` and most components are. The eight files whose
`identifiers:` block turned out to hold nothing but `itrb_app` and
`itrb_group` are why ITRB moved out at the same time: a group is not a name
for a component, it is a namespace around an application.

**5. How much should be pulled versus pinned?** A fetched value is always
current and sometimes unavailable; a pinned value is always available and
sometimes wrong. This proposal pulls everything it can and pins nothing, on
the grounds that a wrong answer is worse than a missing one.

## How this replaces the sheet

Not in this pull request. The order after it:

1. A fetcher reads `catalog/components/*.yaml`, queries SmartAPI once, fetches each
   `openapi` and `status` endpoint, and writes an enriched `components.json`
   into the gitignored `data/`. It caches, and a component being down never
   fails the diagram.
2. `loading.py` reads YAML instead of CSV, and `--google-sheet` retires. A
   one-way `--export-csv` keeps a spreadsheet view available for anyone who
   wants one.
3. [Issue #6](https://github.com/NCATSTranslator/translator-diagram/issues/6)
   — reconciling against the list ITRB sends — joins on `itrb.app` and
   `itrb.group`.
