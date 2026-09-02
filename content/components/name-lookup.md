# Name Lookup (NameRes)

| Field | Value |
|---|---|
| Id | `name-lookup` |
| Owner | DOGSLED |
| Type | Utility |
| Refactor status | Continues into Refactor |
| Stage | Step 7: User interface |
| Layer | Shared services |
| Part of |  |
| Hosted at | ITRB |

## Identifiers

| Namespace | Value |
|---|---|
| infores | `infores:sri-name-resolver` |
| SmartAPI | [9995fed757acd034ef099dbb483c4c82](https://smart-api.info/registry?q=9995fed757acd034ef099dbb483c4c82) |
| Helm chart | `name-lookup` |
| Translator-All wiki | [Name-Resolution-Service](https://github.com/NCATSTranslator/Translator-All/wiki/Name-Resolution-Service) |
| OpenTelemetry services | Nameres, infores:sri-name-resolver |
| ITRB app | name-lookup |
| ITRB group | SRI-Ranking |

## Connections

- Gets results from: none recorded
- Calls: [Jaeger (OTel)](jaeger.md)
- Used by: [Translator SDK](translator-sdk.md) (calls), [Translator UI](ui.md) (calls)
- Externals: none recorded

## Repositories

| Repository | Role | Visibility | Note |
|---|---|---|---|
| [https://github.com/NCATSTranslator/NameResolution](https://github.com/NCATSTranslator/NameResolution) | source | public |  |
| [https://github.com/helxplatform/translator-devops/tree/develop/helm/name-lookup](https://github.com/helxplatform/translator-devops/tree/develop/helm/name-lookup) | helm-chart | public |  |

## Documentation

| Link | Kind |
|---|---|
| [https://github.com/NCATSTranslator/Translator-All/wiki/Name-Resolution-Service](https://github.com/NCATSTranslator/Translator-All/wiki/Name-Resolution-Service) | wiki |

## Endpoints

| Kind | Path |
|---|---|
| openapi | `openapi.json` |
| status | `status?full=true` |
| docs | `docs` |

<!-- live -->

## Deployments

| Environment | URL | Version | Source | TRAPI | Biolink | Data release | Reachable | Drift |
|---|---|---|---|---|---|---|---|---|
| dev | [https://name-resolution-sri.renci.org/](https://name-resolution-sri.renci.org/) | 1.5.2 | OpenAPI |  |  | babel 2025sep1 · biolink master | yes (HTTP 200) |  |
| ci | [https://name-lookup.ci.transltr.io/](https://name-lookup.ci.transltr.io/) | 1.5.2 | OpenAPI |  |  | babel 2025sep1 · biolink master | yes (HTTP 200) |  |
| test | [https://name-lookup.test.transltr.io/](https://name-lookup.test.transltr.io/) | 1.5.2 | OpenAPI |  |  | babel 2025sep1 · biolink master | yes (HTTP 200) |  |
| prod | [https://name-lookup.transltr.io/](https://name-lookup.transltr.io/) | 1.4.5 | OpenAPI |  |  |  | yes (HTTP 200) | version |

## Releases

| Tag | Published | Running somewhere | Pre-release |
|---|---|---|---|
| [v1.7.1](https://github.com/NCATSTranslator/NameResolution/releases/tag/v1.7.1) | 2026-09-01 | no | yes |
| [v1.7.0](https://github.com/NCATSTranslator/NameResolution/releases/tag/v1.7.0) | 2026-07-23 | no | no |
| [v1.5.2](https://github.com/NCATSTranslator/NameResolution/releases/tag/v1.5.2) | 2026-04-08 | yes | no |
| [v1.4.5](https://github.com/NCATSTranslator/NameResolution/releases/tag/v1.4.5) | 2024-10-21 | yes | no |

- Last updated: 2026-09-01 (release, v1.7.1)
- SmartAPI uptime: pass
- Helm chart version: 1.5.2_2025sep1
- Helm images: nameresolution:v1.5.2, solr:9.1, renci-python-image:latest
