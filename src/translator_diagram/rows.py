"""One row per component: its cells, plus everything the drawer reads.

`build_rows` is the assembler. It merges the deployments, calls `build_cell`
per environment, then decorates the row with the dates, releases, charts and
OpenTelemetry findings the page shows.

Drift is marked here rather than in `build_cell` because it is a comparison
*between* an environment and its neighbours, which a single cell cannot see.
"""

from collections import Counter
from datetime import UTC, datetime
from typing import Any

from .cells import _helm_facts, _openapi_facts, build_cell
from .components import ENVIRONMENTS, ComponentFile, github_repo
from .deployments import (
    deployments_from_smartapi,
    merge_deployments,
    smartapi_record_for,
)
from .flow import flow_depths, isolated
from .payload_details import (
    catalog_detail,
    helm_detail,
    releases_detail,
    repo_meta_detail,
    same_version,
    smartapi_detail,
)
from .stages import in_stage_order, load_stages
from .synced_data import SyncedData

# How many of a repository's newest releases the Repository column shows before
# it starts adding the ones an environment is actually running. Three fits the
# column at the width the table is read at; the deployed extras are what make
# the list answer "where are the notes for the version in front of me?".
RELEASES_SHOWN = 3


# Where a "last updated" date came from. A separate vocabulary from
# SOURCE_LABELS on purpose: that one says where a version number came from,
# this one says where a date did, and conflating them would put "OpenAPI" and
# "release" in the same badge row meaning different kinds of thing.
UPDATED_LABELS = {"release": "release", "registry": "registry"}


# --- Dates, and the release a cell is running ------------------------------

def _instant(value: Any) -> datetime | None:
    """One ISO timestamp as a comparable instant, or None.

    Comparing the strings instead would be wrong in a way that shows up only
    on close dates: GitHub writes `2026-08-01T09:00:00Z` and SmartAPI writes
    `2026-08-01T09:00:00.5+00:00`, and `"Z" > "+"`, so a string sort hands
    every tie to GitHub. A naive stamp is read as UTC — comparing naive with
    aware raises, and it would raise inside the row loop, taking the whole
    table with it.
    """
    if not isinstance(value, str):
        return None
    try:
        # 3.11's fromisoformat takes the trailing Z that GitHub writes.
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _last_updated(
    entries: list[dict[str, Any]], record: dict[str, Any]
) -> dict[str, Any] | None:
    """The most recent date we can honestly claim for a component.

    The newest of the two signals rather than the best of them: the question
    is when anything about this component last changed, and a release and a
    registration are answers to different halves of it. A tie goes to the
    release, because a tag is a claim about the software and a registry stamp
    is a claim about a document.

    Reads the raw release entries rather than the chips, which are pruned to
    the few worth showing and truncated to the day. Returns None where there
    is no signal at all, which is the honest answer for 13 of 26 components:
    they publish no releases and are in no registry.
    """
    candidates = []
    for entry in entries:
        tag = entry.get("tag_name")
        moment = _instant(entry.get("published_at"))
        if tag and moment and not entry.get("draft"):
            candidates.append((moment, "release", tag))
    registered = _instant((record.get("_meta") or {}).get("last_updated"))
    if registered:
        candidates.append((registered, "registry", None))
    if not candidates:
        return None
    moment, source, tag = max(candidates, key=lambda c: c[0])
    return {
        "at": moment.isoformat(),
        "date": moment.date().isoformat(),
        "source": source,
        "tag": tag,
    }


def _mark_running_release(
    cells: dict[str, dict[str, Any]], chips: list[dict[str, Any]]
) -> None:
    """Date each environment by the release it is running, where one matches.

    The other half of the Repository column: `_release_chips` keeps an older
    release precisely because some environment is still on it, so the same
    fact read from the cell's side says how old what is running here is. Ten
    of twenty running versions match no release — a cell with no match simply
    has no `released` key, rather than a null that would sort as a date.
    """
    for cell in cells.values():
        version = cell.get("version")
        if not cell.get("deployed") or not version:
            continue
        for chip in chips:
            if same_version(chip["tag"], version):
                cell["released"] = chip["published"]
                cell["release_tag"] = chip["tag"]
                cell["release_url"] = chip["url"]
                break


def _release_chips(detail: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The releases the Repository column shows, out of `releases_detail`.

    The newest few, plus any older release that some environment is running:
    prod lags dev often enough that the newest three would miss the version the
    reader is looking at, which is the one whose notes they want. The detail
    list has already sorted by publication date, dropped drafts and marked what
    is running, so this only cuts it shorter.
    """
    return [
        {
            "tag": entry["tag"],
            "name": entry["name"] or entry["tag"],
            "url": entry["url"],
            "published": entry["published"] or "",
            "prerelease": bool(entry["prerelease"]),
            "deployed": entry["deployed"],
        }
        for index, entry in enumerate(detail)
        if index < RELEASES_SHOWN or entry["deployed"]
    ]


# --- Comparisons between an environment and its neighbours -----------------

def _mark_drift(cells: dict[str, dict[str, Any]], key: str) -> None:
    """Flag the environments whose value is in the minority.

    Borrowed from babel-validation's dashboard, where it answers the same
    shape of question. Only a genuine split is marked: when every environment
    agrees, or only one reports at all, nothing is tinted — colouring every
    row would teach the reader to ignore the colour.

    A tie has no minority in it, so every reporting environment is marked
    rather than one arbitrary side. `Counter.most_common` breaks a tie by
    insertion order, which is the column order — so a two-against-two split
    used to tint whichever pair happened to sit further right, and a
    one-against-one split made the later environment the deviant. Marking the
    whole row says what is true: these environments disagree, and none of them
    is the odd one out.
    """
    values = [
        cell.get(key) for cell in cells.values() if cell.get("deployed") and cell.get(key)
    ]
    if len(values) < 2 or len(set(values)) < 2:
        return
    ranked = Counter(values).most_common()
    majority = ranked[0][0] if ranked[0][1] > ranked[1][1] else None
    for cell in cells.values():
        if cell.get("deployed") and cell.get(key) and cell[key] != majority:
            cell.setdefault("drift", []).append(key)


def otel_presence(
    names: list[str], by_env: dict[str, list[str]]
) -> list[dict[str, Any]]:
    """Which collectors have seen each of a component's recorded service names.

    One entry per *recorded* name, including the names nothing has reported —
    an empty `seen_in` is the finding this exists for. A name that appears in
    no collector is either a service that has stopped tracing or a name written
    down wrong, and both are worth seeing; dropping it would leave the page
    showing only the names that need no attention.

    The match is case-sensitive, and that is a decision rather than an
    oversight. shepherd-arax records the service `arax`; what prod reports is
    `ARAX`, which is the separate `arax` component. Folding case joins those
    two, and the page then says the ARAX worker is tracing when it is its
    neighbour that is. Collector names are chosen by whoever configured the
    exporter, so they are identifiers, not prose.
    """
    return [
        {
            "service": name,
            "seen_in": [
                env
                for env in ENVIRONMENTS
                if name in (by_env.get(env) or [])
            ],
        }
        for name in names
    ]


def _helm_blocks(
    component: ComponentFile, charts: list[str], synced: SyncedData
) -> list[dict[str, Any]]:
    """One block per chart the component records, each dated by its last commit.

    `last_changed` is on the chart rather than on the row because it is a fact
    about the chart: when the directory in translator-devops last changed. It
    says nothing about when a deployment happened — a chart edited and never
    rolled out carries a date anyway — so it travels with the block that is
    already labelled "what should be running" and never joins `last_updated`.
    """
    blocks = []
    for chart in charts:
        detail = helm_detail(
            chart,
            synced.helm(chart, "Chart.yaml") or {},
            synced.helm(chart, "values.yaml") or {},
            component.repository("helm-chart"),
        )
        if detail is None:
            continue
        detail["last_changed"] = synced.chart_commit(chart)
        blocks.append(detail)
    return blocks


def _repo_document(synced: SyncedData, repo: str | None) -> dict[str, Any] | None:
    """The cached GitHub document for an `owner/name` slug, or nothing."""
    if not repo:
        return None
    owner, _, name = repo.partition("/")
    return synced.repo_meta(owner, name)


# --- The assembler ---------------------------------------------------------

def build_rows(
    components: list[ComponentFile],
    synced: SyncedData,
    *,
    stages: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """One dictionary per component, in the stage order the config file sets.

    `stages` is a keyword argument with a default so the loader runs once per
    build rather than once per call: `dashboard.build_payload` reads the file
    and hands the same list to `stage_blocks` afterwards, and the two must be
    the same list or the step numbers on the rows and the step numbers on the
    bands could be computed from different files.
    """
    depths = flow_depths(components)
    stranded = set(isolated(components))
    rows = []
    for component, step, stage in in_stage_order(
        components, load_stages() if stages is None else stages
    ):
        # Two ways a component reaches its registry entry, and the row has to
        # carry which one it was: an id somebody recorded, or the one record
        # claiming this component's infores. Everything below reads `record`
        # without caring — the deployments it declares, the version the chain
        # falls back to, the uptime — because a record matched by infores is
        # the same document, found by a different pointer.
        hit, matched_by, candidates = smartapi_record_for(
            component, list(synced.smartapi.values())
        )
        # Copied rather than annotated in place: `synced.smartapi` is shared by
        # every row and by the next build from the same cache, and stamping how
        # *this* component found a record onto the registry's own dictionary is
        # how two components come to disagree about one document.
        record = dict(hit) if hit else {}
        if matched_by:
            record["_matched_by"] = matched_by
        derived = synced.derived.get(component.id, {})
        deployments = merge_deployments(
            component, deployments_from_smartapi(record), derived
        )
        charts = component.helm_charts
        helm = _helm_facts(synced, charts)

        cells = {
            env: build_cell(
                component, env, deployments.get(env), synced, record, helm
            )
            for env in ENVIRONMENTS
        }
        # A gap in a registration that exists at all: this component is in
        # SmartAPI, and this environment is not in its record. Computed from
        # the registry rather than from how the URL was found, so it stays true
        # once a discovered URL is written into the component file — which is
        # exactly what happened to answer-appraiser's ci and test.
        # Only where the *file* records an id: "this environment is missing
        # from the registration" is a claim about a registration somebody
        # filed, and a record we attached ourselves by infores is not that. A
        # match we made cannot be the evidence for a gap we then report.
        registered = set(deployments_from_smartapi(record))
        for env, cell in cells.items():
            if (
                cell.get("deployed")
                and component.smartapi_id
                and registered
                and env not in registered
            ):
                cell["unregistered"] = True
        for key in ("version", "trapi", "biolink"):
            _mark_drift(cells, key)

        source_repo = github_repo(component.repository("source"))
        releases = synced.releases(source_repo)
        detail = releases_detail(
            releases,
            {version for cell in cells.values() if (version := cell.get("version"))},
        )
        chips = _release_chips(detail)
        _mark_running_release(cells, chips)

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
                "releases": chips,
                "last_updated": _last_updated(releases, record),
                "step": step,
                "step_label": (
                    stage.get("title") or ""
                    if stage.get("unplaced")
                    else f"Step {step}"
                ),
                "step_title": stage.get("title") or "",
                "step_description": stage.get("description") or "",
                "documentation": (component.documentation or [{}])[0].get("url"),
                # On the row, not in the cells: SmartAPI records one uptime
                # result per *record*, from its own probe of whichever server it
                # picked. Copying it into four columns would show four
                # measurements where there is one.
                "uptime": uptime,
                "helm_version": helm.get("version"),
                "helm_images": helm.get("images") or [],
                "notes": component.notes,
                "externals": [
                    {"direction": d, "name": n} for d, n in component.externals
                ],
                # What the component file records about itself, as it records
                # it. `type` above is the same question answered with a registry
                # fallback; this one is the file's own claim and nothing else,
                # so a reader can tell "nobody wrote this down" from "the
                # registry says KP".
                "component_type": component.component_type,
                "hosted_at": component.hosted_at,
                "part_of": component.part_of,
                "itrb": {"app": component.itrb_app, "group": component.itrb_group},
                # Every chart the file records. `helm_chart` above is the first
                # of them, and `helm_charts` below is the detail block per chart.
                "chart_names": charts,
                "translator_all_wiki": component.translator_all_wiki,
                "repositories": [
                    {
                        "url": repo.get("url"),
                        "role": repo.get("role"),
                        "visibility": repo.get("visibility"),
                    }
                    for repo in component.repositories
                ],
                # The whole list. `documentation` above is the first URL and
                # stays a string: it is a payload key with consumers, and a
                # string that becomes a list is the rename this contract forbids.
                "docs": [
                    {"url": doc.get("url"), "kind": doc.get("kind")}
                    for doc in component.documentation
                ],
                "endpoints": dict(component.endpoints),
                "diagram": {
                    "ubiquitous": component.ubiquitous,
                    "hide": component.hidden,
                },
                "connections": component.connection_ids(),
                "smartapi_record": smartapi_detail(record),
                # The records that share this component's infores where more
                # than one does. None of them is used — see
                # `smartapi_record_for` — and listing them is what lets a
                # reader settle it instead of the build guessing.
                "smartapi_candidates": candidates,
                "helm_charts": _helm_blocks(component, charts, synced),
                # Three answers, never a blank: this chart is recorded, or
                # translator-devops has no chart for a component ITRB deploys,
                # or this component is not deployed from translator-devops at
                # all. The third is not a gap in our data — it is where the
                # component runs.
                "helm_status": (
                    "recorded"
                    if charts
                    else "not-devops-hosted"
                    if component.hosted_at not in (None, "ITRB")
                    else "none-in-devops"
                ),
                "releases_detail": detail,
                # The source repository's own description, branch and activity.
                # `pushed_at` in it is deliberately not fed into `last_updated`:
                # a push is not a release, and ranking it beside one would date
                # a component by somebody editing its README.
                "repository_meta": repo_meta_detail(
                    _repo_document(synced, source_repo)
                ),
                # What the platform's own registry says this thing *is*, as
                # opposed to what it is doing: status, knowledge level, agent
                # type, and who consumes it.
                "catalog": catalog_detail(
                    synced.catalog().get(component.infores or "")
                ),
                "otel_presence": otel_presence(component.otel_services, synced.otel),
                # Probed and not confirmed, which is not "down": the convention
                # said a host would be here and what answered was not this
                # component. In ladder order, so the list reads dev to prod like
                # every other row of environments on the page.
                "derived_rejected": [
                    {"env": env, "url": spec["url"]}
                    for env in ENVIRONMENTS
                    if (spec := synced.rejected.get(component.id, {}).get(env))
                ],
                "environments": cells,
            }
        )
    return rows
