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

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

# Our environment ladder, in the order a change travels along it. Also the
# column order in the dashboard, so it is defined once, here.
ENVIRONMENTS = ("dev", "ci", "test", "prod")

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

# SmartAPI's `x-maturity` vocabulary is not ours. `ci` is "staging", which is
# the mapping people get wrong: it is not "development".
MATURITY_TO_ENV = {
    "development": "dev",
    "staging": "ci",
    "testing": "test",
    "production": "prod",
}


@dataclass(frozen=True)
class Deployment:
    """One environment a component is deployed to."""

    env: str
    url: str
    location: str | None = None
    # Overrides the component's shared `endpoints` for this environment only.
    endpoints: dict[str, str | None] = field(default_factory=dict)


@dataclass
class ComponentFile:
    """One components/<id>.yaml, parsed."""

    id: str
    name: str
    owner: str
    component_type: str | None = None
    description: str | None = None
    identifiers: dict[str, Any] = field(default_factory=dict)
    repositories: list[dict[str, str]] = field(default_factory=list)
    documentation: list[dict[str, str]] = field(default_factory=list)
    endpoints: dict[str, str | None] = field(default_factory=dict)
    environments: dict[str, Deployment] = field(default_factory=dict)
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
    def helm_chart(self) -> str | None:
        return self.identifiers.get("helm_chart")

    @property
    def otel_services(self) -> list[str]:
        return list(self.identifiers.get("otel_services") or [])

    # -- diagram ----------------------------------------------------------

    @property
    def refactor_status(self) -> str:
        return self.diagram.get("refactor_status", "")

    @property
    def layer(self) -> str | None:
        return self.diagram.get("layer")

    @property
    def hidden(self) -> bool:
        return bool(self.diagram.get("hide"))

    @property
    def upstream(self) -> list[str]:
        """Component ids that supply this one, '~' stripped.

        Both edge kinds count: a component you get results from and a
        component you call both hand you data back, and for a data-flow
        ordering that is the same relationship. The diagram draws them
        differently because *how* they are called differs, which is a
        rendering concern, not a flow one.
        """
        edges = (self.diagram.get("gets_results_from") or []) + (
            self.diagram.get("calls") or []
        )
        return [ref.lstrip("~") for ref in edges]

    @property
    def externals(self) -> list[tuple[str, str]]:
        return [
            (e["direction"], e["name"])
            for e in (self.diagram.get("externals") or [])
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


def deployments_from_smartapi(record: dict[str, Any]) -> dict[str, Deployment]:
    """The environments a SmartAPI record declares.

    Records routinely list the same server twice, and some carry no
    `x-maturity` at all — node-annotator's ci and test entries do not, and are
    declared http:// rather than https://. Both are dropped rather than
    guessed at: an environment we cannot name is not one we can put in a
    column.
    """
    out: dict[str, Deployment] = {}
    for server in record.get("servers") or []:
        env = MATURITY_TO_ENV.get(server.get("x-maturity") or "")
        url = server.get("url")
        if not env or not url or env in out:
            continue
        out[env] = Deployment(env=env, url=url, location=server.get("x-location"))
    return out


def merge_deployments(
    component: ComponentFile, discovered: dict[str, Deployment]
) -> dict[str, Deployment]:
    """Deployments for a component: what we recorded, plus what we found.

    A recorded deployment wins. Those exist precisely because the discovered
    source was wrong or absent — node-annotator is recorded because SmartAPI
    registers it at a host that does not serve its OpenAPI — so letting the
    discovery overwrite them would reintroduce the bug they document.
    """
    merged = dict(discovered)
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
        identifiers=dict(data.get("identifiers") or {}),
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
