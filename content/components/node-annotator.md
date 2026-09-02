# Node Annotator

| Field | Value |
|---|---|
| Id | `node-annotator` |
| Owner | CoCoWG |
| Type | Utility |
| Refactor status | Continues into Refactor |
| Stage | Step 7: User interface |
| Layer | Shared services |
| Part of |  |
| Hosted at | ITRB |

## Identifiers

| Namespace | Value |
|---|---|
| infores |  |
| SmartAPI | [5a4c41bf2076b469a0e9cfcf2f2b8f29](https://smart-api.info/registry?q=5a4c41bf2076b469a0e9cfcf2f2b8f29) |
| Helm chart |  |
| Translator-All wiki |  |
| OpenTelemetry services | BioThingsAnnotator |
| ITRB app | Biothings annotator |
| ITRB group | Exploring-Agent |

## Connections

- Gets results from: none recorded
- Calls: [Jaeger (OTel)](jaeger.md) (planned), [BioThings Pending API](pending-api.md)
- Used by: [ARS](ars.md) (calls), [Translator SDK](translator-sdk.md) (calls)
- Externals: none recorded

## Repositories

| Repository | Role | Visibility | Note |
|---|---|---|---|
| [https://github.com/biothings/biothings_annotator](https://github.com/biothings/biothings_annotator) | source | public |  |

## Endpoints

| Kind | Path |
|---|---|
| openapi | `webapp/openapi.json` |

## Recorded environments

| Environment | URL | Location |
|---|---|---|
| ci | [https://annotator.ci.transltr.io/](https://annotator.ci.transltr.io/) | ITRB |
| test | [https://annotator.test.transltr.io/](https://annotator.test.transltr.io/) | ITRB |
| prod | [https://annotator.transltr.io/](https://annotator.transltr.io/) | ITRB |

## Notes

Registered in SmartAPI without an infores, and its ci/test servers carry no x-maturity and are declared http:// not https://. SmartAPI registers it at biothings.ci.transltr.io/annotator, which does not serve the OpenAPI document; annotator.ci.transltr.io does. Both were live on 2026-08-31, so the ci base URL is recorded here rather than pulled. Prod serves its OpenAPI at openapi.json rather than the webapp/openapi.json that ci and test use, so it carries a per-environment override; ci and test are the intended convention going forward.

<!-- live -->

## Deployments

| Environment | URL | Version | Source | TRAPI | Biolink | Data release | Reachable | Drift |
|---|---|---|---|---|---|---|---|---|
| dev |  | — |  |  |  |  |  |  |
| ci | [https://annotator.ci.transltr.io/](https://annotator.ci.transltr.io/) | 1.0 | OpenAPI |  |  |  | yes (HTTP 200) |  |
| test | [https://annotator.test.transltr.io/](https://annotator.test.transltr.io/) | 1.0 | OpenAPI |  |  |  | yes (HTTP 200) |  |
| prod | [https://annotator.transltr.io/](https://annotator.transltr.io/) | 1.0.0 | OpenAPI |  |  |  | yes (HTTP 200) | version |

- Last updated: 2026-06-17 (registry)
- SmartAPI uptime: pass
