"""Builders the dashboard test modules share.

Separate from `helpers.py` on purpose: that file's `_comp` builds a `Component`
-- one row of the sheet -- and this one builds a `ComponentFile`, one
`catalog/components/<id>.yaml`. The two models deliberately do not know about each
other, so neither builder can stand in for the other.
"""

import json

from translator_diagram.charts import CHART_META_FILES
from translator_diagram.components import ComponentFile, Deployment, parse_component
from translator_diagram.files import (
    chart_commit_path,
    derived_path,
    endpoint_key,
    endpoint_path,
    helm_file_path,
    helm_index_path,
    infores_catalog_path,
    manifest_path,
    otel_path,
    releases_path,
    repo_meta_path,
    smartapi_path,
)
from translator_diagram.rows import build_rows
from translator_diagram.synced_data import SyncedData


def _comp(cid, **kwargs):
    """A ComponentFile straight from its fields, defaulting what tests rarely set."""
    kwargs.setdefault("refactor_status", "New in Refactor")
    return ComponentFile(id=cid, name=kwargs.pop("name", cid), owner="DOGSLED", **kwargs)


# The smallest mapping parse_component accepts: what a test adds to it is the
# whole point of the test.
MINIMAL = {"id": "svc", "name": "Service", "owner": "DOGSLED",
           "refactor_status": "New in Refactor"}


def _parse(**overrides):
    """A ComponentFile through parse_component, the way a file arrives.

    Unlike `_comp`, nested blocks arrive in their raw YAML shape — an
    `environments` mapping becomes Deployment objects here, not before.
    """
    return parse_component({**MINIMAL, **overrides})


def _registry(hits):
    """A SmartAPI registry body as the fetcher hands it back: bytes of JSON."""
    return json.dumps({"hits": hits}).encode()


class FakeFetcher:
    """Answers from a dict, and records what it was asked for."""

    def __init__(self, responses, default=(404, b"")):
        self.responses = responses
        self.default = default
        self.urls = []

    def __call__(self, url):
        self.urls.append(url)
        value = self.responses.get(url, self.default)
        if isinstance(value, Exception):
            raise value
        return value


class _Probes:
    """A sync directory built one recorded fact at a time.

    Every test of the build turns on the same thing -- which requests this run
    made and how each answered, and what earlier runs left behind -- and
    writing that as files by hand is how a fixture comes to disagree with what
    `sync` actually writes. So: one builder, the same shapes `fetch.probe_to`
    and `fetch.fetch_to` produce, every path through `files.py`'s layout
    functions, and the manifest assembled from what was asked for rather than
    declared separately.

    Methods that take `cid` default it to the component this builder was made
    for; pass one to put several components in one directory.

    Nothing is written until a method asks for it, so a builder over a
    directory something else already reads -- the `synced` fixture's, or one
    `sync()` is about to run in -- adds files beside what is there. `build()`
    writes the manifest and, where no registry has been written, an empty one.
    """

    def __init__(self, tmp_path, component_id="svc"):
        self.root = tmp_path
        self.id = component_id
        self.fetches = []

    # -- the per-deployment files -------------------------------------------

    def _record(self, relative, status, error=None, url=None):
        self.fetches.append({
            "path": relative, "url": url or f"https://svc.ci/{relative}",
            "status": status, "error": error,
        })

    def _write(self, path, text):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text if isinstance(text, str) else json.dumps(text))

    def probe(self, env, status, error=None, content_type=None, cid=None):
        """A root probe: a summary on disk whatever happened, plus a fetch."""
        cid = cid or self.id
        self._write(endpoint_path(self.root, "root", cid, env),
                    {"status": status, "content_type": content_type, "error": error})
        self._record(endpoint_key("root", cid, env), status, error)
        return self

    def document(self, kind, env, status, body=None, error=None, cid=None, url=None):
        """An endpoint fetch: a body only on a 200, the way `fetch_to` writes."""
        cid = cid or self.id
        if status == 200 and body is not None:
            self._write(endpoint_path(self.root, kind, cid, env), body)
        self._record(endpoint_key(kind, cid, env), status, error, url)
        return self

    def body(self, kind, env, body, cid=None):
        """A body on disk with no manifest entry: what an earlier run left."""
        self._write(endpoint_path(self.root, kind, cid or self.id, env), body)
        return self

    # -- the registries and the previous run's verdicts ----------------------

    def registry(self, hits):
        self._write(smartapi_path(self.root), {"hits": hits})
        return self

    def _derived(self, half, env, spec, cid):
        path = derived_path(self.root)
        probes = json.loads(path.read_text()) if path.exists() else {}
        probes.setdefault(half, {}).setdefault(cid or self.id, {})[env] = spec
        self._write(path, probes)
        return self

    def confirmed(self, env, url, location=None, cid=None):
        """A conventional host an earlier run confirmed."""
        return self._derived("confirmed", env, {"url": url, "location": location}, cid)

    def rejected(self, env, url, cid=None, **verdict):
        """A conventional host an earlier run probed and turned away."""
        return self._derived("rejected", env, {
            "url": url, "checked_at": "2026-09-02T00:00:00+00:00", **verdict
        }, cid)

    def otel(self, env, names=None, *, body=None):
        """One collector's service list, or a raw body for the malformed cases."""
        self._write(otel_path(self.root, env), body if body is not None else {"data": names or []})
        return self

    def catalog(self, text):
        """The infores catalog, as YAML text."""
        self._write(infores_catalog_path(self.root), text)
        return self

    # -- GitHub: charts, releases, repositories --------------------------------

    def chart(self, name, *, chart=None, values=None, images=None, commit=None):
        """One chart's cached files. A str is written verbatim (YAML), anything
        else is dumped as JSON, which is YAML too."""
        for key, text in (("chart", chart), ("values", values), ("images", images)):
            if text is not None:
                self._write(helm_file_path(self.root, name, CHART_META_FILES[key]), text)
        if commit is not None:
            self._write(chart_commit_path(self.root, name), commit)
        return self

    def chart_index(self, names=None, *, entries=None):
        """The translator-devops helm/ listing: directories by name, or raw entries."""
        listing = entries if entries is not None else [
            {"name": name, "type": "dir"} for name in names or []
        ]
        self._write(helm_index_path(self.root), listing)
        return self

    def releases(self, repo, entries):
        """One repository's release list; a dict is the throttled-object case."""
        self._write(releases_path(self.root, repo), entries)
        return self

    def repo_meta(self, repo, body):
        self._write(repo_meta_path(self.root, repo), body)
        return self

    def file(self, relative, text):
        """Any other file, for the one-off shapes no method above describes."""
        self._write(self.root / relative, text)
        return self

    # -- and the manifest ------------------------------------------------------

    def build(self, **manifest):
        """Write the manifest from what was recorded, and read it all back.

        Extra keys (`started_at`, `finished_at`, `counts`) land on the manifest
        beside `fetches`, for the tests of what the page says about the run.
        """
        if not smartapi_path(self.root).exists():
            self.registry([])
        self._write(manifest_path(self.root), {"fetches": self.fetches, **manifest})
        return SyncedData(self.root)


def _cell(probes, component=None, env="ci"):
    """One cell, built the way `build_payload` builds it."""
    if component is None:
        component = _comp(
            "svc", environments={env: Deployment(env=env, url="https://svc.ci/")}
        )
    return build_rows([component], probes.build())[0]["environments"][env]


def _row(cid, **kwargs):
    """One row, reduced to what the graph builders read."""
    return {
        "id": cid,
        "step": kwargs.pop("step", 1),
        "connections": kwargs.pop("connections", {}),
        "externals": kwargs.pop("externals", []),
        **kwargs,
    }
