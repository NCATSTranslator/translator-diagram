# NodeNorm ES

| Field | Value |
|---|---|
| Id | `nodenorm-es` |
| Owner | CoCoWG |
| Type |  |
| Refactor status | New in Refactor |
| Stage | Step 1: Data ingest |
| Layer | Shared services |
| Part of |  |
| Hosted at | ITRB |

## Identifiers

| Namespace | Value |
|---|---|
| infores |  |
| SmartAPI |  |
| Helm chart |  |
| Translator-All wiki |  |
| OpenTelemetry services | NodeNorm |
| ITRB app | NodeNormAPI |
| ITRB group | Nodenorm |

## Connections

- Gets results from: none recorded
- Calls: [Jaeger (OTel)](jaeger.md)
- Used by: [ARS](ars.md) (calls), [DINGO Ingests](dingo-ingest.md) (calls), [Translator SDK](translator-sdk.md) (calls)
- Externals: none recorded

## Repositories

| Repository | Role | Visibility | Note |
|---|---|---|---|
| [https://github.com/biothings/NodeNormalizationAPI](https://github.com/biothings/NodeNormalizationAPI) | source | public |  |

## Endpoints

| Kind | Path |
|---|---|
| openapi | `webapp/openapi.json` |

## Recorded environments

| Environment | URL | Location |
|---|---|---|
| ci | [https://nodenorm-es.ci.transltr.io/](https://nodenorm-es.ci.transltr.io/) | ITRB |
| test | [https://nodenorm-es.test.transltr.io/](https://nodenorm-es.test.transltr.io/) | ITRB |

<!-- live -->

## Deployments

| Environment | URL | Version | Source | TRAPI | Biolink | Data release | Reachable | Drift |
|---|---|---|---|---|---|---|---|---|
| dev |  | — |  |  |  |  |  |  |
| ci | [https://nodenorm-es.ci.transltr.io/](https://nodenorm-es.ci.transltr.io/) | 1.0.0 | OpenAPI | 1.5.0 |  |  | yes (HTTP 200) |  |
| test | [https://nodenorm-es.test.transltr.io/](https://nodenorm-es.test.transltr.io/) | 1.0.0 | OpenAPI | 1.5.0 |  |  | yes (HTTP 200) |  |
| prod |  | — |  |  |  |  |  |  |

- Last updated: unknown
