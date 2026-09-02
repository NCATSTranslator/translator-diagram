# RTX/ARAX

| Field | Value |
|---|---|
| Id | `arax` |
| Owner | CATRAX |
| Type | ARA |
| Refactor status | Continues into Refactor |
| Stage | Step 5: Shepherd |
| Layer |  |
| Part of |  |
| Hosted at | ITRB |

## Identifiers

| Namespace | Value |
|---|---|
| infores | `infores:arax` |
| SmartAPI | [03e63fbd5ed251bce08cb5801b6b169b](https://smart-api.info/registry?q=03e63fbd5ed251bce08cb5801b6b169b) |
| Helm chart |  |
| Translator-All wiki | [Expander-Agent](https://github.com/NCATSTranslator/Translator-All/wiki/Expander-Agent) |
| OpenTelemetry services | ARAX |
| ITRB app | arax |
| ITRB group | TeamExpander |

## Connections

- Gets results from: none recorded
- Calls: none recorded
- Used by: none recorded
- Externals: none recorded

## Repositories

| Repository | Role | Visibility | Note |
|---|---|---|---|
| [https://github.com/RTXteam/RTX](https://github.com/RTXteam/RTX) | source | public |  |

## Documentation

| Link | Kind |
|---|---|
| [https://github.com/NCATSTranslator/Translator-All/wiki/Expander-Agent](https://github.com/NCATSTranslator/Translator-All/wiki/Expander-Agent) | wiki |
| [https://ncatstranslator.github.io/TranslatorTechnicalDocumentation/architecture/ara/arax/](https://ncatstranslator.github.io/TranslatorTechnicalDocumentation/architecture/ara/arax/) | technical-documentation |

## Notes

SmartAPI registers the TRAPI base URL with the API version in the path (.../api/arax/v1.4), so the version moves when TRAPI does.

## Private

Recorded in this repository only. Nothing in this section reaches the published page.

- Contacts:
  - PRIVATE
- Internal hosts:
  - PRIVATE
- Notes: PRIVATE

<!-- live -->

## Deployments

| Environment | URL | Version | Source | TRAPI | Biolink | Data release | Reachable | Drift |
|---|---|---|---|---|---|---|---|---|
| dev | [https://arax.ncats.io/beta/api/arax/v1.4](https://arax.ncats.io/beta/api/arax/v1.4) | 1.6.2 | OpenAPI | 1.6.0 | 4.2.5 |  | yes (HTTP 200) |  |
| ci | [https://arax.ci.transltr.io/api/arax/v1.4](https://arax.ci.transltr.io/api/arax/v1.4) | 1.6.2 | OpenAPI | 1.6.0 | 4.2.5 |  | yes (HTTP 200) |  |
| test | [https://arax.test.transltr.io/api/arax/v1.4](https://arax.test.transltr.io/api/arax/v1.4) | 1.6.2 | OpenAPI | 1.6.0 | 4.2.5 |  | yes (HTTP 200) |  |
| prod | [https://arax.transltr.io/api/arax/v1.4](https://arax.transltr.io/api/arax/v1.4) | 1.5.4 | OpenAPI | 1.5.0 | 4.2.1 |  | yes (HTTP 200) | version, trapi, biolink |

## Releases

| Tag | Published | Running somewhere | Pre-release |
|---|---|---|---|
| [itrb-test-premerge-2026-08-04](https://github.com/RTXteam/RTX/releases/tag/itrb-test-premerge-2026-08-04) | 2026-08-05 | no | yes |
| [tier0-20260408](https://github.com/RTXteam/RTX/releases/tag/tier0-20260408) | 2026-07-01 | no | yes |
| [last-kg2-arax](https://github.com/RTXteam/RTX/releases/tag/last-kg2-arax) | 2026-05-11 | no | yes |

- Last updated: 2026-08-05 (release, itrb-test-premerge-2026-08-04)
- SmartAPI uptime: fail
