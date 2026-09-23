"""One cell of the overview: which version, from which source, or why not.

The version-source chain is the point of the whole exercise: the question this
dashboard exists to answer is whether the OpenAPI `info` block is a good
enough source of version information, so the answer must be visible per cell
rather than assumed. `SOURCE_LABELS` is written in the order `build_cell`
actually asks in.

`CELL_REASONS` is the other half of that promise. A cell with no version says
why it has none, because "we never asked" and "we asked and there is nothing
there" are different answers, and an empty cell gives neither.
"""

from typing import Any

from .components import (
    ComponentFile,
    Deployment,
    deployments_from_smartapi,
    endpoint_url_in,
)
from .synced_data import SyncedData

# Ordered best to worst, and the order `build_cell` actually asks in: two live
# endpoints, then a registration someone filed by hand, then a chart that
# describes what should have been deployed. This dict is only the badge
# vocabulary, but writing it in a different order from the chain is how the
# README came to document the precedence backwards.
SOURCE_LABELS = {
    "openapi": "OpenAPI",
    "status": "status",
    "smartapi": "SmartAPI",
    "helm": "Helm",
}


# Why a cell has no version in it. One vocabulary, in one place, because three
# readers need to agree on it: this module writes the string, the page renders
# it in the cell, and a person reading the page has to be able to tell "we
# never asked" from "we asked and there is nothing there". An empty cell says
# neither, which is what these replace.
#
# Every label is lowercase and short enough to sit in a version column. Two
# carry a placeholder — the environment and an HTTP code — and are formatted at
# the point of use; the rest are used as they are. A cell that *has* a version
# has no reason at all: `reason` is null there, never "ok".
CELL_REASONS = {
    # Not deployed here, for five different reasons.
    "not-registered": "not in registry for {env}",
    "no-such-host": "no such host",
    "another-service": "host answers as another service",
    "unverified-host": "host answers, unverified",
    "not-confirmed": "probed, not confirmed",
    "no-host": "no host recorded",
    "not-hosted": "not a hosted service",
    # Deployed, and still no version to show.
    "unreachable": "unreachable",
    "html-document": "up · serves HTML, no API document",
    "no-version-in-document": "up · document has no version",
    "http-error": "HTTP {code}",
    "no-endpoint": "up · no version endpoint",
    "no-document": "up · no API document",
    # And the one that is a gap in our own data rather than in the platform's:
    # this build's sync recorded no request for this deployment at all, which
    # is what a cache written before root probes existed looks like.
    "not-probed": "not probed",
}


# A status the host itself answered with, however unhappily, still means
# something is there. `reachable` counts 2xx and 3xx and nothing else, so a
# redirect to a login page reads as up — which it is — while a 500 does not.
REACHABLE_STATUSES = range(200, 400)


# Document statuses that are the document's problem rather than the host's: the
# host answered, and answered this way. Anything else with a live root is
# "no API document", which is the 404 case and by far the commonest.
DOCUMENT_ERROR_STATUSES = frozenset({403}) | frozenset(range(500, 600))


# `*_version` keys in a /status body that name something other than the
# software's own version. Babel and Biolink are *data* releases and TRAPI is a
# spec, and a body is free to report any of them before it reports its own
# version — at which point the first `*_version` key would become the
# component's version, badged `status`, tinted for drift against its
# neighbours, and matched against the repository's releases.
NOT_SOFTWARE_VERSIONS = frozenset(
    {"babel_version", "biolink_version", "biolink_model_version", "trapi_version"}
)


# --- What one fetched document says ----------------------------------------

def _openapi_facts(document: dict[str, Any] | None) -> dict[str, Any]:
    """The fields worth a column, out of an OpenAPI `info` block."""
    if not document:
        return {}
    info = document.get("info") or {}
    translator = info.get("x-translator") or {}
    trapi = info.get("x-trapi") or {}
    return {
        "version": info.get("version"),
        "trapi": trapi.get("version"),
        "biolink": translator.get("biolink-version"),
        "component_type": translator.get("component"),
        "title": info.get("title"),
    }


def _live_openapi_facts(document: dict[str, Any] | None) -> dict[str, Any]:
    """What a *served* OpenAPI document says about the endpoint serving it.

    Separate from `_openapi_facts`, and the separation is the point.
    `_openapi_facts` is asked the same questions about a SmartAPI registration,
    which is a document somebody filed by hand and which carries no `paths` at
    all — so reading these fields off a registration would report the
    operations a team registered as the operations this environment serves.
    Those are different claims, and the gap between them is exactly what this
    dashboard is for.

    Every field is therefore only ever read from a live body, and the caller
    gets it through `synced.openapi`, which returns nothing unless this run's
    fetch of that endpoint was a 200. A 404 this run reports no operations
    rather than last run's.
    """
    info = _blocks(document, "info")
    trapi = _blocks(info, "x-trapi")
    paths = (document or {}).get("paths")
    asyncquery = trapi.get("asyncquery")
    return {
        "operations": [
            name for name in (trapi.get("operations") or []) if isinstance(name, str)
        ],
        "asyncquery": asyncquery if isinstance(asyncquery, bool) else None,
        "paths_count": len(paths) if isinstance(paths, dict) else None,
        "title": info.get("title") if isinstance(info.get("title"), str) else None,
    }


def _blocks(document: dict[str, Any] | None, key: str) -> dict[str, Any]:
    """One nested mapping out of a document, or an empty one.

    These files are written by other teams. A key that is present and null is
    how a hand-edited document spells "not set", and chaining `.get` through
    one is the usual way a reader raises instead of losing a field.
    """
    value = (document or {}).get(key) if isinstance(document, dict) else None
    return value if isinstance(value, dict) else {}


def _recent_queries(value: Any) -> dict[str, Any] | None:
    """The query-latency summary a /status body reports, cut to three numbers.

    Name Lookup's block also carries buckets, rates and inter-arrival times —
    a monitoring console's worth of detail, on a page that is not one. A count
    and two percentiles say whether this deployment is being used and how it
    feels; the rest belongs where it is served.

    The keys keep their unit, because `p50` alone is a number whose scale a
    reader has to guess, and the body's own name for it is milliseconds.
    Rounded to a tenth: 14.009746 ms is six digits of precision about a figure
    that changes between one request and the next.

    A block with no numeric `count` is not a summary we can show — a body that
    has grown a different shape here is a gap, not a zero.
    """
    if not isinstance(value, dict):
        return None
    count = value.get("count")
    if not isinstance(count, (int, float)) or isinstance(count, bool):
        return None
    return {
        "count": count,
        "p50_ms": _tenth(value.get("p50_ms")),
        "p95_ms": _tenth(value.get("p95_ms")),
    }


def _tenth(value: Any) -> float | None:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    return round(float(value), 1)


def _status_facts(document: dict[str, Any] | None) -> dict[str, Any]:
    """Version and data-release fields out of a /status body.

    There is no Translator-wide /status schema — NameRes's shape is its own,
    and its OpenAPI declares the response `additionalProperties: true`. So this
    looks for conventions rather than parsing a schema: any `*_version` key
    that is not one of the known data or spec releases, plus the Babel and
    Biolink fields that carry the *data* release, which is a genuinely
    separate axis from the software version and which nothing else exposes at
    runtime.

    Key order is the tie-break when a body reports several, which is why the
    exclusions matter: a document that lists its Biolink version before its
    own would otherwise have that reported as the software it is running.
    """
    if not document:
        return {}
    versions = {
        key: value
        for key, value in document.items()
        if key.endswith("_version") and isinstance(value, str)
    }
    biolink = document.get("biolink_model")
    release = []
    if babel := document.get("babel_version"):
        release.append(f"babel {babel}")
    if isinstance(biolink, dict) and biolink.get("tag"):
        release.append(f"biolink {biolink['tag']}")
    message = document.get("message")
    return {
        "version": next(
            (v for k, v in versions.items() if k not in NOT_SOFTWARE_VERSIONS), None
        ),
        "data_release": " · ".join(release) or None,
        "reported": document.get("status"),
        # A sentence the service wrote about itself — "Reporting results from
        # primary core." Strings only: a structured `message` is a shape the
        # page has not seen, and rendering a mapping at a reader is worse than
        # rendering nothing.
        "message": message if isinstance(message, str) else None,
        "recent_queries": _recent_queries(document.get("recent_queries")),
    }


def _helm_facts(synced: SyncedData, charts: str | list[str] | None) -> dict[str, Any]:
    """The version chain's view of a component's charts: one number and a list.

    Takes every chart the component records, because a component can be
    deployed from more than one, and the image list is the union across them.

    ponytail: `version` comes from the *first* chart. Where a component has
    two they are two halves of one deployment, and the table has room for one
    number — showing "1.2.0 / 0.9.1" in a cell sized for a version buys
    nothing. If two charts ever disagree that disagreement is itself a finding,
    and the upgrade is a per-chart version in the detail block, which the
    `helm_charts` row field already carries, rather than a longer string here.
    """
    names = [charts] if isinstance(charts, str) else list(charts or [])
    if not names:
        return {}
    tags: list[str] = []
    for chart in names:
        images = synced.helm(chart, "ncats-images-meta.yaml") or {}
        tags.extend(
            f"{spec['image'].split('/')[-1]}:{spec['version']}"
            for spec in images.values()
            if isinstance(spec, dict) and spec.get("image") and spec.get("version")
        )
    first = synced.helm(names[0], "Chart.yaml") or {}
    return {
        "version": first.get("appVersion"),
        "chart_version": first.get("version"),
        "images": tags,
    }


# --- Why a cell has no version ---------------------------------------------

def _first(*candidates: tuple[str, Any]) -> tuple[Any, str | None]:
    """The first non-empty candidate, with the name of where it came from."""
    for source, value in candidates:
        if value:
            return value, source
    return None, None


def _undeployed_reason(
    component: ComponentFile,
    env: str,
    smartapi_record: dict[str, Any],
    synced: SyncedData,
) -> str:
    """Why this component has no deployment in this environment.

    Ordered by how much each answer knows, most to least. A component that
    does not run on a server at all is the strongest statement and comes
    first; a candidate host we contacted and were turned away from is the next
    strongest, because something was actually asked; a registration that lists
    other environments and not this one is a fact about a document somebody
    filed; and "no host recorded" is what is left, which is a gap in this
    repository rather than a finding about the platform.
    """
    if (component.hosted_at or "") == "Local":
        return CELL_REASONS["not-hosted"]
    verdict = synced.rejected.get(component.id, {}).get(env)
    if verdict is not None:
        return _rejection_reason(verdict)
    if deployments_from_smartapi(smartapi_record):
        return CELL_REASONS["not-registered"].format(env=env)
    return CELL_REASONS["no-host"]


def _rejection_reason(verdict: dict[str, Any]) -> str:
    """What a conventional hostname's probe found, in three words.

    A rejection is never "down": nothing here established that a deployment
    exists at all, so the strongest thing that can be said is what the probe
    saw. An error is the DNS failure nine of these are — `curl` exits 6 and
    the manifest records a URLError.

    A 200 says two different things depending on what was asked, which is why
    the verdict records that too. To a document check it is the dangerous
    case: something is serving at the predicted address and the infores it
    reports is somebody else's, which is the whole reason the confirmation
    step exists. To a root probe — all a component with no infores can be
    given — it is only "something answers here", and calling that another
    service would be inventing the finding rather than making it. That one is
    worth a person looking at: a live host under the conventional name and
    nothing in this repository able to confirm it.

    Anything else was asked and did not settle it.
    """
    if verdict.get("error"):
        return CELL_REASONS["no-such-host"]
    if verdict.get("status") == 200:
        return CELL_REASONS[
            "another-service" if verdict.get("checked") == "document"
            else "unverified-host"
        ]
    return CELL_REASONS["not-confirmed"]


def _missing_version_reason(
    *,
    reachable: bool | None,
    document: str | None,
    status_answered: bool,
    http_status: int | None,
    openapi_url: str | None,
) -> str:
    """Why a deployment we can see is showing no version.

    Reads off `reachable` rather than recomputing the same three states beside
    it: a cell that says "up · no API document" next to a red dot is the
    contradiction this page exists not to print, and the only way to be sure
    of that is for one of them to be derived from the other.

    Then the documents, in the order they would have supplied a version: a 200
    that was not JSON at all, a document with no version in it, a status body
    with no version in it. Only after those does the absence of a document
    become the answer, and the two kinds of absence are kept apart — an
    endpoint that was never recorded, and one that was recorded and 404s.
    """
    if reachable is None:
        return CELL_REASONS["not-probed"]
    if reachable is False:
        return CELL_REASONS["unreachable"]
    if document == "not-json":
        return CELL_REASONS["html-document"]
    if document == "no-version" or status_answered:
        return CELL_REASONS["no-version-in-document"]
    if http_status in DOCUMENT_ERROR_STATUSES:
        return CELL_REASONS["http-error"].format(code=http_status)
    if openapi_url is None:
        return CELL_REASONS["no-endpoint"]
    return CELL_REASONS["no-document"]


def _probe_statuses(
    synced: SyncedData, component_id: str, env: str
) -> list[int | None]:
    """Every status this run recorded for one deployment, root probe included.

    From the manifest rather than from the bodies, because a probe that failed
    wrote no body and is exactly the one worth counting. An empty list means
    nothing was asked, which is the third state `reachable` needs and the one
    a boolean cannot hold.
    """
    return [
        fetch.get("status")
        for kind in ("root", "openapi", "status")
        if (fetch := synced.statuses.get(f"{kind}/{component_id}/{env}.json"))
    ]


def _reachable(statuses: list[int | None]) -> bool | None:
    """Whether anything answered, out of every probe this run made.

    Three states, and each says something different. True: something at this
    address answered 2xx or 3xx — the root, or a document, and either is
    enough. False: everything we asked failed, whether that was DNS, a
    timeout or a 500. None: nothing was asked, which is not a finding about
    the deployment and must not be drawn as one.

    The root probe is what makes this honest. Before it, `reachable` meant
    "did an API document parse", so the four UI environments — which record no
    OpenAPI endpoint, so nothing was ever fetched — were drawn with a red dot
    and no HTTP status, reporting four live hosts as down on the strength of a
    request that was never made.
    """
    if not statuses:
        return None
    return any(
        isinstance(status, int) and status in REACHABLE_STATUSES
        for status in statuses
    )


# --- The chain itself ------------------------------------------------------

def build_cell(
    component: ComponentFile,
    env: str,
    deployment: Deployment | None,
    synced: SyncedData,
    smartapi_record: dict[str, Any],
    helm: dict[str, Any],
) -> dict[str, Any]:
    """One component in one environment."""
    if deployment is None:
        return {
            "deployed": False,
            "reason": _undeployed_reason(component, env, smartapi_record, synced),
        }

    # One read, then two readings of it: the fields the version chain compares
    # across sources, and the fields only a served document can answer for.
    document = synced.openapi(component.id, env)
    openapi = _openapi_facts(document)
    live = _live_openapi_facts(document)
    status_document = synced.status(component.id, env)
    status = _status_facts(status_document)
    registered = _openapi_facts(smartapi_record)

    version, source = _first(
        ("openapi", openapi.get("version")),
        ("status", status.get("version")),
        ("smartapi", registered.get("version")),
        ("helm", helm.get("version")),
    )
    trapi, trapi_source = _first(
        ("openapi", openapi.get("trapi")), ("smartapi", registered.get("trapi"))
    )
    biolink, _ = _first(
        ("openapi", openapi.get("biolink")), ("smartapi", registered.get("biolink"))
    )

    openapi_url = endpoint_url_in(component, deployment, "openapi")
    relative = f"openapi/{component.id}/{env}.json"
    http_status = synced.http_status(relative) if openapi_url else None
    probe = synced.root_probe(component.id, env) or {}
    reachable = _reachable(_probe_statuses(synced, component.id, env))
    cell = {
        "deployed": True,
        "url": deployment.url,
        "location": deployment.location,
        "openapi_url": openapi_url,
        "status_url": endpoint_url_in(component, deployment, "status"),
        "version": version,
        "version_source": source,
        "trapi": trapi,
        "trapi_source": trapi_source,
        "biolink": biolink,
        "data_release": status.get("data_release"),
        "http_status": http_status,
        # The document's status and the host's, kept apart. They answer two
        # questions that used to share one number, and every cell where they
        # disagree — a host serving its app at `/` and nothing at
        # `openapi.json` — is one the page was previously getting wrong.
        "root_status": probe.get("status"),
        "reachable": reachable,
        # What this environment actually serves, as opposed to what its record
        # says it should. Everything below inherits the manifest-200 gate from
        # `synced.openapi` and `synced.status`, so a 404 this run reports no
        # operations rather than the ones cached from the last one.
        "openapi_title": live["title"],
        "trapi_operations": live["operations"],
        "asyncquery": live["asyncquery"],
        "paths_count": live["paths_count"],
        "status_message": status.get("message"),
        "recent_queries": status.get("recent_queries"),
        # What the OpenAPI fetch got back, as a word rather than as an absence:
        # "version", "no-version", "not-json", or null where nothing was
        # fetched at all. `version` above says what we found; this says what we
        # were looking at when we did or did not find it.
        "document": synced.openapi_outcome(component.id, env),
        # Null while there is a version to show, filled in below when there is
        # not. Always present, unlike `inferred`: an empty version cell is the
        # thing this key exists to explain, and a renderer that has to ask
        # whether the key is there before asking what it says will one day
        # forget.
        "reason": None,
        # An environment nobody declared, read off the server's own description
        # in the registry. Absent rather than false where the maturity was
        # declared, the way `unregistered` and `drift` are: a key that is
        # always there is a key the page has to render an answer for.
        **({"inferred": True} if deployment.inferred else {}),
    }
    if version is None:
        # Only where there is nothing to show. A reason beside a version would
        # be a caption on a fact, and the two would drift apart the first time
        # a fallback source filled the cell in.
        cell["reason"] = _missing_version_reason(
            reachable=reachable,
            document=cell["document"],
            status_answered=status_document is not None,
            http_status=http_status,
            openapi_url=openapi_url,
        )
    return cell
