"""Resolving cells and rendering the page, from a fixture directory."""

import json

import pytest

from translator_diagram.components import ComponentFile, Deployment
from translator_diagram.dashboard import (
    SyncedData,
    _helm_facts,
    _mark_drift,
    build_payload,
    build_rows,
    render_html,
    source_tally,
    write_dashboard,
)


def _comp(cid, **kwargs):
    kwargs.setdefault("diagram", {"refactor_status": "New in Refactor"})
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
        cell = build_rows([component], synced)[0]["environments"]["dev"]
        assert cell == {"deployed": False}


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

    def test_an_even_split_still_marks_one_side(self):
        # Two against two has no majority worth the name, but leaving both
        # unmarked would hide a genuine disagreement.
        cells = {
            "dev": {"deployed": True, "version": "a"},
            "ci": {"deployed": True, "version": "a"},
            "test": {"deployed": True, "version": "b"},
            "prod": {"deployed": True, "version": "b"},
        }
        _mark_drift(cells, "version")
        marked = [e for e, c in cells.items() if c.get("drift")]
        assert len(marked) == 2

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
        # It must open from file:// with no network: no stylesheet link, no
        # script src, no CDN.
        html = render_html(build_payload([component], synced))
        assert "<link" not in html
        assert "script src=" not in html


class TestDerivedDeployments:
    """Environments found by convention rather than registered anywhere."""

    def test_a_derived_environment_is_used_and_marked(self, tmp_path):
        (tmp_path / "manifest.json").write_text('{"fetches": []}')
        (tmp_path / "smartapi.json").write_text('{"hits": []}')
        (tmp_path / "derived.json").write_text(json.dumps({
            "svc": {"ci": {"url": "https://svc.ci.transltr.io/", "location": "ITRB"}}}))
        path = tmp_path / "openapi" / "svc" / "ci.json"
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({"info": {"version": "0.8.2"}}))

        cell = build_rows([_comp("svc")], SyncedData(tmp_path))[0]["environments"]["ci"]
        assert cell["deployed"] and cell["version"] == "0.8.2"
        assert cell["derived"] is True

    def test_a_registered_environment_wins_over_a_derived_one(self, tmp_path):
        # Precedence is recorded, then registered, then derived. A derived URL
        # is a discovery; anything stated explicitly outranks it.
        (tmp_path / "manifest.json").write_text('{"fetches": []}')
        (tmp_path / "smartapi.json").write_text(json.dumps({"hits": [{
            "_id": "abc", "info": {},
            "servers": [{"url": "https://registered.ci/", "x-maturity": "staging"}],
        }]}))
        (tmp_path / "derived.json").write_text(json.dumps({
            "svc": {"ci": {"url": "https://derived.ci/", "location": "ITRB"}}}))
        component = _comp("svc", identifiers={"smartapi": "abc"})
        cell = build_rows([component], SyncedData(tmp_path))[0]["environments"]["ci"]
        assert cell["url"] == "https://registered.ci/"

    def test_no_derived_file_is_not_an_error(self, tmp_path):
        (tmp_path / "manifest.json").write_text('{"fetches": []}')
        (tmp_path / "smartapi.json").write_text('{"hits": []}')
        assert SyncedData(tmp_path).derived == {}

    def test_the_payload_counts_them(self, tmp_path):
        (tmp_path / "manifest.json").write_text('{"fetches": []}')
        (tmp_path / "smartapi.json").write_text('{"hits": []}')
        (tmp_path / "derived.json").write_text(json.dumps({
            "svc": {"ci": {"url": "https://svc.ci.transltr.io/"},
                    "test": {"url": "https://svc.test.transltr.io/"}}}))
        payload = build_payload([_comp("svc")], SyncedData(tmp_path))
        assert payload["derived_count"] == 2


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
