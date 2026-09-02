# Tier 0: Gandalf (full KGX)

| Field | Value |
|---|---|
| Id | `dogpark-tier-0` |
| Owner | DOGSLED |
| Type | KP |
| Refactor status | New in Refactor |
| Stage | Step 3: DogPark |
| Layer | DogPark and Retriever |
| Part of | Dog Park |
| Hosted at | ITRB |

## Identifiers

| Namespace | Value |
|---|---|
| infores | `infores:dogpark-tier0` |
| SmartAPI |  |
| Helm chart |  |
| Translator-All wiki |  |
| OpenTelemetry services | gandalf |
| ITRB app | retriever-ci-pipeline |
| ITRB group | Retriever |

## Connections

- Gets results from: [KGX Storage](kgx-storage-pipeline.md), [DogPark Ranger](dogpark-ranger.md) (planned)
- Calls: [Jaeger (OTel)](jaeger.md)
- Used by: [Retriever (query API)](retriever.md) (gets results from)
- Externals: none recorded

## Repositories

| Repository | Role | Visibility | Note |
|---|---|---|---|
| [https://github.com/ranking-agent/gandalf](https://github.com/ranking-agent/gandalf) | source | public |  |

## Endpoints

| Kind | Path |
|---|---|
| openapi | `openapi.json` |
| docs | `docs` |
| status | none (checked) |

## Recorded environments

| Environment | URL | Location |
|---|---|---|
| dev | [https://gandalf.renci.org/](https://gandalf.renci.org/) | RENCI |

<!-- live -->

## Deployments

| Environment | URL | Version | Source | TRAPI | Biolink | Data release | Reachable | Drift |
|---|---|---|---|---|---|---|---|---|
| dev | [https://gandalf.renci.org/](https://gandalf.renci.org/) | 1.0.0 | OpenAPI | 1.5.0 | 4.2.1 |  | yes (HTTP 200) |  |
| ci |  | — |  |  |  |  |  |  |
| test |  | — |  |  |  |  |  |  |
| prod |  | — |  |  |  |  |  |  |

## Releases

| Tag | Published | Running somewhere | Pre-release |
|---|---|---|---|
| [v1.0.0](https://github.com/ranking-agent/gandalf/releases/tag/v1.0.0) | 2026-07-21 | yes | no |
| [v0.4.2](https://github.com/ranking-agent/gandalf/releases/tag/v0.4.2) | 2026-07-14 | no | no |
| [v0.4.1](https://github.com/ranking-agent/gandalf/releases/tag/v0.4.1) | 2026-07-09 | no | no |

- Last updated: 2026-07-21 (release, v1.0.0)
