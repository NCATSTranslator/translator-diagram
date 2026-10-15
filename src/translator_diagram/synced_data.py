"""Reading what `sync-components` left behind, and nothing else.

`SyncedData` is the build's reader of the sync cache (`sync` reads its own
previous run through the same `files` parsers), and it is where the 200 gate
lives. The gate is three rules, not one, and they differ on purpose:

- An endpoint body (`openapi`, `status`) is refused when this run's manifest
  records a failed fetch of it, so a document cached before a service started
  404ing cannot answer for the current one. A body with *no* manifest entry
  is still read: nothing this run says it is wrong, and a build from a cache
  that predates a component file's new endpoint would otherwise go blank.
- `openapi_outcome` is stricter — it answers only for a path this run fetched
  with a 200 — because its job is to say what *this run* got back.
- A root probe is read whenever this run made it, whatever the status: a 404
  at `/` is the answer, not a reason to look away.

Every reader returns `None` or an empty container rather than raising — a
missing file in a gitignored scratch directory is the normal case, not an
error.
"""

from collections.abc import Callable
from pathlib import Path
from typing import Any

from .charts import chart_dirs, chart_meta
from .components import OTEL_ENVIRONMENTS, Deployment
from .files import (
    chart_commit_path,
    confirmed_hosts,
    derived_path,
    endpoint_key,
    helm_file_path,
    helm_index_path,
    infores_catalog_path,
    manifest_fetches,
    manifest_path,
    otel_path,
    read_json,
    read_yaml,
    rejected_hosts,
    releases_path,
    repo_meta_path,
    smartapi_hits,
    smartapi_path,
)
from .payload_details import mapping, text


def _read_json_list(path: Path) -> list[Any]:
    """A JSON array, or an empty list for anything else.

    GitHub answers a rate-limited request with a 200-shaped *object* carrying a
    message, and `sync` saves whatever came back, so the shape has to be
    checked rather than assumed.
    """
    loaded = read_json(path)
    return loaded if isinstance(loaded, list) else []


def _service_names(document: dict[str, Any] | None) -> list[str]:
    """The service names one OpenTelemetry collector reported.

    Strings only, and a list only. The tile that counts these is a footnote,
    and a collector that answers with a `data` array of objects — or with no
    array at all — must cost that tile its number rather than take the whole
    build down on an unhashable name.
    """
    data = mapping(document).get("data")
    if not isinstance(data, list):
        return []
    return [name for name in data if isinstance(name, str)]


class SyncedData:
    """Everything `sync` wrote, read back."""

    def __init__(self, root: Path):
        self.root = root
        self.manifest = mapping(read_json(manifest_path(root)))
        self.smartapi = smartapi_hits(read_json(smartapi_path(root)))
        # One read, two answers. `sync` writes both halves of the same probe
        # into this file, and reading it twice would let a rebuild pick up a
        # confirmation from one moment and a rejection from another.
        probes = read_json(derived_path(root))
        self.derived = {
            cid: {
                env: Deployment(env=env, url=spec["url"], location=spec.get("location"))
                for env, spec in envs.items()
            }
            for cid, envs in confirmed_hosts(probes).items()
        }
        # The other half: hosts the convention predicted and the probe did not
        # confirm, with the verdict attached. Never "this is down", which is a
        # claim about a deployment we have no evidence exists.
        self.rejected = rejected_hosts(probes)
        # Everything below is read once per build and kept: a chart's
        # values.yaml answers two questions and shepherd's is 623 lines of it,
        # three shepherd components share one chart commit and one release
        # list, and the infores catalog is 500 entries of YAML that only has
        # to be parsed if a row has an infores. One memo, keyed by what was
        # asked, so a new reader cannot forget to add a cache of its own.
        self._memo: dict[tuple[str, ...], Any] = {}
        self.otel = {
            env: _service_names(read_json(otel_path(root, env)))
            for env in OTEL_ENVIRONMENTS
        }
        self.statuses = manifest_fetches(self.manifest)

    def openapi(self, component_id: str, env: str) -> dict[str, Any] | None:
        return self._endpoint_body("openapi", component_id, env)

    def status(self, component_id: str, env: str) -> dict[str, Any] | None:
        return self._endpoint_body("status", component_id, env)

    def root_probe(self, component_id: str, env: str) -> dict[str, Any] | None:
        """How the deployment's own URL answered this run, or None.

        `{"status", "content_type", "error"}` — what `fetch.probe_to` saved,
        which is a summary rather than the page itself. Gated the way the
        endpoint bodies are: a summary is only read when this run's manifest
        has an entry for it, so a host that has since been taken out of the
        component file does not keep answering from an old file.

        The gate is "was it probed", not "did it answer 200", and that is the
        difference from `_endpoint_body`. There the question is whether a
        document can be believed, and only a 200 makes one believable. Here a
        404 *is* the answer, and dropping it would leave the page unable to
        tell it from silence. It is shown as the HTTP status, not counted as
        up: `cells._reachable` takes 2xx and 3xx only, because a 404 at `/` is
        also what an ingress says for a deployment that has gone away.

        Not named `root`: this class already has one, the sync directory
        itself, and a method shadowing it would be a bug that reads as a name.
        """
        relative = endpoint_key("root", component_id, env)
        if relative not in self.statuses:
            return None
        probe = read_json(self.root / relative)
        return probe if isinstance(probe, dict) else None

    def openapi_outcome(self, component_id: str, env: str) -> str | None:
        """What this run's OpenAPI fetch actually got back, as a word.

        `openapi()` answers with a document or None, and None is three
        different things: nothing was fetched, something was fetched and was
        not JSON, or the fetch failed. The middle one is real — BioThings'
        pending API answers every path with the single-page app's HTML and a
        200, so `fetch_to` saves a page of markup that `read_json` then
        refuses — and reported as None it is indistinguishable from never
        having asked.

        So: None where this run fetched nothing at that path, `"not-json"`
        where a 200 was not a document, `"no-version"` where it was a document
        with no `info.version`, and `"version"` where there is one to show.
        """
        relative = endpoint_key("openapi", component_id, env)
        fetch = self.statuses.get(relative)
        if not fetch or fetch.get("status") != 200 or fetch.get("error"):
            return None
        path = self.root / relative
        if not path.exists():
            return None
        document = self._body(relative)
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

        A body this run never asked about is read as it is: the manifest says
        nothing against it, and `test_a_body_this_run_never_asked_for_is_left_alone`
        pins that. `openapi_outcome` is the stricter reader.

        Only the endpoints are gated this way. A release list or a Helm chart
        makes no claim about what is running right now, so dropping a cached
        one when GitHub rate-limits a run would lose real information and say
        nothing new in its place.
        """
        relative = endpoint_key(kind, component_id, env)
        fetch = self.statuses.get(relative)
        if fetch and not (fetch.get("status") == 200 and not fetch.get("error")):
            return None
        # A 200 can carry any JSON at all — an array, a bare string — and every
        # reader of these bodies indexes them as objects.
        body = self._body(relative)
        return body if isinstance(body, dict) else None

    def _once(self, key: tuple[str, ...], load: Callable[[], Any]) -> Any:
        """`load()` the first time `key` is asked for, the memo after that."""
        if key not in self._memo:
            self._memo[key] = load()
        return self._memo[key]

    def _body(self, relative: str) -> Any:
        """A cached JSON body, parsed once per build: the version chain and
        `openapi_outcome` both read every OpenAPI document."""
        return self._once(("body", relative), lambda: read_json(self.root / relative))

    def releases(self, repo: str | None) -> list[dict[str, Any]]:
        """One repository's releases, newest first, as GitHub returned them."""
        if not repo:
            return []
        return self._once(
            ("releases", repo),
            lambda: [
                entry
                for entry in _read_json_list(releases_path(self.root, repo))
                if isinstance(entry, dict)
            ],
        )

    def helm(self, chart: str, name: str) -> dict[str, Any] | None:
        """One file out of one cached chart, parsed once per build.

        The same document now answers two questions — the version chain asks
        `Chart.yaml` for an appVersion, the detail block asks it for everything
        else — and the three shepherd components share one chart, so an
        uncached read parsed shepherd's 623-line values.yaml six times over.
        """
        return self._once(
            ("helm", chart, name),
            lambda: read_yaml(helm_file_path(self.root, chart, name)),
        )

    def chart_index(self) -> list[str]:
        """Every chart directory translator-devops holds, sorted."""
        return chart_dirs(read_json(helm_index_path(self.root)))

    def chart_meta(self, chart: str) -> dict[str, Any | None]:
        """One chart's three cached files, keyed the way the matcher reads them.

        `values.yaml` and `ncats-images-meta.yaml` are only fetched for charts a
        component already claims, so both are None for most charts here. That is
        the cache being proportional rather than a gap, and `charts.chart_matches`
        treats a missing document as a rule that cannot fire.
        """
        return chart_meta(self.helm, chart)

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
        def load() -> dict[str, Any] | None:
            entries = _read_json_list(chart_commit_path(self.root, chart))
            first = entries[0] if entries and isinstance(entries[0], dict) else None
            return _commit_facts(first)

        return self._once(("commit", chart), load)

    def repo_meta(self, repo: str | None) -> dict[str, Any] | None:
        """One `owner/name` repository's own document, as GitHub returned it."""
        if not repo:
            return None
        return self._once(
            ("repo", repo), lambda: read_json(repo_meta_path(self.root, repo))
        )

    def catalog(self) -> dict[str, dict[str, Any]]:
        """The infores catalog, indexed by infores id and parsed once.

        The file is one top-level key over a list of entries, and the key is
        found rather than named: `information_resources` is what it is called
        today, and this reads a registry maintained by another project. An
        entry with no `id` is not addressable and is left out.
        """
        def load() -> dict[str, dict[str, Any]]:
            loaded = read_yaml(infores_catalog_path(self.root)) or {}
            entries: list[Any] = next(
                (value for value in loaded.values() if isinstance(value, list)), []
            )
            return {
                entry["id"]: entry
                for entry in entries
                if isinstance(entry, dict) and isinstance(entry.get("id"), str)
            }

        return self._once(("catalog",), load)

    def http_status(self, kind: str, component_id: str, env: str) -> int | None:
        """The status this run recorded for one document fetch, or None."""
        fetch = self.statuses.get(endpoint_key(kind, component_id, env))
        return (fetch or {}).get("status")


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
    commit = mapping(entry.get("commit"))
    date = text(mapping(commit.get("committer")).get("date"))
    sha = text(entry.get("sha"))
    message = text(commit.get("message"))
    return {
        "date": date[:10] if date else None,
        "sha": sha[:7] if sha else None,
        "url": text(entry.get("html_url")),
        "subject": message.splitlines()[0].strip() if message else None,
    }
