# Future work

Things worth doing that are not done, with enough of the reasoning that the
next person does not have to rediscover why. Open issues live on GitHub; this
file is for the ideas that came out of building something and would otherwise
be lost in a pull request description.

## Date a deployment, not just a release

Tracked in [#23](https://github.com/NCATSTranslator/translator-diagram/issues/23).

The dashboard's `Last updated` column answers "when did this component last
change" from a GitHub release or a SmartAPI registration. Neither answers the
question people actually ask, which is **when was this environment last
deployed**. Nothing we currently fetch knows: the OpenAPI documents carry no
date, the Helm chart files carry no date, and SmartAPI's `_status.refresh_ts`
is its own uptime probe.

**The Helm chart's last commit is the closest available proxy, and it is
half built.** ITRB deploys from
[`helxplatform/translator-devops`](https://github.com/helxplatform/translator-devops),
so the last commit touching `helm/<chart>/` dates the intent to deploy.
`sync-components` already fetches it, one call per recorded chart, and the
Component view's Helm section shows it as "Chart last changed", labelled
*intent to deploy, not a deployment*.

What is not built is putting it on the table, where a reader scanning
environments would see it. Two things to be careful about there:

- It dates the *intent*, not the deployment. A chart change that was never
  rolled out, or a rollout of an unchanged chart, both make it wrong. It
  belongs in its own column or its own badge — `deployed`, say — and never
  silently merged into `Last updated`.
- It would give `jaeger` a date it currently lacks, but only two of the eight
  charted components (`jaeger` and `dogpark-tier-0`) are among the thirteen
  with no date at all, so it is worth doing for what it *means* rather than for
  the coverage.

## Fill in the components with no date at all

Tracked in [#24](https://github.com/NCATSTranslator/translator-diagram/issues/24).

Thirteen of twenty-six components show no `Last updated`: they publish no
GitHub releases and appear in no SmartAPI record. `GET /repos/{owner}/{name}`
returns `pushed_at`, which would date every one of them that has a repository,
at the cost of a second GitHub call per repository — about 19 more per sync,
on top of the 46 it already spends.

Deliberately not done for now: a push to any branch moves `pushed_at`, so it
answers "has anyone touched this repository" rather than "has this component
changed", and it would outrank the release date on nearly every row and make
the `release` badge vanish. If it is added, it should rank *below* a release
rather than by recency.

## Sample OpenTelemetry traces per environment

The dashboard already counts OTel services per environment from the Jaeger
query API. Showing individual trace samples — latency, error rate, last seen —
would need a separate sampled job with its own cache and TTL, because the
query endpoint is not cheap enough to hit on every `sync-components` run and
the answer is not stable enough to treat as a version fact. If built, it belongs
in its own tile or Component view section, labelled as sampled telemetry
rather than deployment truth.

## Rendered Helm manifests per environment

`helm template` against each chart and environment would show the intended
Kubernetes objects — image, resources, env vars — beyond the `appVersion` the
page already reads from the chart file. The cost is one Helm invocation per
(chart, environment) pair, a Helm binary in CI (which `pages.yml` deliberately
does not install today), and a trust boundary: rendered YAML is intent, not
what is running. Chart metadata stays in the published build; only image tags
are withheld today.

## Watch the GitHub budget

The two dating ideas at the top spend from the same allowance: **60 requests
an hour** for an unauthenticated address, 5000 with a `GITHUB_TOKEN` in the
environment (see `_headers` in `fetch.py`). One full sync currently spends
about 46, broken down in the comment above `_source_repos` in `sync.py`.
Release lists are already keyed by repository rather than by component, so the
three shepherds cost one call between them; anything added here should be keyed
the same way.

## Retire the sheet as an input

The component files replace the Google Sheet in four steps, and the first has
shipped: `sync-components` reads every file, follows its pointers, and caches
the answers under `data/sync/` for `build-dashboard`. What is left, in order:

1. `loading.py` reads YAML instead of CSV, and `--google-sheet` retires —
   [#19](https://github.com/NCATSTranslator/translator-diagram/issues/19). Until then `generate-diagram` draws from the sheet and the
   dashboard from the files, so the two can disagree.
2. The 70 sheet rows with no file yet get one — [#20](https://github.com/NCATSTranslator/translator-diagram/issues/20). They are
   historical, but the diagram draws them as ghost nodes when an active
   component still points at one, so #19 cannot drop them.
3. A read-only sheet is generated *from* the files, for the people who work
   in spreadsheets — [#39](https://github.com/NCATSTranslator/translator-diagram/issues/39). That keeps a sheet as an output, which is
   a different thing from keeping it as an input.
4. Reconciling against the list ITRB sends — [#6](https://github.com/NCATSTranslator/translator-diagram/issues/6) — joins on
   `itrb.app` and `itrb.group`, which 25 of the 26 files already record.

## Settle the component identifier before #20

Tracked as a comment on [#20](https://github.com/NCATSTranslator/translator-diagram/issues/20).

The kebab-case id is decided *for now*
([`component-metadata.md`](docs/component-metadata.md#decisions) has the
argument and the two alternatives: the GitHub repository and the URL slug).
Switching later is cheap, because `identifiers` already records both
alternatives, so a switch is a rename and a reference rewrite. What is not
cheap is switching *twice*. So the question wants an answer before #20 adds 70
more files under the current scheme, not after.

## Check the recorded data flow against what is observed

Tracked in [#61](https://github.com/NCATSTranslator/translator-diagram/issues/61).

`connections:` is written by hand, and two upstream sources observe the same
graph independently:

- **OpenTelemetry traces.** Span parent/child links across services show which
  service actually called which; the survey's sample is in
  [`metadata-sources.md`](docs/metadata-sources.md#traces-carry-the-call-graph).
  `sync-components` reads only each collector's service *list* today, not its
  traces.
- **The infores catalog's `consumes` / `consumed_by`.** These are already in
  the payload as `catalog_edges` and drawn on the map beside the recorded
  edges, but nothing compares the two.

The useful output is the disagreements: an observed edge nobody recorded,
and a recorded edge nothing observes. Each has its own catch. Service names
are their own naming space, so the join goes through
`identifiers.otel_services`. Async work produces odd parentage (`retriever`
shows up as a parent of `shepherd-server`). And a trace only shows edges that
were exercised, so a missing edge proves nothing. The catalog describes
knowledge flowing between resources rather than API calls, so it disagrees
with `connections:` for reasons that are not errors. Either check belongs in
the sync summary as a report for a curator, not as a correction applied to
the files.

## Require a metadata block in the Helm chart

Tracked in [#62](https://github.com/NCATSTranslator/translator-diagram/issues/62).

Today `Chart.yaml` is `helm create` boilerplate — see
[`metadata-sources.md`](docs/metadata-sources.md#helm-charts) — so a chart
says nothing about which component it deploys. If Translator ever wants to
*require* every component to declare basic metadata (infores, source
repository, owning team), the chart is a plausible place to do it. It is the
one artifact every deployed component must have, and its `values.yaml` already
carries resource requests, storage sizes and data-download URLs that exist
nowhere else.

The argument against is coverage. Only eight of the 26 components here have a
chart in the public `translator-devops` repository (six charts, since the
three shepherds share one), while SmartAPI and GitHub already cover most of
them. This is a proposal to make to ITRB and the teams, not something this
repository can do alone.

## Attribute the Helm charts

[#41](https://github.com/NCATSTranslator/translator-diagram/issues/41) and [#52](https://github.com/NCATSTranslator/translator-diagram/issues/52). Of the 50 charts in `translator-devops`, 43
match no component, and the one match the rules find on their own (`aragorn`
→ `shepherd-aragorn`) is a name collision rather than a finding. See
[`metadata-sources.md`](docs/metadata-sources.md#matching-a-chart-to-a-component).
And #52 asks which of the identifiable ones are Translator components at all.

## A platform-wide Gaps view

The Component view shows one component's gaps: the catalog fields nobody has
recorded, the environments no host answers for, the OpenTelemetry names
nothing reports under. The same list across every component is the
maintenance to-do for the whole platform, and the payload already carries
what it needs (`recorded`, `component_schema`, `otel_presence`,
`derived_rejected`, the cells' `reason`s).

The shape, sketched in #51: a `findings.py` below `rows` that computes a
`findings` list per row (unrecorded schema fields, cells with a `reason`,
OpenTelemetry services not reporting, derived hosts rejected, an unclaimed
SmartAPI candidate, an unclaimed Helm chart), each with a kind, a sentence
and the section of the Component view it points at. A `?view=gaps` lists
them grouped by kind, each linking to `?view=component&sel=<id>#cv-<section>`,
and the Component view gains a Findings section near the top showing the
same list for one component, which is the "what needs updating" a developer
opens the page for.

## A mini-map on the Component view

The Connections section lists the one-hop neighbourhood; a small map of it,
this node and its neighbours drawn by the same layout engine, would show the
shape as well as the names. `map.js` is a singleton (one host, one scene, one
camera at module level), so a second instance means turning about 1300 lines
into a factory first. Until then **Show on map** is the answer: it switches
to the full map, which rings the component and flies to it.

## Report a problem from the Component view

The view has Copy link and Edit catalog file. A prefilled new-issue link
(`/issues/new?title=<id>: …&body=<link>`) was left out of #51 so the page
would not open with three ways to say the same thing before anyone had used
one. Worth adding once it is clear which of the two the readers reach for.

## Path-shaped component URLs

`?view=component&sel=<id>` is a query string on the one self-contained page.
If a path-shaped address (`/component/<id>`) turns out to matter, for a chat
client's link preview say, the cheap version is one tiny
`component/<id>.html` per component in the Pages artifact, each a
`<meta http-equiv="refresh">` to `../?view=component&sel=<id>`, written by
`write_dashboard` from the rows the policy kept. No second copy of the
payload, and a withheld component gets no stub. Not done because nothing has
asked for it yet.

## Upstream gaps worth reporting

The survey in [`metadata-sources.md`](docs/metadata-sources.md) records how
each source behaves, and `sync-components` copes with all of what follows.
Each item is still a place where Translator's own metadata disagrees with
itself, and only the owner upstream can fix it:

- **SmartAPI registrations are incomplete or inconsistent** —
  [#63](https://github.com/NCATSTranslator/translator-diagram/issues/63). `answer-appraiser` registers only
  production but runs in ci and test too. `node-annotator` declares `http://`
  and omits `x-maturity`. `name-lookup` and `sri-node-normalizer` list every
  server twice. `arax` puts its TRAPI version in the base URL.
  ([survey](docs/metadata-sources.md#smartapi-registry))
- **What is running is often not a release** —
  [#64](https://github.com/NCATSTranslator/translator-diagram/issues/64). Twelve of 19 source repositories
  publish no releases. RTX's tags mark deployments rather than versions.
  PloverDB runs `2.10.2`, which is tagged nowhere.
  ([survey](docs/metadata-sources.md#releases))
- **There is no Translator-wide `/status` schema** —
  [#65](https://github.com/NCATSTranslator/translator-diagram/issues/65). Each component's `/status` is shaped its
  own way, so the data-provenance versions it exposes (`babel_version`, the
  Biolink tag) cannot be read generically.
  ([survey](docs/metadata-sources.md#status-endpoints))
- **OpenTelemetry service names drift** — [#66](https://github.com/NCATSTranslator/translator-diagram/issues/66). The
  same component reports under a different name per environment
  (`ANSWER-APPRAISER`, `STRIDER-DEV`), processing steps report as services,
  and case alone separates `ARAX` from `arax`.
  ([survey](docs/metadata-sources.md#service-names-are-not-component-names))
- **The Jaeger query API may be open to the public** — [#44](https://github.com/NCATSTranslator/translator-diagram/issues/44).
