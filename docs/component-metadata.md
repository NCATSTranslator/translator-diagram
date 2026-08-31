# Component metadata: a proposal

**Status:** proposal, for discussion. Nothing here is wired into the diagram
generator yet — `loading.py` still reads the Google Sheet.

## The problem

The single source of truth today is a world-readable Google Sheet. It works,
and it is about to stop working. The live export already has 19 columns, five
of which nothing reads, and every new kind of link we want to record — the
OpenAPI document, the Helm chart, the wiki page, the four deployment
environments — makes it wider. Recording all of that in the sheet would turn
this repo into a second copy of information that already exists somewhere
else, and second copies go stale.

[Issue #7](https://github.com/NCATSTranslator/translator-diagram/issues/7)
names the trap: *"We don't want this repo to become another documentation
source that could go out of date."*

## What this repo is actually for

**Establishing identifiers.** Translator components are named independently in
at least five places, and no two of those names can be computed from each
other. Name Lookup is:

| Naming space | Name |
|---|---|
| GitHub repository | `NCATSTranslator/NameResolution` |
| Helm chart | `name-lookup` |
| Information Resource | `infores:sri-name-resolver` |
| Deployment hostname | `name-lookup.ci.transltr.io` |
| Translator-All wiki | `Name-Resolution-Service` |

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
- how it should be drawn (layer, grouping, refactor status).

**Pointed at**, because somewhere upstream is already authoritative:

| Wanted | Authoritative source |
|---|---|
| Description, API version, TRAPI version, team | OpenAPI `info.x-translator` |
| Deployment URLs per environment | SmartAPI `servers[].x-maturity` |
| Software version, data release, liveness | the component's `/status` |
| Container image, resources, data downloads | Helm `values.yaml` |
| Prose documentation | the repo, the wiki, the tech docs site |
| Knowledge level, agent type, consumers | the infores catalog |

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

identifiers:                     # this component's name everywhere else
  infores: infores:sri-name-resolver
  smartapi: "9995fed757acd034ef099dbb483c4c82"
  helm_chart: name-lookup
  itrb_app: name-lookup
  itrb_group: SRI-Ranking
  translator_all_wiki: Name-Resolution-Service

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

diagram:                         # the part nothing upstream knows
  refactor_status: Continues into Refactor
  layer: Shared services
  hosted_at: ITRB
  ubiquitous: false
  hide: false
  gets_results_from: []
  calls: [jaeger]
  externals: []
```

### Conventions

**Absent means "not recorded yet". Explicit `null` means "checked, there is
none."** The sheet already needs this distinction — it writes `NA` in the
`OpenAPI URL` column for components that genuinely have no OpenAPI document.
Collapsing the two would send a fetcher back to the same dead ends forever.

**Endpoints are relative paths, not URLs.** One line covers all four
environments instead of four near-identical absolute URLs per endpoint kind.
Where an environment does not follow the shared pattern, it carries its own
`endpoints:` block — `node-annotator` is the live example, and the reason the
override exists.

**Environments are recorded only where SmartAPI cannot supply them.** For a
registered component the block should be *absent*, and a fetcher fills it in.
Every `environments:` block in this repo is a component SmartAPI does not
cover.

**A `~` prefix marks a planned relationship**, unchanged from the sheet:
`calls: [~jaeger]` is an edge we intend but have not built, and renders red.
Note that a bare `~` is YAML `null`; the schema requires at least one
character after it, so a stray tilde fails validation rather than becoming a
silent null in the middle of a list.

**The file set is closed under references.** Every id in `gets_results_from`
or `calls` must have a file, even when the component itself is filtered out of
the diagram — the generator's ghost-node rendering exists for exactly that
case. `docmetadata-api` has a file only because `ui` calls it.

**Public information only.** Every URL in this repo is already publicly
reachable; the transltr.io endpoints are all discoverable through SmartAPI. A
private repository may be *linked* (`visibility: private`), but nothing inside
it may be copied here, and no fetcher may read it. That rule is what keeps
this repo publishable without a per-field review.

## Open questions

These are the parts worth arguing about before anyone fills in 96 files.

**1. Is the kebab-case id the right identifier?** It is readable and it is
what the sheet already uses, so this proposal keeps it. But it is *our*
invention, which means we have to maintain it. Two alternatives are
unambiguous and externally maintained:

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

**2. Should Helm charts become a required metadata source?** Today
`Chart.yaml` is boilerplate — see [`metadata-sources.md`](metadata-sources.md)
— so we cannot pull identity from it. But `values.yaml` already carries
resource requests, storage sizes and data-download URLs that exist nowhere
else, and the chart is the one artifact every deployed component must have.
If we want to *require* components to declare basic metadata, the chart is a
plausible place to require it. The counter-argument is coverage: only 5 of the
26 components here have a chart in the public `translator-devops` repo, and
SmartAPI and GitHub already cover far more.

**3. Is `diagram:` the right nesting?** Grouping the drawing-only fields keeps
it obvious which fields describe the component and which describe the picture.
It also means a consumer that only wants the data flow reads one key.

**4. How much should be pulled versus pinned?** A fetched value is always
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
   — reconciling against the list ITRB sends — joins on `identifiers.itrb_app`
   and `identifiers.itrb_group`.
