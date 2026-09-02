"""The detail blocks behind the dashboard's cells: shaping, and nothing else.

The table has room for a version and a badge. Everything else a source told us
— what a chart asks Kubernetes for, which maturities a TRAPI endpoint serves,
what the last ten releases said — is shaped here into plain dictionaries the
page can open on demand.

**The one rule: the Helm block must never carry a container image.** Image
repositories and tags already have a payload field of their own, `helm_images`,
and `config/privacy.yaml` withholds that field from the published page —
alongside a grid of versions, a list of image tags is a CVE inventory, which is
a different document from the one this dashboard is. So the chart reader below
emits capacity and only capacity: replicas, resource requests and limits,
storage sizes, ingress hosts. It never looks inside an `image:` mapping, and
`tests/test_payload_details.py` scans every cached chart's real output for an
image key or a registry hostname rather than trusting this paragraph.

Dict in, dict out, no I/O and no package imports, for the same reason
`privacy.py` is a leaf: the shaping is where the mistakes are, and it should be
testable without a network, a checkout, or a rendered page.

**A malformed input costs the field, never the build.** These documents are
written by other teams and change without telling us: a SmartAPI record whose
`test_data_location` has grown a shape the page has not seen, a release body
whose HTML does not parse, a releases endpoint that answered a rate-limit
object instead of a list. Each of those drops the field it belongs to and
leaves the rest of the row standing. A dashboard that stops building because
one upstream document changed shape is reporting on itself rather than on the
platform.
"""

from html.parser import HTMLParser
from typing import Any

DESCRIPTION_EXCERPT = 400
"""How much of a SmartAPI description the detail panel keeps."""

RELEASES_DETAILED = 10
"""How many releases the detail panel lists.

Counted over entries *kept*, not entries seen — the same cut the three release
chips get wrong when it is written the other way round, where two drafts spend
two of the places and the reader is shown eight releases in a list that says
ten.
"""

BODY_EXCERPT = 300
"""How much of a release body survives. Release notes run to screens of HTML."""


class _TextOnly(HTMLParser):
    """Keeps the text of an HTML document and throws the markup away.

    `html.parser` is in the standard library and already knows every way this
    markup is malformed, which a regular expression over `<[^>]*>` does not:
    the descriptions in the registry contain unclosed tags, bare `<` in prose,
    and entities that must survive as the characters they name.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def strip_html(value: Any, *, limit: int) -> str | None:
    """The readable text of an HTML fragment, cut to `limit` characters.

    SmartAPI descriptions and GitHub release bodies are markup written for
    somewhere else. The page shows them as one line of plain text, so the tags
    come out, the entities are decoded, and every run of whitespace collapses
    to a single space — a description formatted as a paragraph should not
    arrive as a column of ragged lines.

    `limit` counts the returned string, ellipsis included, so a caller sizing a
    panel gets the number it asked for. A non-string, a blank one, or markup
    the parser cannot get through returns None: the field is lost, the build is
    not.
    """
    if not isinstance(value, str) or not value.strip():
        return None
    parser = _TextOnly()
    try:
        parser.feed(value)
        parser.close()
    except Exception:  # noqa: BLE001 - any parse failure costs this field only
        # Deliberately broad. Whatever a future html.parser raises on a
        # document nobody has seen yet, the answer is the same: one description
        # is worth less than the build.
        return None
    text = " ".join("".join(parser.parts).split())
    if not text:
        return None
    if len(text) > limit:
        text = text[: limit - 1].rstrip() + "…"
    return text


def smartapi_detail(record: Any) -> dict[str, Any] | None:
    """One SmartAPI registry hit, reshaped into what the panel shows.

    The registry document is an OpenAPI file with Translator extensions bolted
    on, so the facts a reader wants are spread across `info`, `info
    ["x-translator"]`, `info["x-trapi"]`, `servers`, and the two underscore
    blocks the registry itself maintains. Flattening them here means the page
    reads one dictionary instead of chaining `.get` through five levels, which
    is the shape that raises when a team omits a block.

    Missing keys become None, missing lists become empty lists. A record that
    is empty or is not a mapping returns None — there is no detail to show,
    which is different from a record whose fields are blank.
    """
    if not record or not isinstance(record, dict):
        return None
    info = _mapping(record.get("info"))
    translator = _mapping(info.get("x-translator"))
    trapi = _mapping(info.get("x-trapi"))
    status = _mapping(record.get("_status"))
    meta = _mapping(record.get("_meta"))
    contact = _mapping(info.get("contact"))
    api_id = _text(record.get("_id"))
    return {
        "id": api_id,
        "registry_url": f"https://smart-api.info/ui/{api_id}" if api_id else None,
        "title": _text(info.get("title")),
        "version": _text(info.get("version")),
        "team": _strings(translator.get("team")),
        "component": _text(translator.get("component")),
        "infores": _text(translator.get("infores")),
        # Both spellings, hyphen first because that is what 98 of the 127
        # records use. Retriever registers `biolink_version` with an
        # underscore, and reading only the hyphen showed it as having no
        # Biolink version at all — a gap that reads as a finding about the
        # team rather than about our parser.
        "biolink_version": _text(
            translator.get("biolink-version") or translator.get("biolink_version")
        ),
        "trapi": {
            "version": _text(trapi.get("version")),
            "asyncquery": trapi.get("asyncquery"),
            "operations": _strings(trapi.get("operations")),
            "batch_size_limit": trapi.get("batch_size_limit"),
            "rate_limit": trapi.get("rate_limit"),
            "test_data_location": _test_data(trapi.get("test_data_location")),
        },
        "servers": [
            {
                "url": _text(server.get("url")),
                "maturity": _text(server.get("x-maturity")),
                "location": _text(server.get("x-location")),
                "description": _text(server.get("description")),
            }
            for server in _items(record.get("servers"))
        ],
        "status": {
            "uptime_status": _text(status.get("uptime_status")),
            "uptime_ts": _text(status.get("uptime_ts")),
            # ponytail: passed through whole. The registry writes one line per
            # path probed, and the longest seen is Retriever's 23 — small
            # enough that a cap would be a guess about the ceiling rather than
            # a protection against it. If a record ever arrives with hundreds,
            # cut it here and say how many were dropped.
            "uptime_msg": _strings(status.get("uptime_msg")),
            "refresh_status": status.get("refresh_status"),
            "refresh_ts": _text(status.get("refresh_ts")),
        },
        "meta": {
            "date_created": _text(meta.get("date_created")),
            "last_updated": _text(meta.get("last_updated")),
            "username": _text(meta.get("username")),
            "source_url": _text(meta.get("url")),
            "has_metakg": meta.get("has_metakg"),
        },
        "tags": [
            name
            for tag in _items(record.get("tags"))
            if (name := _text(tag.get("name")))
        ],
        "contact": {
            "name": _text(contact.get("name")),
            "email": _text(contact.get("email")),
            "url": _text(contact.get("url")),
        },
        "description_text": strip_html(
            info.get("description"), limit=DESCRIPTION_EXCERPT
        ),
        # How this record came to be attached to this component, so a reader
        # can tell a registered identifier from a match we made ourselves.
        "matched_by": _text(record.get("_matched_by")) or "id",
    }


def _test_data(value: Any) -> dict[str, str] | None:
    """`x-trapi.test_data_location` normalised to `{maturity: url}`.

    Two shapes are in the registry today: `{maturity: {"url": "..."}}`, and the
    same with a *list* of urls where a team points at more than one test file.
    The list takes its first entry, because the panel has room for one link and
    the first is the one the team put first.

    A shape neither of those is dropped rather than passed through. Passing it
    on hands a mapping or a number to a template that expects a link, and the
    page renders a Python repr at a reader; showing nothing says the same thing
    and says it honestly.
    """
    if not isinstance(value, dict):
        return None
    found: dict[str, str] = {}
    for maturity, entry in value.items():
        if not isinstance(maturity, str) or not isinstance(entry, dict):
            continue
        url = entry.get("url")
        if isinstance(url, list):
            url = next((item for item in url if isinstance(item, str)), None)
        text = _text(url)
        if text:
            found[maturity] = text
    return found or None


# --- Helm ------------------------------------------------------------------
#
# ponytail: this reads values.yaml as a document, not as a template. What comes
# out is therefore the chart's *defaults* — never the per-environment overrides
# ITRB deploys with — and a workload is recognised by two conventions the cached
# charts happen to follow (a `resources` block, a `replicaCount`). A chart that
# names its workloads some other way contributes nothing, silently; a chart that
# uses either key for something that is not a workload contributes a service that
# does not exist. That happened once already — gandalf's
# `app.gandalf.autoscaling.replicaCount: 1` was published as a workload of its
# own, so `autoscaling` is now named below as a block that is never a service —
# and the next such block will be found the same way, by someone reading the
# list and not recognising a name on it.
# The upgrade path is `helm template` with the environment's values file, which
# renders the real manifests and needs no conventions at all; it also needs the
# helm binary and a values file we do not currently fetch.

_MAX_VALUES_DEPTH = 6
"""How deep the values walker goes.

Deep enough for `jaeger.storage.cassandra.password` and everything above it,
shallow enough that a chart with a recursive-looking block cannot cost the run.
"""

_NEVER_ENTERED = frozenset({"image", "images"})
"""Mappings the walker refuses to descend into, so images cannot leak by accident.

Nothing under either key is read for anything, and none of the collector keys
appears there — but the rule at the top of this module is worth enforcing by
construction rather than by the absence of a lookup somebody could add later.
"""

_COLLECTED_KEYS = frozenset(
    {"resources", "replicaCount", "size", "storage", "host", "hosts", "dependencies"}
)
"""Every key this module reads out of a chart. Documentation, and a checklist.

`repository` is not here, and the one place it is read — `dependencies[].
repository` — is a *chart* repository like https://charts.bitnami.com/bitnami,
which says where the subchart comes from and nothing about what runs.
"""

_STORAGE_WRAPPERS = frozenset({"persistence", "persistentvolume", "volume"})
"""Path segments that name the wrapper rather than the thing being sized."""

_NEVER_A_SERVICE = frozenset({"autoscaling"})
"""Path segments whose block describes a workload without being one.

An `autoscaling:` block carries the replica count a HorizontalPodAutoscaler
would scale *to*, which is the same key a real workload uses — so gandalf's
`app.gandalf.autoscaling.replicaCount: 1` came out as a service beside the
`app.gandalf` it configures, and the panel listed one more workload than the
chart deploys. Anywhere in the path, not just at the end: a block below an
`autoscaling:` is describing the same thing.
"""

_PLACEHOLDERS = ("fillthisin", "ingress_host", "changeme", "change-me")
"""What a chart writes where the deploying environment fills the value in.

These reach the page as real values otherwise, and `ingress_HOST` shown as a
hostname is worse than an empty list: it looks like a fact.
"""


def helm_detail(
    chart: Any,
    chart_yaml: Any,
    values_yaml: Any,
    source_url: Any = None,
) -> dict[str, Any] | None:
    """What a chart says should run, and how much of the cluster it asks for.

    `chart_version` and `app_version` are kept apart and the second is never
    called "version". A chart version numbers the packaging; `appVersion`
    numbers the application the packaging *intends* to deploy, which is a claim
    about what should be running and not evidence about what is. The dashboard
    exists to keep those apart, so this block does too.

    Returns None for a falsy chart: with no chart there is nothing to describe,
    and an empty block would render as a panel saying nothing.
    """
    if not chart:
        return None
    meta = _mapping(chart_yaml)
    values = _mapping(values_yaml)
    name = _text(meta.get("name")) or str(chart)
    services, storage, hosts = _read_values(values, name)
    return {
        "chart": name,
        "chart_version": _version(meta.get("version")),
        "app_version": _version(meta.get("appVersion")),
        "description": _text(meta.get("description")),
        "dependencies": _dependencies(meta.get("dependencies")),
        "services": services,
        "storage": storage,
        "ingress_hosts": hosts,
        "source_url": _text(source_url),
    }


def _read_values(
    values: dict[str, Any], chart_name: str
) -> tuple[list[dict[str, Any]], list[dict[str, str]], list[str]]:
    """Walk values.yaml for workloads, volumes and hostnames.

    Every rule below was forced by one of the charts we cache, and each is
    named where it applies. The walk enters mapping values only: a list item
    with a `resources` block is an init container, not a service, and
    answer-appraiser has one — `redis.master.initContainers[0]` — that would
    otherwise be published as a workload of its own.
    """
    services: dict[str, dict[str, Any]] = {}
    storage: dict[str, str] = {}
    hosts: list[str] = []

    def visit(node: dict[str, Any], path: tuple[str, ...]) -> None:
        if len(path) > _MAX_VALUES_DEPTH:
            return
        name = ".".join(path) or chart_name
        replicas = node.get("replicaCount")
        # A YAML `true` is an int in Python, and a chart that writes
        # `replicaCount: true` means something we cannot render as a number.
        counted = isinstance(replicas, int) and not isinstance(replicas, bool)
        configures = any(part.casefold() in _NEVER_A_SERVICE for part in path)
        if ("resources" in node or counted) and not configures:
            # Two conventions, either of which marks a workload: a resources
            # block (answer-appraiser and test-harness carry theirs at the root,
            # so the service is named for the chart) or a replica count
            # (shepherd's `arax_pathfinder`, answer-appraiser's `redis.master`).
            resources = _mapping(node.get("resources"))
            services[name] = {
                "name": name,
                # `counted` and not `replicas or None`: answer-appraiser scales
                # `redis.replica` to 0 on purpose, and a real zero is a fact
                # about the chart where a None is a gap in our reading of it.
                "replicas": replicas if counted else None,
                "requests": _quantities(resources.get("requests")),
                "limits": _quantities(resources.get("limits")),
            }
        for key in ("size", "storage"):
            if key not in node:
                continue
            value = node[key]
            if isinstance(value, (dict, list)):
                # jaeger's `jaeger.storage` is a mapping of storage *backends*.
                # Read as a size it would publish a dictionary as a disk.
                continue
            if _is_placeholder(value):
                continue
            size = _quantity(value)
            if size:
                storage.setdefault(_storage_name(path, chart_name), size)
        for key, value in node.items():
            if not isinstance(key, str) or not isinstance(value, dict):
                continue
            if key.casefold() in _NEVER_ENTERED:
                continue
            if key.casefold() == "ingress":
                hosts.extend(_ingress_hosts(value))
            visit(value, path + (key,))

    visit(values, ())
    return (
        sorted(services.values(), key=lambda service: service["name"]),
        [{"name": name, "size": size} for name, size in sorted(storage.items())],
        sorted(dict.fromkeys(hosts)),
    )


def _storage_name(path: tuple[str, ...], chart_name: str) -> str:
    """The workload a volume belongs to, not the key that wrapped it.

    `redis.master.persistence.size` is redis's master storage and
    `logs.persistentVolume.size` is the logs volume; carrying the wrapper
    segment into the name would put the Kubernetes spelling on the page instead
    of the thing being sized.
    """
    parts = list(path)
    if parts and parts[-1].casefold() in _STORAGE_WRAPPERS:
        parts.pop()
    return ".".join(parts) or chart_name


def _ingress_hosts(block: dict[str, Any]) -> list[str]:
    """Hostnames out of one `ingress:` mapping, in both spellings charts use.

    `hosts` is the one list the walker enters, and only here: a list of ingress
    entries is a list of hostnames, where a list anywhere else in values.yaml
    is init containers, arguments or access modes.

    Only under a key literally called `ingress`, which is why a `redis_host` or
    a `jaegerHost` elsewhere in the file is not mistaken for a public name.
    """
    found = []
    host = _text(block.get("host"))
    if host and not _is_placeholder(host):
        found.append(host)
    entries = block.get("hosts")
    if isinstance(entries, list):
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            host = _text(entry.get("host"))
            if host and not _is_placeholder(host):
                found.append(host)
    return found


def _dependencies(value: Any) -> list[dict[str, str | None]]:
    """Subcharts, with the chart repository each comes from.

    This `repository` is the one in the module's rule that is allowed: it names
    a Helm repository — https://charts.bitnami.com/bitnami — which says where
    the packaging was downloaded from, not which container image runs.
    """
    return [
        {
            "name": _text(entry.get("name")),
            "version": _version(entry.get("version")),
            "repository": _text(entry.get("repository")),
        }
        for entry in _items(value)
    ]


def _quantities(block: Any) -> dict[str, str | None] | None:
    """A `requests:` or `limits:` block as `{cpu, memory}`, or None if absent."""
    if not isinstance(block, dict):
        return None
    return {
        "cpu": _quantity(block.get("cpu")),
        "memory": _quantity(block.get("memory")),
    }


def _quantity(value: Any) -> str | None:
    """One Kubernetes quantity, spelled the way the chart spelled it.

    `4000m` and `20Gi` stay as they are. Parsing them into cores and bytes
    would let the page show a number the chart does not contain, and the reader
    who goes to check it against values.yaml would find something else there.
    """
    if isinstance(value, str):
        return value.strip() or None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value)
    return None


def _version(value: Any) -> str | None:
    """A version as written. Unquoted `1.0` parses as a float; `str` restores it."""
    return _quantity(value)


def _is_placeholder(value: Any) -> bool:
    """Whether a chart wrote a hole here rather than a value.

    `fillthisin`, `ingress_HOST` and `change-me` are what these charts put where
    the deploying environment supplies the real thing. Published as data they
    read as facts, which is worse than the gap they actually are.
    """
    if value is None:
        return True
    if not isinstance(value, str):
        return False
    lowered = value.casefold().strip()
    return not lowered or any(token in lowered for token in _PLACEHOLDERS)


# --- GitHub ----------------------------------------------------------------


def releases_detail(entries: Any) -> list[dict[str, Any]]:
    """The newest releases, newest first, drafts left out.

    Two things this gets right that the same code got wrong elsewhere first.
    The cut counts entries *kept*: two drafts at the top of the list must not
    spend two of the ten places and leave the panel showing eight. And the sort
    is by `published_at`, not by the order GitHub returned — that order is by
    creation, so a release drafted in March and published in September arrives
    ahead of everything published since.

    The GitHub releases endpoint answers a JSON *object* when it rate-limits,
    so a non-list input is not an empty repository: it is an answer we could
    not read, and returning `[]` for it keeps that from being drawn as a fact.
    """
    if not isinstance(entries, list):
        return []
    kept: list[dict[str, Any]] = []
    for entry in sorted(_items(entries), key=_published_key, reverse=True):
        if entry.get("draft"):
            continue
        kept.append(
            {
                "tag": _text(entry.get("tag_name")),
                "name": _text(entry.get("name")),
                "url": _text(entry.get("html_url")),
                "published": _date_part(entry.get("published_at")),
                "prerelease": entry.get("prerelease"),
                # The login and nothing else. The author object also carries
                # avatar, gravatar and a dozen API urls, none of which the page
                # shows and all of which would be republished by keeping it.
                "author": _text(_mapping(entry.get("author")).get("login")),
                "body_excerpt": strip_html(entry.get("body"), limit=BODY_EXCERPT),
            }
        )
        if len(kept) == RELEASES_DETAILED:
            break
    return kept


def _published_key(entry: dict[str, Any]) -> str:
    """Sort key: the ISO timestamp, which sorts correctly as text.

    An entry with no `published_at` sorts to the end in the newest-first order
    used here, for the same reason undated rows stay last in both directions of
    the table: an unknown date must not be promoted to the top.
    """
    return _text(entry.get("published_at")) or ""


def _date_part(value: Any) -> str | None:
    """The calendar date out of an ISO timestamp. The panel shows days."""
    text = _text(value)
    return text.split("T")[0] if text else None


def repo_meta_detail(doc: Any) -> dict[str, Any] | None:
    """A GitHub repository document, reduced to what a reader would ask about."""
    if not doc or not isinstance(doc, dict):
        return None
    license_doc = _mapping(doc.get("license"))
    return {
        "description": _text(doc.get("description")),
        "default_branch": _text(doc.get("default_branch")),
        "pushed_at": _text(doc.get("pushed_at")),
        "archived": doc.get("archived"),
        # The SPDX id when GitHub recognised the licence, its own name when it
        # only guessed; either is more useful than the whole licence object.
        "license": _text(license_doc.get("spdx_id")) or _text(license_doc.get("name")),
        "topics": _strings(doc.get("topics")),
        "open_issues": doc.get("open_issues_count"),
        "stars": doc.get("stargazers_count"),
        "homepage": _text(doc.get("homepage")),
    }


def catalog_detail(entry: Any) -> dict[str, Any] | None:
    """One infores catalog entry: what the registry says this thing *is*.

    Every other source here reports what a component is doing. This one carries
    the platform's own description of it — its status, the knowledge level and
    agent type it claims, and who consumes it — which is the context a version
    number is read against.
    """
    if not entry or not isinstance(entry, dict):
        return None
    return {
        "name": _text(entry.get("name")),
        "description": _text(entry.get("description")),
        "status": _text(entry.get("status")),
        "knowledge_level": _text(entry.get("knowledge_level")),
        "agent_type": _text(entry.get("agent_type")),
        "xref": _strings(entry.get("xref")),
        "consumes": _strings(entry.get("consumes")),
        "consumed_by": _strings(entry.get("consumed_by")),
    }


# --- Shared readers --------------------------------------------------------


def _mapping(value: Any) -> dict[str, Any]:
    """A mapping, or an empty one.

    Chaining `.get` through a key that is absent — or, worse, present and null,
    which is how a hand-edited YAML file spells "not set yet" — is the most
    common way one of these documents raises instead of losing a field.
    """
    return value if isinstance(value, dict) else {}


def _items(value: Any) -> list[dict[str, Any]]:
    """The mappings in a list, in order. A list that is not a list is empty."""
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _text(value: Any) -> str | None:
    """A non-blank string, or nothing.

    A number, a list or a mapping arriving in a text field is a shape the page
    has not seen. Dropping it keeps `{'url': ...}` off the screen.
    """
    return (value.strip() or None) if isinstance(value, str) else None


def _strings(value: Any) -> list[str]:
    """The non-blank strings in a list. Anything else in it is left out."""
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]
