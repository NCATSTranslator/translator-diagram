"""Which component each Helm chart in translator-devops belongs to.

Fifty charts and twenty-six components, matched by rules ordered by how much
each claims. Both `sync` (for its summary) and `dashboard` (for the unclaimed
charts on the page) ask, so the rules live here, below both of them, and the
two cannot come to disagree about which charts nobody accounts for.
"""

from collections.abc import Callable
from typing import Any

from .components import ComponentFile, github_repo

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


def chart_dirs(index: Any) -> list[str]:
    """Every chart directory in a cached translator-devops `helm/` listing, sorted.

    Directories only, and read defensively: `helm/` also holds loose files, and
    a `redirects` entry that is raw Ingress manifests with no Chart.yaml would
    otherwise be planned as a chart and 404 every run. A throttled contents call
    answers with an object carrying a message rather than an array. An index we
    cannot read has to mean "we do not know", never "the repository has no
    charts" — the second is a claim, and it would publish forty-nine charts as
    unclaimed.
    """
    return sorted(
        entry["name"]
        for entry in (index if isinstance(index, list) else [])
        if isinstance(entry, dict)
        and entry.get("type") == "dir"
        and isinstance(entry.get("name"), str)
        and entry["name"]
    )


def unclaimed_charts(
    chart_names: list[str],
    charts_meta: dict[str, dict[str, Any]],
    components: list[ComponentFile],
) -> list[str]:
    """The charts `chart_matches` attributes to no component, sorted.

    One definition for the sync summary and the page, so the two cannot come to
    disagree about which charts nobody accounts for.
    """
    matched = chart_matches(chart_names, charts_meta, components)
    return sorted(
        chart for chart, match in matched.items() if match["confidence"] == "none"
    )


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
