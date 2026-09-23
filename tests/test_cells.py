"""Resolving one cell: the version-source chain, and every reason it can give.

The chain is the point of the dashboard, so it is tested from both ends: the
fact extractors directly, and the resolved cell that comes out of `build_rows`.
`_Probes` builds the recorded-probe shapes `sync` actually writes.
"""

import json

from tests.dashboard_helpers import _cell, _comp, _Probes
from translator_diagram.cells import (
    CELL_REASONS,
    _helm_facts,
    _live_openapi_facts,
    _status_facts,
)
from translator_diagram.components import Deployment
from translator_diagram.dashboard import build_payload
from translator_diagram.rows import build_rows
from translator_diagram.synced_data import SyncedData


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
        # Deliberate: an ingress answers 404 for a deployment that has gone
        # away, so `reachable` counts 2xx and 3xx only. The 404 still shows as
        # the cell's HTTP status.
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
