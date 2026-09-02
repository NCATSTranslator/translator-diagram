"""Reading components/*.yaml — the per-component metadata files.

Deliberately separate from `model.Component`, which is one row of the sheet
CSV. These files carry what the sheet cannot: a component's name in each of
the other naming spaces, its repositories and documentation, and its
per-environment deployments. The two will merge if and when `loading.py`
switches over; until then, conflating them would mean one of the two loses
fields it needs.

Nothing here imports anything else in the package, and nothing here reaches
the network. `sync` fetches, this parses, `dashboard` renders.
"""

import re
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import yaml

# Our environment ladder, in the order a change travels along it. Also the
# column order in the dashboard, so it is defined once, here.
ENVIRONMENTS = ("dev", "ci", "test", "prod")

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

# Where an endpoint lives when the component file does not say. Only applied
# when the key is *absent*: an explicit null means someone checked and this
# component has no endpoint of that kind, and defaulting over that would send
# a fetcher back to the same dead end on every run.
#
# Only `openapi` gets a default. A SmartAPI server URL is a TRAPI base and
# `openapi.json` sits at its root often enough to be worth trying, and a 404 is
# itself a finding. `status` has no such convention — defaulting it would
# manufacture a hundred 404s and call them data.
DEFAULT_ENDPOINT_PATHS = {"openapi": "openapi.json"}

# A URL naming a whole GitHub repository, and nothing inside it. The capture
# groups are the two halves of the `owner/name` slug the API is addressed by.
GITHUB_REPO = re.compile(
    r"^https?://github\.com/(?P<owner>[^/]+)/(?P<name>[^/#?]+?)(?:\.git)?/?$"
)

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


@dataclass(frozen=True)
class Deployment:
    """One environment a component is deployed to."""

    env: str
    url: str
    location: str | None = None
    # Overrides the component's shared `endpoints` for this environment only.
    endpoints: dict[str, str | None] = field(default_factory=dict)
    # True when nothing declared this environment and it was read off the
    # server's own description. A weaker claim than a declared `x-maturity`,
    # and the page says so rather than showing the two as one kind of fact.
    inferred: bool = False


@dataclass
class ComponentFile:
    """One components/<id>.yaml, parsed."""

    id: str
    name: str
    owner: str
    component_type: str | None = None
    description: str | None = None
    refactor_status: str = ""
    layer: str | None = None
    part_of: str | None = None
    hosted_at: str | None = None
    identifiers: dict[str, Any] = field(default_factory=dict)
    itrb: dict[str, Any] = field(default_factory=dict)
    connections: dict[str, Any] = field(default_factory=dict)
    repositories: list[dict[str, str]] = field(default_factory=list)
    documentation: list[dict[str, str]] = field(default_factory=list)
    endpoints: dict[str, str | None] = field(default_factory=dict)
    environments: dict[str, Deployment] = field(default_factory=dict)
    # Rendering flags only, and absent from every file today. What used to
    # live here -- the status, the layer, the edges -- are fields above.
    diagram: dict[str, Any] = field(default_factory=dict)
    notes: str | None = None

    # -- identifiers ------------------------------------------------------

    @property
    def infores(self) -> str | None:
        return self.identifiers.get("infores")

    @property
    def smartapi_id(self) -> str | None:
        return self.identifiers.get("smartapi")

    @property
    def helm_charts(self) -> list[str]:
        """Every chart this component is deployed from, in the order recorded.

        `identifiers.helm_chart` is a string or a list of strings, because one
        component can be deployed from several charts — a web server and its
        loader are two charts and one thing — and recording both is more honest
        than picking one and losing the other. A string is the one-chart case
        spelled the short way, and an absent key is the empty list rather than
        `[None]`.
        """
        recorded = self.identifiers.get("helm_chart")
        if isinstance(recorded, str):
            recorded = [recorded]
        elif not isinstance(recorded, list):
            recorded = []

        names: list[str] = []
        seen: set[str] = set()
        for name in recorded:
            if not isinstance(name, str):
                continue
            cleaned = name.strip()
            if cleaned and cleaned not in seen:
                seen.add(cleaned)
                names.append(cleaned)
        return names

    @property
    def helm_chart(self) -> str | None:
        """The first chart, or None.

        Kept alongside `helm_charts` because `overview.json` has carried this
        key since before a component could have two, and a payload key is a
        contract: a consumer reading `helm_chart` must keep getting a string.
        """
        charts = self.helm_charts
        return charts[0] if charts else None

    @property
    def otel_services(self) -> list[str]:
        return list(self.identifiers.get("otel_services") or [])

    @property
    def translator_all_wiki(self) -> str | None:
        """The page name in the Translator-All wiki, not a URL.

        The wiki is one identifier space among several, so the file records the
        page name the way it records an infores or a chart name; whoever renders
        it builds the link.
        """
        return self.identifiers.get("translator_all_wiki")

    # -- itrb -------------------------------------------------------------

    @property
    def itrb_app(self) -> str | None:
        return self.itrb.get("app")

    @property
    def itrb_group(self) -> str | None:
        return self.itrb.get("group")

    # -- connections and rendering ----------------------------------------

    @property
    def hidden(self) -> bool:
        return bool(self.diagram.get("hide"))

    @property
    def ubiquitous(self) -> bool:
        """Drawn beside each caller rather than once in the middle."""
        return bool(self.diagram.get("ubiquitous"))

    def connection_ids(self) -> dict[str, list[str]]:
        """The four recorded edge lists, planned ones separated out.

        `gets_results_from` and `calls` are two different relationships and the
        page draws them differently, so unlike `upstream` — which flattens both
        because a data-flow ordering does not care how a call was made — this
        keeps them apart. A leading `~` means planned rather than implemented,
        and it is a marker on the reference, not part of the id: it is stripped
        here so every list holds ids that resolve, and the tilde survives as the
        list the reference landed in.

        Every key is always present, empty where the file records nothing, so a
        consumer can index all four without asking whether the component
        happens to have any.
        """
        found: dict[str, list[str]] = {
            "gets_results_from": [],
            "calls": [],
            "planned_gets_results_from": [],
            "planned_calls": [],
        }
        for kind in ("gets_results_from", "calls"):
            for ref in self.connections.get(kind) or []:
                if not isinstance(ref, str) or not ref.strip():
                    continue
                text = ref.strip()
                planned = text.startswith("~")
                found[f"planned_{kind}" if planned else kind].append(text.lstrip("~"))
        return found

    @property
    def upstream(self) -> list[str]:
        """Component ids that supply this one, '~' stripped.

        Both edge kinds count: a component you get results from and a
        component you call both hand you data back, and for a data-flow
        ordering that is the same relationship. The diagram draws them
        differently because *how* they are called differs, which is a
        rendering concern, not a flow one.
        """
        edges = (self.connections.get("gets_results_from") or []) + (
            self.connections.get("calls") or []
        )
        return [ref.lstrip("~") for ref in edges]

    @property
    def externals(self) -> list[tuple[str, str]]:
        return [
            (e["direction"], e["name"])
            for e in (self.connections.get("externals") or [])
        ]

    @property
    def fed_by_external(self) -> bool:
        """True if something outside the diagram feeds data in."""
        return any(direction == "in" for direction, _ in self.externals)

    # -- links ------------------------------------------------------------

    def repository(self, role: str = "source") -> str | None:
        for repo in self.repositories:
            if repo.get("role") == role:
                return repo.get("url")
        return None

    def endpoint_url(self, env: str, kind: str) -> str | None:
        """Absolute URL of this component's `kind` endpoint in `env`.

        Only sees deployments recorded in the file. Most components have none,
        deliberately — SmartAPI already knows their URLs, so recording them
        here would be a second copy. Pass the merged mapping from
        `merge_deployments` to `endpoint_url_in` for those.
        """
        deployment = self.environments.get(env)
        if deployment is None:
            return None
        return endpoint_url_in(self, deployment, kind)


def endpoint_url_in(
    component: ComponentFile, deployment: Deployment, kind: str
) -> str | None:
    """Join a component's relative endpoint path onto one deployment's base.

    Endpoint paths are recorded relative to the environment's base URL, so one
    line covers four environments. An environment that does not follow the
    shared pattern carries its own override — node-annotator's prod serves
    `openapi.json` where ci and test serve `webapp/openapi.json`.

    Returns None when there is no path, or the path is explicitly null:
    checked, and this component has no endpoint of that kind. An absent key
    falls through to DEFAULT_ENDPOINT_PATHS instead, which is the whole reason
    the format distinguishes absent from null.
    """
    if kind in deployment.endpoints:
        path = deployment.endpoints[kind]
    elif kind in component.endpoints:
        path = component.endpoints[kind]
    else:
        path = DEFAULT_ENDPOINT_PATHS.get(kind)
    if not path:
        return None
    # Not urljoin: a base of .../api/arax/v1.4 must keep its path, and urljoin
    # would discard everything after the last slash.
    return deployment.url.rstrip("/") + "/" + path.lstrip("/")


def github_repo(url: str | None) -> str | None:
    """`owner/name` for a URL that names a whole GitHub repository.

    A URL pointing *into* a repository is not one: the `helm-chart` entries are
    all `.../translator-devops/tree/develop/helm/<chart>`, and that repository's
    releases are the devops team's, not this component's. Labelling those as a
    component's releases would be worse than showing none, so they are rejected
    here rather than filtered downstream.
    """
    if not url:
        return None
    match = GITHUB_REPO.match(url.strip())
    return f"{match['owner']}/{match['name']}" if match else None


CHART_META_FILES = {
    "chart": "Chart.yaml",
    "values": "values.yaml",
    "images": "ncats-images-meta.yaml",
}
"""What one cached chart looks like to `chart_matches`, key by cached file.

Two readers build this mapping — the dashboard out of its per-build cache, the
sync summary straight off disk — and a matcher that reads `values` from one and
`values_yaml` from the other would silently match nothing for half the callers.
So the vocabulary is written down once, here, beside the function that reads it.
"""


def chart_matches(
    chart_names: list[str],
    charts_meta: dict[str, dict[str, Any]],
    components: list[ComponentFile],
) -> dict[str, dict[str, Any]]:
    """Which component each Helm chart in translator-devops belongs to.

    Fifty charts, twenty-six components, and five ways one can point at the
    other. The rules are tried in the order below and the first that matches
    wins, because they are ordered by how much they claim: a chart somebody
    wrote down beats a chart whose name happens to match, which beats a chart
    that ships an image from the component's repository.

    | Rule | Confidence | What it reads |
    |---|---|---|
    | `identifiers.helm_chart` names the chart | `recorded` | the component file |
    | chart name equals a component id | `strong` | the component file |
    | chart name is one of `otel_services` | `strong` | the component file |
    | the chart's values name the component's infores | `strong` | `values.yaml` |
    | an image repository names the source repository | `plausible` | `values.yaml`, `ncats-images-meta.yaml` |

    The last two read files that are only cached for charts a component
    already claims — `values.yaml` and `ncats-images-meta.yaml` are fetched for
    those, and `Chart.yaml` for everything — so `charts_meta[chart]["values"]`
    is None for most charts and both rules simply do not fire there. That is
    the cache staying proportional to what the page can show, not a gap: a
    chart nothing claims is reported by name so somebody can look at it.

    `component` is one id or None even where several components share a chart,
    because most callers want the one answer; `components` lists every match at
    the winning rule, so the shepherd chart says all three rather than picking
    the alphabetical first and looking decided. `evidence` names the rule and
    the value it matched, for the first of them.
    """
    matched: dict[str, dict[str, Any]] = {}
    for chart in chart_names:
        meta = charts_meta.get(chart) or {}
        matched[chart] = _match_one_chart(chart, meta, components)
    return matched


def _match_one_chart(
    chart: str, meta: dict[str, Any], components: list[ComponentFile]
) -> dict[str, Any]:
    for confidence, rule in _CHART_RULES:
        found = [
            (component, evidence)
            for component in components
            if (evidence := rule(chart, meta, component))
        ]
        if found:
            return {
                "component": found[0][0].id,
                "components": [component.id for component, _ in found],
                "confidence": confidence,
                "evidence": found[0][1],
            }
    return {
        "component": None,
        "components": [],
        "confidence": "none",
        "evidence": "",
    }


def _recorded_chart(chart: str, meta: dict[str, Any], c: ComponentFile) -> str | None:
    for name in c.helm_charts:
        if name.lower() == chart.lower():
            return f"recorded: {c.id} lists identifiers.helm_chart {name}"
    return None


def _chart_named_for_id(chart: str, meta: dict[str, Any], c: ComponentFile) -> str | None:
    # Case-insensitively, the way every other reference to a component id
    # resolves in this repo.
    if chart.lower() == c.id.lower():
        return f"chart name: equals the component id {c.id}"
    return None


def _chart_named_for_service(
    chart: str, meta: dict[str, Any], c: ComponentFile
) -> str | None:
    """The rule that finds `gandalf` for dogpark-tier-0.

    Case-insensitive, unlike the OpenTelemetry join in the dashboard, and for
    the opposite reason: there a name is an identifier a collector reports and
    folding case merges two real services, here it is a directory name in one
    repository being compared with a service name in another, and the two are
    written by different hands.
    """
    for service in c.otel_services:
        if service.lower() == chart.lower():
            return f"otel service: {c.id} records the service {service}"
    return None


def _chart_names_the_infores(
    chart: str, meta: dict[str, Any], c: ComponentFile
) -> str | None:
    if c.infores and c.infores in _infores_strings(meta.get("values")):
        return f"infores in values: {c.infores}"
    return None


def _chart_ships_the_repository(
    chart: str, meta: dict[str, Any], c: ComponentFile
) -> str | None:
    repo = github_repo(c.repository("source"))
    if not repo:
        return None
    for image in _image_repositories(meta):
        if image == repo.lower():
            return f"image repository: names {repo}, {c.id}'s source repository"
    return None


# Ordered by how much each claims, most to least. `_match_one_chart` stops at
# the first rule that matches anything, so a chart somebody wrote down is never
# re-attributed by a name collision further down.
_ChartRule = Callable[[str, dict[str, Any], ComponentFile], str | None]

_CHART_RULES: tuple[tuple[str, _ChartRule], ...] = (
    ("recorded", _recorded_chart),
    ("strong", _chart_named_for_id),
    ("strong", _chart_named_for_service),
    ("strong", _chart_names_the_infores),
    ("plausible", _chart_ships_the_repository),
)


def _infores_strings(values: Any) -> set[str]:
    """Every `infores:...` string anywhere in a chart's values.

    Charts write it in two different places already — `app.serverName` in
    name-lookup, `datasetDesc.provenanceTag` in gandalf — so the key is not
    worth guessing at. The whole tree is walked and the strings that look like
    an infores are collected, which costs nothing on a document this size.
    """
    found: set[str] = set()
    _walk_values(values, lambda key, value: (
        found.add(value.strip())
        if isinstance(value, str) and value.strip().startswith("infores:")
        else None
    ))
    return found


def _image_repositories(meta: dict[str, Any]) -> set[str]:
    """`owner/name` for every container image a chart names, lowercased.

    Read from `values.yaml` and `ncats-images-meta.yaml` under the two keys
    that ever hold one — `image` (a string, or a mapping whose `repository` is
    one) and `repository`. The registry host is dropped and only the last two
    path segments are kept, so `ghcr.io/ncatstranslator/nameresolution` is
    compared with `NCATSTranslator/NameResolution` as the same pair of names.

    A single-segment image (`solr`, `busybox`) names no repository and is left
    out rather than half-matched.
    """
    found: set[str] = set()

    def collect(key: str, value: Any) -> None:
        if key not in ("image", "repository") or not isinstance(value, str):
            return
        # A tag on the end (`ghcr.io/x/y:1.2`) is not part of the name; a port
        # on the registry host is dropped with the host.
        path = value.strip().split("/")
        if len(path) < 2:
            return
        owner, name = path[-2], path[-1].split(":")[0]
        if owner and name:
            found.add(f"{owner.lower()}/{name.lower()}")

    _walk_values(meta.get("values"), collect)
    _walk_values(meta.get("images"), collect)
    return found


def _walk_values(
    node: Any, visit: Callable[[str, Any], None], key: str = ""
) -> None:
    """Call `visit(key, value)` on every scalar in a nested YAML document."""
    if isinstance(node, dict):
        for child_key, child in node.items():
            _walk_values(child, visit, str(child_key))
    elif isinstance(node, list):
        for child in node:
            _walk_values(child, visit, key)
    else:
        visit(key, node)


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
        for hit in hits:
            if hit.get("_id") == recorded:
                return hit, "id", []
    infores = component.infores
    if not infores:
        return None, None, []
    sharing = [hit for hit in hits if _record_infores(hit) == infores]
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


def _record_infores(hit: dict[str, Any]) -> str | None:
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


def _parse_environments(raw: dict[str, Any]) -> dict[str, Deployment]:
    out = {}
    for env, spec in (raw or {}).items():
        out[env] = Deployment(
            env=env,
            url=spec["url"],
            location=spec.get("location"),
            endpoints=dict(spec.get("endpoints") or {}),
        )
    return out


def parse_component(data: dict[str, Any]) -> ComponentFile:
    return ComponentFile(
        id=data["id"],
        name=data.get("name") or data["id"],
        owner=data.get("owner") or "None",
        component_type=data.get("component_type"),
        description=data.get("description"),
        refactor_status=data.get("refactor_status") or "",
        layer=data.get("layer"),
        part_of=data.get("part_of"),
        hosted_at=data.get("hosted_at"),
        identifiers=dict(data.get("identifiers") or {}),
        itrb=dict(data.get("itrb") or {}),
        connections=dict(data.get("connections") or {}),
        repositories=list(data.get("repositories") or []),
        documentation=list(data.get("documentation") or []),
        endpoints=dict(data.get("endpoints") or {}),
        environments=_parse_environments(data.get("environments") or {}),
        diagram=dict(data.get("diagram") or {}),
        notes=data.get("notes"),
    )


def load_components(directory: Path) -> list[ComponentFile]:
    """Every components/*.yaml, sorted by lowercased id.

    Sorted for the same reason `load_components` in loading.py sorts: so the
    generated output does not churn when a file is added.
    """
    components = [
        parse_component(yaml.safe_load(path.read_text(encoding="utf-8")))
        for path in sorted(directory.glob("*.yaml"))
    ]
    return sorted(components, key=lambda c: c.id.lower())


def index_by_id(components: list[ComponentFile]) -> dict[str, ComponentFile]:
    """Case-insensitive lookup, matching how references resolve."""
    return {c.id.lower(): c for c in components}
