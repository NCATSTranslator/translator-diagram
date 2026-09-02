# ARS

| Field | Value |
|---|---|
| Id | `ars` |
| Owner | NCATS |
| Type | ARS |
| Refactor status | Continues into Refactor |
| Stage | Step 6: ARS |
| Layer | ARS and UI |
| Part of |  |
| Hosted at | ITRB |

## Identifiers

| Namespace | Value |
|---|---|
| infores | `infores:ars` |
| SmartAPI | [4c12efd48ced755ac4b72b1922202ec2](https://smart-api.info/registry?q=4c12efd48ced755ac4b72b1922202ec2) |
| Helm chart |  |
| Translator-All wiki | [Autonomous-Relay-System-(ARS)](https://github.com/NCATSTranslator/Translator-All/wiki/Autonomous-Relay-System-(ARS)) |
| OpenTelemetry services | ARS |
| ITRB app | ARS |
| ITRB group | NCATS |

## Connections

- Gets results from: [ARAX](shepherd-arax.md), [ARAGORN](shepherd-aragorn.md), [BioThings Explorer (BTE)](shepherd-bte.md)
- Calls: [NodeNorm ES](nodenorm-es.md), [Jaeger (OTel)](jaeger.md), [Answer Appraiser](answer-appraiser.md), [Node Annotator](node-annotator.md), [SmartAPI](smartapi.md)
- Used by: [ARS Test Server](ars-test-server.md) (calls), [Test Harness](test-harness.md) (gets results from), [Translator Component Toolkit](translator-component-toolkit.md) (gets results from), [Translator UI](ui.md) (gets results from)
- Externals: none recorded

## Repositories

| Repository | Role | Visibility | Note |
|---|---|---|---|
| [https://github.com/NCATSTranslator/Relay](https://github.com/NCATSTranslator/Relay) | source | public |  |

## Documentation

| Link | Kind |
|---|---|
| [https://github.com/NCATSTranslator/Translator-All/wiki/Autonomous-Relay-System-(ARS)](https://github.com/NCATSTranslator/Translator-All/wiki/Autonomous-Relay-System-(ARS)) | wiki |

## Notes

Calls SmartAPI on boot to fetch registration data

<!-- live -->

## Deployments

| Environment | URL | Version | Source | TRAPI | Biolink | Data release | Reachable | Drift |
|---|---|---|---|---|---|---|---|---|
| dev | [https://ars-dev.transltr.io](https://ars-dev.transltr.io) | 1.0.0 | SmartAPI | 1.6.0 | 3.1.1 |  | no |  |
| ci | [https://ars.ci.transltr.io/](https://ars.ci.transltr.io/) | 1.0.0 | SmartAPI | 1.6.0 | 3.1.1 |  | no (HTTP 503) |  |
| test | [https://ars.test.transltr.io](https://ars.test.transltr.io) | 1.0.0 | SmartAPI | 1.6.0 | 3.1.1 |  | no (HTTP 404) |  |
| prod | [https://ars-prod.transltr.io](https://ars-prod.transltr.io) | 1.0.0 | SmartAPI | 1.6.0 | 3.1.1 |  | no (HTTP 404) |  |

- Last updated: 2026-05-24 (registry)
- SmartAPI uptime: pass
