# Retriever (query API)

| Field | Value |
|---|---|
| Id | `retriever` |
| Owner | DOGSURF |
| Type | KP |
| Refactor status | New in Refactor |
| Stage | Step 4: Retriever |
| Layer | DogPark and Retriever |
| Part of |  |
| Hosted at | ITRB |

## Identifiers

| Namespace | Value |
|---|---|
| infores | `infores:retriever` |
| SmartAPI | [7a12feb2fbd8fe4af532a77ee19b7800](https://smart-api.info/registry?q=7a12feb2fbd8fe4af532a77ee19b7800) |
| Helm chart |  |
| Translator-All wiki |  |
| OpenTelemetry services | retriever |
| ITRB app | retriever-ci-pipeline |
| ITRB group | Retriever |

## Connections

- Gets results from: [Tier 0: Gandalf (full KGX)](dogpark-tier-0.md), [Tier 1: ElasticSearch (KGX split out by data source)](dogpark-tier-1.md)
- Calls: [Jaeger (OTel)](jaeger.md)
- Used by: [ARAGORN](shepherd-aragorn.md) (gets results from), [ARAX](shepherd-arax.md) (gets results from), [BioThings Explorer (BTE)](shepherd-bte.md) (gets results from), [Translator Component Toolkit](translator-component-toolkit.md) (gets results from)
- Externals: none recorded

## Repositories

| Repository | Role | Visibility | Note |
|---|---|---|---|
| [https://github.com/BioPack-team/retriever](https://github.com/BioPack-team/retriever) | source | public |  |

## Endpoints

| Kind | Path |
|---|---|
| openapi | `openapi.json` |

## Notes

API server to route calls to the different tiers

<!-- live -->

## Deployments

| Environment | URL | Version | Source | TRAPI | Biolink | Data release | Reachable | Drift |
|---|---|---|---|---|---|---|---|---|
| dev | [https://dev.retriever.biothings.io/](https://dev.retriever.biothings.io/) | 0.0.1 | OpenAPI | 1.6.0 |  |  | yes (HTTP 200) |  |
| ci | [https://retriever.ci.transltr.io/](https://retriever.ci.transltr.io/) | 0.0.1 | OpenAPI | 1.6.0 |  |  | yes (HTTP 200) |  |
| test | [https://retriever.test.transltr.io/](https://retriever.test.transltr.io/) | 0.0.1 | OpenAPI | 1.6.0 |  |  | yes (HTTP 200) |  |
| prod |  | — |  |  |  |  |  |  |

- Last updated: 2026-09-01 (registry)
- SmartAPI uptime: pass
