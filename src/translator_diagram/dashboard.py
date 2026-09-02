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

import base64
import json
from collections import Counter
from datetime import UTC, datetime
from importlib import resources
from pathlib import Path
from typing import Any

import click
import yaml

from .colors import load_owner_colors, owner_styles, text_color_for
from .components import (
    CHART_META_FILES,
    ENVIRONMENTS,
    ComponentFile,
    Deployment,
    chart_matches,
    deployments_from_smartapi,
    endpoint_url_in,
    github_repo,
    merge_deployments,
    smartapi_record_for,
)
from .flow import flow_depths, in_flow_order, isolated
from .payload_details import (
    catalog_detail,
    helm_detail,
    releases_detail,
    repo_meta_detail,
    smartapi_detail,
)
from .privacy import Policy, Report
from .privacy import apply as apply_policy

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

# How many of a repository's newest releases the Repository column shows before
# it starts adding the ones an environment is actually running. Three fits the
# column at the width the table is read at; the deployed extras are what make
# the list answer "where are the notes for the version in front of me?".
RELEASES_SHOWN = 3

# `*_version` keys in a /status body that name something other than the
# software's own version. Babel and Biolink are *data* releases and TRAPI is a
# spec, and a body is free to report any of them before it reports its own
# version — at which point the first `*_version` key would become the
# component's version, badged `status`, tinted for drift against its
# neighbours, and matched against the repository's releases.
NOT_SOFTWARE_VERSIONS = frozenset(
    {"babel_version", "biolink_version", "biolink_model_version", "trapi_version"}
)

# Where a "last updated" date came from. A separate vocabulary from
# SOURCE_LABELS on purpose: that one says where a version number came from,
# this one says where a date did, and conflating them would put "OpenAPI" and
# "release" in the same badge row meaning different kinds of thing.
UPDATED_LABELS = {"release": "release", "registry": "registry"}


CONFIG_STAGES_PATH = Path("config/flow-steps.yaml")

UNPLACED_TITLE = "Not yet placed"


def _find_stages() -> Path | None:
    """config/flow-steps.yaml in the working directory or the nearest parent."""
    cwd = Path.cwd()
    for directory in (cwd, *cwd.parents):
        candidate = directory / CONFIG_STAGES_PATH
        if candidate.exists():
            return candidate
    return None


def load_stages(path: Path | None = None) -> list[dict[str, Any]]:
    """The platform's stages, in the order the page shows them.

    This file is the row order, not a set of labels on a computed one. The
    recorded `gets_results_from` / `calls` edges are too sparse to order 26
    components — nothing records the UI calling Name Lookup, so Name Lookup
    sorted near the sources, and nothing records the ARS calling Answer
    Appraiser, so Answer Appraiser sorted above everything. A hand-written
    order is more honest than a plausible-looking one derived from data that
    is missing.

    The trailing entry is the components no stage claims, named in the file's
    `unplaced` block so a new component cannot quietly sort last.

    With no path, the file is looked for in the working directory and every
    directory above it — the same walk `load_owner_colors` and `load_policy`
    do, so building from a subdirectory of the checkout behaves the same way.
    A missing file is an error rather than an empty list: `in_stage_order`
    falls back to data-flow order, which is the ordering this file exists to
    replace, so degrading quietly would publish the wrong page and say
    nothing. An empty file is still allowed — that one is somebody's decision.
    """
    found = path if path is not None else _find_stages()
    if found is None:
        raise click.ClickException(
            f"No stage file at {CONFIG_STAGES_PATH}. It sets the row order, "
            f"and without it the page falls back to data-flow order. Run from "
            f"the repository root."
        )
    if not found.exists():
        raise click.ClickException(f"Stage file not found: {found}")
    loaded = _read_yaml(found)
    if not loaded:
        return []
    stages = [
        {
            "title": stage.get("title") or "",
            "description": stage.get("description") or "",
            "components": list(stage.get("components") or []),
        }
        for stage in (loaded.get("stages") or [])
    ]
    unplaced = loaded.get("unplaced") or {}
    stages.append(
        {
            "title": UNPLACED_TITLE,
            "description": unplaced.get("description") or "",
            "components": list(unplaced.get("components") or []),
            "unplaced": True,
        }
    )
    return stages


def in_stage_order(
    components: list[ComponentFile], stages: list[dict[str, Any]]
) -> list[tuple[ComponentFile, int, dict[str, Any]]]:
    """Each component with the stage it belongs to and that stage's number.

    Components are shown in the order their stage lists them: within a stage
    that order is a judgement too, and alphabetising it would throw the
    judgement away. Anything no stage names falls to the end in data-flow
    order, which is the best guess available for something nobody has placed.
    """
    if not stages:
        return [(component, 1, {}) for component in in_flow_order(components)]
    by_id = {component.id.lower(): component for component in components}
    ordered: list[tuple[ComponentFile, int, dict[str, Any]]] = []
    seen: set[str] = set()
    for number, stage in enumerate(stages, 1):
        for cid in stage["components"]:
            component = by_id.get(cid.lower())
            if component and component.id not in seen:
                seen.add(component.id)
                ordered.append((component, number, stage))
    trailing = stages[-1]
    for component in in_flow_order(components):
        if component.id not in seen:
            ordered.append((component, len(stages), trailing))
    return ordered


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        # A body saved from a 200 that was not actually JSON. Real: several
        # Translator endpoints answer 200 with an HTML error page.
        return None


def _read_json_list(path: Path) -> list[Any]:
    """A JSON array, or an empty list for anything else.

    GitHub answers a rate-limited request with a 200-shaped *object* carrying a
    message, and `sync` saves whatever came back, so the shape has to be
    checked rather than assumed.
    """
    loaded = _read_json(path)
    return loaded if isinstance(loaded, list) else []


def _read_yaml(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError:
        return None
    return loaded if isinstance(loaded, dict) else None


def _service_names(document: dict[str, Any] | None) -> list[str]:
    """The service names one OpenTelemetry collector reported.

    Strings only, and a list only. The tile that counts these is a footnote,
    and a collector that answers with a `data` array of objects — or with no
    array at all — must cost that tile its number rather than take the whole
    build down on an unhashable name.
    """
    data = (document or {}).get("data")
    if not isinstance(data, list):
        return []
    return [name for name in data if isinstance(name, str)]


class SyncedData:
    """Everything `sync` wrote, read back."""

    def __init__(self, root: Path):
        self.root = root
        self.manifest = _read_json(root / "manifest.json") or {}
        payload = _read_json(root / "smartapi.json") or {}
        self.smartapi = {
            hit["_id"]: hit for hit in payload.get("hits", []) if hit.get("_id")
        }
        # One read, two answers. `sync` writes both halves of the same probe
        # into this file, and reading it twice would let a rebuild pick up a
        # confirmation from one moment and a rejection from another.
        probes = _read_json(root / "derived.json") or {}
        self.derived = {
            cid: {
                env: Deployment(env=env, url=spec["url"], location=spec.get("location"))
                for env, spec in envs.items()
            }
            for cid, envs in (probes.get("confirmed") or {}).items()
        }
        # The other half: hosts the convention predicted and the probe did not
        # confirm. "We looked here and this is not it" — never "this is down",
        # which is a claim about a deployment we have no evidence exists.
        self.rejected = {
            cid: {
                env: spec["url"]
                for env, spec in envs.items()
                if isinstance(spec, dict) and spec.get("url")
            }
            for cid, envs in (probes.get("rejected") or {}).items()
        }
        # The same rejections with the verdict attached — how the candidate was
        # turned away, which is what tells "there is no such host" from "there
        # is one and it is not this component". Kept beside `rejected` rather
        # than replacing it: that one is a URL map with a payload key built
        # from it, and widening it would change what `derived_rejected` holds.
        self.rejected_detail = {
            cid: {
                env: spec
                for env, spec in envs.items()
                if isinstance(spec, dict) and spec.get("url")
            }
            for cid, envs in (probes.get("rejected") or {}).items()
        }
        # Per instance, because the same values.yaml is now read for two
        # different questions and shepherd's is 623 lines of it.
        self._charts: dict[tuple[str, str], dict[str, Any] | None] = {}
        # The same three lazily: a chart commit is read once per chart even
        # though three shepherd components ask for it, the infores catalog is
        # 500 entries of YAML that only has to be parsed if a row has an
        # infores, and a repository description is shared the same way a
        # release list is.
        self._commits: dict[str, dict[str, Any] | None] = {}
        self._repos: dict[str, dict[str, Any] | None] = {}
        self._catalog: dict[str, dict[str, Any]] | None = None
        self.otel = {
            env: _service_names(_read_json(root / "otel" / f"{env}.json"))
            for env in ("ci", "test", "prod")
        }
        self.statuses = {
            fetch["path"]: fetch for fetch in self.manifest.get("fetches", [])
        }

    def openapi(self, component_id: str, env: str) -> dict[str, Any] | None:
        return self._endpoint_body("openapi", component_id, env)

    def status(self, component_id: str, env: str) -> dict[str, Any] | None:
        return self._endpoint_body("status", component_id, env)

    def root_probe(self, component_id: str, env: str) -> dict[str, Any] | None:
        """How the deployment's own URL answered this run, or None.

        `{"status", "content_type", "error"}` — what `sync.probe_to` saved,
        which is a summary rather than the page itself. Gated the way the
        endpoint bodies are: a summary is only read when this run's manifest
        has an entry for it, so a host that has since been taken out of the
        component file does not keep answering from an old file.

        The gate is "was it probed", not "did it answer 200", and that is the
        difference from `_endpoint_body`. There the question is whether a
        document can be believed, and only a 200 makes one believable. Here a
        404 *is* the answer — the host is up and has nothing at `/` — and
        dropping it would leave the page unable to tell that from silence.

        Not named `root`: this class already has one, the sync directory
        itself, and a method shadowing it would be a bug that reads as a name.
        """
        relative = f"root/{component_id}/{env}.json"
        if relative not in self.statuses:
            return None
        probe = _read_json(self.root / relative)
        return probe if isinstance(probe, dict) else None

    def openapi_outcome(self, component_id: str, env: str) -> str | None:
        """What this run's OpenAPI fetch actually got back, as a word.

        `openapi()` answers with a document or None, and None is three
        different things: nothing was fetched, something was fetched and was
        not JSON, or the fetch failed. The middle one is real — BioThings'
        pending API answers every path with the single-page app's HTML and a
        200, so `fetch_to` saves a page of markup that `_read_json` then
        refuses — and reported as None it is indistinguishable from never
        having asked.

        So: None where this run fetched nothing at that path, `"not-json"`
        where a 200 was not a document, `"no-version"` where it was a document
        with no `info.version`, and `"version"` where there is one to show.
        """
        relative = f"openapi/{component_id}/{env}.json"
        fetch = self.statuses.get(relative)
        if not fetch or fetch.get("status") != 200 or fetch.get("error"):
            return None
        path = self.root / relative
        if not path.exists():
            return None
        document = _read_json(path)
        if not isinstance(document, dict):
            return "not-json"
        info = document.get("info")
        version = info.get("version") if isinstance(info, dict) else None
        return "version" if version else "no-version"

    def _endpoint_body(
        self, kind: str, component_id: str, env: str
    ) -> dict[str, Any] | None:
        """One endpoint's body, but only if this run's fetch of it succeeded.

        `sync` writes a body on a 200 and leaves the previous one in place
        otherwise, so a file on disk is not by itself evidence that the
        endpoint answered. Without this a deployment that has gone away keeps
        reporting the version it last served, and the cell says `reachable`
        next to its own `http_status` of 404 — the one contradiction this page
        must never print, because "was this endpoint up at 14:05" is the
        question it exists to answer.

        Only the endpoints are gated this way. A release list or a Helm chart
        makes no claim about what is running right now, so dropping a cached
        one when GitHub rate-limits a run would lose real information and say
        nothing new in its place.
        """
        relative = f"{kind}/{component_id}/{env}.json"
        fetch = self.statuses.get(relative)
        if fetch and not (fetch.get("status") == 200 and not fetch.get("error")):
            return None
        return _read_json(self.root / relative)

    def releases(self, repo: str | None) -> list[dict[str, Any]]:
        """One repository's releases, newest first, as GitHub returned them."""
        if not repo:
            return []
        return [
            entry
            for entry in _read_json_list(self.root / "releases" / f"{repo}.json")
            if isinstance(entry, dict)
        ]

    def helm(self, chart: str, name: str) -> dict[str, Any] | None:
        """One file out of one cached chart, parsed once per build.

        The same document now answers two questions — the version chain asks
        `Chart.yaml` for an appVersion, the detail block asks it for everything
        else — and the three shepherd components share one chart, so an
        uncached read parsed shepherd's 623-line values.yaml six times over.
        """
        key = (chart, name)
        if key not in self._charts:
            self._charts[key] = _read_yaml(self.root / "helm" / chart / name)
        return self._charts[key]

    def chart_index(self) -> list[str]:
        """Every chart directory translator-devops holds, sorted.

        Directories only, and read defensively: `helm/` also holds loose files,
        and a throttled contents call answers with an object carrying a message
        rather than an array. An index we cannot read has to mean "we do not
        know", never "the repository has no charts" — the second is a claim,
        and it would publish forty-nine charts as unclaimed.
        """
        entries = _read_json_list(self.root / "helm" / "index.json")
        return sorted(
            entry["name"]
            for entry in entries
            if isinstance(entry, dict)
            and entry.get("type") == "dir"
            and isinstance(entry.get("name"), str)
            and entry["name"]
        )

    def chart_meta(self, chart: str) -> dict[str, Any | None]:
        """One chart's three cached files, keyed the way the matcher reads them.

        `values.yaml` and `ncats-images-meta.yaml` are only fetched for charts a
        component already claims, so both are None for most charts here. That is
        the cache being proportional rather than a gap, and `chart_matches`
        treats a missing document as a rule that cannot fire.
        """
        return {
            key: self.helm(chart, name) for key, name in CHART_META_FILES.items()
        }

    def chart_commit(self, chart: str) -> dict[str, Any] | None:
        """When the chart directory last changed, and what the change said.

        The *intent* to deploy, dated — a chart edited and never rolled out,
        and a rollout of an unchanged chart, both make it wrong as a deployment
        date, so whatever renders it has to say which claim it is.

        GitHub answers a throttled request with an object carrying a message
        rather than the array this asks for, and `_read_json_list` returns
        nothing for it: no commit is the honest answer to a call that did not
        happen.
        """
        if chart not in self._commits:
            entries = _read_json_list(self.root / "helm" / chart / "commit.json")
            first = entries[0] if entries and isinstance(entries[0], dict) else None
            self._commits[chart] = _commit_facts(first)
        return self._commits[chart]

    def repo_meta(self, owner: str, name: str) -> dict[str, Any] | None:
        """One source repository's own document, as GitHub returned it."""
        if not owner or not name:
            return None
        key = f"{owner}/{name}"
        if key not in self._repos:
            self._repos[key] = _read_json(self.root / "repos" / owner / f"{name}.json")
        return self._repos[key]

    def catalog(self) -> dict[str, dict[str, Any]]:
        """The infores catalog, indexed by infores id and parsed once.

        The file is one top-level key over a list of entries, and the key is
        found rather than named: `information_resources` is what it is called
        today, and this reads a registry maintained by another project. An
        entry with no `id` is not addressable and is left out.
        """
        if self._catalog is None:
            loaded = _read_yaml(self.root / "infores_catalog.yaml") or {}
            entries: list[Any] = next(
                (value for value in loaded.values() if isinstance(value, list)), []
            )
            self._catalog = {
                entry["id"]: entry
                for entry in entries
                if isinstance(entry, dict) and isinstance(entry.get("id"), str)
            }
        return self._catalog

    def http_status(self, relative: str) -> int | None:
        return (self.statuses.get(relative) or {}).get("status")


def _commit_facts(entry: dict[str, Any] | None) -> dict[str, Any] | None:
    """One GitHub commit, cut to the four things a "last changed" line needs.

    The committer's date rather than the author's: a rebased or cherry-picked
    change carries the date it was written, and what this dates is when the
    chart directory in `develop` changed. The subject is the first line of the
    message for the same reason a release excerpt is truncated — the body is a
    paragraph, and this is a line under a chart name.
    """
    if not entry:
        return None
    commit = entry.get("commit") if isinstance(entry.get("commit"), dict) else {}
    committer = commit.get("committer") if isinstance(commit.get("committer"), dict) else {}
    date = committer.get("date")
    sha = entry.get("sha")
    message = commit.get("message")
    return {
        "date": date[:10] if isinstance(date, str) else None,
        "sha": sha[:7] if isinstance(sha, str) else None,
        "url": entry.get("html_url") if isinstance(entry.get("html_url"), str) else None,
        "subject": (
            message.splitlines()[0].strip()
            if isinstance(message, str) and message.strip()
            else None
        ),
    }


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
    verdict = synced.rejected_detail.get(component.id, {}).get(env)
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
            if _same_version(chip["tag"], version):
                cell["released"] = chip["published"]
                cell["release_tag"] = chip["tag"]
                cell["release_url"] = chip["url"]
                break


def _same_version(a: str | None, b: str | None) -> bool:
    """Whether a release tag and a reported version name the same release.

    Only the `v` prefix is normalised away, because that is the only difference
    that actually occurs here: NameResolution tags `v1.5.2` and reports
    `1.5.2`. Anything cleverer — stripping suffixes, comparing as semver —
    would start claiming matches that are not there, and a wrong release-notes
    link is worse than none.
    """
    if not a or not b:
        return False
    return a.strip().lower().removeprefix("v") == b.strip().lower().removeprefix("v")


def _release_chips(
    entries: list[dict[str, Any]], deployed: set[str]
) -> list[dict[str, Any]]:
    """The releases worth showing for one component, newest first.

    The newest few, plus any older release that some environment is running:
    prod lags dev often enough that the newest three would miss the version the
    reader is looking at, which is the one whose notes they want.

    Drafts are dropped. They are invisible to an unauthenticated fetch, so they
    appear only once someone sets a GITHUB_TOKEN — and a link that works for
    the person who ran the sync and 404s for everyone else is a trap.
    """
    # GitHub orders /releases by when the release was *created*, which is not
    # when it was published: NameResolution's v1.5.2 was published after
    # v1.6.2. The dates are on the chips, so the order has to match them.
    ordered = sorted(
        entries, key=lambda entry: entry.get("published_at") or "", reverse=True
    )
    chips = []
    shown = 0
    for entry in ordered:
        tag = entry.get("tag_name")
        if not tag or entry.get("draft"):
            continue
        running = any(_same_version(tag, version) for version in deployed)
        # Counted after the skips, not from the enumeration: a repository
        # whose two newest entries are drafts showed one chip where it should
        # show three, because the drafts spent two of the three places.
        if shown >= RELEASES_SHOWN and not running:
            continue
        shown += 1
        chips.append(
            {
                "tag": tag,
                "name": entry.get("name") or tag,
                "url": entry.get("html_url"),
                "published": (entry.get("published_at") or "")[:10],
                "prerelease": bool(entry.get("prerelease")),
                "deployed": running,
            }
        )
    return chips


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


def build_rows(
    components: list[ComponentFile],
    synced: SyncedData,
    *,
    stages: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """One dictionary per component, in the stage order the config file sets.

    `stages` is a keyword argument with a default so the loader runs once per
    build rather than once per call: `build_payload` reads the file and hands
    the same list to `stage_blocks` afterwards, and the two must be the same
    list or the step numbers on the rows and the step numbers on the bands
    could be computed from different files.
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
        chips = _release_chips(
            releases,
            {version for cell in cells.values() if (version := cell.get("version"))},
        )
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
                "identifiers": {
                    "infores": component.infores,
                    "smartapi": component.smartapi_id,
                    "helm_chart": component.helm_chart,
                    "helm_charts": charts,
                    "translator_all_wiki": component.translator_all_wiki,
                    "otel_services": component.otel_services,
                },
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
                "releases_detail": releases_detail(releases),
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
                    {"env": env, "url": url}
                    for env in ENVIRONMENTS
                    if (url := synced.rejected.get(component.id, {}).get(env))
                ],
                "environments": cells,
            }
        )
    return rows


def stage_blocks(
    stages: list[dict[str, Any]], rows: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """The bands the page draws, built from the rows that survived the policy.

    Built *from the rows*, which is what keeps a published build honest without
    a second privacy pass: a band can only name a component whose row is still
    here. A stage with no kept rows is absent rather than empty — the
    Engineering stage holds jaeger and test-harness and nothing else, and a
    published build shows no heading for it rather than a heading over a gap.

    `step` is the stage's position in `config/flow-steps.yaml`, so the stages
    that remain keep the numbers they have locally: a published page runs 1–8
    and skips 9, rather than renumbering and disagreeing with the full build
    about which step Shepherd is.

    The roster is in row order, so the page's bands and its table list the same
    components in the same order without either having to sort.
    """
    rostered: dict[int, list[str]] = {}
    for row in rows:
        rostered.setdefault(row.get("step"), []).append(row["id"])
    blocks = []
    for number, stage in enumerate(stages, 1):
        members = rostered.get(number)
        if not members:
            continue
        blocks.append(
            {
                "step": number,
                "title": stage.get("title") or "",
                "description": stage.get("description") or "",
                "components": members,
                # Explicit on every block, not only the trailing one: a reader
                # of the payload should not have to know that a missing key
                # means False.
                "unplaced": bool(stage.get("unplaced")),
            }
        )
    return blocks


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
    matches = chart_matches(
        names, {name: synced.chart_meta(name) for name in names}, components
    )
    unclaimed = []
    for name in sorted(names):
        if matches[name]["confidence"] != "none":
            continue
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
                "matched_by": "infores",
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
    if policy is not None:
        rows, report = apply_policy(rows, policy)
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
        "unclaimed_charts": build_unclaimed_charts(components, synced),
        "smartapi_suggestions": build_smartapi_suggestions(rows),
        "rows": rows,
    }


def _css_string(value: str) -> str:
    """Escape a string for a double-quoted CSS attribute selector.

    Not html.escape: a <style> element's contents are not HTML-decoded, so an
    entity there stays literal and the selector matches nothing. Only the
    backslash and the quote need escaping inside a CSS string.
    """
    return value.replace("\\", "\\\\").replace('"', '\\"')


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
{owner_css}
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
