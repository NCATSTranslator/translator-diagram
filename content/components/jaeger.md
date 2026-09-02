# Jaeger (OTel)

| Field | Value |
|---|---|
| Id | `jaeger` |
| Owner | DOGSLED |
| Type |  |
| Refactor status | Continues into Refactor |
| Stage | Step 9: Engineering |
| Layer | Shared services |
| Part of |  |
| Hosted at | ITRB |

## Identifiers

| Namespace | Value |
|---|---|
| infores |  |
| SmartAPI |  |
| Helm chart | `jaeger` |
| Translator-All wiki |  |
| OpenTelemetry services |  |
| ITRB app | jaeger |
| ITRB group | SRI-Ranking |

## Connections

- Gets results from: none recorded
- Calls: none recorded
- Used by: [ARS](ars.md) (calls), [Tier 0: Gandalf (full KGX)](dogpark-tier-0.md) (calls), [Name Lookup (NameRes)](name-lookup.md) (calls), [Node Annotator](node-annotator.md) (calls), [NodeNorm ES](nodenorm-es.md) (calls), [Retriever (query API)](retriever.md) (calls), [ARAGORN](shepherd-aragorn.md) (calls), [ARAX](shepherd-arax.md) (calls), [BioThings Explorer (BTE)](shepherd-bte.md) (calls)
- Externals: Engineering (out)

## Repositories

| Repository | Role | Visibility | Note |
|---|---|---|---|
| [https://github.com/jaegertracing/jaeger](https://github.com/jaegertracing/jaeger) | related | public |  |
| [https://github.com/helxplatform/translator-devops/tree/develop/helm/jaeger](https://github.com/helxplatform/translator-devops/tree/develop/helm/jaeger) | helm-chart | public |  |

## Endpoints

| Kind | Path |
|---|---|
| services | `api/services` |
| docs | `search` |

## Recorded environments

| Environment | URL | Location |
|---|---|---|
| ci | [https://translator-otel.ci.transltr.io/](https://translator-otel.ci.transltr.io/) | ITRB |
| test | [https://translator-otel.test.transltr.io/](https://translator-otel.test.transltr.io/) | ITRB |
| prod | [https://translator-otel.transltr.io/](https://translator-otel.transltr.io/) | ITRB |

## Notes

Third-party software, not a Translator component: we deploy upstream Jaeger. Only the chart is ours.

<!-- live -->

## Deployments

| Environment | URL | Version | Source | TRAPI | Biolink | Data release | Reachable | Drift |
|---|---|---|---|---|---|---|---|---|
| dev |  | — |  |  |  |  |  |  |
| ci | [https://translator-otel.ci.transltr.io/](https://translator-otel.ci.transltr.io/) | 1.16.0 | Helm |  |  |  | no (HTTP 200) |  |
| test | [https://translator-otel.test.transltr.io/](https://translator-otel.test.transltr.io/) | 1.16.0 | Helm |  |  |  | no (HTTP 200) |  |
| prod | [https://translator-otel.transltr.io/](https://translator-otel.transltr.io/) | 1.16.0 | Helm |  |  |  | no (HTTP 200) |  |

- Last updated: unknown
- Helm chart version: 1.16.0
