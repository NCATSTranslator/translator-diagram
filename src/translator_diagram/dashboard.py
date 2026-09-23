"""Turning the synced responses into one overview table.

This module is the top of the dashboard stack: it assembles the payload the
page reads, builds the graph views over the rows, and renders the HTML. It
never fetches and never reads the command line, so every decision it makes is
testable from a fixture directory.

The judgement lives below it, one subject per module: `synced_data` reads the
cache, `cells` resolves one cell, `rows` assembles one component's row, and
`stages` orders them. `privacy.apply` runs inside `build_payload` — after
`build_rows`, before the tallies — so a published build is the local build
minus rows rather than a different page.
"""

import base64
import dataclasses
import json
from collections import Counter
from importlib import resources
from pathlib import Path
from typing import Any

from .cells import SOURCE_LABELS
from .charts import unclaimed_charts
from .colors import load_owner_colors, owner_styles
from .components import ENVIRONMENTS, ComponentFile
from .privacy import UNCLAIMED_CHART_FREE_TEXT, Policy, Report, patterns_for, scrub
from .privacy import apply as apply_policy
from .rows import UPDATED_LABELS, build_rows
from .stages import load_stages, stage_blocks
from .synced_data import SyncedData

ASSET_PACKAGE = "translator_diagram.web"


# Order matters: earlier files define what later ones read. tokens.css holds
# every custom property, and core.js the namespace and the pure helpers.
CSS_FILES = (
    "tokens.css",
    "base.css",
    "controls.css",
    "table.css",
    "map.css",
    "drawer.css",
)


JS_FILES = (
    "core.js",
    "controls.js",
    "table.js",
    "layout.js",
    "map.js",
    "drawer.js",
    "app.js",
)  # app.js runs last


FAVICON_FILE = "favicon.ico"
"""The real NCATS icon, 1150 bytes, inlined as a data URI.

Not a `<link href="favicon.ico">`: the page is one file that has to open from
file://, out of a mail attachment, from anywhere — and a relative href there
asks for a second file that is not going to be beside it. A data URI is not an
external resource, which is why the self-containment test allows it and allows
nothing else.

Not in CSS_FILES or JS_FILES either: those two are the concatenation, and
`tests/test_web_assets.py` checks them against the `*.css` and `*.js` globs,
which an `.ico` is not in the way of.
"""


# --- Graph views over the rows ---------------------------------------------

def build_edges(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Every recorded connection between two kept rows, as the map draws it.

    `results` edges are reversed and `calls` edges are not, which looks
    inconsistent and is not: both keys are written from the caller's side, and
    an edge on a map points the way data moves. A gets results from B means
    the data leaves B and arrives at A; A calls B means the request leaves A.
    Drawing both as written would have half the arrows pointing upstream.

    Built after the privacy policy runs, from the rows it left behind, so an
    edge cannot name a withheld component: a target with no row is dropped
    rather than drawn to nothing. That also means a published build shows a
    genuinely smaller graph rather than the same graph with holes in it.

    An implemented and a planned edge between the same pair both survive. They
    are different claims — this is wired, and this is meant to be — and the map
    draws them differently.
    """
    canonical = {row["id"].lower(): row["id"] for row in rows}
    edges: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, bool]] = set()

    def add(source: str, target: str, kind: str, planned: bool) -> None:
        key = (source, target, kind, planned)
        if key in seen:
            return
        seen.add(key)
        edges.append(
            {"from": source, "to": target, "kind": kind, "planned": planned}
        )

    for row in rows:
        cid = row["id"]
        connections = row.get("connections") or {}
        for key, kind, planned in (
            ("gets_results_from", "results", False),
            ("planned_gets_results_from", "results", True),
            ("calls", "calls", False),
            ("planned_calls", "calls", True),
        ):
            for ref in connections.get(key) or []:
                # References resolve case-insensitively, the same way they do
                # everywhere else in this repo, and the edge carries the id as
                # the component file spells it.
                other = canonical.get(str(ref).lower())
                if other is None:
                    continue
                if kind == "results":
                    add(other, cid, kind, planned)
                else:
                    add(cid, other, kind, planned)
        for external in row.get("externals") or []:
            name = external.get("name")
            if not name:
                continue
            if external.get("direction") == "in":
                add(name, cid, "external_in", False)
            else:
                add(cid, name, "external_out", False)
    return edges


def build_externals(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The things outside the platform that kept rows name, first seen first.

    An external is a name somebody typed, not an id, so two components naming
    the same source are the same node on the map only because the strings
    match. First-seen order rather than sorted: it follows the rows, which
    follow the stages, so the sources appear in the order a reader meets them.
    """
    found: dict[tuple[str, str], dict[str, str]] = {}
    for row in rows:
        for external in row.get("externals") or []:
            name, direction = external.get("name"), external.get("direction")
            if not name:
                continue
            found.setdefault(
                (name, direction), {"name": name, "direction": direction}
            )
    return list(found.values())


def build_catalog_edges(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The dataflow the infores catalog records, between components we show.

    A second opinion on the graph, and deliberately a separate list from
    `edges`: this one is knowledge flowing between resources, ours is API calls
    between services, and merging them would let the catalog's opinion arrive
    on the page as something this repository recorded. The map draws them
    differently and can switch them off.

    Direction follows the data, the same way a `results` edge does: X in this
    row's `consumes` means the data leaves X and arrives here. `consumed_by` is
    the same statement from the other end and gives the mirror, which is why
    the pair is deduped — the catalog records most of these twice.

    Both ends must resolve to a kept row, so an infores naming a data source
    with no component here is dropped rather than drawn to nothing, and a
    withheld component cannot appear: it has no row to resolve to.
    """
    by_infores = {
        row["infores"]: row["id"] for row in rows if row.get("infores")
    }
    edges: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    def add(source: str, target: str) -> None:
        # A resource that consumes itself is a statement about a knowledge
        # source, not an edge a map can draw.
        if source == target or (source, target) in seen:
            return
        seen.add((source, target))
        edges.append({"from": source, "to": target, "kind": "catalog"})

    for row in rows:
        catalog = row.get("catalog")
        if not isinstance(catalog, dict):
            continue
        for infores in catalog.get("consumes") or []:
            if (other := by_infores.get(infores)) is not None:
                add(other, row["id"])
        for infores in catalog.get("consumed_by") or []:
            if (other := by_infores.get(infores)) is not None:
                add(row["id"], other)
    return edges


def build_unclaimed_charts(
    components: list[ComponentFile], synced: SyncedData
) -> list[dict[str, Any]]:
    """The charts in translator-devops that no component file accounts for.

    Run over *every* component rather than the kept rows, and that is a privacy
    decision as much as a correctness one: a chart claimed by a withheld
    component is claimed, and matching against the kept rows only would list
    `jaeger` here by name on the published page — the one build that must not
    say it. Nothing else in the entry names a component, so no further pass is
    needed.

    Sorted by name, because this is a list somebody reads down looking for
    something they recognise rather than a list in any meaningful order.
    """
    names = synced.chart_index()
    unclaimed = []
    for name in unclaimed_charts(
        names, {name: synced.chart_meta(name) for name in names}, components
    ):
        meta = synced.chart_meta(name).get("chart") or {}
        description = meta.get("description")
        unclaimed.append(
            {
                "name": name,
                # Usually `helm create`'s unedited default; still the only
                # sentence about the chart that exists.
                "description": (
                    description.strip() or None
                    if isinstance(description, str)
                    else None
                ),
            }
        )
    return unclaimed


def build_smartapi_suggestions(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Registry records we attached by infores, as pointers to record by hand.

    The data PR this asks for is one line in a component file — the record's
    id under `identifiers.smartapi` — after which the match is somebody's
    decision rather than ours and stops depending on the registry keeping its
    infores in step. Built from the kept rows, so a suggestion cannot name a
    withheld component.
    """
    suggestions = []
    for row in rows:
        record = row.get("smartapi_record")
        if not isinstance(record, dict) or record.get("matched_by") != "infores":
            continue
        suggestions.append(
            {
                "component": row["id"],
                "smartapi_id": record.get("id"),
                "title": record.get("title"),
            }
        )
    return suggestions


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


# --- The payload -----------------------------------------------------------

def build_payload(
    components: list[ComponentFile],
    synced: SyncedData,
    policy: Policy | None = None,
) -> dict[str, Any]:
    """Everything the page needs, with `policy` withheld from it.

    The policy is applied here, between building the rows and counting them,
    and the position is the whole design. `source_tally` and
    `unregistered_count` below are computed *from* `rows`, so a withheld row
    leaves the table and the tiles together — the page cannot end up reporting
    more components than it shows, which it has done before.

    Just as deliberate: `build_rows` sees every component, so `flow_depths` and
    `isolated` run over the full platform. A published build is the local build
    minus rows — same order, same depths, same left bars. Filtering the
    components *before* that would let a withheld component change where
    everyone else sits, and the two builds would disagree about the shape of
    the platform rather than about how much of it is shown.

    The same position does one more job. `stages`, `edges`, `externals`,
    `catalog_edges` and `smartapi_suggestions` are built *below* the policy, out
    of the rows it left behind, so none of them can name a component that was
    withheld — a band cannot roster a row that is gone, and an edge to a missing
    row is dropped. That is why `privacy.apply` does not walk them: there is
    nothing in them to walk that did not come from a kept row.

    `unclaimed_charts` is the exception and reads the full component list on
    purpose: "no component claims this chart" is only true if the withheld ones
    do not either, and asking the kept rows would publish the withheld
    components' charts under their own names.
    """
    stages = load_stages()
    rows = build_rows(components, synced, stages=stages)
    report = Report()
    unclaimed = build_unclaimed_charts(components, synced)
    if policy is not None:
        rows, report = apply_policy(rows, policy)
        report = dataclasses.replace(
            report,
            mentions=report.mentions
            + scrub(unclaimed, UNCLAIMED_CHART_FREE_TEXT, patterns_for(policy)),
        )
    manifest = synced.manifest
    colors = load_owner_colors()
    return {
        "generated_at": manifest.get("finished_at") or "",
        "synced_at": manifest.get("finished_at") or "",
        "sync_counts": manifest.get("counts") or {},
        "environments": list(ENVIRONMENTS),
        "owner_colors": colors,
        # The same colours with everything derived from them worked out once:
        # the text colour that reads on each, and the four gradient stops the
        # metal is drawn with. Two renderers deriving the same gradient
        # separately is how a page and a legend come to disagree about a team.
        "owner_styles": owner_styles(colors),
        "source_labels": SOURCE_LABELS,
        "updated_labels": UPDATED_LABELS,
        "source_tally": source_tally(rows),
        "unregistered_count": sum(
            1
            for row in rows
            for cell in row["environments"].values()
            if cell.get("unregistered")
        ),
        "otel_service_counts": {
            env: len(names) for env, names in synced.otel.items()
        },
        # Distinct across the three collectors, not their sum: only two names
        # report to all three, so summing counts most services twice over.
        "otel_service_total": len(
            {name for names in synced.otel.values() for name in names}
        ),
        # Absent when nothing was withheld, so the page says nothing rather
        # than announcing an empty redaction on a full build.
        **({"redacted": report.for_payload()} if report else {}),
        # All three read the kept rows, and are therefore withheld-free by
        # construction rather than by a second filter that could fall behind.
        "stages": stage_blocks(stages, rows),
        "edges": build_edges(rows),
        "externals": build_externals(rows),
        "catalog_edges": build_catalog_edges(rows),
        # The one list here built from every component rather than the kept
        # rows, and it has to be: a chart is unclaimed only if *nobody* claims
        # it, and a withheld component still claims its chart. See
        # `build_unclaimed_charts`.
        "unclaimed_charts": unclaimed,
        "smartapi_suggestions": build_smartapi_suggestions(rows),
        "rows": rows,
    }


# --- The page --------------------------------------------------------------

def _assets(names: tuple[str, ...]) -> str:
    """The named files from web/, concatenated in the order given.

    The order is these tuples, not the directory: a tokens sheet defines the
    custom properties the others read, and the boot script must come last.

    Concatenated into one block rather than loaded as modules, because the page
    must open from file:// and `import` there needs a server. So every file
    shares one top-level scope -- a `const` declared twice is a SyntaxError
    that `node --check` on each file separately cannot see, which is why
    tests/test_web_assets.py also checks the concatenation.
    """
    return "\n".join(
        (resources.files(ASSET_PACKAGE) / name).read_text(encoding="utf-8")
        for name in names
    )


def _favicon_data_uri() -> str:
    """The packaged icon as a data URI, read through `resources.files`.

    The same reader the CSS and the JS go through, so an installed wheel with
    no checkout to look at finds it in the package the way it finds everything
    else in web/.
    """
    raw = (resources.files(ASSET_PACKAGE) / FAVICON_FILE).read_bytes()
    return "data:image/x-icon;base64," + base64.b64encode(raw).decode("ascii")


def render_html(payload: dict[str, Any]) -> str:
    """One self-contained page.

    The data is inlined rather than fetched so the file works from file:// —
    it can be emailed, or opened from a checkout, with no server. The same
    payload is written beside it as overview.json, which is the contract a
    scheduled job would publish; keeping both means the page never has to
    choose between being shareable and being automatable.
    """
    data = json.dumps(payload, indent=None, separators=(",", ":"))
    # </script> inside a JSON string would close the tag early.
    data = data.replace("</", "<\\/")
    return f"""<!doctype html>
<html lang="en">
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<!-- Reachable, but not indexed. Someone given the link gets the page; a search
     for a hostname on it does not. The privacy policy decides what the page
     contains, this decides who arrives at it without asking, and the two are
     worth keeping separate: this line is one edit to undo when the public
     /private split in issue #7 is settled. -->
<meta name="robots" content="noindex, nofollow">
<title>Translator components overview</title>
<link rel="icon" type="image/x-icon" href="{_favicon_data_uri()}">
<style>
{_assets(CSS_FILES)}
</style>
<script>
// Applied before the body renders, or the page flashes the wrong theme.
(() => {{
  // "auto" — follow the operating system — is the default, and the only way
  // out of it is someone clicking the theme button on this page.
  let choice = "auto";
  try {{
    const stored = localStorage.getItem("theme");
    if (stored === "light" || stored === "dark" || stored === "auto") choice = stored;
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
{_assets(JS_FILES)}
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
