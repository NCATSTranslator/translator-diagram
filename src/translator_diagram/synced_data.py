"""Reading what `sync-components` left behind, and nothing else.

`SyncedData` is the only thing that touches the sync cache, and it is where the
200 gate lives: a body answers for a cell only when *this* run recorded a hit
for it, so a document cached before a service started 404ing cannot answer for
the current one. Every reader returns `None` or an empty container rather than
raising — a missing file in a gitignored scratch directory is the normal case,
not an error.
"""

from pathlib import Path
from typing import Any

from .charts import CHART_META_FILES, chart_dirs
from .components import Deployment, read_json, read_yaml


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
    data = (document or {}).get("data")
    if not isinstance(data, list):
        return []
    return [name for name in data if isinstance(name, str)]


class SyncedData:
    """Everything `sync` wrote, read back."""

    def __init__(self, root: Path):
        self.root = root
        self.manifest = read_json(root / "manifest.json") or {}
        payload = read_json(root / "smartapi.json") or {}
        self.smartapi = {
            hit["_id"]: hit for hit in payload.get("hits", []) if hit.get("_id")
        }
        # One read, two answers. `sync` writes both halves of the same probe
        # into this file, and reading it twice would let a rebuild pick up a
        # confirmation from one moment and a rejection from another.
        probes = read_json(root / "derived.json") or {}
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
        # The other half: hosts the convention predicted and the probe did not
        # confirm, with the verdict attached — how the candidate was turned
        # away, which is what tells "there is no such host" from "there is one
        # and it is not this component". Never "this is down", which is a claim
        # about a deployment we have no evidence exists.
        self.rejected = {
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
        self._bodies: dict[str, Any] = {}
        self._releases: dict[str, list[dict[str, Any]]] = {}
        self._catalog: dict[str, dict[str, Any]] | None = None
        self.otel = {
            env: _service_names(read_json(root / "otel" / f"{env}.json"))
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
        404 *is* the answer, and dropping it would leave the page unable to
        tell it from silence. It is shown as the HTTP status, not counted as
        up: `cells._reachable` takes 2xx and 3xx only, because a 404 at `/` is
        also what an ingress says for a deployment that has gone away.

        Not named `root`: this class already has one, the sync directory
        itself, and a method shadowing it would be a bug that reads as a name.
        """
        relative = f"root/{component_id}/{env}.json"
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

        Only the endpoints are gated this way. A release list or a Helm chart
        makes no claim about what is running right now, so dropping a cached
        one when GitHub rate-limits a run would lose real information and say
        nothing new in its place.
        """
        relative = f"{kind}/{component_id}/{env}.json"
        fetch = self.statuses.get(relative)
        if fetch and not (fetch.get("status") == 200 and not fetch.get("error")):
            return None
        return self._body(relative)

    def _body(self, relative: str) -> Any:
        """A cached JSON body, parsed once per build: the version chain and
        `openapi_outcome` both read every OpenAPI document."""
        if relative not in self._bodies:
            self._bodies[relative] = read_json(self.root / relative)
        return self._bodies[relative]

    def releases(self, repo: str | None) -> list[dict[str, Any]]:
        """One repository's releases, newest first, as GitHub returned them."""
        if not repo:
            return []
        # Cached per repository: the three shepherds share one release list.
        if repo not in self._releases:
            self._releases[repo] = [
                entry
                for entry in _read_json_list(self.root / "releases" / f"{repo}.json")
                if isinstance(entry, dict)
            ]
        return self._releases[repo]

    def helm(self, chart: str, name: str) -> dict[str, Any] | None:
        """One file out of one cached chart, parsed once per build.

        The same document now answers two questions — the version chain asks
        `Chart.yaml` for an appVersion, the detail block asks it for everything
        else — and the three shepherd components share one chart, so an
        uncached read parsed shepherd's 623-line values.yaml six times over.
        """
        key = (chart, name)
        if key not in self._charts:
            self._charts[key] = read_yaml(self.root / "helm" / chart / name)
        return self._charts[key]

    def chart_index(self) -> list[str]:
        """Every chart directory translator-devops holds, sorted."""
        return chart_dirs(read_json(self.root / "helm" / "index.json"))

    def chart_meta(self, chart: str) -> dict[str, Any | None]:
        """One chart's three cached files, keyed the way the matcher reads them.

        `values.yaml` and `ncats-images-meta.yaml` are only fetched for charts a
        component already claims, so both are None for most charts here. That is
        the cache being proportional rather than a gap, and `charts.chart_matches`
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
            self._repos[key] = read_json(self.root / "repos" / owner / f"{name}.json")
        return self._repos[key]

    def catalog(self) -> dict[str, dict[str, Any]]:
        """The infores catalog, indexed by infores id and parsed once.

        The file is one top-level key over a list of entries, and the key is
        found rather than named: `information_resources` is what it is called
        today, and this reads a registry maintained by another project. An
        entry with no `id` is not addressable and is left out.
        """
        if self._catalog is None:
            loaded = read_yaml(self.root / "infores_catalog.yaml") or {}
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
