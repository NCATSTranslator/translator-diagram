"""Where a component is deployed, and on whose word.

Three sources, in the order `merge_deployments` believes them: what a
component file records, what its SmartAPI registration declares (or, failing
that, describes), and what the ITRB hostname convention predicts. The first is
parsed in `components`; this module finds the registry record, reads its
servers, derives the missing hosts and merges the three.

Nothing here reaches the network. A derived deployment is a candidate until
`sync` confirms it.
"""

import re
from collections import Counter
from typing import Any
from urllib.parse import urlsplit

from .components import ENVIRONMENTS, ComponentFile, Deployment

# ITRB deploys on a fixed hostname convention: `<stem>.ci.transltr.io`,
# `<stem>.test.transltr.io`, `<stem>.transltr.io`. Knowing one environment's
# host therefore tells you where to *look* for the others — which matters
# because SmartAPI registration is manual and routinely incomplete.
#
# `dev` is deliberately absent: development deployments live at RENCI, at
# BioThings, and elsewhere, with no convention to derive from.
TRANSLTR_HOST = re.compile(
    r"^(?P<stem>[^.]+)\.(?:(?P<maturity>ci|test)\.)?transltr\.io$"
)
DERIVABLE_HOSTS = {
    "ci": "{stem}.ci.transltr.io",
    "test": "{stem}.test.transltr.io",
    "prod": "{stem}.transltr.io",
}

# SmartAPI's `x-maturity` vocabulary is not ours. `ci` is "staging", which is
# the mapping people get wrong: it is not "development".
MATURITY_TO_ENV = {
    "development": "dev",
    "staging": "ci",
    "testing": "test",
    "production": "prod",
}

# The same vocabulary read out of a server's prose `description` when the
# record declares no `x-maturity` at all — smartapi's own registration lists
# "Production server" and "Development server" and nothing else, so a record
# describing two environments used to produce none.
#
# The description only, never the URL. `dev.smart-api.info` and
# `ci.transltr.io` look like they name a maturity, and a component whose
# production host happens to contain "test" would be filed as test on the
# strength of a substring — which is the guess these files exist to avoid. A
# description is somebody writing down what the server *is*; a hostname is not.
#
# Ordered longest-first inside the alternation so "testing" is not read as
# "test", and matched leftmost so a description naming two of them takes the
# one it leads with.
DESCRIBED_MATURITY = re.compile(
    r"\b(production|development|staging|testing|test)\b", re.IGNORECASE
)
DESCRIPTION_TO_ENV = {
    "production": "prod",
    "development": "dev",
    "staging": "ci",
    "testing": "test",
    "test": "test",
}


def smartapi_record_for(
    component: ComponentFile, hits: list[dict[str, Any]]
) -> tuple[dict[str, Any] | None, str | None, list[dict[str, Any]]]:
    """The registry record that belongs to one component, and how we know.

    Two ways, and only two. A `identifiers.smartapi` id is somebody's decision
    and is believed outright. Failing that, a record whose
    `info.x-translator.infores` is the component's infores is the same
    component under a different pointer — but only when exactly one record
    claims that infores: three infores in the registry today are claimed by
    more than one record, and picking one of them would attach a version, a
    TRAPI level and an uptime result to a component off a coin toss. Several
    hits therefore attach nothing and are returned as candidates, so the page
    can show them and somebody can record the right id.

    Titles are never matched on. "ARAX" is a component, an OpenTelemetry
    service and the first word of several registry titles, and a match on prose
    is the kind that looks right until it is wrong.

    Returns `(record, matched_by, candidates)`: the record and `"id"` or
    `"infores"`, or `(None, None, candidates)` where candidates is the
    ambiguous set — empty when nothing matched at all.
    """
    recorded = component.smartapi_id
    if recorded:
        # A recorded id that is not in the registry attaches nothing. Falling
        # back to the infores here would dress a guess up as the record
        # somebody chose, and hide that their id has gone stale.
        for hit in hits:
            if hit.get("_id") == recorded:
                return hit, "id", []
        return None, None, []
    infores = component.infores
    if not infores:
        return None, None, []
    sharing = [hit for hit in hits if record_infores(hit) == infores]
    if len(sharing) == 1:
        return sharing[0], "infores", []
    if len(sharing) > 1:
        return None, None, [
            {
                "smartapi_id": hit.get("_id"),
                "title": (hit.get("info") or {}).get("title"),
            }
            for hit in sharing
        ]
    return None, None, []


def record_infores(hit: Any) -> str | None:
    """`info.x-translator.infores` out of a registry record or OpenAPI document."""
    if not isinstance(hit, dict):
        return None
    info = hit.get("info")
    translator = info.get("x-translator") if isinstance(info, dict) else None
    value = translator.get("infores") if isinstance(translator, dict) else None
    return value if isinstance(value, str) else None


def deployments_from_smartapi(record: dict[str, Any]) -> dict[str, Deployment]:
    """The environments a SmartAPI record declares, or describes.

    Two passes, and the order between them is the point. A declared
    `x-maturity` is somebody filling in the field that exists for this, and
    every one of those is taken first. Only then does the second pass read a
    maturity out of a server's `description` — "Production server",
    "Development server" — and only for an environment the first pass did not
    fill. A declaration therefore can never be overwritten by a sentence, which
    is what an ordering by server position would have allowed.

    The second pass exists because a record with no `x-maturity` anywhere used
    to yield *no* environments at all: smartapi's own registration lists a
    production and a development server, describes both in prose, and so had an
    empty row on a page about deployments. What it reads is marked
    `inferred` all the way through to the cell, because "this record says
    production" and "this record's description says production" are two
    different strengths of claim.

    Records routinely list the same server twice — name-lookup and
    sri-node-normalizer each list every server twice — and the first of a
    duplicate wins in both passes.
    """
    out: dict[str, Deployment] = {}
    for server in record.get("servers") or []:
        env = MATURITY_TO_ENV.get(server.get("x-maturity") or "")
        url = server.get("url")
        if not env or not url or env in out:
            continue
        out[env] = Deployment(env=env, url=url, location=server.get("x-location"))
    for server in record.get("servers") or []:
        if server.get("x-maturity"):
            continue
        env = _described_env(server.get("description"))
        url = server.get("url")
        if not env or not url or env in out:
            continue
        out[env] = Deployment(
            env=env,
            url=url,
            location=server.get("x-location"),
            inferred=True,
        )
    return out


def _described_env(description: Any) -> str | None:
    """The environment a server's prose description names, if it names one."""
    if not isinstance(description, str):
        return None
    found = DESCRIBED_MATURITY.search(description)
    return DESCRIPTION_TO_ENV.get(found.group(1).lower()) if found else None


def derive_deployments(known: dict[str, Deployment]) -> dict[str, Deployment]:
    """Where a component's missing environments would be, by convention.

    Candidates, not facts. Nothing here has been contacted, so a caller must
    confirm each one before believing it — `sync` does that by fetching the
    endpoint and checking the infores it reports. Deriving without confirming
    would be guessing, which is the one thing these files must never do.

    The stem and any path are taken from an environment we already know, so
    arax's `/api/arax/v1.4` survives into its siblings.

    One stem is chosen even when the known hosts disagree, because a
    conventional hostname has one shape and probing several would race two
    fetches for the same cache file. It is the commonest stem, and the
    earliest on the ladder among equals — a rule the deployments decide,
    rather than the alphabetical accident of sorting the stems and taking the
    first, which is what this did while reading as though it tried each.
    """
    stems: list[tuple[str, str]] = []
    for env in ENVIRONMENTS:
        deployment = known.get(env)
        if deployment is None:
            continue
        parts = urlsplit(deployment.url)
        match = TRANSLTR_HOST.match(parts.hostname or "")
        if match:
            stems.append((match.group("stem"), parts.path.rstrip("/")))
    if not stems:
        return {}
    seen = Counter(stem for stem, _ in stems)
    # max() keeps the first of equals, and `stems` is in ladder order.
    stem, path = max(stems, key=lambda pair: seen[pair[0]])
    return {
        env: Deployment(
            env=env,
            url=f"https://{template.format(stem=stem)}{path}/",
            location="ITRB",
        )
        for env, template in DERIVABLE_HOSTS.items()
        if env not in known
    }


def merge_deployments(
    component: ComponentFile,
    discovered: dict[str, Deployment],
    derived: dict[str, Deployment] | None = None,
) -> dict[str, Deployment]:
    """Deployments for a component, best source first.

    A recorded deployment wins over a registered one, which wins over a
    derived one. Recorded entries exist precisely because the registry was
    wrong or absent — node-annotator is recorded because SmartAPI registers it
    at a host that does not serve its OpenAPI — so letting anything overwrite
    them would reintroduce the bug they document.
    """
    merged = dict(derived or {})
    merged.update(discovered)
    merged.update(component.environments)
    return {env: merged[env] for env in ENVIRONMENTS if env in merged}
