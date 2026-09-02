"""Resolving cells and rendering the page, from a fixture directory."""

import json

import click
import pytest

from translator_diagram.components import ComponentFile, Deployment
from translator_diagram.dashboard import (
    UNPLACED_TITLE,
    SyncedData,
    _helm_facts,
    _instant,
    _last_updated,
    _mark_drift,
    _release_chips,
    _same_version,
    build_payload,
    build_rows,
    in_stage_order,
    load_stages,
    render_html,
    source_tally,
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
        cell = build_rows([component], synced)[0]["environments"]["dev"]
        assert cell == {"deployed": False}


class TestStaleBodies:
    """A cached body from an earlier run must not answer for this one."""

    def _synced(self, tmp_path, fetch):
        (tmp_path / "manifest.json").write_text(json.dumps({"fetches": [fetch]}))
        (tmp_path / "smartapi.json").write_text('{"hits": []}')
        path = tmp_path / "openapi" / "svc" / "ci.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"info": {"version": "1.5.4"}}))
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

    def test_every_row_carries_what_a_band_needs(self, component, synced):
        # Adding a key to the payload is safe and renaming one is not: the JS
        # reads these three by name to draw a band, and a row missing any of
        # them silently loses its heading.
        row = build_payload([component], synced)["rows"][0]
        for key in ("step", "step_label", "step_title", "step_description"):
            assert key in row


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
        # It must open from file:// with no network: no stylesheet link, no
        # script src, no CDN.
        html = render_html(build_payload([component], synced))
        assert "<link" not in html
        assert "script src=" not in html

    def test_the_page_asks_not_to_be_indexed(self, component, synced):
        """Reachable by link, not by search. A deliberate decision that should
        be removed on purpose rather than lost in a template edit — see the
        public/private split in issue #7."""
        html = render_html(build_payload([component], synced))
        assert '<meta name="robots" content="noindex, nofollow">' in html


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
