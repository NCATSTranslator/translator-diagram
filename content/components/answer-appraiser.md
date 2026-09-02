# Answer Appraiser

| Field | Value |
|---|---|
| Id | `answer-appraiser` |
| Owner | DOGSLED |
| Type | Utility |
| Refactor status | Continues into Refactor |
| Stage | Step 6: ARS |
| Layer | ARS and UI |
| Part of |  |
| Hosted at | ITRB |

## Identifiers

| Namespace | Value |
|---|---|
| infores | `infores:sri-answer-appraiser` |
| SmartAPI | [6dcc5454fe4e0095090d8a956781c438](https://smart-api.info/registry?q=6dcc5454fe4e0095090d8a956781c438) |
| Helm chart | `answer-appraiser` |
| Translator-All wiki | [SRI-Answer-Appraiser](https://github.com/NCATSTranslator/Translator-All/wiki/SRI-Answer-Appraiser) |
| OpenTelemetry services | ANSWER-APPRAISER |
| ITRB app | answer-appraiser |
| ITRB group | SRI-Ranking |

## Connections

- Gets results from: none recorded
- Calls: none recorded
- Used by: [ARS](ars.md) (calls)
- Externals: none recorded

## Repositories

| Repository | Role | Visibility | Note |
|---|---|---|---|
| [https://github.com/TranslatorSRI/answer-appraiser](https://github.com/TranslatorSRI/answer-appraiser) | source | public |  |
| [https://github.com/helxplatform/translator-devops/tree/develop/helm/answer-appraiser](https://github.com/helxplatform/translator-devops/tree/develop/helm/answer-appraiser) | helm-chart | public |  |

## Documentation

| Link | Kind |
|---|---|
| [https://github.com/NCATSTranslator/Translator-All/wiki/SRI-Answer-Appraiser](https://github.com/NCATSTranslator/Translator-All/wiki/SRI-Answer-Appraiser) | wiki |

## Recorded environments

| Environment | URL | Location |
|---|---|---|
| ci | [https://answerappraiser.ci.transltr.io/](https://answerappraiser.ci.transltr.io/) | ITRB |
| test | [https://answerappraiser.test.transltr.io/](https://answerappraiser.test.transltr.io/) | ITRB |

<!-- live -->

## Deployments

| Environment | URL | Version | Source | TRAPI | Biolink | Data release | Reachable | Drift |
|---|---|---|---|---|---|---|---|---|
| dev |  | — |  |  |  |  |  |  |
| ci | [https://answerappraiser.ci.transltr.io/](https://answerappraiser.ci.transltr.io/) | 0.8.2 | OpenAPI | 1.6.0 | 4.2.0 |  | yes (HTTP 200) |  |
| test | [https://answerappraiser.test.transltr.io/](https://answerappraiser.test.transltr.io/) | 0.8.2 | OpenAPI | 1.6.0 | 4.2.0 |  | yes (HTTP 200) |  |
| prod | [https://answerappraiser.transltr.io](https://answerappraiser.transltr.io) | 0.6.1 | OpenAPI | 1.5.0 | 4.2.0 |  | yes (HTTP 200) | version, trapi |

## Releases

| Tag | Published | Running somewhere | Pre-release |
|---|---|---|---|
| [v0.8.2](https://github.com/TranslatorSRI/answer-appraiser/releases/tag/v0.8.2) | 2026-05-19 | yes | no |
| [v0.8.1](https://github.com/TranslatorSRI/answer-appraiser/releases/tag/v0.8.1) | 2026-05-19 | no | no |
| [v0.8.0](https://github.com/TranslatorSRI/answer-appraiser/releases/tag/v0.8.0) | 2025-07-17 | no | no |
| [v0.6.1](https://github.com/TranslatorSRI/answer-appraiser/releases/tag/v0.6.1) | 2024-10-04 | yes | no |

- Last updated: 2026-05-24 (registry)
- SmartAPI uptime: fail
- Helm chart version: 1.16.0
- Helm images: answer-appraiser:v0.8.2
