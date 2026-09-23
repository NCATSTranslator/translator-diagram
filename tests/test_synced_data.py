"""Reading the sync cache: the 200 gate and the readers around it.

A test belongs to the module whose decision it pins, not to the function it
happens to call. Most of these drive `SyncedData` through `build_rows`, because
what the gate is *for* only becomes visible in the cell that comes out of it.
"""

import json

from tests.dashboard_helpers import _cell, _comp, _Probes
from translator_diagram.components import Deployment
from translator_diagram.rows import build_rows
from translator_diagram.synced_data import SyncedData


class TestStaleBodies:
    """A cached body from an earlier run must not answer for this one."""

    def _synced(self, tmp_path, fetch, body=None):
        (tmp_path / "manifest.json").write_text(json.dumps({"fetches": [fetch]}))
        (tmp_path / "smartapi.json").write_text('{"hits": []}')
        path = tmp_path / "openapi" / "svc" / "ci.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(body or {"info": {"version": "1.5.4"}}))
        return SyncedData(tmp_path)

    def _cell(self, synced):
        component = _comp(
            "svc", environments={"ci": Deployment(env="ci", url="https://svc.ci/")}
        )
        return build_rows([component], synced)[0]["environments"]["ci"]

    def test_a_404_this_run_does_not_report_last_run_version(self, tmp_path):
        # The failure this is here for: prod's OpenAPI is cached at 1.5.4,
        # prod goes away, and the page keeps saying prod runs 1.5.4 and is
        # reachable — beside its own http_status of 404.
        synced = self._synced(tmp_path, {
            "path": "openapi/svc/ci.json", "url": "https://svc.ci/openapi.json",
            "status": 404,
        })
        cell = self._cell(synced)
        assert cell["http_status"] == 404
        assert cell["version"] is None
        assert cell["reachable"] is False

    def test_a_failed_fetch_this_run_does_not_either(self, tmp_path):
        # A DNS failure records no status at all, which is not a 200 either.
        synced = self._synced(tmp_path, {
            "path": "openapi/svc/ci.json", "url": "https://svc.ci/openapi.json",
            "status": None, "error": "URLError: [Errno 8] nodename nor servname",
        })
        assert self._cell(synced)["reachable"] is False

    def test_a_cached_hit_is_still_a_hit(self, tmp_path):
        # --max-age skips the fetch and records a 200 from cache. That is an
        # answer, not a gap.
        synced = self._synced(tmp_path, {
            "path": "openapi/svc/ci.json", "url": "https://svc.ci/openapi.json",
            "status": 200, "cached": True,
        })
        assert self._cell(synced)["version"] == "1.5.4"

    def test_a_404_this_run_reports_no_operations_either(self, tmp_path):
        # The same gate, over the fields that arrived with the drawer. A cell
        # that has lost its version must not keep last run's operation list
        # beside its own 404 — that is the contradiction the gate exists for,
        # written out once per field the page shows.
        synced = self._synced(
            tmp_path,
            {
                "path": "openapi/svc/ci.json",
                "url": "https://svc.ci/openapi.json",
                "status": 404,
            },
            body={
                "info": {
                    "title": "Service",
                    "version": "1.5.4",
                    "x-trapi": {"operations": ["lookup"], "asyncquery": True},
                },
                "paths": {"/query": {}, "/meta_knowledge_graph": {}},
            },
        )
        cell = self._cell(synced)
        assert cell["trapi_operations"] == []
        assert cell["paths_count"] is None
        assert cell["openapi_title"] is None
        assert cell["asyncquery"] is None

    def test_a_body_this_run_never_asked_for_is_left_alone(self, tmp_path):
        # No manifest entry means no contradiction to resolve: the endpoint
        # was not planned this run, so the file is all there is to go on.
        synced = self._synced(tmp_path, {
            "path": "openapi/other/ci.json", "url": "https://other/", "status": 200,
        })
        assert self._cell(synced)["version"] == "1.5.4"


class TestChartCommit:
    """When a chart directory last changed — the intent to deploy, dated."""

    def _synced(self, tmp_path, body):
        (tmp_path / "manifest.json").write_text('{"fetches": []}')
        (tmp_path / "smartapi.json").write_text('{"hits": []}')
        path = tmp_path / "helm" / "shepherd" / "commit.json"
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps(body))
        return SyncedData(tmp_path)

    def _commit(self, **kwargs):
        return {
            "sha": kwargs.pop("sha", "1c729f5b7ac10823fe9b216092c03d8dd6aac6d7"),
            "html_url": kwargs.pop(
                "html_url", "https://github.com/helxplatform/translator-devops/commit/1c729f5"
            ),
            "commit": {
                "committer": {"date": kwargs.pop("date", "2026-09-02T15:18:59Z")},
                "message": kwargs.pop("message", "bump patch version"),
            },
        }

    def test_the_four_facts_a_last_changed_line_needs(self, tmp_path):
        synced = self._synced(tmp_path, [self._commit()])
        assert synced.chart_commit("shepherd") == {
            "date": "2026-09-02",
            "sha": "1c729f5",
            "url": "https://github.com/helxplatform/translator-devops/commit/1c729f5",
            "subject": "bump patch version",
        }

    def test_only_the_first_line_of_the_message(self, tmp_path):
        # A commit body is a paragraph; this renders under a chart name.
        synced = self._synced(
            tmp_path, [self._commit(message="bump chart\n\nand the appVersion")]
        )
        assert synced.chart_commit("shepherd")["subject"] == "bump chart"

    def test_an_empty_array_is_no_commit(self, tmp_path):
        assert self._synced(tmp_path, []).chart_commit("shepherd") is None

    def test_a_throttled_body_is_no_commit_rather_than_an_error(self, tmp_path):
        # GitHub answers a rate-limited request with an object carrying a
        # message, and "no commit" is the honest reading of a call that did not
        # happen.
        synced = self._synced(tmp_path, {"message": "API rate limit exceeded"})
        assert synced.chart_commit("shepherd") is None

    def test_a_chart_with_no_commit_file(self, tmp_path):
        assert self._synced(tmp_path, []).chart_commit("no-such-chart") is None

    def test_it_reaches_the_chart_block_on_the_row(self, synced, component):
        chart = synced.root / "helm" / "my-chart"
        chart.mkdir(parents=True)
        (chart / "Chart.yaml").write_text("name: my-chart\nappVersion: 1.16.0\n")
        (chart / "commit.json").write_text(json.dumps([self._commit()]))
        component.identifiers = {"smartapi": "abc", "helm_chart": "my-chart"}
        row = build_rows([component], SyncedData(synced.root))[0]
        assert row["helm_charts"][0]["last_changed"]["date"] == "2026-09-02"

    def test_a_chart_with_no_commit_still_has_the_key(self, synced, component):
        # Absent, not missing: the drawer reads `last_changed` on every chart
        # block and a key that appears only sometimes is the shape that throws.
        chart = synced.root / "helm" / "my-chart"
        chart.mkdir(parents=True)
        (chart / "Chart.yaml").write_text("name: my-chart\n")
        component.identifiers = {"smartapi": "abc", "helm_chart": "my-chart"}
        row = build_rows([component], SyncedData(synced.root))[0]
        assert row["helm_charts"][0]["last_changed"] is None


class TestCatalog:
    """The infores catalog: what the platform's registry says a thing is."""

    CATALOG = """
information_resources:
  - id: infores:svc
    name: The Service
    status: released
    knowledge_level: knowledge_assertion
    agent_type: automated_agent
    consumes:
      - infores:upstream
  - id: infores:upstream
    name: Upstream
"""

    def _synced(self, tmp_path, text=None):
        (tmp_path / "manifest.json").write_text('{"fetches": []}')
        (tmp_path / "smartapi.json").write_text('{"hits": []}')
        if text is not None:
            (tmp_path / "infores_catalog.yaml").write_text(text)
        return SyncedData(tmp_path)

    def test_entries_are_indexed_by_their_infores(self, tmp_path):
        catalog = self._synced(tmp_path, self.CATALOG).catalog()
        assert set(catalog) == {"infores:svc", "infores:upstream"}
        assert catalog["infores:svc"]["name"] == "The Service"

    def test_the_list_is_found_rather_than_named(self, tmp_path):
        # `information_resources` is what the key is called today, in a file
        # another project maintains.
        catalog = self._synced(tmp_path, "resources:\n  - id: infores:svc\n").catalog()
        assert list(catalog) == ["infores:svc"]

    def test_it_reaches_the_row_shaped_for_the_panel(self, tmp_path):
        synced = self._synced(tmp_path, self.CATALOG)
        row = build_rows(
            [_comp("svc", identifiers={"infores": "infores:svc"})], synced
        )[0]
        assert row["catalog"]["status"] == "released"
        assert row["catalog"]["consumes"] == ["infores:upstream"]

    def test_a_component_the_catalog_does_not_list(self, tmp_path):
        synced = self._synced(tmp_path, self.CATALOG)
        row = build_rows(
            [_comp("svc", identifiers={"infores": "infores:nope"})], synced
        )[0]
        assert row["catalog"] is None

    def test_a_component_with_no_infores(self, tmp_path):
        synced = self._synced(tmp_path, self.CATALOG)
        assert build_rows([_comp("svc")], synced)[0]["catalog"] is None

    def test_no_catalog_file_is_none_everywhere(self, tmp_path):
        # The fetch can fail like any other, and every row simply has no
        # catalog block rather than the build ending.
        synced = self._synced(tmp_path)
        assert synced.catalog() == {}
        row = build_rows(
            [_comp("svc", identifiers={"infores": "infores:svc"})], synced
        )[0]
        assert row["catalog"] is None


class TestStaleBodiesKeepTheNewKeys:
    """The 404-this-run rule, over the keys that arrived with the reasons."""

    def test_a_404_this_run_nulls_the_document_and_the_version(self, tmp_path):
        probes = _Probes(tmp_path).probe("ci", 200)
        # A body cached by an earlier run, with no fetch of it this run.
        path = tmp_path / "openapi" / "svc" / "ci.json"
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({"info": {"version": "1.5.4"}}))
        probes.document("openapi", "ci", 404)
        cell = _cell(probes)
        assert cell["version"] is None
        assert cell["document"] is None
        assert cell["trapi_operations"] == []
        assert cell["reason"] == "up · no API document"
