# Translator UI

| Field | Value |
|---|---|
| Id | `ui` |
| Owner | UI |
| Type |  |
| Refactor status | Continues into Refactor |
| Stage | Step 7: User interface |
| Layer | ARS and UI |
| Part of |  |
| Hosted at | ITRB |

## Identifiers

| Namespace | Value |
|---|---|
| infores |  |
| SmartAPI |  |
| Helm chart |  |
| Translator-All wiki |  |
| OpenTelemetry services |  |
| ITRB app | translator-ui-ci-pipeline |
| ITRB group | UI |

## Connections

- Gets results from: [ARS](ars.md)
- Calls: [docmetadata-api](docmetadata-api.md), [Name Lookup (NameRes)](name-lookup.md)
- Used by: none recorded
- Externals: User (out)

## Repositories

| Repository | Role | Visibility | Note |
|---|---|---|---|
| [https://github.com/NCATSTranslator/ui-fe](https://github.com/NCATSTranslator/ui-fe) | source | public |  |
| [https://github.com/NCATSTranslator/ui-be](https://github.com/NCATSTranslator/ui-be) | source | public |  |

## Endpoints

| Kind | Path |
|---|---|
| openapi | none (checked) |

## Recorded environments

| Environment | URL | Location |
|---|---|---|
| dev | [https://transltr-bma-ui-dev.ncats.io/](https://transltr-bma-ui-dev.ncats.io/) |  |
| ci | [https://ui.ci.transltr.io/](https://ui.ci.transltr.io/) | ITRB |
| test | [https://ui.test.transltr.io/](https://ui.test.transltr.io/) | ITRB |
| prod | [https://ui.transltr.io/](https://ui.transltr.io/) | ITRB |

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
| dev | [https://transltr-bma-ui-dev.ncats.io/](https://transltr-bma-ui-dev.ncats.io/) | ? |  |  |  |  | no |  |
| ci | [https://ui.ci.transltr.io/](https://ui.ci.transltr.io/) | ? |  |  |  |  | no |  |
| test | [https://ui.test.transltr.io/](https://ui.test.transltr.io/) | ? |  |  |  |  | no |  |
| prod | [https://ui.transltr.io/](https://ui.transltr.io/) | ? |  |  |  |  | no |  |

- Last updated: unknown
