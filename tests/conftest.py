"""The two fixtures the dashboard test modules share.

Both are function-scoped and must stay that way: tests mutate `component` in
place and write extra files into `synced.root`, so a wider scope would leak one
test's setup into the next. There is nothing to gain by widening it either --
the fixture is five small writes into `tmp_path`, and the whole dashboard suite
runs in well under a second.

Only the fixtures live here. The plain builders are in `dashboard_helpers.py`
and imported explicitly, the way `helpers.py` already is.
"""

import json

import pytest

from tests.dashboard_helpers import _comp
from translator_diagram.synced_data import SyncedData


@pytest.fixture
def synced(tmp_path):
    """A minimal sync directory: one component, four environments."""
    (tmp_path / "manifest.json").write_text(json.dumps({
        "started_at": "2026-08-31T00:00:00+00:00",
        "finished_at": "2026-08-31T00:01:00+00:00",
        "counts": {"attempted": 5, "succeeded": 4, "cached": 0, "failed": 1},
        "fetches": [{"path": "openapi/svc/ci.json", "status": 200, "url": "https://svc.ci/"}],
    }))
    (tmp_path / "smartapi.json").write_text(json.dumps({"hits": [{
        "_id": "abc",
        "info": {"version": "9.9.9", "x-trapi": {"version": "1.4.0"}},
        "_status": {"uptime_status": "pass"},
        "servers": [
            {"url": "https://svc.ci/", "x-maturity": "staging"},
            {"url": "https://svc.test/", "x-maturity": "testing"},
            {"url": "https://svc/", "x-maturity": "production"},
        ],
    }]}))
    for env, version in (("ci", "2.0.0"), ("test", "2.0.0"), ("prod", "1.0.0")):
        path = tmp_path / "openapi" / "svc" / f"{env}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"info": {
            "version": version,
            "x-trapi": {"version": "1.6.0"},
            "x-translator": {"component": "KP", "biolink-version": "4.2.5"},
        }}))
    return SyncedData(tmp_path)


@pytest.fixture
def component():
    return _comp("svc", identifiers={"smartapi": "abc"})
