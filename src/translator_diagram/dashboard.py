"""Turning the synced responses into one overview table.

This module holds the judgement — which source a version came from, whether an
environment is the odd one out — and returns plain dictionaries. It renders
HTML from those dictionaries, but it never fetches and never reads the command
line, so every decision it makes is testable from a fixture directory.

The version-source chain is the point of the whole exercise: the question this
dashboard exists to answer is whether the OpenAPI `info` block is a good
enough source of version information, so the answer must be visible per cell
rather than assumed.
"""

import json
from collections import Counter
from importlib import resources
from pathlib import Path
from typing import Any

import yaml

from .colors import load_owner_colors, text_color_for
from .components import (
    ENVIRONMENTS,
    ComponentFile,
    Deployment,
    deployments_from_smartapi,
    endpoint_url_in,
    merge_deployments,
)
from .flow import flow_depths, in_flow_order, isolated

PACKAGED_ASSETS = ("translator_diagram.data", ("dashboard.css", "dashboard.js"))

# Ordered best to worst. "Best" means closest to what is actually running: a
# live endpoint beats a registration someone filed by hand, which beats a
# chart that describes what should have been deployed.
SOURCE_LABELS = {
    "openapi": "OpenAPI",
    "smartapi": "SmartAPI",
    "status": "status",
    "helm": "Helm",
}


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        # A body saved from a 200 that was not actually JSON. Real: several
        # Translator endpoints answer 200 with an HTML error page.
        return None


def _read_yaml(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError:
        return None
    return loaded if isinstance(loaded, dict) else None


class SyncedData:
    """Everything `sync` wrote, read back."""

    def __init__(self, root: Path):
        self.root = root
        self.manifest = _read_json(root / "manifest.json") or {}
        payload = _read_json(root / "smartapi.json") or {}
        self.smartapi = {
            hit["_id"]: hit for hit in payload.get("hits", []) if hit.get("_id")
        }
        self.otel = {
            env: (_read_json(root / "otel" / f"{env}.json") or {}).get("data") or []
            for env in ("ci", "test", "prod")
        }
        self.statuses = {
            fetch["path"]: fetch for fetch in self.manifest.get("fetches", [])
        }

    def openapi(self, component_id: str, env: str) -> dict[str, Any] | None:
        return _read_json(self.root / "openapi" / component_id / f"{env}.json")

    def status(self, component_id: str, env: str) -> dict[str, Any] | None:
        return _read_json(self.root / "status" / component_id / f"{env}.json")

    def helm(self, chart: str, name: str) -> dict[str, Any] | None:
        return _read_yaml(self.root / "helm" / chart / name)

    def http_status(self, relative: str) -> int | None:
        return (self.statuses.get(relative) or {}).get("status")


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


def _status_facts(document: dict[str, Any] | None) -> dict[str, Any]:
    """Version and data-release fields out of a /status body.

    There is no Translator-wide /status schema — NameRes's shape is its own,
    and its OpenAPI declares the response `additionalProperties: true`. So this
    looks for conventions rather than parsing a schema: any `*_version` key,
    plus the Babel and Biolink fields that carry the *data* release, which is a
    genuinely separate axis from the software version and which nothing else
    exposes at runtime.
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
    return {
        # babel_version is a data release, not the software's version.
        "version": next(
            (v for k, v in versions.items() if k != "babel_version"), None
        ),
        "data_release": " · ".join(release) or None,
        "reported": document.get("status"),
    }


def _helm_facts(synced: SyncedData, chart: str | None) -> dict[str, Any]:
    if not chart:
        return {}
    chart_yaml = synced.helm(chart, "Chart.yaml") or {}
    images = synced.helm(chart, "ncats-images-meta.yaml") or {}
    tags = [
        f"{spec['image'].split('/')[-1]}:{spec['version']}"
        for spec in images.values()
        if isinstance(spec, dict) and spec.get("image") and spec.get("version")
    ]
    return {
        "version": chart_yaml.get("appVersion"),
        "chart_version": chart_yaml.get("version"),
        "images": tags,
    }


def _first(*candidates: tuple[str, Any]) -> tuple[Any, str | None]:
    """The first non-empty candidate, with the name of where it came from."""
    for source, value in candidates:
        if value:
            return value, source
    return None, None


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
        return {"deployed": False}

    openapi = _openapi_facts(synced.openapi(component.id, env))
    status = _status_facts(synced.status(component.id, env))
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
    return {
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
        "http_status": synced.http_status(relative) if openapi_url else None,
        "reachable": bool(openapi) or bool(status),
    }


def _mark_drift(cells: dict[str, dict[str, Any]], key: str) -> None:
    """Flag the environments whose value is in the minority.

    Borrowed from babel-validation's dashboard, where it answers the same
    shape of question. Only a genuine split is marked: when every environment
    agrees, or only one reports at all, nothing is tinted — colouring every
    row would teach the reader to ignore the colour.
    """
    values = [
        cell.get(key) for cell in cells.values() if cell.get("deployed") and cell.get(key)
    ]
    if len(values) < 2 or len(set(values)) < 2:
        return
    majority, _ = Counter(values).most_common(1)[0]
    for cell in cells.values():
        if cell.get("deployed") and cell.get(key) and cell[key] != majority:
            cell.setdefault("drift", []).append(key)


def build_rows(
    components: list[ComponentFile], synced: SyncedData
) -> list[dict[str, Any]]:
    """One dictionary per component, in data-flow order."""
    depths = flow_depths(components)
    stranded = set(isolated(components))
    rows = []
    for component in in_flow_order(components):
        record = synced.smartapi.get(component.smartapi_id or "", {})
        deployments = merge_deployments(
            component, deployments_from_smartapi(record)
        )
        helm = _helm_facts(synced, component.helm_chart)

        cells = {
            env: build_cell(
                component, env, deployments.get(env), synced, record, helm
            )
            for env in ENVIRONMENTS
        }
        for key in ("version", "trapi", "biolink"):
            _mark_drift(cells, key)

        uptime = ((record.get("_status") or {}).get("uptime_status")) or None
        rows.append(
            {
                "id": component.id,
                "name": component.name,
                "owner": component.owner,
                "type": component.component_type
                or _openapi_facts(record).get("component_type"),
                "layer": component.layer,
                "depth": depths[component.id],
                "isolated": component.id in stranded,
                "refactor_status": component.refactor_status,
                "infores": component.infores,
                "smartapi": component.smartapi_id,
                "helm_chart": component.helm_chart,
                "otel_services": component.otel_services,
                "repository": component.repository("source"),
                "documentation": (component.documentation or [{}])[0].get("url"),
                "uptime": uptime,
                "helm_version": helm.get("version"),
                "helm_images": helm.get("images") or [],
                "notes": component.notes,
                "externals": [
                    {"direction": d, "name": n} for d, n in component.externals
                ],
                "environments": cells,
            }
        )
    return rows


def source_tally(rows: list[dict[str, Any]]) -> dict[str, int]:
    """How many deployments each source supplied a version for.

    This is the dashboard's actual finding, and the page states it in a
    sentence rather than making the reader count badges.
    """
    tally = Counter()
    for row in rows:
        for cell in row["environments"].values():
            if not cell.get("deployed"):
                continue
            tally[cell.get("version_source") or "none"] += 1
    return dict(tally)


def build_payload(
    components: list[ComponentFile], synced: SyncedData
) -> dict[str, Any]:
    rows = build_rows(components, synced)
    manifest = synced.manifest
    return {
        "generated_at": manifest.get("finished_at") or "",
        "synced_at": manifest.get("finished_at") or "",
        "sync_counts": manifest.get("counts") or {},
        "environments": list(ENVIRONMENTS),
        "owner_colors": load_owner_colors(),
        "source_labels": SOURCE_LABELS,
        "source_tally": source_tally(rows),
        "otel_service_counts": {
            env: len(names) for env, names in synced.otel.items()
        },
        # Distinct across the three collectors, not their sum: only two names
        # report to all three, so summing counts most services twice over.
        "otel_service_total": len(set().union(*synced.otel.values()))
        if synced.otel
        else 0,
        "rows": rows,
    }


def _css_string(value: str) -> str:
    """Escape a string for a double-quoted CSS attribute selector.

    Not html.escape: a <style> element's contents are not HTML-decoded, so an
    entity there stays literal and the selector matches nothing. Only the
    backslash and the quote need escaping inside a CSS string.
    """
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _asset(name: str) -> str:
    package, _ = PACKAGED_ASSETS
    return (resources.files(package) / name).read_text(encoding="utf-8")


def render_html(payload: dict[str, Any]) -> str:
    """One self-contained page.

    The data is inlined rather than fetched so the file works from file:// —
    it can be emailed, or opened from a checkout, with no server. The same
    payload is written beside it as overview.json, which is the contract a
    scheduled job would publish; keeping both means the page never has to
    choose between being shareable and being automatable.
    """
    colors = load_owner_colors()
    owner_css = "\n".join(
        f'.owner[data-owner="{_css_string(owner)}"] '
        f"{{ background: {color}; color: {text_color_for(color)}; }}"
        for owner, color in colors.items()
    )
    data = json.dumps(payload, indent=None, separators=(",", ":"))
    # </script> inside a JSON string would close the tag early.
    data = data.replace("</", "<\\/")
    return f"""<!doctype html>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Translator components overview</title>
<style>
{_asset("dashboard.css")}
{owner_css}
</style>
<script>
// Applied before the body renders, or the page flashes the wrong theme.
(() => {{
  let choice = "auto";
  try {{
    const stored = localStorage.getItem("theme");
    if (stored === "light" || stored === "dark") choice = stored;
  }} catch {{ /* storage unavailable: fall back to the system preference */ }}
  const dark = choice === "dark" ||
    (choice === "auto" && matchMedia("(prefers-color-scheme: dark)").matches);
  document.documentElement.dataset.theme = dark ? "dark" : "light";
  document.documentElement.dataset.themeChoice = choice;
}})();
</script>
<body>
<div id="app"></div>
<script type="application/json" id="payload">{data}</script>
<script>
{_asset("dashboard.js")}
</script>
</body>
"""


def write_dashboard(payload: dict[str, Any], output_dir: Path) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "overview.json"
    html_path = output_dir / "index.html"
    json_path.write_text(
        json.dumps(payload, indent=2) + "\n", encoding="utf-8"
    )
    html_path.write_text(render_html(payload), encoding="utf-8")
    return html_path, json_path
