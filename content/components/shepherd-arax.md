# ARAX

| Field | Value |
|---|---|
| Id | `shepherd-arax` |
| Owner | CATRAX |
| Type | ARA |
| Refactor status | New in Refactor |
| Stage | Step 5: Shepherd |
| Layer | Shepherd |
| Part of | Shepherd |
| Hosted at | ITRB |

## Identifiers

| Namespace | Value |
|---|---|
| infores | `infores:shepherd-arax` |
| SmartAPI | [355d9ca56f4a528ce43c56ae19c97676](https://smart-api.info/registry?q=355d9ca56f4a528ce43c56ae19c97676) |
| Helm chart | `shepherd` |
| Translator-All wiki |  |
| OpenTelemetry services | arax, arax.pathfinder |
| ITRB app | shepherd-ci-pipeline |
| ITRB group | shepherd |

## Connections

- Gets results from: [Retriever (query API)](retriever.md)
- Calls: [Jaeger (OTel)](jaeger.md)
- Used by: [ARS](ars.md) (gets results from), [Translator Component Toolkit](translator-component-toolkit.md) (gets results from)
- Externals: none recorded

## Repositories

| Repository | Role | Visibility | Note |
|---|---|---|---|
| [https://github.com/BioPack-team/shepherd](https://github.com/BioPack-team/shepherd) | source | public |  |
| [https://github.com/helxplatform/translator-devops/tree/develop/helm/shepherd](https://github.com/helxplatform/translator-devops/tree/develop/helm/shepherd) | helm-chart | public |  |

## Notes

Contains ARAX, ARAGORN and BTE

<!-- live -->

## Deployments

| Environment | URL | Version | Source | TRAPI | Biolink | Data release | Reachable | Drift |
|---|---|---|---|---|---|---|---|---|
| dev | [https://shepherd.renci.org/arax](https://shepherd.renci.org/arax) | 1.1.2 | OpenAPI | 1.5.0 | 4.1.6 |  | yes (HTTP 200) | version |
| ci | [https://shepherd.ci.transltr.io/arax](https://shepherd.ci.transltr.io/arax) | 1.1.4 | OpenAPI | 1.5.0 | 4.1.6 |  | yes (HTTP 200) | version |
| test | [https://shepherd.test.transltr.io/arax](https://shepherd.test.transltr.io/arax) | 1.1.0 | OpenAPI | 1.5.0 | 4.1.6 |  | yes (HTTP 200) | version |
| prod |  | — |  |  |  |  |  |  |

## Releases

| Tag | Published | Running somewhere | Pre-release |
|---|---|---|---|
| [v1.1.4](https://github.com/BioPack-team/shepherd/releases/tag/v1.1.4) | 2026-09-02 | yes | no |
| [v1.1.3](https://github.com/BioPack-team/shepherd/releases/tag/v1.1.3) | 2026-09-01 | no | no |
| [v1.1.2](https://github.com/BioPack-team/shepherd/releases/tag/v1.1.2) | 2026-09-01 | yes | no |
| [v1.1.0](https://github.com/BioPack-team/shepherd/releases/tag/v1.1.0) | 2026-08-12 | yes | no |

- Last updated: 2026-09-02 (registry)
- SmartAPI uptime: unknown
- Helm chart version: 1.0
- Helm images: aragorn:v1.1.4, aragorn_lookup:v1.1.4, aragorn_pathfinder:v1.1.4, aragorn_omnicorp:v1.1.4, aragorn_score:v1.1.4, arax:v1.1.4, arax_pathfinder:v1.1.4, arax_rank:v1.1.4, bte:v1.1.4, bte_lookup:v1.1.4, filter_analyses_top_n:v1.1.4, filter_kgraph_orphans:v1.1.4, filter_results_top_n:v1.1.4, finish_query:v1.1.4, merge_message:v1.1.4, score_paths:v1.1.4, monitor:v1.1.4, shepherd_server:v1.1.4, sipr:v1.1.4, sort_results_score:v1.1.4, postgres:17-bookworm, redis-stack-server:7.2.0-v11
