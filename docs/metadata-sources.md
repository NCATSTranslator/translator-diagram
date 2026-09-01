# Where Translator component metadata already lives

An inventory of the places that know something about a Translator component,
what each one actually offers, and where each one falls short. Everything
below was checked against the live source on **2026-08-31**; the commands are
included so it can be re-checked rather than believed.

This is the research behind
[`component-metadata.md`](component-metadata.md).

## Summary

| Source | Covers | Gives us | Usable today? |
|---|---|---|---|
| SmartAPI registry | 127 Translator APIs | Deployment URLs per environment, component type, team, TRAPI version, infores | **Yes** — the best source |
| OpenAPI `info` | every registered API | Title, version, description, `x-translator`, `x-trapi` | **Yes** |
| GitHub | every component | Source, README, releases, issue tracker | **Yes**, but six orgs |
| `/status` | some components | Software version, data release, liveness | Partly — no shared schema |
| OpenTelemetry | 41 service names | Runtime service identity, and the real call graph | **Yes**, with attribution work |
| Helm charts | 5 of our 26 | Image, resources, storage, data downloads | Partly — see below |
| infores catalog | 496 resources | Stable CURIE, knowledge level, consumers | As a cross-reference only |
| Technical Documentation | ~15 components | Prose architecture pages | Sparse and stale |
| Translator-All wiki | hundreds of pages | Prose, links | Not machine-readable |

## SmartAPI registry

The strongest source, and the only one that knows deployment URLs.

```bash
curl -s 'https://smart-api.info/api/query?q=tags.name:translator&size=200&meta=1\
&fields=info.title,info.version,info.x-translator,info.x-trapi,servers'
```

127 records: 108 KP, 12 ARA, 6 Utility, 1 ARS.

**Gotcha: `meta=1` is required to get `_id` back.** Without it the response
carries no record identifier at all, which makes the results impossible to
link back to a registry page.

Each record's `servers` array carries two Translator extensions:

```json
"servers":[
 {"url":"https://name-lookup.ci.transltr.io/",   "x-location":"ITRB", "x-maturity":"staging"},
 {"url":"https://name-lookup.test.transltr.io/", "x-location":"ITRB", "x-maturity":"testing"},
 {"url":"https://name-lookup.transltr.io/",      "x-location":"ITRB", "x-maturity":"production"},
 {"url":"https://name-resolution-sri.renci.org/","x-location":"RENCI","x-maturity":"development"}]
```

**Gotcha: `ci` is `x-maturity: staging`, not `development`.** Our ladder maps
onto SmartAPI's as:

| Ours | `x-maturity` |
|---|---|
| `dev` | `development` |
| `ci` | `staging` |
| `test` | `testing` |
| `prod` | `production` |

Where the registry is uneven, and a fetcher must cope:

- `answer-appraiser` registers **production only**; `retriever` registers no
  production at all, and its `dev` is `dev.retriever.biothings.io`.
- `node-annotator` and `smartapi` carry **no `x-maturity`** on some servers,
  and `node-annotator`'s ci/test entries are declared `http://`, not `https://`.
- `arax` registers the API version *in the path*
  (`https://arax.ci.transltr.io/api/arax/v1.4`), so the base URL moves when
  TRAPI does. It also lists four separate `development` servers.
- `name-lookup` and `sri-node-normalizer` list every server **twice**.
- Registration is manual and tied to a GitHub username, so a component nobody
  registered is simply absent.

## OpenAPI `info`

```bash
curl -s https://name-lookup.ci.transltr.io/openapi.json | jq .info
```

```json
{"title":"Name Resolver",
 "version":"1.5.2",
 "x-translator":{"component":"Utility",
                 "team":["Standards Reference Implementation Team"],
                 "infores":"infores:sri-name-resolver"},
 "description":"Name Resolution/Name Lookup service<p/>This service takes …"}
```

`contact` and `license` are commonly absent. `description` contains raw HTML.

The `x-translator` and `x-trapi` extensions are schema'd in
[`NCATSTranslator/translator_extensions`](https://github.com/NCATSTranslator/translator_extensions),
and they give us two controlled vocabularies worth adopting rather than
reinventing:

- `component` ∈ `KP`, `ARA`, `ARS`, `Utility`, `DINGO`, `DAWG`, `SHEPHERD`,
  `COCO`;
- `team`, whose enum **already contains `DOGSLED`, `DOGSURF` and `CATRAX`** —
  so the sheet's `Owner` column is largely this vocabulary already.

A TRAPI component adds `x-trapi` with `version`, `operations`, `asyncquery`,
`rate_limit`, `batch_size_limit` and `test_data_location`.

## GitHub

Every component has source somewhere, but **not in one organisation**. The 26
components recorded here draw on six:

`NCATSTranslator`, `TranslatorSRI`, `RTXteam`, `biothings`, `BioPack-team`,
`helxplatform` — plus `jaegertracing` for the third-party piece we deploy.

Repository names follow no convention a parser could rely on: PascalCase
(`NameResolution`, `TestHarness`), kebab-case (`answer-appraiser`,
`translator-ingests`), snake_case (`Translator_sdk`), and dotted
(`pending.api`). Roughly a third of `NCATSTranslator` repos have an empty
`description`.

The mapping is not one-to-one in either direction: `ui` is `ui-fe` **and**
`ui-be`; `shepherd-arax`, `shepherd-aragorn` and `shepherd-bte` are all one
repo, `BioPack-team/shepherd`.

### Releases

```bash
curl -s 'https://api.github.com/repos/TranslatorSRI/answer-appraiser/releases?per_page=100'
```

`tag_name`, `name`, `html_url`, `published_at`, `prerelease`, `draft`. The
dashboard's Repository column is built from this, matching a tag to a running
version on the `v` prefix alone — `v1.5.2` is what NameResolution tags and
`1.5.2` is what it reports.

**Half of what is running is not a release.** The 21 components with a source
repository point at 19 repositories; 7 of those publish releases at all, and
10 of the 20 distinct running versions match one. The misses are not all the
same kind of miss:

- **No releases published**, in 12 of the 19: the four `biothings`
  repositories, `Relay`, `ui-fe`, `retriever`, `kgx-storage`,
  `Translator_sdk`, `Translator_component_toolkit`, `smartAPI` and
  `DogPark-Ranger`. Nothing can be matched for them.
- **Tags that are not versions.** `RTXteam/RTX` publishes releases, but they
  mark deployments (`itrb-test-premerge-2026-08-04`, `tier0-20260408`) rather
  than the `1.6.2` ARAX reports. The tags and the version are different
  vocabularies, and no normalisation joins them.
- **Running ahead of the repository.** PloverDB reports `2.10.2` while its
  newest release *and* newest tag are both `v2.1.0` — that version is not
  tagged anywhere, so falling back from `/releases` to `/tags` would not find
  it either.

Note also that `published_at` is not the order `/releases` returns: it sorts
by when the release was created, and NameResolution's `v1.5.2` was published
after `v1.6.2`.

Rate limit: 60 requests an hour per address unauthenticated, 5000 with a
token. Nineteen repositories is one sync, so this only bites when re-syncing
with `--force`; `sync.py` sends `GITHUB_TOKEN` when the environment has one.

### Dates

The registry is one of only two places that dates anything, and the useful
field is not the obvious one:

| Field | What it means | Usable? |
|---|---|---|
| `_meta.last_updated` | when the registered document last changed | **Yes** — 11 of our 26 |
| `_meta.date_created` | when it was first registered | As history only |
| `_status.refresh_ts` | when SmartAPI last re-fetched the registration | No |
| `_status.uptime_ts` | when SmartAPI last probed the API | No |

The two `_status` stamps look like what you want and are not: across all 127
records they span two minutes of the same morning, because they record
SmartAPI's own polling rather than any change to a component. `_meta` has to be
asked for by name in the `fields=` list — `meta=1` is a different parameter,
and what it does is make `_id` appear.

Nothing in any source dates a *deployment*. See [`../FUTURE.md`](../FUTURE.md).

## Status endpoints

```bash
curl -s 'https://name-lookup.ci.transltr.io/status?full=true'
```

```json
{"status":"ok",
 "nameres_version":"v1.5.2",
 "babel_version":"2025sep1",
 "babel_version_url":"https://github.com/ncatstranslator/Babel/blob/master/releases/2025sep1.md",
 "biolink_model":{"tag":"master","url":"…","download_url":"…"},
 "recent_queries":{…}, "solr":{…}}
```

**There is no Translator-wide `/status` schema** — this shape is specific to
NameRes, and its own OpenAPI declares the response
`additionalProperties: true`. So `/status` is a per-component pointer, not
something a fetcher can parse generically.

What it uniquely offers is **data provenance**: `babel_version` and
`biolink_model.tag` are a different axis from software version, and nothing
else exposes them at runtime. `?full=true` adds JVM/OS/cache detail; the
default is cheap enough for a liveness probe.

## OpenTelemetry collectors

One Jaeger per environment, all three publicly readable:

| Environment | Collector | Services reporting |
|---|---|---|
| ci | <https://translator-otel.ci.transltr.io/> | 26 |
| test | <https://translator-otel.test.transltr.io/> | 33 |
| prod | <https://translator-otel.transltr.io/> | 15 |

```bash
curl -s https://translator-otel.ci.transltr.io/api/services
curl -s 'https://translator-otel.ci.transltr.io/api/traces?service=ARS&limit=6&lookback=168h'
```

41 distinct service names across the three, and **the three sets barely
overlap** — only `ARAX` and `infores:sri-name-resolver` report in all of them.
Prod is still running the pre-refactor architecture (`strider`, `molepro`,
`automat-*`, `COHD`), while ci and test run Shepherd and Retriever. So the
service list is also a rough picture of what each environment actually is.

### Service names are not component names

They are a sixth naming space, and a messier one than the rest:

- **A component reports under several names.** `shepherd-aragorn` emits as
  `aragorn`, `aragorn.lookup`, `aragorn.omnicorp`, `aragorn.pathfinder` and
  `aragorn.score`. So `identifiers.otel_services` is a list, not a scalar.
- **Case distinguishes different components.** `ARAX` is the standalone ARAX;
  lowercase `arax` is the Shepherd worker that calls it. The call graph shows
  `arax -> ARAX` directly, which is the only reason we can tell.
- **One name is an infores CURIE.** Name Lookup reports as both `Nameres` and
  `infores:sri-name-resolver`, so the naming spaces have already started to
  leak into each other.
- **Processing steps get their own service names.** `merge_message`,
  `score_paths`, `filter_results_top_n` and four others are child spans of
  `shepherd-server` and appear in the service list beside real components.
- **The same component is named differently per environment.**
  `answer-appraiser` is `ANSWER-APPRAISER` in prod; `strider` is
  `STRIDER-DEV` in test.

### Traces carry the call graph

This is what the other sources cannot give us. Span parent/child
relationships across services, from 15 traces in ci:

```text
ARS              -> shepherd-server, NodeNorm
shepherd-server  -> aragorn, arax, bte, and the seven operations
arax             -> ARAX
retriever        -> gandalf
ARAX             -> NodeNorm, retriever
```

Every one of those edges is an observation, not a declaration, which makes it
the natural check on the `connections:` edges we record by hand. It
is also how the ambiguous service names above were attributed at all: `gandalf`
is `dogpark-tier-0` because `retriever` calls it, and `arax` is the Shepherd
worker because it calls `ARAX`.

Two cautions before treating the graph as truth: async work shows up with
surprising parentage (`retriever` appears as a parent of `shepherd-server`),
and a trace only shows the edges that were exercised, so absence proves
nothing.

## The ITRB hostname convention

Deployments follow a fixed pattern, so knowing one environment's host says
where to look for the others:

| Environment | Hostname |
|---|---|
| ci | `<stem>.ci.transltr.io` |
| test | `<stem>.test.transltr.io` |
| prod | `<stem>.transltr.io` |

This matters because SmartAPI registration is manual and routinely
incomplete. `answer-appraiser` registers only production, and is deployed to
ci and test as well — where it runs two minor versions and a TRAPI version
ahead of the prod its registration describes.

`sync-components` derives the missing hosts and probes them. **Deriving is not
guessing, and the confirmation step is the difference**: a candidate is
believed only if the document it returns reports the same `infores` the
component records. Where a component records no infores there is nothing to
check against and the candidate is dropped. A host that answers 200 with
something else has its body deleted rather than cached — several Translator
hosts answer 200 with an HTML error page, and a later run would read one as
real.

`dev` is not derivable. Development deployments live at RENCI, at BioThings
and elsewhere, with no convention to follow.

### What the convention does not buy

Guessing a hostname from a component's **id** or its **ITRB app name**, rather
than deriving it from a host already known, finds nothing. Tried across the
ten components with no known deployment at all — `dingo-ingest`, the three
`dogpark-*`, `test-harness`, `translator-sdk`,
`translator-component-toolkit`, `smartapi`, `docmetadata-api`,
`ars-test-server` — it produced 42 candidates and 42 DNS failures. Those
components have no transltr.io deployment to find, and this is worth not
retrying: it is the obvious next idea.

## Helm charts

The public charts are in
[`helxplatform/translator-devops`](https://github.com/helxplatform/translator-devops/tree/develop/helm)
— 48 of them.

```bash
gh api "repos/helxplatform/translator-devops/contents/helm?ref=develop" \
  --jq '.[] | select(.type=="dir") | .name'
```

**Coverage is the first problem.** Only five of those charts belong to the 26
components recorded here — `answer-appraiser`, `jaeger`, `name-lookup`,
`shepherd`, `test-harness` — and they cover seven components, because all
three `shepherd-*` components share one chart. The rest are deployed from
charts that are private, elsewhere, or not Helm at all. Two components are
confirmed to have no chart at all rather than an unfound one:
`translator-component-toolkit` and `translator-sdk` carry
`helm_chart: null`.

**`Chart.yaml` is empty boilerplate.** Across the charts checked, `home`,
`sources`, `maintainers` and `keywords` are universally absent, and
`description` is usually the literal `helm create` default:

```yaml
apiVersion: v2
name: name-lookup
description: A Helm chart for Kubernetes   # the default string, unedited
type: application
version: 0.5.2
appVersion: 1.5.2_2025sep1                 # image tag + Babel release date
```

**`values.yaml` is where the real information is**, and some of it exists
nowhere else:

```yaml
webServer:
  image: {repository: ghcr.io/ncatstranslator/nameresolution, tag: v1.5.2}
dataUrl: "https://stars.renci.org/var/babel_outputs/2025sep1/nameres/snapshot.backup.tar.gz"
data: {babelVersion: 2025sep1, babelVersionURL: "https://github.com/…"}
solr:
  storage: 400Gi
  heap_mem: "-Xms30G -Xmx30G"
  resources: {requests: {memory: "32Gi", cpu: 4000m},
              limits:   {memory: "32Gi", cpu: 6000m}}
app:
  serverName: "infores:sri-name-resolver"   # the chart ↔ infores link
```

Resource requests, storage sizes and the data-download URL are genuinely
unique to the chart. `app.serverName` is the only place a chart states its
infores.

Two caveats:

- The values schema is **per-chart, not standardised**. `automat/values.yaml`
  puts `image:` at the top level and uses a different registry entirely.
- **Every environment-specific values file is git-crypt encrypted**
  (`ncats-{dev,test,prod}-values.yaml`, `*-values-populated.yaml` — they begin
  with the bytes `\0GITCRYPT`), and `ingress.host` is null in the plaintext
  `values.yaml`. So **hostnames cannot come from the charts**, and under the
  public-information-only rule nothing in those files may be read.

There is also a per-chart `ncats-images-meta.yaml`, which is plain, small and
machine-readable:

```yaml
nameLookup:      {image: ghcr.io/ncatstranslator/nameresolution, version: v1.5.2}
solr:            {image: solr, version: "9.1"}
renciPythonImage:{image: ghcr.io/translatorsri/renci-python-image, version: latest}
```

**Conclusion:** charts are not usable for *identity* today, but they are the
only source for resources and data downloads, and they are the one artifact
every deployed component must have. That makes them the natural place to
*require* a metadata block, if we ever want to require one — see the open
questions in [`component-metadata.md`](component-metadata.md).

## infores catalog

```bash
curl -sL https://raw.githubusercontent.com/biolink/information-resource-registry/main/infores_catalog.yaml
```

496 entries under one `information_resources:` key. LinkML-schema'd, with a
rule making `knowledge_level` and `agent_type` required once `status:
released`.

```yaml
  - status: released
    name: Name Resolver
    id: infores:sri-name-resolver
    xref:
      - https://github.com/NCATSTranslator/Translator-All/wiki/Name-Resolution-Service
    knowledge_level: knowledge_assertion
    agent_type: not_provided
```

The complete field set, with usage counts across the 496 entries: `name` 496,
`id` 496, `knowledge_level` 496, `agent_type` 496, `status` 496, `xref` 469,
`description` 267, `consumed_by` 247, `synonym` 178, `consumes` 68.

**There is no field for a repository, an endpoint, an image, a team or a
deployment.** What it does uniquely offer is `consumes`/`consumed_by`, which
makes the catalog a dataflow graph in its own right — worth comparing against
ours, though it describes knowledge flow between resources rather than API
calls between services.

Two reasons it cannot be our primary key: it mixes upstream data sources
(`infores:aact`) with Translator software (`infores:arax`) with no field
separating them, and several components here have no infores at all.

Its `xref` field is also the best index of the Translator-All wiki: 469 of the
496 entries point into it.

## Technical Documentation and the wiki

[TranslatorTechnicalDocumentation](https://github.com/NCATSTranslator/TranslatorTechnicalDocumentation)
is MkDocs + Material, rendered at
<https://ncatstranslator.github.io/TranslatorTechnicalDocumentation/>. Content
is a hand-maintained `nav:` tree with no per-page front matter and no
generation from any registry.

Two per-component conventions exist, both partial: `docs/architecture/ara/*.md`
and `docs/architecture/kp/*.md` (e.g.
`/architecture/ara/arax/`), and `docs/teams/*.md`. Several pages exist on disk
but are absent from `nav:`, and the whole `teams/` tree is unlinked.

The [Translator-All wiki](https://github.com/NCATSTranslator/Translator-All/wiki)
carries hundreds of one-page-per-resource entries and is where most infores
`xref`s point. Pages are free-text Markdown with a loose section convention —
the Name Resolution Service page keeps its actual metadata as prose bullets
under a **Links** heading. Nothing is machine-parseable, and page slugs are
yet another naming space (`Name-Resolution-Service`).
