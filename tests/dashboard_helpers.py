"""Builders the dashboard test modules share.

Separate from `helpers.py` on purpose: that file's `_comp` builds a `Component`
-- one row of the sheet -- and this one builds a `ComponentFile`, one
`components/<id>.yaml`. The two models deliberately do not know about each
other, so neither builder can stand in for the other.
"""

import json

from translator_diagram.components import ComponentFile, Deployment
from translator_diagram.rows import build_rows
from translator_diagram.synced_data import SyncedData


def _comp(cid, **kwargs):
    kwargs.setdefault("refactor_status", "New in Refactor")
    return ComponentFile(id=cid, name=kwargs.pop("name", cid), owner="DOGSLED", **kwargs)


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
    """A sync directory built one recorded probe at a time.

    Every test below turns on the same thing -- which requests this run made
    and how each answered -- and writing that as a manifest by hand four lines
    at a time is how a fixture comes to disagree with what `sync` actually
    writes. So: one builder, the same shapes `fetch.probe_to` and
    `fetch.fetch_to` produce, and the manifest assembled from what was asked
    for rather than declared separately.
    """

    def __init__(self, tmp_path, component_id="svc"):
        self.root = tmp_path
        self.id = component_id
        self.fetches = []
        (tmp_path / "smartapi.json").write_text('{"hits": []}')

    def _record(self, relative, status, error=None):
        self.fetches.append({
            "path": relative, "url": f"https://svc.ci/{relative}",
            "status": status, "error": error,
        })

    def _write(self, relative, text):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    def probe(self, env, status, error=None, content_type=None):
        """A root probe: a summary on disk whatever happened, plus a fetch."""
        relative = f"root/{self.id}/{env}.json"
        self._write(relative, json.dumps(
            {"status": status, "content_type": content_type, "error": error}
        ))
        self._record(relative, status, error)
        return self

    def document(self, kind, env, status, body=None, error=None):
        """An endpoint fetch: a body only on a 200, the way `fetch_to` writes."""
        relative = f"{kind}/{self.id}/{env}.json"
        if status == 200 and body is not None:
            self._write(relative, body if isinstance(body, str) else json.dumps(body))
        self._record(relative, status, error)
        return self

    def rejected(self, env, url, **verdict):
        path = self.root / "derived.json"
        probes = json.loads(path.read_text()) if path.exists() else {}
        probes.setdefault("rejected", {}).setdefault(self.id, {})[env] = {
            "url": url, "checked_at": "2026-09-02T00:00:00+00:00", **verdict
        }
        path.write_text(json.dumps(probes))
        return self

    def registry(self, hits):
        (self.root / "smartapi.json").write_text(json.dumps({"hits": hits}))
        return self

    def build(self):
        (self.root / "manifest.json").write_text(
            json.dumps({"fetches": self.fetches})
        )
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
