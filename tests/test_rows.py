"""Assembling one component's row: drift, dates, releases and findings.

Drift, the "last updated" date and the release a cell is running are all
comparisons a single cell cannot make, which is why they are decided here.
"""

import json

from tests.dashboard_helpers import _comp
from translator_diagram.payload_details import releases_detail
from translator_diagram.rows import (
    _instant,
    _last_updated,
    _mark_drift,
    _release_chips,
    build_rows,
    otel_presence,
)
from translator_diagram.synced_data import SyncedData


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


def _release(tag, **kwargs):
    return {
        "tag_name": tag,
        "name": kwargs.pop("name", tag),
        "html_url": kwargs.pop("html_url", f"https://github.com/a/b/releases/tag/{tag}"),
        "published_at": kwargs.pop("published_at", "2026-08-01T00:00:00Z"),
        **kwargs,
    }


def _chips(entries, running):
    return _release_chips(releases_detail(entries, running))


class TestReleaseChips:
    def test_the_newest_few(self):
        entries = [_release(f"v{n}.0.0") for n in (9, 8, 7, 6, 5)]
        assert [c["tag"] for c in _chips(entries, set())] == [
            "v9.0.0", "v8.0.0", "v7.0.0"]

    def test_a_deployed_older_release_is_kept(self):
        # answer-appraiser's prod trails its ci by two minor versions; the
        # notes for what prod is running are the ones worth a link.
        entries = [_release(f"v0.{n}.0") for n in (8, 7, 6, 5, 4)]
        chips = _chips(entries, {"0.4.0"})
        assert [c["tag"] for c in chips] == ["v0.8.0", "v0.7.0", "v0.6.0", "v0.4.0"]
        assert [c["deployed"] for c in chips] == [False, False, False, True]

    def test_a_deployed_newest_release_is_marked_not_duplicated(self):
        chips = _chips([_release("v2.0.0"), _release("v1.0.0")], {"2.0.0"})
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
        assert [c["published"] for c in _chips(entries, set())] == [
            "2026-07-23", "2026-04-08", "2026-02-20"]

    def test_drafts_are_dropped(self):
        # Invisible without a token, visible with one: a link that works only
        # for whoever ran the sync is worse than no link.
        chips = _chips(
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
        assert [c["tag"] for c in _chips(entries, set())] == [
            "v7.0.0", "v6.0.0", "v5.0.0"]

    def test_a_tagless_entry_does_not_either(self):
        entries = [
            {"html_url": "https://x/", "published_at": "2026-08-09T00:00:00Z"},
            _release("v7.0.0", published_at="2026-08-07T00:00:00Z"),
            _release("v6.0.0", published_at="2026-08-06T00:00:00Z"),
            _release("v5.0.0", published_at="2026-08-05T00:00:00Z"),
        ]
        assert [c["tag"] for c in _chips(entries, set())] == [
            "v7.0.0", "v6.0.0", "v5.0.0"]

    def test_the_fields_the_page_renders(self):
        chip = _chips([_release("v1.0.0", prerelease=True)], set())[0]
        assert chip["url"] == "https://github.com/a/b/releases/tag/v1.0.0"
        assert chip["published"] == "2026-08-01"
        assert chip["prerelease"] is True

    def test_an_entry_without_a_tag_is_skipped(self):
        assert _chips([{"html_url": "https://x/"}], set()) == []

    def test_no_releases_at_all(self):
        assert _chips([], {"1.0.0"}) == []


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
        assert row["chart_names"] == ["one", "two"]
        assert row["helm_chart"] == "one"
        assert row["translator_all_wiki"] == "Some-Page"
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
