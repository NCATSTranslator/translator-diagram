"""The `content/` tree: what people with repository access read on GitHub.

The published dashboard is one page, redacted by `config/privacy.yaml`, that
anyone can reach. This module writes the other half of issue #7's answer: the
same facts with nothing withheld, plus everything a component file records
that the page has no column for, as Markdown and CSV that GitHub renders in
the browser. Nothing here is interactive; the interactive full view is still
`build-dashboard --include-private`, run locally. What this gives up in
sorting and filtering it gets back in being linkable, diffable and readable
by a tool with a checkout.

Two rules shape every file written here:

- **No timestamps.** A build that changes nothing must write nothing, so a
  scheduled refresh on a quiet day produces no diff and no pull request. When
  a file was last built is `git log -1 -- content/`, which is a better answer
  anyway: it says who merged it.
- **Static above the marker, live below it.** Each component page is the file
  on disk down to `LIVE_MARKER`, then what the sync fetched. The static half
  can be rebuilt from a checkout alone, so a test can check it is fresh; the
  live half needs `data/sync`, so only a run with a sync writes it.

Imports `components` for the files and `dashboard` for the stage order, and
nothing else: the payload it renders is the one `build_payload` returns, so
it never re-derives a version or a drift mark. If the page and these files
ever disagree, the page is wrong too.
"""

import csv
import io
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import yaml

from .components import ENVIRONMENTS, ComponentFile
from .dashboard import in_stage_order, load_stages

# The sheet's columns, in the sheet's order. `generate-diagram --input` reads
# exactly this shape (loading.py), which is what makes components.csv a
# replacement for the Google Sheet rather than a report about it. The last
# column is the one `--layer-column Tier` names.
SHEET_COLUMNS = (
    "id",
    "Name",
    "Owner",
    "URL",
    "Component in ITRB",
    "Refactor status",
    "Gets results from",
    "Calls",
    "Notes",
    "Ubiquitous",
    "Hide",
    "Part of",
    "Hosted at",
    "Externals",
    "Tier",
)

DEPLOYMENT_COLUMNS = (
    "id",
    "name",
    "owner",
    "env",
    "deployed",
    "url",
    "location",
    "version",
    "version_source",
    "trapi",
    "trapi_source",
    "biolink",
    "data_release",
    "http_status",
    "reachable",
    "unregistered",
    "drift",
    "released",
    "release_tag",
    "release_url",
    "openapi_url",
    "status_url",
)

LIVE_MARKER = "<!-- live -->"
"""The line dividing a component page's static half from its live half."""

NOT_DEPLOYED = "—"
NO_VERSION = "?"


# -- the sheet ----------------------------------------------------------------


def sheet_row(component: ComponentFile) -> dict[str, str]:
    """One sheet row from one component file.

    The YAML has no `URL` column: the sheet's is the node's click target, and
    the nearest recorded thing is the source repository, then the first
    documentation link. Everything the YAML records that the sheet has no
    column for goes to the component's page instead.
    """
    connections = component.connections
    diagram = component.diagram
    return {
        "id": component.id,
        "Name": component.name,
        "Owner": component.owner,
        "URL": component.repository("source")
        or (component.documentation or [{}])[0].get("url")
        or "",
        "Component in ITRB": component.itrb_group or "",
        "Refactor status": component.refactor_status,
        "Gets results from": ", ".join(connections.get("gets_results_from") or []),
        "Calls": ", ".join(connections.get("calls") or []),
        "Notes": component.notes or "",
        "Ubiquitous": "TRUE" if diagram.get("ubiquitous") else "",
        "Hide": "TRUE" if diagram.get("hide") else "",
        "Part of": component.part_of or "",
        "Hosted at": component.hosted_at or "",
        "Externals": _externals_cell(component.externals),
        "Tier": component.layer or "",
    }


def _externals_cell(externals: list[tuple[str, str]]) -> str:
    """`<Source, >Sink` — written through the CSV module, so a name with a comma
    in it is quoted the way `loading.parse_externals`'s reader expects."""
    if not externals:
        return ""
    tokens = [
        ("<" if direction == "in" else ">") + name for direction, name in externals
    ]
    buffer = io.StringIO()
    csv.writer(buffer, lineterminator="").writerow(tokens)
    return buffer.getvalue()


def write_components_csv(components: list[ComponentFile], path: Path) -> None:
    _write_csv(path, SHEET_COLUMNS, (sheet_row(c) for c in components))


def _write_csv(path: Path, columns: tuple[str, ...], rows: Iterable[dict]) -> None:
    # lineterminator: csv.writer's default is \r\n, which would make every
    # commit of these files a CRLF diff.
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({column: _csv_value(row.get(column)) for column in columns})


def _csv_value(value: Any) -> str:
    if value is None:
        return ""
    if value is True:
        return "TRUE"
    if value is False:
        return "FALSE"
    if isinstance(value, list):
        return ";".join(str(item) for item in value)
    return str(value)


# -- the private block --------------------------------------------------------


def read_private(directory: Path) -> dict[str, dict[str, Any]]:
    """The `private:` block of every component file that has one, by id.

    Read from the YAML directly rather than from `ComponentFile`, on purpose:
    the parser does not know the key, so the dashboard cannot carry it into
    the page, and this is the only reader. See components/CLAUDE.md.
    """
    out: dict[str, dict[str, Any]] = {}
    for path in sorted(directory.glob("*.yaml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        block = data.get("private")
        if block:
            out[data["id"]] = block
    return out


# -- the deployments ----------------------------------------------------------


def deployment_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """One row per component and environment, including the empty ones.

    Every component contributes a row for every environment, deployed or not,
    so the file's row count is fixed by the platform and a diff shows values
    changing rather than rows appearing.
    """
    rows = []
    for row in payload["rows"]:
        for env in payload.get("environments") or ENVIRONMENTS:
            cell = row["environments"].get(env) or {"deployed": False}
            rows.append(
                {
                    "id": row["id"],
                    "name": row["name"],
                    "owner": row["owner"],
                    "env": env,
                    **{key: cell.get(key) for key in DEPLOYMENT_COLUMNS[4:]},
                    "deployed": bool(cell.get("deployed")),
                }
            )
    return rows


def write_deployments_csv(payload: dict[str, Any], path: Path) -> None:
    _write_csv(path, DEPLOYMENT_COLUMNS, deployment_rows(payload))


# -- markdown helpers ---------------------------------------------------------


def _md(value: Any) -> str:
    """One table cell or list item: no pipes, no line breaks, no `None`."""
    if value is None or value == "":
        return ""
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, list):
        return ", ".join(_md(item) for item in value)
    return " ".join(str(value).split()).replace("|", "\\|")


def _table(headers: list[str], rows: list[list[Any]]) -> str:
    lines = [
        "| " + " | ".join(headers) + " |",
        "|" + "|".join("---" for _ in headers) + "|",
    ]
    lines.extend("| " + " | ".join(_md(cell) for cell in row) + " |" for row in rows)
    return "\n".join(lines) + "\n"


def _link(text: str, url: str | None) -> str:
    return f"[{_md(text)}]({url})" if url else _md(text)


def _version_cell(cell: dict[str, Any], labels: dict[str, str]) -> str:
    if not cell.get("deployed"):
        return NOT_DEPLOYED
    version = cell.get("version")
    if not version:
        return NO_VERSION
    text = f"{version} ({labels.get(cell.get('version_source'), cell.get('version_source'))})"
    if "version" in (cell.get("drift") or []):
        text += " \\*"
    return text


def _stage_label(step: int, stage: dict[str, Any]) -> str:
    title = stage.get("title") or ""
    if stage.get("unplaced"):
        return title
    return f"Step {step}: {title}" if title else f"Step {step}"


# -- the dashboard as one file ------------------------------------------------


def dashboard_markdown(payload: dict[str, Any]) -> str:
    labels = payload.get("source_labels") or {}
    tally = payload.get("source_tally") or {}
    rows = payload["rows"]
    environments = list(payload.get("environments") or ENVIRONMENTS)
    total = sum(tally.values())
    named = [
        f"{tally[key]} from {labels.get(key, key)}"
        for key in ("openapi", "status", "smartapi", "helm")
        if tally.get(key)
    ]
    if named:
        named[0] = named[0].replace(" from ", " have a version from ", 1)
    if tally.get("none"):
        named.append(f"{tally['none']} from nothing at all")
    if len(named) > 1:
        named[-1] = "and " + named[-1]
    drifting = [
        row["id"]
        for row in rows
        if any((cell.get("drift") or []) for cell in row["environments"].values())
    ]

    out = [
        "# Translator components\n",
        (
            "The published dashboard's table with nothing withheld, as one file. "
            "Generated by `build-content` from the same payload the page is built "
            "from; each component links to its own page under "
            "[`components/`](components/), and [`deployments.csv`](deployments.csv) "
            "has every field of every cell.\n"
        ),
        f"Of {total} deployments, {', '.join(named) if named else 'none has a version'}."
        + (
            f" {payload['unregistered_count']} are absent from their "
            f"component's SmartAPI record, which does list other environments."
            if payload.get("unregistered_count")
            else ""
        )
        + "\n",
        (
            f"{len(drifting)} disagree across environments: "
            + ", ".join(f"[{cid}](components/{cid}.md)" for cid in drifting)
            + ".\n"
            if drifting
            else "Every component reports the same version in every environment.\n"
        ),
        (
            f"A cell reads `version (source)`. `{NO_VERSION}` is deployed with no "
            f"version found; `{NOT_DEPLOYED}` is not deployed there; `\\*` marks a "
            f"version in the minority for its row.\n"
        ),
    ]

    current: tuple[Any, ...] | None = None
    band: list[list[Any]] = []

    def flush() -> None:
        if current is None:
            return
        _, label, title, description = current
        heading = f"{label}: {title}" if title and label != title else title or label
        out.append(f"## {heading}\n")
        if description:
            out.append(f"{description}\n")
        out.append(_table(["Component", "Owner", *environments, "Last updated"], band))

    for row in rows:
        key = (
            row.get("step"),
            row.get("step_label") or "",
            row.get("step_title") or "",
            row.get("step_description") or "",
        )
        if key != current:
            flush()
            current = key
            band = []
        updated = row.get("last_updated") or {}
        band.append(
            [
                f"[{_md(row['name'])}](components/{row['id']}.md) `{row['id']}`",
                row["owner"],
                *(
                    _version_cell(row["environments"].get(env) or {}, labels)
                    for env in environments
                ),
                (
                    f"{updated.get('date')} ({updated.get('source')})"
                    if updated.get("date")
                    else ""
                ),
            ]
        )
    flush()
    return "\n".join(out)


# -- the component pages ------------------------------------------------------


def _used_by(components: list[ComponentFile]) -> dict[str, list[tuple[str, str]]]:
    """Reverse edges: who gets results from, or calls, each component."""
    out: dict[str, list[tuple[str, str]]] = {c.id: [] for c in components}
    for component in components:
        for kind in ("gets_results_from", "calls"):
            for ref in component.connections.get(kind) or []:
                target = ref.lstrip("~")
                if target in out:
                    out[target].append((component.id, kind))
    return out


def _refs(refs: list[str], by_id: dict[str, ComponentFile]) -> str:
    """`[Name](id.md)` for each reference, keeping a planned `~` visible."""
    parts = []
    for ref in refs:
        planned = ref.startswith("~")
        cid = ref.lstrip("~")
        target = by_id.get(cid)
        text = _link(target.name, f"{cid}.md") if target else f"`{cid}`"
        parts.append(f"{text} (planned)" if planned else text)
    return ", ".join(parts) if parts else "none recorded"


def component_page(
    component: ComponentFile,
    step: int,
    stage: dict[str, Any],
    by_id: dict[str, ComponentFile],
    used_by: list[tuple[str, str]],
    private: dict[str, Any] | None,
    row: dict[str, Any] | None,
    labels: dict[str, str],
) -> str:
    """One component's page: everything its file records, then what is running."""
    out = [f"# {_md(component.name)}\n"]
    out.append(
        _table(
            ["Field", "Value"],
            [
                ["Id", f"`{component.id}`"],
                ["Owner", component.owner],
                ["Type", component.component_type],
                ["Refactor status", component.refactor_status],
                ["Stage", _stage_label(step, stage)],
                ["Layer", component.layer],
                ["Part of", component.part_of],
                ["Hosted at", component.hosted_at],
            ],
        )
    )
    if component.description:
        out.append(_md(component.description) + "\n")

    identifiers = component.identifiers
    smartapi = identifiers.get("smartapi")
    wiki = identifiers.get("translator_all_wiki")
    id_rows = [
        ["infores", f"`{identifiers['infores']}`" if identifiers.get("infores") else ""],
        [
            "SmartAPI",
            _link(smartapi, f"https://smart-api.info/registry?q={smartapi}")
            if smartapi
            else "",
        ],
        ["Helm chart", f"`{identifiers['helm_chart']}`" if identifiers.get("helm_chart") else ""],
        [
            "Translator-All wiki",
            _link(wiki, f"https://github.com/NCATSTranslator/Translator-All/wiki/{wiki}")
            if wiki
            else "",
        ],
        ["OpenTelemetry services", component.otel_services],
        ["ITRB app", component.itrb_app],
        ["ITRB group", component.itrb_group],
    ]
    out.append("## Identifiers\n")
    out.append(_table(["Namespace", "Value"], id_rows))

    out.append("## Connections\n")
    out.append(
        f"- Gets results from: "
        f"{_refs(component.connections.get('gets_results_from') or [], by_id)}\n"
        f"- Calls: {_refs(component.connections.get('calls') or [], by_id)}\n"
        "- Used by: "
        + (
            ", ".join(
                f"{_link(by_id[cid].name, f'{cid}.md')} ({kind.replace('_', ' ')})"
                for cid, kind in used_by
            )
            or "none recorded"
        )
        + "\n"
        + "- Externals: "
        + (
            ", ".join(
                f"{_md(name)} ({'in' if direction == 'in' else 'out'})"
                for direction, name in component.externals
            )
            or "none recorded"
        )
        + "\n"
    )

    if component.repositories:
        out.append("## Repositories\n")
        out.append(
            _table(
                ["Repository", "Role", "Visibility", "Note"],
                [
                    [
                        _link(repo.get("url", ""), repo.get("url")),
                        repo.get("role"),
                        repo.get("visibility", "public"),
                        repo.get("note"),
                    ]
                    for repo in component.repositories
                ],
            )
        )
    if component.documentation:
        out.append("## Documentation\n")
        out.append(
            _table(
                ["Link", "Kind"],
                [
                    [_link(doc.get("url", ""), doc.get("url")), doc.get("kind")]
                    for doc in component.documentation
                ],
            )
        )
    if component.endpoints:
        out.append("## Endpoints\n")
        out.append(
            _table(
                ["Kind", "Path"],
                [
                    [kind, f"`{path}`" if path else "none (checked)"]
                    for kind, path in component.endpoints.items()
                ],
            )
        )
    if component.environments:
        out.append("## Recorded environments\n")
        out.append(
            _table(
                ["Environment", "URL", "Location"],
                [
                    [env, _link(dep.url, dep.url), dep.location]
                    for env, dep in component.environments.items()
                ],
            )
        )
    if component.notes:
        out.append("## Notes\n")
        out.append(_md(component.notes) + "\n")

    if private:
        out.append("## Private\n")
        out.append(
            "Recorded in this repository only. Nothing in this section reaches "
            "the published page.\n"
        )
        items = []
        for key, value in private.items():
            title = key.replace("_", " ").capitalize()
            if isinstance(value, list):
                items.append(f"- {title}:\n" + "".join(f"  - {_md(v)}\n" for v in value))
            else:
                items.append(f"- {title}: {_md(value)}\n")
        out.append("".join(items))

    out.append(LIVE_MARKER + "\n")
    out.append(_live_section(row, labels))
    return "\n".join(out)


def _live_section(row: dict[str, Any] | None, labels: dict[str, str]) -> str:
    if row is None:
        return (
            "_No live data in this build. Run `uv run sync-components` before "
            "`uv run build-content` to fill in what is running._\n"
        )
    out = ["## Deployments\n"]
    cells = row.get("environments") or {}
    out.append(
        _table(
            [
                "Environment",
                "URL",
                "Version",
                "Source",
                "TRAPI",
                "Biolink",
                "Data release",
                "Reachable",
                "Drift",
            ],
            [
                [
                    env,
                    _link(cell.get("url", ""), cell.get("url")),
                    cell.get("version") or (NO_VERSION if cell.get("deployed") else ""),
                    labels.get(cell.get("version_source"), cell.get("version_source")),
                    cell.get("trapi"),
                    cell.get("biolink"),
                    cell.get("data_release"),
                    (
                        ("yes" if cell.get("reachable") else "no")
                        + (f" (HTTP {cell['http_status']})" if cell.get("http_status") else "")
                    )
                    if cell.get("deployed")
                    else "",
                    ", ".join(cell.get("drift") or []),
                ]
                if cell.get("deployed")
                else [env, "", NOT_DEPLOYED, "", "", "", "", "", ""]
                for env, cell in cells.items()
            ],
        )
    )
    if row.get("releases"):
        out.append("## Releases\n")
        out.append(
            _table(
                ["Tag", "Published", "Running somewhere", "Pre-release"],
                [
                    [
                        _link(chip["tag"], chip.get("url")),
                        chip.get("published"),
                        chip.get("deployed"),
                        chip.get("prerelease"),
                    ]
                    for chip in row["releases"]
                ],
            )
        )
    updated = row.get("last_updated") or {}
    facts = [
        (
            "Last updated",
            f"{updated['date']} ({updated['source']}"
            + (f", {updated['tag']}" if updated.get("tag") else "")
            + ")"
            if updated.get("date")
            else "unknown",
        ),
        ("SmartAPI uptime", row.get("uptime")),
        ("Helm chart version", row.get("helm_version")),
        ("Helm images", row.get("helm_images")),
    ]
    out.append(
        "".join(f"- {name}: {_md(value)}\n" for name, value in facts if _md(value))
    )
    return "\n".join(out)


def components_index(
    ordered: list[tuple[ComponentFile, int, dict[str, Any]]],
) -> str:
    """`components/README.md`: every page, by stage. Static, so it exists even
    in a build with no sync."""
    out = [
        "# Component pages\n",
        (
            "One page per file in `components/`, in the dashboard's stage order. "
            "Each page is the file's contents down to a marker, then what the last "
            "sync found running.\n"
        ),
    ]
    current = None
    items: list[str] = []
    for component, step, stage in ordered:
        label = _stage_label(step, stage)
        if label != current:
            if items:
                out.append("".join(items))
                items = []
            out.append(f"## {label}\n")
            current = label
        items.append(f"- [{_md(component.name)}]({component.id}.md) `{component.id}`\n")
    if items:
        out.append("".join(items))
    return "\n".join(out)


# -- the whole tree -----------------------------------------------------------


def write_content(
    components: list[ComponentFile],
    payload: dict[str, Any] | None,
    private: dict[str, dict[str, Any]],
    out_dir: Path,
) -> list[Path]:
    """Write every generated file under `out_dir`, and say which.

    With no payload only the static files are written: the sheet CSV, the
    index, and each page down to its marker. Pages for components that no
    longer exist are removed, so a deleted file does not leave a page behind.
    """
    # Sorted here rather than trusted: the same tree from the same files,
    # whatever order they arrived in.
    components = sorted(components, key=lambda c: c.id.lower())
    out_dir.mkdir(parents=True, exist_ok=True)
    pages_dir = out_dir / "components"
    pages_dir.mkdir(exist_ok=True)
    written: list[Path] = []

    path = out_dir / "components.csv"
    write_components_csv(components, path)
    written.append(path)

    ordered = in_stage_order(components, load_stages())
    by_id = {c.id: c for c in components}
    used_by = _used_by(components)
    rows = {row["id"]: row for row in payload["rows"]} if payload else {}
    labels = (payload or {}).get("source_labels") or {}

    path = pages_dir / "README.md"
    path.write_text(components_index(ordered), encoding="utf-8")
    written.append(path)

    for component, step, stage in ordered:
        path = pages_dir / f"{component.id}.md"
        path.write_text(
            component_page(
                component,
                step,
                stage,
                by_id,
                used_by[component.id],
                private.get(component.id),
                rows.get(component.id),
                labels,
            ),
            encoding="utf-8",
        )
        written.append(path)
    for stale in pages_dir.glob("*.md"):
        if stale not in written:
            stale.unlink()

    if payload is not None:
        path = out_dir / "dashboard.md"
        path.write_text(dashboard_markdown(payload), encoding="utf-8")
        written.append(path)
        path = out_dir / "deployments.csv"
        write_deployments_csv(payload, path)
        written.append(path)
    return written


def static_half(text: str) -> str:
    """The part of a page a checkout alone determines."""
    return text.split(LIVE_MARKER, 1)[0]
