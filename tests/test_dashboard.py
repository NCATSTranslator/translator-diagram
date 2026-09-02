"""Resolving cells and rendering the page, from a fixture directory."""

import base64
import json
import re
from pathlib import Path

import click
import pytest

from translator_diagram import dashboard
from translator_diagram.components import ComponentFile, Deployment
from translator_diagram.dashboard import (
    CELL_REASONS,
    UNPLACED_TITLE,
    SyncedData,
    _helm_facts,
    _instant,
    _last_updated,
    _live_openapi_facts,
    _mark_drift,
    _release_chips,
    _same_version,
    _status_facts,
    build_catalog_edges,
    build_edges,
    build_externals,
    build_payload,
    build_rows,
    in_stage_order,
    load_stages,
    otel_presence,
    render_html,
    source_tally,
    stage_blocks,
    write_dashboard,
)


def _comp(cid, **kwargs):
    kwargs.setdefault("refactor_status", "New in Refactor")
    return ComponentFile(id=cid, name=kwargs.pop("name", cid), owner="DOGSLED", **kwargs)


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


class TestVersionSourceChain:
    def test_a_live_openapi_wins(self, component, synced):
        cell = build_rows([component], synced)[0]["environments"]["ci"]
        assert (cell["version"], cell["version_source"]) == ("2.0.0", "openapi")

    def test_it_falls_back_to_the_stored_smartapi_spec(self, tmp_path, component):
        # ars and ploverdb 404 at every environment; their versions are only in
        # the registry's stored copy.
        (tmp_path / "manifest.json").write_text('{"fetches": []}')
        (tmp_path / "smartapi.json").write_text(json.dumps({"hits": [{
            "_id": "abc", "info": {"version": "7.7.7"},
            "servers": [{"url": "https://svc.ci/", "x-maturity": "staging"}],
        }]}))
        cell = build_rows([component], SyncedData(tmp_path))[0]["environments"]["ci"]
        assert (cell["version"], cell["version_source"]) == ("7.7.7", "smartapi")

    def test_status_beats_the_registry_but_not_the_live_spec(self, tmp_path):
        (tmp_path / "manifest.json").write_text('{"fetches": []}')
        (tmp_path / "smartapi.json").write_text('{"hits": []}')
        path = tmp_path / "status" / "svc" / "ci.json"
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({
            "status": "ok", "nameres_version": "v1.5.2",
            "babel_version": "2025sep1",
            "biolink_model": {"tag": "master"},
        }))
        component = _comp(
            "svc",
            endpoints={"status": "status"},
            environments={"ci": Deployment(env="ci", url="https://svc.ci/")},
        )
        cell = build_rows([component], SyncedData(tmp_path))[0]["environments"]["ci"]
        assert (cell["version"], cell["version_source"]) == ("v1.5.2", "status")
        # babel_version is a *data* release, not the software version.
        assert cell["data_release"] == "babel 2025sep1 · biolink master"

    def test_a_data_release_is_never_read_as_the_software_version(self, tmp_path):
        # A body that reports its Biolink and TRAPI versions before its own.
        # Taking the first *_version key would badge "4.2.5" as the software
        # this component is running, tint its neighbours for drifting from it,
        # and look for release notes under that tag.
        (tmp_path / "manifest.json").write_text('{"fetches": []}')
        (tmp_path / "smartapi.json").write_text('{"hits": []}')
        path = tmp_path / "status" / "svc" / "ci.json"
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({
            "biolink_version": "4.2.5",
            "trapi_version": "1.6.0",
            "plover_version": "2.3.1",
        }))
        component = _comp(
            "svc",
            endpoints={"status": "status"},
            environments={"ci": Deployment(env="ci", url="https://svc.ci/")},
        )
        cell = build_rows([component], SyncedData(tmp_path))[0]["environments"]["ci"]
        assert (cell["version"], cell["version_source"]) == ("2.3.1", "status")

    def test_a_body_with_only_data_releases_reports_no_version(self, tmp_path):
        (tmp_path / "manifest.json").write_text('{"fetches": []}')
        (tmp_path / "smartapi.json").write_text('{"hits": []}')
        path = tmp_path / "status" / "svc" / "ci.json"
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({"babel_version": "2025sep1"}))
        component = _comp(
            "svc",
            endpoints={"status": "status"},
            environments={"ci": Deployment(env="ci", url="https://svc.ci/")},
        )
        cell = build_rows([component], SyncedData(tmp_path))[0]["environments"]["ci"]
        assert cell["version"] is None
        assert cell["data_release"] == "babel 2025sep1"

    def test_the_helm_chart_is_the_last_resort(self, tmp_path):
        # Tier four, and the only tier that describes what *should* be
        # deployed rather than what is. jaeger reaches it: no OpenAPI, no
        # /status, no registration.
        (tmp_path / "manifest.json").write_text('{"fetches": []}')
        (tmp_path / "smartapi.json").write_text('{"hits": []}')
        chart = tmp_path / "helm" / "my-chart"
        chart.mkdir(parents=True)
        (chart / "Chart.yaml").write_text("name: my-chart\nversion: 0.5.2\nappVersion: 1.16.0\n")
        component = _comp(
            "svc",
            identifiers={"helm_chart": "my-chart"},
            endpoints={"openapi": None},
            environments={"ci": Deployment(env="ci", url="https://svc.ci/")},
        )
        cell = build_rows([component], SyncedData(tmp_path))[0]["environments"]["ci"]
        assert (cell["version"], cell["version_source"]) == ("1.16.0", "helm")

    def test_a_live_version_beats_the_chart(self, tmp_path):
        # The chart says what was meant to ship; the endpoint says what did.
        (tmp_path / "manifest.json").write_text('{"fetches": []}')
        (tmp_path / "smartapi.json").write_text('{"hits": []}')
        chart = tmp_path / "helm" / "my-chart"
        chart.mkdir(parents=True)
        (chart / "Chart.yaml").write_text("appVersion: 1.16.0\n")
        live = tmp_path / "openapi" / "svc" / "ci.json"
        live.parent.mkdir(parents=True)
        live.write_text(json.dumps({"info": {"version": "1.17.0"}}))
        component = _comp(
            "svc",
            identifiers={"helm_chart": "my-chart"},
            environments={"ci": Deployment(env="ci", url="https://svc.ci/")},
        )
        cell = build_rows([component], SyncedData(tmp_path))[0]["environments"]["ci"]
        assert (cell["version"], cell["version_source"]) == ("1.17.0", "openapi")

    def test_no_source_at_all_is_recorded_as_such(self, tmp_path):
        (tmp_path / "manifest.json").write_text('{"fetches": []}')
        (tmp_path / "smartapi.json").write_text('{"hits": []}')
        component = _comp("svc", environments={"ci": Deployment(env="ci", url="https://svc.ci/")})
        cell = build_rows([component], SyncedData(tmp_path))[0]["environments"]["ci"]
        assert cell["deployed"] and cell["version"] is None
        assert cell["version_source"] is None

    def test_an_undeployed_environment_is_not_a_missing_version(self, component, synced):
        # Not deployed here, and the cell carries why rather than only that:
        # this component's registration lists three environments and dev is
        # not one of them. What it must not carry is a version, a source, or
        # anything else that would read as a deployment.
        cell = build_rows([component], synced)[0]["environments"]["dev"]
        assert cell == {
            "deployed": False, "reason": "not in registry for dev"
        }


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


class TestDrift:
    def test_the_minority_environment_is_flagged(self):
        cells = {
            "ci": {"deployed": True, "version": "2.0.0"},
            "test": {"deployed": True, "version": "2.0.0"},
            "prod": {"deployed": True, "version": "1.0.0"},
        }
        _mark_drift(cells, "version")
        assert "version" in cells["prod"]["drift"]
        assert "drift" not in cells["ci"]

    def test_agreement_flags_nothing(self):
        cells = {e: {"deployed": True, "version": "1.0"} for e in ("ci", "test")}
        _mark_drift(cells, "version")
        assert all("drift" not in c for c in cells.values())

    def test_a_single_environment_is_never_the_odd_one_out(self):
        cells = {"prod": {"deployed": True, "version": "1.0"}}
        _mark_drift(cells, "version")
        assert "drift" not in cells["prod"]

    def test_an_even_split_marks_every_environment(self):
        # Two against two has no majority worth the name: leaving both
        # unmarked would hide a genuine disagreement, and marking one side
        # would pick it by column order — the pair further right was always
        # the deviant, whichever pair was newer.
        cells = {
            "dev": {"deployed": True, "version": "a"},
            "ci": {"deployed": True, "version": "a"},
            "test": {"deployed": True, "version": "b"},
            "prod": {"deployed": True, "version": "b"},
        }
        _mark_drift(cells, "version")
        marked = [e for e, c in cells.items() if c.get("drift")]
        assert marked == ["dev", "ci", "test", "prod"]

    def test_two_environments_that_disagree_are_both_marked(self):
        # One against one: neither is in the minority, so calling either of
        # them the odd one out is a coin toss dressed up as a finding.
        cells = {
            "test": {"deployed": True, "version": "a"},
            "prod": {"deployed": True, "version": "b"},
        }
        _mark_drift(cells, "version")
        assert [e for e, c in cells.items() if c.get("drift")] == ["test", "prod"]

    def test_a_plurality_is_still_a_majority(self):
        # Three ways, one of them twice: the two that agree are the baseline
        # and the other two are each marked against it.
        cells = {
            "dev": {"deployed": True, "version": "a"},
            "ci": {"deployed": True, "version": "a"},
            "test": {"deployed": True, "version": "b"},
            "prod": {"deployed": True, "version": "c"},
        }
        _mark_drift(cells, "version")
        assert [e for e, c in cells.items() if c.get("drift")] == ["test", "prod"]

    def test_missing_values_are_not_drift(self):
        # An environment that reports nothing is not disagreeing.
        cells = {
            "ci": {"deployed": True, "version": "1.0"},
            "test": {"deployed": True, "version": None},
        }
        _mark_drift(cells, "version")
        assert all("drift" not in c for c in cells.values())

    def test_end_to_end_prod_is_flagged(self, component, synced):
        row = build_rows([component], synced)[0]
        assert row["environments"]["prod"]["drift"] == ["version"]


class TestPayload:
    def test_the_tally_counts_every_deployment(self, component, synced):
        rows = build_rows([component], synced)
        tally = source_tally(rows)
        assert sum(tally.values()) == 3  # ci, test, prod
        assert tally["openapi"] == 3

    def test_uptime_comes_from_the_registry(self, component, synced):
        assert build_rows([component], synced)[0]["uptime"] == "pass"

    def test_payload_carries_the_sync_timestamp(self, component, synced):
        payload = build_payload([component], synced)
        assert payload["generated_at"] == "2026-08-31T00:01:00+00:00"
        assert payload["sync_counts"]["failed"] == 1

    def test_both_badge_vocabularies_reach_the_page(self, component, synced):
        # The page renders a badge by looking its key up in these; a key the
        # payload does not carry renders as the raw key, which is how "openapi"
        # or "registry" would end up in the table in lower case.
        payload = build_payload([component], synced)
        assert payload["source_labels"]["openapi"] == "OpenAPI"
        assert set(payload["updated_labels"]) == {"release", "registry"}

    def test_owner_styles_reach_the_payload(self, component, synced):
        # Derived once here rather than in each renderer: a page and a legend
        # working out the same gradient separately is how the two come to
        # disagree about what colour a team is.
        styles = build_payload([component], synced)["owner_styles"]
        assert set(styles) == set(build_payload([component], synced)["owner_colors"])
        one = styles["DOGSLED"]
        assert one["text"] in ("black", "white")
        assert len(one["metal"]) == 4
        assert one["base"].startswith("#")

    def test_unclaimed_charts_and_suggestions_reach_the_payload(self, synced):
        # The two lists a data PR is written from: charts nothing accounts for,
        # and registry records we attached ourselves that want an id recording.
        root = synced.root
        (root / "helm").mkdir(exist_ok=True)
        (root / "helm" / "index.json").write_text(json.dumps([
            {"name": "my-chart", "type": "dir"},
            {"name": "robokop", "type": "dir"},
            {"name": "README.md", "type": "file"},
        ]))
        for chart, description in (
            ("my-chart", "A Helm chart for Kubernetes"),
            ("robokop", "The ROBOKOP user interface"),
        ):
            (root / "helm" / chart).mkdir()
            (root / "helm" / chart / "Chart.yaml").write_text(
                f"name: {chart}\ndescription: {description}\n"
            )
        (root / "smartapi.json").write_text(json.dumps({"hits": [{
            "_id": "xyz",
            "info": {"title": "Service API",
                     "x-translator": {"infores": "infores:svc"}},
            "servers": [{"url": "https://svc.ci/", "x-maturity": "staging"}],
        }]}))
        component = _comp("svc", identifiers={
            "infores": "infores:svc", "helm_chart": "my-chart"})
        payload = build_payload([component], SyncedData(root))
        assert payload["unclaimed_charts"] == [
            {"name": "robokop", "description": "The ROBOKOP user interface"}]
        assert payload["smartapi_suggestions"] == [{
            "component": "svc", "smartapi_id": "xyz", "title": "Service API",
            "matched_by": "infores"}]

    def test_a_chart_a_withheld_component_claims_is_not_unclaimed(
        self, synced, tmp_path
    ):
        # `unclaimed_charts` is matched against every component rather than the
        # kept rows, and this is why: asking the rows would publish `jaeger` by
        # name on the one build that must not say it.
        from translator_diagram.privacy import Policy, Redaction

        root = synced.root
        (root / "helm").mkdir(exist_ok=True)
        (root / "helm" / "index.json").write_text(
            json.dumps([{"name": "jaeger", "type": "dir"}])
        )
        (root / "helm" / "jaeger").mkdir()
        (root / "helm" / "jaeger" / "Chart.yaml").write_text("name: jaeger\n")
        components = [
            _comp("svc", identifiers={"smartapi": "abc"}),
            _comp("jaeger", identifiers={"helm_chart": "jaeger"}),
        ]
        payload = build_payload(
            components, SyncedData(root), Policy(components=(Redaction("jaeger"),))
        )
        assert payload["unclaimed_charts"] == []

    def test_every_row_carries_what_a_band_needs(self, component, synced):
        # Adding a key to the payload is safe and renaming one is not: the JS
        # reads these three by name to draw a band, and a row missing any of
        # them silently loses its heading.
        row = build_payload([component], synced)["rows"][0]
        for key in ("step", "step_label", "step_title", "step_description"):
            assert key in row


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


class TestCatalogEdges:
    """The catalog's own dataflow graph, between components the page shows."""

    def _catalog_row(self, cid, infores, **catalog):
        return _row(
            cid,
            infores=infores,
            catalog={"consumes": [], "consumed_by": [], **catalog},
        )

    def test_consumes_points_from_the_consumed_to_the_consumer(self):
        rows = [
            self._catalog_row("ars", "infores:ars", consumes=["infores:arax"]),
            self._catalog_row("arax", "infores:arax"),
        ]
        assert build_catalog_edges(rows) == [
            {"from": "arax", "to": "ars", "kind": "catalog"}]

    def test_consumed_by_gives_the_mirror(self):
        rows = [
            self._catalog_row("arax", "infores:arax", consumed_by=["infores:ars"]),
            self._catalog_row("ars", "infores:ars"),
        ]
        assert build_catalog_edges(rows) == [
            {"from": "arax", "to": "ars", "kind": "catalog"}]

    def test_the_two_statements_are_deduped(self):
        # The catalog records most of these from both ends.
        rows = [
            self._catalog_row("ars", "infores:ars", consumes=["infores:arax"]),
            self._catalog_row("arax", "infores:arax", consumed_by=["infores:ars"]),
        ]
        assert build_catalog_edges(rows) == [
            {"from": "arax", "to": "ars", "kind": "catalog"}]

    def test_an_infores_with_no_row_is_dropped(self):
        # arax consumes forty-odd knowledge sources, and none of them is a
        # component here. A withheld component has no row either, which is what
        # keeps a published build's catalog graph honest without a second pass.
        rows = [self._catalog_row(
            "arax", "infores:arax", consumes=["infores:automat-cohd"])]
        assert build_catalog_edges(rows) == []

    def test_a_row_with_no_catalog_entry_contributes_nothing(self):
        assert build_catalog_edges([_row("svc")]) == []


class TestRecordsMatchedByInfores:
    """A record found by infores is the same document, found differently."""

    def _synced(self, tmp_path):
        (tmp_path / "manifest.json").write_text('{"fetches": []}')
        (tmp_path / "smartapi.json").write_text(json.dumps({"hits": [{
            "_id": "xyz",
            "info": {
                "title": "Service API",
                "version": "9.9.9",
                "x-translator": {"infores": "infores:svc"},
                "x-trapi": {"version": "1.5.0"},
            },
            "_status": {"uptime_status": "pass"},
            "servers": [
                {"url": "https://svc.ci/", "x-maturity": "staging"},
                {"url": "https://svc/", "x-maturity": "production"},
            ],
        }]}))
        return SyncedData(tmp_path)

    def _row(self, tmp_path, **identifiers):
        return build_rows(
            [_comp("svc", identifiers=identifiers)], self._synced(tmp_path)
        )[0]

    def test_it_supplies_deployments_the_way_an_id_match_does(self, tmp_path):
        # The environments the registry lists have to appear either way: a
        # component whose file records an infores and no smartapi id is
        # registered, and showing it as deployed nowhere would be a gap we
        # made ourselves.
        row = self._row(tmp_path, infores="infores:svc")
        deployed = {
            env for env, cell in row["environments"].items() if cell["deployed"]
        }
        assert deployed == {"ci", "prod"}
        assert row["environments"]["ci"]["url"] == "https://svc.ci/"

    def test_the_same_environments_as_the_recorded_id(self, tmp_path):
        by_infores = self._row(tmp_path, infores="infores:svc")
        by_id = self._row(tmp_path, smartapi="xyz")
        assert by_infores["environments"] == by_id["environments"]

    def test_the_version_chain_and_the_uptime_read_it_too(self, tmp_path):
        row = self._row(tmp_path, infores="infores:svc")
        assert row["environments"]["ci"]["version"] == "9.9.9"
        assert row["environments"]["ci"]["version_source"] == "smartapi"
        assert row["uptime"] == "pass"

    def test_the_record_says_how_it_was_matched(self, tmp_path):
        assert self._row(tmp_path, infores="infores:svc")[
            "smartapi_record"]["matched_by"] == "infores"
        assert self._row(tmp_path, smartapi="xyz")[
            "smartapi_record"]["matched_by"] == "id"

    def test_a_matched_record_does_not_make_an_environment_unregistered(
        self, tmp_path
    ):
        # "This environment is missing from the registration" is a claim about
        # a registration somebody filed. A match we made ourselves cannot be
        # the evidence for a gap we then report.
        row = self._row(tmp_path, infores="infores:svc")
        assert not any(cell.get("unregistered")
                       for cell in row["environments"].values())

    def test_matching_leaves_the_shared_registry_untouched(self, tmp_path):
        # Every row reads one dictionary per record, and stamping how *this*
        # component found it onto the registry's own copy is how two components
        # come to disagree about one document.
        synced = self._synced(tmp_path)
        build_rows([_comp("svc", identifiers={"infores": "infores:svc"})], synced)
        assert "_matched_by" not in synced.smartapi["xyz"]


class TestOtelTile:
    def _synced(self, tmp_path, bodies):
        (tmp_path / "manifest.json").write_text('{"fetches": []}')
        (tmp_path / "smartapi.json").write_text('{"hits": []}')
        (tmp_path / "otel").mkdir()
        for env, body in bodies.items():
            (tmp_path / "otel" / f"{env}.json").write_text(json.dumps(body))
        return SyncedData(tmp_path)

    def test_the_total_is_distinct_across_collectors(self, tmp_path, component):
        # Only a couple of services report to all three, so summing the three
        # counts would count most of them twice over.
        synced = self._synced(tmp_path, {
            "ci": {"data": ["a", "b"]},
            "test": {"data": ["b", "c"]},
            "prod": {"data": ["c"]},
        })
        payload = build_payload([component], synced)
        assert payload["otel_service_counts"] == {"ci": 2, "test": 2, "prod": 1}
        assert payload["otel_service_total"] == 3

    def test_a_collector_answering_with_objects_costs_the_tile_not_the_build(
        self, tmp_path, component
    ):
        # `data` is an array of service names today. An array of objects would
        # be unhashable, and taking the whole build down over a footnote tile
        # is not a trade worth making.
        synced = self._synced(tmp_path, {
            "ci": {"data": [{"name": "a"}, "b"]},
            "test": {"data": "not-a-list"},
            "prod": {},
        })
        payload = build_payload([component], synced)
        assert payload["otel_service_counts"] == {"ci": 1, "test": 0, "prod": 0}
        assert payload["otel_service_total"] == 1


class TestRendering:
    def test_every_component_appears(self, component, synced):
        html = render_html(build_payload([component], synced))
        assert "svc" in html

    def test_the_inlined_payload_matches_the_written_json(self, component, synced, tmp_path):
        payload = build_payload([component], synced)
        html_path, json_path = write_dashboard(payload, tmp_path / "out")
        html = html_path.read_text()
        start = html.index('id="payload">') + len('id="payload">')
        inline = html[start:html.index("</script>", start)].replace("<\\/", "</")
        assert json.loads(inline) == json.loads(json_path.read_text())

    def test_a_closing_script_tag_in_the_data_cannot_escape(self, tmp_path, synced):
        # Notes come from a spreadsheet. An unescaped </script> there would end
        # the block early and break the page for everyone.
        component = _comp("svc", identifiers={"smartapi": "abc"}, notes="</script><b>x")
        html = render_html(build_payload([component], synced))
        body = html[html.index('id="payload">'):]
        assert "</script><b>" not in body[: body.index("</script>")]

    def test_the_page_is_self_contained(self, component, synced):
        """No external resources: it must open from file://, with no network.

        The rule is what a `<link>` points *at*, not whether there is one. It
        used to be "no <link at all", which was the same thing while the page
        had none — and stopped being the same thing the moment the favicon
        arrived, because an icon inlined as a data URI is not a resource and
        fetches nothing. So every link is checked for a data: href, and a
        stylesheet from a CDN fails here exactly as it did before.
        """
        html = render_html(build_payload([component], synced))
        links = re.findall(r"<link[^>]*>", html)
        assert links, "the favicon link is gone: this test now checks nothing"
        for tag in links:
            assert 'href="data:' in tag, tag
        assert "script src=" not in html

    def test_the_page_carries_the_icon_it_ships(self, component, synced):
        # The bytes in web/favicon.ico, not a placeholder and not a re-encode:
        # what goes into the page has to be the file the repository holds.
        raw = (
            Path(dashboard.__file__).parent / "web" / dashboard.FAVICON_FILE
        ).read_bytes()
        html = render_html(build_payload([component], synced))
        expected = base64.b64encode(raw).decode("ascii")
        assert f'href="data:image/x-icon;base64,{expected}"' in html

    def test_the_page_asks_not_to_be_indexed(self, component, synced):
        """Reachable by link, not by search. A deliberate decision that should
        be removed on purpose rather than lost in a template edit — see the
        public/private split in issue #7."""
        html = render_html(build_payload([component], synced))
        assert '<meta name="robots" content="noindex, nofollow">' in html


class _Probes:
    """A sync directory built one recorded probe at a time.

    Every test below turns on the same thing -- which requests this run made
    and how each answered -- and writing that as a manifest by hand four lines
    at a time is how a fixture comes to disagree with what `sync` actually
    writes. So: one builder, the same shapes `sync.probe_to` and
    `sync.fetch_to` produce, and the manifest assembled from what was asked
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


class TestReachable:
    """Three states, because "we did not ask" is not "it did not answer"."""

    def test_a_live_root_is_reachable_even_with_no_document(self, tmp_path):
        # The bug this whole change is for: the four UI environments record no
        # OpenAPI endpoint, so nothing was fetched, so the page drew four live
        # hosts with a red dot and no HTTP status beside it.
        probes = _Probes(tmp_path).probe("ci", 200)
        cell = _cell(probes, _comp(
            "svc",
            endpoints={"openapi": None},
            environments={"ci": Deployment(env="ci", url="https://svc.ci/")},
        ))
        assert cell["reachable"] is True
        assert cell["root_status"] == 200
        assert cell["http_status"] is None

    def test_a_document_that_answered_is_enough_on_its_own(self, tmp_path):
        probes = (_Probes(tmp_path)
                  .probe("ci", None, error="URLError: refused")
                  .document("openapi", "ci", 200, {"info": {"version": "1.0.0"}}))
        assert _cell(probes)["reachable"] is True

    def test_every_probe_failing_is_not_reachable(self, tmp_path):
        probes = (_Probes(tmp_path)
                  .probe("ci", None, error="URLError: nodename nor servname")
                  .document("openapi", "ci", None, error="URLError: nodename"))
        cell = _cell(probes)
        assert cell["reachable"] is False
        assert cell["root_status"] is None

    def test_a_500_everywhere_is_not_reachable_either(self, tmp_path):
        probes = (_Probes(tmp_path)
                  .probe("ci", 502)
                  .document("openapi", "ci", 502))
        assert _cell(probes)["reachable"] is False

    def test_a_404_at_the_root_is_still_not_reachable(self, tmp_path):
        # Kept for the old contract: a 404 is the host saying "not here", and
        # `reachable` counts 2xx and 3xx only.
        assert _cell(_Probes(tmp_path).probe("ci", 404))["reachable"] is False

    def test_a_redirect_counts_as_up(self, tmp_path):
        assert _cell(_Probes(tmp_path).probe("ci", 302))["reachable"] is True

    def test_nothing_probed_is_null_not_false(self, tmp_path):
        # A cache written before root probes existed, or a component added
        # between a sync and a build. Neither is a finding about the host, and
        # drawing it as one would be the page claiming a service is down
        # because it forgot to ask.
        assert _cell(_Probes(tmp_path))["reachable"] is None

    def test_a_health_body_reporting_green_is_reachable(self, tmp_path):
        # pending-api: `{"success": true, "status": "green"}`, no version key
        # anywhere in it. `_status_facts` reads it without falling over, and
        # the cell is reachable on the strength of the 200 that carried it.
        probes = _Probes(tmp_path).document(
            "status", "ci", 200, {"success": True, "status": "green"}
        )
        cell = _cell(probes, _comp(
            "svc",
            endpoints={"openapi": None, "status": "status"},
            environments={"ci": Deployment(env="ci", url="https://svc.ci/")},
        ))
        assert cell["reachable"] is True
        assert cell["version"] is None


class TestCellReasons:
    """Every string in CELL_REASONS, driven from the shape that produces it.

    One test per label, because the labels are a vocabulary three things share
    -- this module, the page, and the person reading it -- and a rename that
    only half of them hears about is the failure they exist to prevent.
    """

    def test_not_in_registry_for_this_environment(self, tmp_path):
        probes = _Probes(tmp_path).registry([{
            "_id": "abc", "servers": [
                {"url": "https://svc/", "x-maturity": "production"}],
        }])
        component = _comp("svc", identifiers={"smartapi": "abc"})
        cell = build_rows([component], probes.build())[0]["environments"]["ci"]
        assert cell == {"deployed": False, "reason": "not in registry for ci"}

    def test_no_such_host(self, tmp_path):
        # Nine of the derived candidates do not resolve; curl exits 6 and the
        # probe records a URLError.
        probes = _Probes(tmp_path).rejected(
            "prod", "https://svc.transltr.io/",
            status=None, error="URLError: nodename nor servname provided",
        )
        cell = build_rows([_comp("svc")], probes.build())[0]["environments"]["prod"]
        assert cell["reason"] == "no such host"

    def test_a_host_that_answers_as_another_service(self, tmp_path):
        # The dangerous one, and the reason `_confirm_derived` exists: the
        # convention predicted a host, something is serving there, and the
        # OpenAPI document it returned reports somebody else's infores.
        probes = _Probes(tmp_path).rejected(
            "prod", "https://svc.transltr.io/",
            status=200, error=None, checked="document",
        )
        cell = build_rows([_comp("svc")], probes.build())[0]["environments"]["prod"]
        assert cell["reason"] == "host answers as another service"

    def test_a_live_host_nothing_could_verify(self, tmp_path):
        # The same 200, asked a weaker question. A component with no infores
        # gets a root probe rather than a document check, and a page that
        # called this "another service" would be inventing the very finding
        # the check could not make. Something is there; we cannot say what.
        probes = _Probes(tmp_path).rejected(
            "test", "https://svc.test.transltr.io/",
            status=200, error=None, checked="root",
        )
        cell = build_rows([_comp("svc")], probes.build())[0]["environments"]["test"]
        assert cell["reason"] == "host answers, unverified"

    def test_a_candidate_that_settled_nothing(self, tmp_path):
        probes = _Probes(tmp_path).rejected(
            "prod", "https://svc.transltr.io/", status=404, error=None
        )
        cell = build_rows([_comp("svc")], probes.build())[0]["environments"]["prod"]
        assert cell["reason"] == "probed, not confirmed"

    def test_no_host_recorded(self, tmp_path):
        # Nothing known at all: no registration, no recorded URL, no candidate
        # ever derived. A gap in this repository, not a finding about the
        # platform, and the wording says so.
        cell = build_rows([_comp("svc")], _Probes(tmp_path).build())
        assert cell[0]["environments"]["prod"]["reason"] == "no host recorded"

    def test_a_component_that_is_not_a_hosted_service(self, tmp_path):
        component = _comp("svc", hosted_at="Local")
        cell = build_rows([component], _Probes(tmp_path).build())
        assert cell[0]["environments"]["ci"]["reason"] == "not a hosted service"

    def test_up_with_no_api_document(self, tmp_path):
        # kgx-storage's ci: / answers 200, openapi.json 404s.
        probes = (_Probes(tmp_path)
                  .probe("ci", 200)
                  .document("openapi", "ci", 404))
        assert _cell(probes)["reason"] == "up · no API document"

    def test_up_serving_html_where_a_document_should_be(self, tmp_path):
        # A single-page app answers 200 to every path, so the fetch looks like
        # a success and the body parses as nothing. Reported as None it was
        # indistinguishable from never having asked.
        probes = (_Probes(tmp_path)
                  .probe("ci", 200)
                  .document("openapi", "ci", 200, "<html><body>app</body></html>"))
        cell = _cell(probes)
        assert cell["document"] == "not-json"
        assert cell["reason"] == "up · serves HTML, no API document"

    def test_up_with_a_document_that_has_no_version(self, tmp_path):
        probes = (_Probes(tmp_path)
                  .probe("ci", 200)
                  .document("openapi", "ci", 200, {"info": {"title": "KGX"}}))
        cell = _cell(probes)
        assert cell["document"] == "no-version"
        assert cell["reason"] == "up · document has no version"

    def test_a_status_body_with_no_version_says_so_too(self, tmp_path):
        probes = (_Probes(tmp_path)
                  .probe("ci", 200)
                  .document("status", "ci", 200, {"success": True, "status": "green"}))
        cell = _cell(probes, _comp(
            "svc",
            endpoints={"openapi": None, "status": "status"},
            environments={"ci": Deployment(env="ci", url="https://svc.ci/")},
        ))
        assert cell["reason"] == "up · document has no version"

    def test_up_with_nowhere_to_look_for_a_version(self, tmp_path):
        # The UI: four hosts that are up, record `openapi: null`, and publish
        # no version anywhere. Different from a 404, which is an endpoint we
        # asked for and did not get.
        probes = _Probes(tmp_path).probe("ci", 200)
        cell = _cell(probes, _comp(
            "svc",
            endpoints={"openapi": None},
            environments={"ci": Deployment(env="ci", url="https://svc.ci/")},
        ))
        assert cell["reason"] == "up · no version endpoint"

    def test_unreachable(self, tmp_path):
        probes = (_Probes(tmp_path)
                  .probe("ci", None, error="URLError: nodename nor servname")
                  .document("openapi", "ci", None, error="URLError: nodename"))
        assert _cell(probes)["reason"] == "unreachable"

    def test_an_http_error_on_the_document_of_a_live_host(self, tmp_path):
        probes = (_Probes(tmp_path)
                  .probe("ci", 200)
                  .document("openapi", "ci", 503))
        assert _cell(probes)["reason"] == "HTTP 503"

    def test_a_403_on_the_document_is_the_documents_problem(self, tmp_path):
        probes = (_Probes(tmp_path)
                  .probe("ci", 200)
                  .document("openapi", "ci", 403))
        assert _cell(probes)["reason"] == "HTTP 403"

    def test_nothing_probed_says_so_rather_than_guessing(self, tmp_path):
        assert _cell(_Probes(tmp_path))["reason"] == "not probed"

    def test_a_cell_with_a_version_has_no_reason(self, tmp_path):
        probes = (_Probes(tmp_path)
                  .probe("ci", 200)
                  .document("openapi", "ci", 200, {"info": {"version": "1.2.3"}}))
        cell = _cell(probes)
        assert cell["version"] == "1.2.3"
        assert cell["reason"] is None
        assert cell["document"] == "version"

    def test_every_reason_shipped_is_in_the_vocabulary(self, tmp_path):
        # The labels live in one dict so the page can trust them. A string
        # written straight into `build_cell` would render fine and be
        # invisible to anyone reading CELL_REASONS to find out what a cell can
        # say, which is what this catches.
        known = {
            value.replace("{env}", "ci").replace("{code}", "503")
            for value in CELL_REASONS.values()
        }
        probes = (_Probes(tmp_path)
                  .probe("ci", 200)
                  .document("openapi", "ci", 503))
        assert _cell(probes)["reason"] in known


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


class TestInferredEnvironments:
    """A registry record that describes its servers rather than declaring them."""

    def test_the_cell_says_the_maturity_was_inferred(self, tmp_path):
        probes = _Probes(tmp_path).registry([{
            "_id": "abc",
            "info": {"version": "3.1.0"},
            "servers": [
                {"url": "https://svc/", "description": "Production server"}],
        }])
        component = _comp("svc", identifiers={"smartapi": "abc"})
        cell = build_rows([component], probes.build())[0]["environments"]["prod"]
        assert cell["deployed"] and cell["inferred"] is True
        assert cell["version"] == "3.1.0"

    def test_a_declared_environment_carries_no_such_key(self, tmp_path):
        probes = _Probes(tmp_path).registry([{
            "_id": "abc", "servers": [
                {"url": "https://svc/", "x-maturity": "production"}],
        }])
        component = _comp("svc", identifiers={"smartapi": "abc"})
        cell = build_rows([component], probes.build())[0]["environments"]["prod"]
        assert "inferred" not in cell


class TestDerivedDeployments:
    """Environments found by convention rather than registered anywhere."""

    def test_a_derived_environment_is_used_and_marked(self, tmp_path):
        (tmp_path / "manifest.json").write_text('{"fetches": []}')
        (tmp_path / "smartapi.json").write_text('{"hits": []}')
        (tmp_path / "derived.json").write_text(json.dumps({"confirmed": {
            "svc": {"ci": {"url": "https://svc.ci.transltr.io/", "location": "ITRB"}}}}))
        path = tmp_path / "openapi" / "svc" / "ci.json"
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({"info": {"version": "0.8.2"}}))

        cell = build_rows([_comp("svc")], SyncedData(tmp_path))[0]["environments"]["ci"]
        assert cell["deployed"] and cell["version"] == "0.8.2"

    def test_a_registered_environment_wins_over_a_derived_one(self, tmp_path):
        # Precedence is recorded, then registered, then derived. A derived URL
        # is a discovery; anything stated explicitly outranks it.
        (tmp_path / "manifest.json").write_text('{"fetches": []}')
        (tmp_path / "smartapi.json").write_text(json.dumps({"hits": [{
            "_id": "abc", "info": {},
            "servers": [{"url": "https://registered.ci/", "x-maturity": "staging"}],
        }]}))
        (tmp_path / "derived.json").write_text(json.dumps({"confirmed": {
            "svc": {"ci": {"url": "https://derived.ci/", "location": "ITRB"}}}}))
        component = _comp("svc", identifiers={"smartapi": "abc"})
        cell = build_rows([component], SyncedData(tmp_path))[0]["environments"]["ci"]
        assert cell["url"] == "https://registered.ci/"

    def test_no_derived_file_is_not_an_error(self, tmp_path):
        (tmp_path / "manifest.json").write_text('{"fetches": []}')
        (tmp_path / "smartapi.json").write_text('{"hits": []}')
        assert SyncedData(tmp_path).derived == {}

    def test_the_derived_urls_are_loaded(self, tmp_path):
        (tmp_path / "manifest.json").write_text('{"fetches": []}')
        (tmp_path / "smartapi.json").write_text('{"hits": []}')
        (tmp_path / "derived.json").write_text(json.dumps({"confirmed": {
            "svc": {"ci": {"url": "https://svc.ci.transltr.io/"},
                    "test": {"url": "https://svc.test.transltr.io/"}}}}))
        assert set(SyncedData(tmp_path).derived["svc"]) == {"ci", "test"}


class TestHelmFacts:
    def test_images_come_from_the_per_chart_manifest(self, tmp_path):
        # Chart.yaml carries no image information at all; ncats-images-meta.yaml
        # is where it lives, and its keys are per-chart rather than a schema.
        chart = tmp_path / "helm" / "name-lookup"
        chart.mkdir(parents=True)
        (chart / "Chart.yaml").write_text("version: 0.5.2\nappVersion: 1.5.2_2025sep1\n")
        (chart / "ncats-images-meta.yaml").write_text(
            "nameLookup:\n  image: ghcr.io/ncatstranslator/nameresolution\n"
            "  version: v1.5.2\nsolr:\n  image: solr\n  version: '9.1'\n"
        )
        facts = _helm_facts(SyncedData(tmp_path), "name-lookup")
        assert facts["version"] == "1.5.2_2025sep1"
        assert facts["chart_version"] == "0.5.2"
        assert facts["images"] == ["nameresolution:v1.5.2", "solr:9.1"]

    def test_a_missing_chart_is_empty_not_an_error(self, tmp_path):
        assert _helm_facts(SyncedData(tmp_path), "no-such-chart") == {
            "version": None, "chart_version": None, "images": []}

    def test_no_chart_recorded_yields_nothing(self, tmp_path):
        assert _helm_facts(SyncedData(tmp_path), None) == {}

    def test_malformed_yaml_does_not_raise(self, tmp_path):
        # A 200 that was not really YAML. The page must still render.
        chart = tmp_path / "helm" / "broken"
        chart.mkdir(parents=True)
        (chart / "Chart.yaml").write_text("this: [is: not: valid\n")
        assert _helm_facts(SyncedData(tmp_path), "broken")["version"] is None


def _release(tag, **kwargs):
    return {
        "tag_name": tag,
        "name": kwargs.pop("name", tag),
        "html_url": kwargs.pop("html_url", f"https://github.com/a/b/releases/tag/{tag}"),
        "published_at": kwargs.pop("published_at", "2026-08-01T00:00:00Z"),
        **kwargs,
    }


class TestSameVersion:
    def test_the_v_prefix_is_ignored(self):
        # NameResolution tags v1.5.2 and reports 1.5.2.
        assert _same_version("v1.5.2", "1.5.2")
        assert _same_version("1.5.2", "V1.5.2")

    def test_different_versions_do_not_match(self):
        assert not _same_version("v1.5.2", "1.5.1")
        # node-annotator reports "1.0" in ci and "1.0.0" in prod; they are not
        # the same string, and guessing they are the same release would put a
        # wrong link on a row.
        assert not _same_version("v1.0.0", "1.0")

    def test_a_missing_side_never_matches(self):
        assert not _same_version(None, "1.0")
        assert not _same_version("v1.0", None)


class TestReleaseChips:
    def test_the_newest_few(self):
        entries = [_release(f"v{n}.0.0") for n in (9, 8, 7, 6, 5)]
        assert [c["tag"] for c in _release_chips(entries, set())] == [
            "v9.0.0", "v8.0.0", "v7.0.0"]

    def test_a_deployed_older_release_is_kept(self):
        # answer-appraiser's prod trails its ci by two minor versions; the
        # notes for what prod is running are the ones worth a link.
        entries = [_release(f"v0.{n}.0") for n in (8, 7, 6, 5, 4)]
        chips = _release_chips(entries, {"0.4.0"})
        assert [c["tag"] for c in chips] == ["v0.8.0", "v0.7.0", "v0.6.0", "v0.4.0"]
        assert [c["deployed"] for c in chips] == [False, False, False, True]

    def test_a_deployed_newest_release_is_marked_not_duplicated(self):
        chips = _release_chips([_release("v2.0.0"), _release("v1.0.0")], {"2.0.0"})
        assert [(c["tag"], c["deployed"]) for c in chips] == [
            ("v2.0.0", True), ("v1.0.0", False)]

    def test_published_order_beats_the_order_github_returned(self):
        # Real: NameResolution's v1.5.2 was created after v1.6.2, so GitHub
        # lists it first while its date says otherwise.
        entries = [
            _release("v1.7.0", published_at="2026-07-23T00:00:00Z"),
            _release("v1.5.2", published_at="2026-04-08T00:00:00Z"),
            _release("v1.6.2", published_at="2026-02-20T00:00:00Z"),
        ]
        assert [c["published"] for c in _release_chips(entries, set())] == [
            "2026-07-23", "2026-04-08", "2026-02-20"]

    def test_drafts_are_dropped(self):
        # Invisible without a token, visible with one: a link that works only
        # for whoever ran the sync is worse than no link.
        chips = _release_chips(
            [_release("v2.0.0", draft=True), _release("v1.0.0")], set()
        )
        assert [c["tag"] for c in chips] == ["v1.0.0"]

    def test_drafts_do_not_use_up_the_three_places(self):
        # The two newest entries are drafts, so the three chips worth showing
        # are the three published releases below them.
        entries = [
            _release("v9.0.0", draft=True, published_at="2026-08-09T00:00:00Z"),
            _release("v8.0.0", draft=True, published_at="2026-08-08T00:00:00Z"),
            _release("v7.0.0", published_at="2026-08-07T00:00:00Z"),
            _release("v6.0.0", published_at="2026-08-06T00:00:00Z"),
            _release("v5.0.0", published_at="2026-08-05T00:00:00Z"),
            _release("v4.0.0", published_at="2026-08-04T00:00:00Z"),
        ]
        assert [c["tag"] for c in _release_chips(entries, set())] == [
            "v7.0.0", "v6.0.0", "v5.0.0"]

    def test_a_tagless_entry_does_not_either(self):
        entries = [
            {"html_url": "https://x/", "published_at": "2026-08-09T00:00:00Z"},
            _release("v7.0.0", published_at="2026-08-07T00:00:00Z"),
            _release("v6.0.0", published_at="2026-08-06T00:00:00Z"),
            _release("v5.0.0", published_at="2026-08-05T00:00:00Z"),
        ]
        assert [c["tag"] for c in _release_chips(entries, set())] == [
            "v7.0.0", "v6.0.0", "v5.0.0"]

    def test_the_fields_the_page_renders(self):
        chip = _release_chips([_release("v1.0.0", prerelease=True)], set())[0]
        assert chip["url"] == "https://github.com/a/b/releases/tag/v1.0.0"
        assert chip["published"] == "2026-08-01"
        assert chip["prerelease"] is True

    def test_an_entry_without_a_tag_is_skipped(self):
        assert _release_chips([{"html_url": "https://x/"}], set()) == []

    def test_no_releases_at_all(self):
        assert _release_chips([], {"1.0.0"}) == []


class TestReleasesOnRows:
    def _with_releases(self, synced, entries):
        path = synced.root / "releases" / "a" / "b.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(entries))
        return synced

    def test_the_row_carries_the_repository_releases(self, synced, component):
        self._with_releases(synced, [_release("v2.0.0"), _release("v1.0.0")])
        component.repositories = [
            {"url": "https://github.com/a/b", "role": "source"}
        ]
        row = build_rows([component], synced)[0]
        # The fixture runs 2.0.0 in ci and test, 1.0.0 in prod: both releases
        # are deployed somewhere, which is the whole point of the column.
        assert [(c["tag"], c["deployed"]) for c in row["releases"]] == [
            ("v2.0.0", True), ("v1.0.0", True)]

    def test_a_component_with_no_repository(self, synced, component):
        assert build_rows([component], synced)[0]["releases"] == []

    def test_a_rate_limited_body_is_not_a_release_list(self, synced, component):
        # GitHub answers a throttled request with an object, not an array.
        path = synced.root / "releases" / "a" / "b.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"message": "API rate limit exceeded"}))
        component.repositories = [
            {"url": "https://github.com/a/b", "role": "source"}
        ]
        assert build_rows([component], synced)[0]["releases"] == []


class TestLastUpdated:
    def _record(self, last_updated):
        return {"_meta": {"last_updated": last_updated}}

    def test_a_release_alone(self):
        got = _last_updated([_release("v1.0.0", published_at="2026-08-01T00:00:00Z")], {})
        assert got["date"] == "2026-08-01"
        assert got["source"] == "release"
        assert got["tag"] == "v1.0.0"

    def test_a_registration_alone(self):
        got = _last_updated([], self._record("2026-07-28T07:00:57.687292+00:00"))
        assert (got["date"], got["source"], got["tag"]) == ("2026-07-28", "registry", None)

    def test_neither_is_none_not_an_error(self):
        # True for 13 of 26 components: no releases, and in no registry.
        assert _last_updated([], {}) is None
        assert _last_updated([], {"_meta": {}}) is None

    def test_the_newer_signal_wins_either_way(self):
        older = "2026-01-01T00:00:00Z"
        newer = "2026-08-01T00:00:00Z"
        assert _last_updated(
            [_release("v1", published_at=newer)], self._record(older)
        )["source"] == "release"
        assert _last_updated(
            [_release("v1", published_at=older)], self._record(newer)
        )["source"] == "registry"

    def test_the_newest_of_several_releases(self):
        entries = [
            _release("v1.0.0", published_at="2026-01-01T00:00:00Z"),
            _release("v2.0.0", published_at="2026-08-01T00:00:00Z"),
        ]
        assert _last_updated(entries, {})["tag"] == "v2.0.0"

    def test_a_draft_dates_nothing(self):
        entries = [_release("v9", published_at="2026-08-01T00:00:00Z", draft=True)]
        assert _last_updated(entries, {}) is None

    def test_the_two_formats_compare_as_instants_not_strings(self):
        # The load-bearing one. GitHub writes Z, SmartAPI writes +00:00, and
        # "Z" > "+", so comparing the strings hands every near-tie to GitHub.
        # Delete _instant and this is the test that notices.
        got = _last_updated(
            [_release("v1", published_at="2026-08-01T09:00:00Z")],
            self._record("2026-08-01T09:00:00.500000+00:00"),
        )
        assert got["source"] == "registry"

    def test_a_tie_goes_to_the_release(self):
        moment = "2026-08-01T09:00:00+00:00"
        assert _last_updated(
            [_release("v1", published_at=moment)], self._record(moment)
        )["source"] == "release"

    def test_unparseable_dates_are_skipped_not_raised(self):
        assert _last_updated([_release("v1", published_at="whenever")], {}) is None
        assert _last_updated([], self._record(None)) is None
        assert _last_updated([], self._record(12345)) is None

    def test_a_naive_timestamp_does_not_raise(self):
        got = _last_updated(
            [_release("v1", published_at="2026-08-01T09:00:00Z")],
            self._record("2026-08-02T09:00:00"),
        )
        assert got["source"] == "registry"


class TestInstant:
    def test_both_upstream_formats(self):
        assert _instant("2026-08-01T00:00:00Z") == _instant("2026-08-01T00:00:00+00:00")

    def test_junk_is_none(self):
        assert _instant("") is None
        assert _instant(None) is None
        assert _instant("2026-13-45") is None


class TestRunningRelease:
    def _synced_with(self, synced, entries):
        path = synced.root / "releases" / "a" / "b.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(entries))
        return synced

    def test_each_environment_is_dated_by_what_it_runs(self, synced, component):
        # The fixture runs 2.0.0 in ci and test, 1.0.0 in prod — the real
        # shape: prod trailing on an older release.
        self._synced_with(synced, [
            _release("v2.0.0", published_at="2026-08-01T00:00:00Z"),
            _release("v1.0.0", published_at="2024-10-04T00:00:00Z"),
        ])
        component.repositories = [{"url": "https://github.com/a/b", "role": "source"}]
        envs = build_rows([component], synced)[0]["environments"]
        assert envs["ci"]["released"] == "2026-08-01"
        assert envs["prod"]["released"] == "2024-10-04"
        assert envs["prod"]["release_tag"] == "v1.0.0"
        assert envs["prod"]["release_url"].endswith("/v1.0.0")

    def test_a_version_matching_nothing_leaves_the_key_absent(self, synced, component):
        # Absent, not null: a null would sort as though it were a date.
        self._synced_with(synced, [_release("v9.9.9")])
        component.repositories = [{"url": "https://github.com/a/b", "role": "source"}]
        assert "released" not in build_rows([component], synced)[0]["environments"]["ci"]

    def test_no_repository_dates_no_cell(self, synced, component):
        cells = build_rows([component], synced)[0]["environments"]
        assert all("released" not in cell for cell in cells.values())


class TestFlowStepsOnRows:
    def test_every_row_carries_a_step_and_a_label(self, synced):
        rows = build_rows([_comp("a"), _comp("b", diagram={
            "refactor_status": "New in Refactor", "gets_results_from": ["a"]})], synced)
        assert [r["step"] for r in rows] == sorted(r["step"] for r in rows)
        assert all(r["step_label"] for r in rows)

    def test_having_no_recorded_edges_no_longer_decides_the_band(self, synced):
        # It used to: the last band was "No recorded dependencies", computed
        # from the graph. Now the stages decide where a row sits and `isolated`
        # says only what it always meant — nothing records this component's
        # neighbours — which the left bar still shows.
        row = build_rows([_comp("lonely")], synced)[0]
        assert row["isolated"] is True
        assert row["step_label"] != "No recorded dependencies"


class TestStages:
    FILE = """
stages:
  - title: Ingest
    description: Pulls external sources in.
    components: [b, a]
  - title: Serving
    description: Answers questions.
    components: [c]
unplaced:
  description: Not yet placed anywhere.
  components: [d]
"""

    def _stages(self, tmp_path, text=None):
        path = tmp_path / "flow-steps.yaml"
        path.write_text(self.FILE if text is None else text)
        return load_stages(path)

    def _components(self, *ids):
        return [_comp(cid) for cid in ids]

    def test_the_file_is_the_order_not_the_alphabet(self, tmp_path):
        # b before a, because a stage lists its components in the order
        # someone decided they should be read in.
        ordered = in_stage_order(
            self._components("a", "b", "c", "d"), self._stages(tmp_path)
        )
        assert [c.id for c, _, _ in ordered] == ["b", "a", "c", "d"]
        assert [number for _, number, _ in ordered] == [1, 1, 2, 3]

    def test_each_component_carries_its_stage(self, tmp_path):
        ordered = in_stage_order(self._components("a", "c"), self._stages(tmp_path))
        assert [stage["title"] for _, _, stage in ordered] == ["Ingest", "Serving"]

    def test_a_component_no_stage_names_falls_to_the_end(self, tmp_path):
        # The failure this is here for: a new component file nobody has placed
        # must be visible as unplaced, not silently sorted last.
        ordered = in_stage_order(self._components("a", "z"), self._stages(tmp_path))
        component, number, stage = ordered[-1]
        assert component.id == "z"
        assert stage["title"] == UNPLACED_TITLE
        assert number == 3

    def test_an_id_no_component_file_matches_is_skipped(self, tmp_path):
        stages = self._stages(tmp_path, """
stages:
  - title: Ingest
    description: Pulls external sources in.
    components: [a, typo]
""")
        ordered = in_stage_order(self._components("a"), stages)
        assert [c.id for c, _, _ in ordered] == ["a"]

    def test_a_missing_file_is_refused_rather_than_worked_around(self, tmp_path):
        # in_stage_order does fall back to data-flow order, and that is what
        # makes the missing file worth refusing: the page would look finished
        # while showing the ordering this file exists to replace.
        with pytest.raises(click.ClickException):
            load_stages(tmp_path / "absent.yaml")
        ordered = in_stage_order(self._components("a", "b"), [])
        assert len(ordered) == 2

    def test_the_file_is_found_from_a_subdirectory(self, tmp_path, monkeypatch):
        # The same upward walk load_owner_colors and load_policy do: running
        # build-dashboard from anywhere inside a checkout finds the checkout's
        # stages, not nothing.
        (tmp_path / "config").mkdir()
        (tmp_path / "config" / "flow-steps.yaml").write_text(self.FILE)
        deep = tmp_path / "a" / "b"
        deep.mkdir(parents=True)
        monkeypatch.chdir(deep)
        assert [stage["title"] for stage in load_stages()][:2] == ["Ingest", "Serving"]

    def test_an_empty_file_is_not_an_error(self, tmp_path):
        assert self._stages(tmp_path, "") == []

    def test_a_file_with_no_stages_still_yields_the_unplaced_band(self, tmp_path):
        # Every component would land in it, which is a legible failure: the
        # page says "not yet placed" 26 times rather than showing no bands.
        stages = self._stages(tmp_path, """
unplaced:
  description: Nothing is placed.
  components: [a]
""")
        assert len(stages) == 1 and stages[0]["unplaced"] is True
        ordered = in_stage_order(self._components("a", "b"), stages)
        assert {number for _, number, _ in ordered} == {1}

    def test_the_rows_carry_the_stage_prose(self, synced, component):
        row = build_rows([component], synced)[0]
        assert "step" in row and "step_title" in row and "step_description" in row


class TestUnregisteredEnvironments:
    """A gap in a registration that exists — the finding, computed from the
    registry rather than from how the URL was found."""

    def _synced(self, tmp_path, servers):
        (tmp_path / "manifest.json").write_text('{"fetches": []}')
        (tmp_path / "smartapi.json").write_text(json.dumps({"hits": [{
            "_id": "abc", "info": {}, "servers": servers}]}))
        return SyncedData(tmp_path)

    def test_a_recorded_environment_the_registry_omits_is_flagged(self, tmp_path):
        # answer-appraiser: registers production only, deployed to ci as well.
        # Recording the discovered URL must not hide the gap.
        synced = self._synced(tmp_path, [
            {"url": "https://svc/", "x-maturity": "production"}])
        component = _comp("svc", identifiers={"smartapi": "abc"},
                          environments={"ci": Deployment(env="ci", url="https://svc.ci/")})
        cells = build_rows([component], synced)[0]["environments"]
        assert cells["ci"]["unregistered"] is True
        assert "unregistered" not in cells["prod"]

    def test_a_server_without_maturity_leaves_a_gap(self, tmp_path):
        # node-annotator's ci and test servers carry no x-maturity, so they are
        # not registered environments however many servers the record lists.
        synced = self._synced(tmp_path, [
            {"url": "https://svc/", "x-maturity": "production"},
            {"url": "https://svc.ci/"},
        ])
        component = _comp("svc", identifiers={"smartapi": "abc"},
                          environments={"ci": Deployment(env="ci", url="https://svc.ci/")})
        assert build_rows([component], synced)[0]["environments"]["ci"]["unregistered"]

    def test_an_unregistered_component_is_not_flagged(self, tmp_path):
        # Nothing to be missing from. Flagging every environment of every
        # unregistered component would drown the components that are.
        (tmp_path / "manifest.json").write_text('{"fetches": []}')
        (tmp_path / "smartapi.json").write_text('{"hits": []}')
        component = _comp("svc", environments={
            "ci": Deployment(env="ci", url="https://svc.ci/")})
        cells = build_rows([component], SyncedData(tmp_path))[0]["environments"]
        assert "unregistered" not in cells["ci"]

    def test_the_payload_counts_the_gaps(self, tmp_path):
        synced = self._synced(tmp_path, [
            {"url": "https://svc/", "x-maturity": "production"}])
        component = _comp("svc", identifiers={"smartapi": "abc"}, environments={
            "ci": Deployment(env="ci", url="https://svc.ci/"),
            "test": Deployment(env="test", url="https://svc.test/"),
        })
        assert build_payload([component], synced)["unregistered_count"] == 2


class TestLiveOpenapiFacts:
    """What an endpoint serves, which is not what its registration claims."""

    def test_a_registration_never_supplies_operations(self, tmp_path):
        # `_openapi_facts` is asked the same questions about a SmartAPI record,
        # and a record carries no `paths` at all. Reading operations off one
        # would print the operations a team registered as the ones this
        # environment serves — the exact gap the page exists to show.
        record = {
            "_id": "abc",
            "info": {
                "title": "Registered Service",
                "version": "9.9.9",
                "x-trapi": {"operations": ["lookup"], "asyncquery": True},
            },
            "servers": [{"url": "https://svc.ci/", "x-maturity": "staging"}],
        }
        (tmp_path / "manifest.json").write_text('{"fetches": []}')
        (tmp_path / "smartapi.json").write_text(json.dumps({"hits": [record]}))
        component = _comp("svc", identifiers={"smartapi": "abc"})
        cell = build_rows([component], SyncedData(tmp_path))[0]["environments"]["ci"]
        # The version does come from the registration. Nothing else does.
        assert cell["version_source"] == "smartapi"
        assert cell["trapi_operations"] == []
        assert cell["openapi_title"] is None
        assert cell["paths_count"] is None
        assert cell["asyncquery"] is None

    def test_a_served_document_supplies_all_four(self):
        facts = _live_openapi_facts({
            "info": {
                "title": "ARAX",
                "x-trapi": {"operations": ["lookup", "overlay"], "asyncquery": True},
            },
            "paths": {"/query": {}, "/asyncquery": {}, "/status": {}},
        })
        assert facts == {
            "operations": ["lookup", "overlay"],
            "asyncquery": True,
            "paths_count": 3,
            "title": "ARAX",
        }

    def test_no_document_at_all_is_empty_not_an_error(self):
        assert _live_openapi_facts(None) == {
            "operations": [], "asyncquery": None, "paths_count": None, "title": None}


class TestStatusFacts:
    def test_recent_queries_keeps_three_numbers_and_their_unit(self):
        # Name Lookup's block also carries buckets, rates and inter-arrival
        # times. Three numbers say whether this deployment is used and how it
        # feels; the rest belongs in the monitoring console this is not.
        facts = _status_facts({
            "status": "ok",
            "message": "Reporting results from primary core.",
            "recent_queries": {
                "count": 50000,
                "mean_time_ms": 121.69,
                "p50_ms": 14.009746,
                "p95_ms": 38.77254415,
                "p99_ms": 459.49534798,
                "latency_buckets": {"slow_threshold_ms": 500.0},
            },
        })
        assert facts["message"] == "Reporting results from primary core."
        # Rounded to a tenth: six digits of precision about a figure that
        # changes between one request and the next is noise. The keys keep the
        # unit, because "p50: 14" is a number whose scale a reader must guess.
        assert facts["recent_queries"] == {
            "count": 50000, "p50_ms": 14.0, "p95_ms": 38.8}

    def test_a_body_with_no_recent_queries_is_none(self):
        # Name Lookup's prod answers with Solr's own status document, which has
        # no query summary in it. A gap, not a deployment serving no queries.
        assert _status_facts({"status": "ok", "numDocs": 5})["recent_queries"] is None
        assert _status_facts({"recent_queries": {"p50_ms": 3}})["recent_queries"] is None
        assert _status_facts({"recent_queries": "soon"})["recent_queries"] is None

    def test_a_structured_message_is_not_a_message(self):
        # Strings only: rendering a mapping at a reader is worse than nothing.
        assert _status_facts({"message": {"text": "ok"}})["message"] is None

    def test_the_cell_carries_both(self, tmp_path):
        (tmp_path / "manifest.json").write_text('{"fetches": []}')
        (tmp_path / "smartapi.json").write_text('{"hits": []}')
        path = tmp_path / "status" / "svc" / "ci.json"
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({
            "status": "ok", "message": "Reporting results from primary core.",
            "recent_queries": {"count": 12, "p50_ms": 1.25, "p95_ms": 9.0},
        }))
        component = _comp(
            "svc",
            endpoints={"status": "status"},
            environments={"ci": Deployment(env="ci", url="https://svc.ci/")},
        )
        cell = build_rows([component], SyncedData(tmp_path))[0]["environments"]["ci"]
        assert cell["status_message"] == "Reporting results from primary core."
        assert cell["recent_queries"]["p50_ms"] == 1.2


class TestOtelPresence:
    def test_a_name_no_collector_has_seen_is_the_finding(self):
        # Recorded names with an empty seen_in are why this exists: a service
        # that has stopped tracing, or a name written down wrong. Dropping them
        # would leave the page showing only the names needing no attention.
        found = otel_presence(
            ["gandalf", "ghost"],
            {"ci": ["gandalf"], "test": ["gandalf"], "prod": []},
        )
        assert found == [
            {"service": "gandalf", "seen_in": ["ci", "test"]},
            {"service": "ghost", "seen_in": []},
        ]

    def test_the_match_is_case_sensitive(self):
        # shepherd-arax records `arax`; prod reports `ARAX`, which is the
        # separate `arax` component. Folding case makes the page say the ARAX
        # worker is tracing when it is its neighbour that is.
        assert otel_presence(["arax"], {"prod": ["ARAX"]}) == [
            {"service": "arax", "seen_in": []}]
        assert otel_presence(["ARAX"], {"prod": ["ARAX"]}) == [
            {"service": "ARAX", "seen_in": ["prod"]}]

    def test_it_reaches_the_row_in_ladder_order(self, tmp_path):
        (tmp_path / "manifest.json").write_text('{"fetches": []}')
        (tmp_path / "smartapi.json").write_text('{"hits": []}')
        (tmp_path / "otel").mkdir()
        for env, names in (("ci", ["a"]), ("test", []), ("prod", ["a"])):
            (tmp_path / "otel" / f"{env}.json").write_text(
                json.dumps({"data": names}))
        component = _comp("svc", identifiers={"otel_services": ["a"]})
        row = build_rows([component], SyncedData(tmp_path))[0]
        assert row["otel_presence"] == [{"service": "a", "seen_in": ["ci", "prod"]}]


class TestDerivedRejected:
    """Hosts the convention predicted and the probe did not confirm."""

    def _synced(self, tmp_path, rejected):
        (tmp_path / "manifest.json").write_text('{"fetches": []}')
        (tmp_path / "smartapi.json").write_text('{"hits": []}')
        (tmp_path / "derived.json").write_text(
            json.dumps({"confirmed": {}, "rejected": rejected})
        )
        return SyncedData(tmp_path)

    def test_the_rejections_reach_the_row(self, tmp_path):
        # "We looked here and this is not it", which is a different claim from
        # "this deployment is down" — there is no evidence one exists.
        synced = self._synced(tmp_path, {"svc": {"prod": {
            "url": "https://svc.transltr.io/", "checked_at": "2026-09-02T15:29:22+00:00"}}})
        row = build_rows([_comp("svc")], synced)[0]
        assert row["derived_rejected"] == [
            {"env": "prod", "url": "https://svc.transltr.io/"}]

    def test_they_come_out_in_ladder_order(self, tmp_path):
        # dev, ci, test, prod — the order every other row of environments on
        # the page reads in, whatever order the JSON happened to be written.
        synced = self._synced(tmp_path, {"svc": {
            "prod": {"url": "https://svc.transltr.io/"},
            "test": {"url": "https://svc.test.transltr.io/"},
        }})
        row = build_rows([_comp("svc")], synced)[0]
        assert [entry["env"] for entry in row["derived_rejected"]] == ["test", "prod"]

    def test_no_derived_file_is_not_an_error(self, tmp_path):
        (tmp_path / "manifest.json").write_text('{"fetches": []}')
        (tmp_path / "smartapi.json").write_text('{"hits": []}')
        synced = SyncedData(tmp_path)
        assert synced.rejected == {}
        assert build_rows([_comp("svc")], synced)[0]["derived_rejected"] == []


def _row(cid, **kwargs):
    """One row, reduced to what the graph builders read."""
    return {
        "id": cid,
        "step": kwargs.pop("step", 1),
        "connections": kwargs.pop("connections", {}),
        "externals": kwargs.pop("externals", []),
        **kwargs,
    }


class TestEdges:
    def test_a_results_edge_points_the_way_data_moves(self):
        # `gets_results_from` is written from the caller's side. An arrow on a
        # map points where the data goes, so the recorded direction is
        # reversed: A gets results from B means the data leaves B.
        rows = [_row("a", connections={"gets_results_from": ["b"]}), _row("b")]
        assert build_edges(rows) == [
            {"from": "b", "to": "a", "kind": "results", "planned": False}]

    def test_a_calls_edge_is_not_reversed(self):
        # The request leaves the caller, so this one is already pointing the
        # way the arrow should. Reversing both would send half of them upstream.
        rows = [_row("a", connections={"calls": ["b"]}), _row("b")]
        assert build_edges(rows) == [
            {"from": "a", "to": "b", "kind": "calls", "planned": False}]

    def test_a_planned_edge_is_marked(self):
        # And coexists with the implemented one: they are different claims —
        # this is wired, and this is meant to be — and the map draws them apart.
        rows = [
            _row("a", connections={"calls": ["b"], "planned_calls": ["b"]}),
            _row("b"),
        ]
        assert build_edges(rows) == [
            {"from": "a", "to": "b", "kind": "calls", "planned": False},
            {"from": "a", "to": "b", "kind": "calls", "planned": True},
        ]

    def test_an_external_in_and_an_external_out(self):
        rows = [
            _row("a", externals=[{"direction": "in", "name": "External Data Sources"}]),
            _row("b", externals=[{"direction": "out", "name": "User"}]),
        ]
        assert build_edges(rows) == [
            {"from": "External Data Sources", "to": "a",
             "kind": "external_in", "planned": False},
            {"from": "b", "to": "User", "kind": "external_out", "planned": False},
        ]

    def test_an_edge_to_a_missing_row_is_dropped(self):
        # What makes a published build's graph smaller rather than holed: nine
        # component files call jaeger, and jaeger has no row.
        rows = [_row("a", connections={"calls": ["gone"], "gets_results_from": ["gone"]})]
        assert build_edges(rows) == []

    def test_a_reference_resolves_case_insensitively(self):
        # The same rule references follow everywhere else here; the edge
        # carries the id as the component file spells it.
        rows = [_row("a", connections={"calls": ["B"]}), _row("b")]
        assert build_edges(rows)[0]["to"] == "b"

    def test_externals_are_unique_and_first_seen(self):
        rows = [
            _row("a", externals=[{"direction": "in", "name": "Sources"}]),
            _row("b", externals=[
                {"direction": "out", "name": "User"},
                {"direction": "in", "name": "Sources"},
            ]),
        ]
        assert build_externals(rows) == [
            {"name": "Sources", "direction": "in"},
            {"name": "User", "direction": "out"},
        ]


class TestStagePayload:
    def _stages(self):
        return [
            {"title": "Ingest", "description": "Pulls sources in.",
             "components": ["a"]},
            {"title": "Serving", "description": "Answers.", "components": ["b"]},
            {"title": UNPLACED_TITLE, "description": "Nowhere yet.",
             "components": ["c"], "unplaced": True},
        ]

    def test_every_stage_carries_its_step(self):
        blocks = stage_blocks(
            self._stages(),
            [_row("a", step=1), _row("b", step=2), _row("c", step=3)],
        )
        assert [(b["step"], b["title"]) for b in blocks] == [
            (1, "Ingest"), (2, "Serving"), (3, UNPLACED_TITLE)]
        assert blocks[0]["description"] == "Pulls sources in."

    def test_a_stage_with_no_kept_rows_is_absent_not_empty(self):
        # The Engineering stage holds jaeger and test-harness and nothing else,
        # so a published build shows no heading for it rather than a heading
        # over a gap — and the stages that remain keep their numbers, so the
        # page runs 1–8 and skips 9 instead of renumbering.
        blocks = stage_blocks(self._stages(), [_row("a", step=1), _row("c", step=3)])
        assert [b["step"] for b in blocks] == [1, 3]
        assert all(b["components"] for b in blocks)

    def test_the_roster_matches_the_row_order(self):
        # Within a stage the order is a judgement recorded in the config file,
        # and the rows are already in it. Sorting here would throw it away and
        # make the band disagree with the table under it.
        rows = [_row("b", step=1), _row("a", step=1)]
        assert stage_blocks(self._stages(), rows)[0]["components"] == ["b", "a"]

    def test_the_unplaced_block_is_flagged(self):
        # Explicit on every block, not only the trailing one: a reader of the
        # payload should not have to know that a missing key means False.
        blocks = stage_blocks(self._stages(), [_row("a", step=1), _row("c", step=3)])
        assert [b["unplaced"] for b in blocks] == [False, True]

    def test_the_payload_carries_the_bands_and_the_graph(self, synced, component):
        payload = build_payload([component], synced)
        assert [stage["components"] for stage in payload["stages"]] == [["svc"]]
        assert payload["edges"] == [] and payload["externals"] == []


class TestHelmStatus:
    """Three answers, never a blank."""

    def _row(self, synced, **kwargs):
        return build_rows([_comp("svc", **kwargs)], synced)[0]

    def test_a_recorded_chart(self, synced):
        row = self._row(synced, identifiers={"helm_chart": "my-chart"})
        assert row["helm_status"] == "recorded"

    def test_itrb_with_no_chart_in_devops(self, synced):
        # 13 ITRB-hosted components have no chart in translator-devops. That is
        # a gap in what we know, and saying so is the point.
        assert self._row(synced, hosted_at="ITRB")["helm_status"] == "none-in-devops"
        assert self._row(synced)["helm_status"] == "none-in-devops"

    def test_hosted_somewhere_else_entirely(self, synced):
        # dogpark-ranger runs at Scripps. Not a gap in our data — it is where
        # the component runs, and translator-devops would never have a chart.
        row = self._row(synced, hosted_at="Scripps")
        assert row["helm_status"] == "not-devops-hosted"


class TestTheMetadataBlock:
    def test_the_file_speaks_for_itself(self, synced):
        component = _comp(
            "svc",
            component_type="ARA",
            hosted_at="ITRB",
            part_of="Shepherd",
            itrb={"app": "shepherd-ci-pipeline", "group": "shepherd"},
            identifiers={
                "infores": "infores:svc",
                "helm_chart": ["one", "two"],
                "translator_all_wiki": "Some-Page",
                "otel_services": ["svc"],
            },
            repositories=[{"url": "https://github.com/a/b", "role": "source",
                           "visibility": "public"}],
            documentation=[{"url": "https://wiki/one", "kind": "wiki"},
                           {"url": "https://docs/two", "kind": "technical-documentation"}],
            endpoints={"openapi": "openapi.json", "status": None},
            diagram={"ubiquitous": True},
            connections={"calls": ["other", "~later"]},
        )
        row = build_rows([component], synced)[0]
        assert row["component_type"] == "ARA"
        assert (row["hosted_at"], row["part_of"]) == ("ITRB", "Shepherd")
        assert row["itrb"] == {"app": "shepherd-ci-pipeline", "group": "shepherd"}
        assert row["identifiers"]["helm_charts"] == ["one", "two"]
        assert row["identifiers"]["helm_chart"] == "one"
        assert row["identifiers"]["translator_all_wiki"] == "Some-Page"
        assert row["repositories"] == [
            {"url": "https://github.com/a/b", "role": "source", "visibility": "public"}]
        # The full list is new; `documentation` stays the first URL, because a
        # payload key that changes type is the rename this contract forbids.
        assert row["docs"] == [
            {"url": "https://wiki/one", "kind": "wiki"},
            {"url": "https://docs/two", "kind": "technical-documentation"},
        ]
        assert row["documentation"] == "https://wiki/one"
        assert row["endpoints"] == {"openapi": "openapi.json", "status": None}
        assert row["diagram"] == {"ubiquitous": True, "hide": False}
        assert row["connections"]["calls"] == ["other"]
        assert row["connections"]["planned_calls"] == ["later"]

    def test_the_component_type_has_no_registry_fallback(self, tmp_path):
        # `type` answers the same question with the registry standing in;
        # `component_type` is the file's own claim, so a reader can tell "nobody
        # wrote this down" from "the registry says KP".
        (tmp_path / "manifest.json").write_text('{"fetches": []}')
        (tmp_path / "smartapi.json").write_text(json.dumps({"hits": [{
            "_id": "abc",
            "info": {"x-translator": {"component": "KP"}},
            "servers": [{"url": "https://svc.ci/", "x-maturity": "staging"}],
        }]}))
        component = _comp("svc", identifiers={"smartapi": "abc"})
        row = build_rows([component], SyncedData(tmp_path))[0]
        assert row["type"] == "KP"
        assert row["component_type"] is None

    def test_the_helm_block_and_the_releases_reach_the_row(self, synced, component):
        chart = synced.root / "helm" / "my-chart"
        chart.mkdir(parents=True)
        (chart / "Chart.yaml").write_text("name: my-chart\nversion: 0.5.2\nappVersion: 1.16.0\n")
        (chart / "values.yaml").write_text("resources:\n  requests:\n    cpu: 800m\n")
        path = synced.root / "releases" / "a" / "b.json"
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps([_release("v2.0.0", body="Notes <b>here</b>")]))
        component.identifiers = {"smartapi": "abc", "helm_chart": "my-chart"}
        component.repositories = [{"url": "https://github.com/a/b", "role": "source"}]
        row = build_rows([component], synced)[0]
        assert [c["chart"] for c in row["helm_charts"]] == ["my-chart"]
        assert row["helm_charts"][0]["app_version"] == "1.16.0"
        assert [s["name"] for s in row["helm_charts"][0]["services"]] == ["my-chart"]
        assert [r["tag"] for r in row["releases_detail"]] == ["v2.0.0"]
        assert row["releases_detail"][0]["body_excerpt"] == "Notes here"

    def test_the_smartapi_record_is_shaped_for_the_panel(self, synced, component):
        record = build_rows([component], synced)[0]["smartapi_record"]
        assert record["id"] == "abc"
        assert record["registry_url"] == "https://smart-api.info/ui/abc"
        assert record["trapi"]["version"] == "1.4.0"

    def test_no_registration_is_none_not_an_empty_block(self, synced):
        # Different from a record whose fields are blank, and the drawer says
        # so: "not registered" is a finding the page already counts.
        assert build_rows([_comp("svc")], synced)[0]["smartapi_record"] is None
