# Test Harness

| Field | Value |
|---|---|
| Id | `test-harness` |
| Owner | DOGSLED |
| Type |  |
| Refactor status | Continues into Refactor |
| Stage | Step 9: Engineering |
| Layer | Shared services |
| Part of |  |
| Hosted at | RENCI |

## Identifiers

| Namespace | Value |
|---|---|
| infores |  |
| SmartAPI |  |
| Helm chart | `test-harness` |
| Translator-All wiki |  |
| OpenTelemetry services |  |
| ITRB app |  |
| ITRB group |  |

## Connections

- Gets results from: [ARS](ars.md)
- Calls: [SmartAPI](smartapi.md)
- Used by: none recorded
- Externals: Engineering (out)

## Repositories

| Repository | Role | Visibility | Note |
|---|---|---|---|
| [https://github.com/TranslatorSRI/TestHarness](https://github.com/TranslatorSRI/TestHarness) | source | public |  |
| [https://github.com/helxplatform/translator-devops/tree/develop/helm/test-harness](https://github.com/helxplatform/translator-devops/tree/develop/helm/test-harness) | helm-chart | public |  |

## Notes

The Test Harness uses Smart API to grab the urls for the various components it tests. It isn't really hosted, but is a spawned python script that runs on the RENCI server.

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
| dev |  | — |  |  |  |  |  |  |
| ci |  | — |  |  |  |  |  |  |
| test |  | — |  |  |  |  |  |  |
| prod |  | — |  |  |  |  |  |  |

## Releases

| Tag | Published | Running somewhere | Pre-release |
|---|---|---|---|
| [v0.6.7](https://github.com/TranslatorSRI/TestHarness/releases/tag/v0.6.7) | 2026-08-26 | no | no |
| [v0.6.6](https://github.com/TranslatorSRI/TestHarness/releases/tag/v0.6.6) | 2026-07-13 | no | no |
| [v0.6.5](https://github.com/TranslatorSRI/TestHarness/releases/tag/v0.6.5) | 2026-06-01 | no | no |

- Last updated: 2026-08-26 (release, v0.6.7)
- Helm chart version: 1.16.0
