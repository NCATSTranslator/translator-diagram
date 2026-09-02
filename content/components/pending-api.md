# BioThings Pending API

| Field | Value |
|---|---|
| Id | `pending-api` |
| Owner | DOGSURF |
| Type |  |
| Refactor status | Continues into Refactor |
| Stage | Step 7: User interface |
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
| OpenTelemetry services |  |
| ITRB app | BioThings PendingAPI (BTEP) |
| ITRB group | Exploring-Agent |

## Connections

- Gets results from: none recorded
- Calls: none recorded
- Used by: [Node Annotator](node-annotator.md) (calls)
- Externals: none recorded

## Repositories

| Repository | Role | Visibility | Note |
|---|---|---|---|
| [https://github.com/biothings/pending.api](https://github.com/biothings/pending.api) | source | public |  |

## Recorded environments

| Environment | URL | Location |
|---|---|---|
| ci | [https://biothings.ci.transltr.io/](https://biothings.ci.transltr.io/) | ITRB |
| test | [https://biothings.test.transltr.io/](https://biothings.test.transltr.io/) | ITRB |
| prod | [https://biothings.transltr.io/](https://biothings.transltr.io/) | ITRB |

## Notes

Hosts a number of APIs from the previous phase. Some have moved to CoCo's own ES server (nodenorm, annotator, nameres) and the BTE ones are expected to be removed, but this host is likely to stay live while any of its APIs are still in use, and could host tier 2 knowledge graph APIs later.

<!-- live -->

## Deployments

| Environment | URL | Version | Source | TRAPI | Biolink | Data release | Reachable | Drift |
|---|---|---|---|---|---|---|---|---|
| dev |  | — |  |  |  |  |  |  |
| ci | [https://biothings.ci.transltr.io/](https://biothings.ci.transltr.io/) | ? |  |  |  |  | no (HTTP 200) |  |
| test | [https://biothings.test.transltr.io/](https://biothings.test.transltr.io/) | ? |  |  |  |  | no (HTTP 200) |  |
| prod | [https://biothings.transltr.io/](https://biothings.transltr.io/) | ? |  |  |  |  | no (HTTP 200) |  |

- Last updated: unknown
