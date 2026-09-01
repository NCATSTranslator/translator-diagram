"""The fetchers, driven by an injected fetcher so nothing here reaches the network."""

import json
from datetime import UTC, datetime

from translator_diagram.components import ComponentFile, Deployment
from translator_diagram.sync import (
    SMARTAPI_QUERY,
    FetchResult,
    _confirm_derived,
    _headers,
    _plan_release_fetches,
    _still_fresh,
    deployments_from_smartapi,
    fetch_to,
    sync,
)


def _comp(cid, **kwargs):
    kwargs.setdefault("diagram", {"refactor_status": "New in Refactor"})
    return ComponentFile(id=cid, name=cid, owner="None", **kwargs)


def _now_iso():
    return datetime.now(UTC).isoformat(timespec="seconds")


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


class TestDeploymentsFromSmartapi:
    def test_maturities_map_to_our_ladder(self):
        record = {"servers": [
            {"url": "https://x.dev/", "x-maturity": "development"},
            {"url": "https://x.ci/", "x-maturity": "staging"},
            {"url": "https://x.test/", "x-maturity": "testing"},
            {"url": "https://x/", "x-maturity": "production"},
        ]}
        assert set(deployments_from_smartapi(record)) == {"dev", "ci", "test", "prod"}

    def test_ci_is_staging_not_development(self):
        # The mapping everyone gets wrong, and the reason it is a constant.
        record = {"servers": [{"url": "https://x.ci/", "x-maturity": "staging"}]}
        assert deployments_from_smartapi(record)["ci"].url == "https://x.ci/"

    def test_a_server_without_maturity_is_dropped(self):
        # Real: node-annotator's ci and test entries carry none. An environment
        # we cannot name is not one we can put in a column.
        record = {"servers": [{"url": "https://x/"}]}
        assert deployments_from_smartapi(record) == {}

    def test_the_first_of_a_duplicated_server_wins(self):
        # name-lookup and sri-node-normalizer each list every server twice.
        record = {"servers": [
            {"url": "https://first/", "x-maturity": "production"},
            {"url": "https://second/", "x-maturity": "production"},
        ]}
        assert deployments_from_smartapi(record)["prod"].url == "https://first/"

    def test_no_servers_at_all(self):
        assert deployments_from_smartapi({}) == {}


class TestFetchTo:
    def test_a_200_is_written(self, tmp_path):
        target = tmp_path / "out" / "body.json"
        result = fetch_to("https://x/", target, FakeFetcher({"https://x/": (200, b"{}")}),
                          max_age=0, root=tmp_path)
        assert result.ok and target.read_bytes() == b"{}"

    def test_a_404_is_recorded_and_writes_nothing(self, tmp_path):
        # ars and ploverdb 404 at every environment. That is a finding worth
        # keeping, not a crash, and it must not leave a bogus cached body.
        target = tmp_path / "body.json"
        result = fetch_to("https://x/", target, FakeFetcher({}), max_age=0, root=tmp_path)
        assert result.status == 404
        assert not result.ok
        assert not target.exists()

    def test_an_exception_is_recorded_rather_than_raised(self, tmp_path):
        fetcher = FakeFetcher({"https://x/": TimeoutError("timed out")})
        result = fetch_to("https://x/", tmp_path / "b.json", fetcher, max_age=0, root=tmp_path)
        assert result.status is None
        assert "TimeoutError" in result.error

    def test_a_fresh_file_is_not_refetched(self, tmp_path):
        target = tmp_path / "body.json"
        target.write_bytes(b"cached")
        fetcher = FakeFetcher({})
        result = fetch_to("https://x/", target, fetcher, max_age=9999, root=tmp_path)
        assert result.cached and fetcher.urls == []
        assert target.read_bytes() == b"cached"

    def test_max_age_zero_always_refetches(self, tmp_path):
        target = tmp_path / "body.json"
        target.write_bytes(b"stale")
        fetcher = FakeFetcher({"https://x/": (200, b"fresh")})
        fetch_to("https://x/", target, fetcher, max_age=0, root=tmp_path)
        assert target.read_bytes() == b"fresh"

    def test_the_recorded_path_is_relative_to_the_root(self, tmp_path):
        # The manifest is read back by the dashboard to look up HTTP statuses,
        # so an absolute path here would make every lookup miss.
        result = fetch_to("https://x/", tmp_path / "openapi" / "a" / "ci.json",
                          FakeFetcher({"https://x/": (200, b"{}")}),
                          max_age=0, root=tmp_path)
        assert result.path == "openapi/a/ci.json"


class TestSync:
    def _smartapi_body(self, hits):
        return json.dumps({"hits": hits}).encode()

    def test_it_plans_endpoints_from_the_registry(self, tmp_path):
        hits = [{"_id": "abc", "servers": [
            {"url": "https://svc.ci/", "x-maturity": "staging"}]}]
        fetcher = FakeFetcher({
            SMARTAPI_QUERY: (200, self._smartapi_body(hits)),
            "https://svc.ci/openapi.json": (200, b'{"info":{"version":"1.0"}}'),
        })
        component = _comp("svc", identifiers={"smartapi": "abc"})
        sync([component], tmp_path, fetcher=fetcher, max_age=0)
        assert "https://svc.ci/openapi.json" in fetcher.urls
        assert (tmp_path / "openapi" / "svc" / "ci.json").exists()

    def test_a_recorded_environment_beats_a_discovered_one(self, tmp_path):
        # node-annotator is recorded precisely because SmartAPI registers it at
        # a host that does not serve its OpenAPI.
        hits = [{"_id": "abc", "servers": [
            {"url": "https://wrong.ci/", "x-maturity": "staging"}]}]
        fetcher = FakeFetcher({SMARTAPI_QUERY: (200, self._smartapi_body(hits))})
        component = _comp(
            "svc",
            identifiers={"smartapi": "abc"},
            environments={"ci": Deployment(env="ci", url="https://right.ci/")},
        )
        sync([component], tmp_path, fetcher=fetcher, max_age=0)
        assert "https://right.ci/openapi.json" in fetcher.urls
        assert "https://wrong.ci/openapi.json" not in fetcher.urls

    def test_an_explicit_null_endpoint_is_never_fetched(self, tmp_path):
        # ploverdb records `openapi: null` — checked, there is none. Defaulting
        # over that would send the fetcher back to a known dead end every run.
        hits = [{"_id": "abc", "servers": [
            {"url": "https://svc.ci/", "x-maturity": "staging"}]}]
        fetcher = FakeFetcher({SMARTAPI_QUERY: (200, self._smartapi_body(hits))})
        component = _comp("svc", identifiers={"smartapi": "abc"},
                          endpoints={"openapi": None})
        sync([component], tmp_path, fetcher=fetcher, max_age=0)
        assert not [u for u in fetcher.urls if "svc.ci" in u]

    def test_the_manifest_records_failures_too(self, tmp_path):
        fetcher = FakeFetcher({SMARTAPI_QUERY: (200, self._smartapi_body([]))})
        report = sync([_comp("svc")], tmp_path, fetcher=fetcher, max_age=0)
        manifest = json.loads((tmp_path / "manifest.json").read_text())
        assert manifest["counts"]["attempted"] == len(report.fetches)
        assert manifest["counts"]["failed"] >= 1  # the OTel collectors 404 here
        assert manifest["finished_at"]

    def test_helm_files_are_fetched_for_a_charted_component(self, tmp_path):
        fetcher = FakeFetcher({SMARTAPI_QUERY: (200, self._smartapi_body([]))})
        sync([_comp("svc", identifiers={"helm_chart": "my-chart"})],
             tmp_path, fetcher=fetcher, max_age=0)
        assert any("helm/my-chart/Chart.yaml" in url for url in fetcher.urls)

    def test_a_component_being_down_does_not_fail_the_run(self, tmp_path):
        # The whole point: "was this endpoint reachable" is the question, so an
        # unreachable one is an answer.
        hits = [{"_id": "abc", "servers": [
            {"url": "https://down.ci/", "x-maturity": "staging"}]}]
        fetcher = FakeFetcher(
            {SMARTAPI_QUERY: (200, self._smartapi_body(hits))},
            default=ConnectionError("refused"),
        )
        report = sync([_comp("svc", identifiers={"smartapi": "abc"})],
                      tmp_path, fetcher=fetcher, max_age=0)
        assert report.succeeded >= 1
        assert any(f.error for f in report.fetches)


class TestReleaseFetches:
    def _repo(self, url, role="source"):
        return _comp("svc", repositories=[{"url": url, "role": role}])

    def test_a_source_repository_is_fetched(self, tmp_path):
        jobs = _plan_release_fetches(
            [self._repo("https://github.com/RTXteam/RTX")], tmp_path
        )
        assert jobs == [(
            "https://api.github.com/repos/RTXteam/RTX/releases?per_page=100",
            tmp_path / "releases" / "RTXteam" / "RTX.json",
        )]

    def test_one_repository_shared_by_three_components_is_fetched_once(self, tmp_path):
        # The three shepherds. GitHub allows sixty calls an hour unauthenticated;
        # spending three of them on one answer is how that budget disappears.
        shepherds = [
            _comp(cid, repositories=[
                {"url": "https://github.com/BioPack-team/shepherd", "role": "source"}
            ])
            for cid in ("shepherd-arax", "shepherd-bte", "shepherd-aragorn")
        ]
        assert len(_plan_release_fetches(shepherds, tmp_path)) == 1

    def test_a_helm_chart_path_is_not_a_repository(self, tmp_path):
        assert _plan_release_fetches([self._repo(
            "https://github.com/helxplatform/translator-devops"
            "/tree/develop/helm/jaeger", role="helm-chart")], tmp_path) == []

    def test_only_the_source_role_counts(self, tmp_path):
        # jaeger links jaegertracing/jaeger as `related`: upstream's releases
        # are not this deployment's.
        assert _plan_release_fetches(
            [self._repo("https://github.com/jaegertracing/jaeger", role="related")],
            tmp_path,
        ) == []

    def test_sync_fetches_them(self, tmp_path):
        fetcher = FakeFetcher({SMARTAPI_QUERY: (200, json.dumps({"hits": []}).encode())})
        sync([self._repo("https://github.com/a/b")], tmp_path,
             fetcher=fetcher, max_age=0)
        assert "https://api.github.com/repos/a/b/releases?per_page=100" in fetcher.urls


class TestSmartapiQuery:
    def test_every_field_the_dashboard_reads_is_requested(self):
        # A botched edit to this string fails silently: the request still
        # succeeds and the missing field looks like an upstream gap.
        for field in (
            "info.title", "info.version", "info.x-translator", "info.x-trapi",
            "servers", "_status", "_meta",
        ):
            assert field in SMARTAPI_QUERY

    def test_meta_is_asked_for_by_name(self):
        # meta=1 is a different parameter — it is what makes _id appear — and
        # does not bring _meta with it.
        assert "meta=1" in SMARTAPI_QUERY and "_meta" in SMARTAPI_QUERY


class TestChangedUrlInvalidatesCache:
    def _manifest(self, tmp_path, path, url):
        (tmp_path / "manifest.json").write_text(json.dumps(
            {"fetches": [{"path": path, "url": url, "status": 200}]}
        ))

    def test_a_body_fetched_from_another_url_is_refetched(self, tmp_path):
        # The real case: adding a field to SMARTAPI_QUERY leaves a fresh
        # smartapi.json that answered the older question.
        (tmp_path / "smartapi.json").write_text('{"hits": []}')
        self._manifest(tmp_path, "smartapi.json", "https://smart-api.info/old")
        fetcher = FakeFetcher({SMARTAPI_QUERY: (200, b'{"hits": []}')})
        sync([_comp("svc")], tmp_path, fetcher=fetcher, max_age=9999)
        assert SMARTAPI_QUERY in fetcher.urls

    def test_the_same_url_still_comes_from_cache(self, tmp_path):
        (tmp_path / "smartapi.json").write_text('{"hits": []}')
        self._manifest(tmp_path, "smartapi.json", SMARTAPI_QUERY)
        fetcher = FakeFetcher({})
        report = sync([_comp("svc")], tmp_path, fetcher=fetcher, max_age=9999)
        assert SMARTAPI_QUERY not in fetcher.urls
        assert any(f.cached for f in report.fetches)


class TestHeaders:
    def test_a_token_reaches_github_and_nowhere_else(self, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", "s3cret")
        assert _headers("https://api.github.com/repos/a/b/releases")[
            "Authorization"] == "Bearer s3cret"
        assert "Authorization" not in _headers("https://smart-api.info/api/query")

    def test_no_token_is_no_header(self, monkeypatch):
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        assert "Authorization" not in _headers("https://api.github.com/repos/a/b")


class TestConfirmDerived:
    """A derived host is believed only if it says it is the right component."""

    def _openapi(self, infores):
        return json.dumps({"info": {"version": "1.0", "x-translator": {
            "infores": infores}}}).encode()

    def test_a_matching_infores_is_accepted(self, tmp_path):
        component = _comp("svc", identifiers={"infores": "infores:svc"})
        candidate = Deployment(env="ci", url="https://svc.ci.transltr.io/")
        fetcher = FakeFetcher({
            "https://svc.ci.transltr.io/openapi.json":
                (200, self._openapi("infores:svc"))})
        result = _confirm_derived(component, candidate, fetcher, tmp_path, 0)
        assert result is not None and result.ok
        assert (tmp_path / "openapi" / "svc" / "ci.json").exists()

    def test_a_different_infores_is_rejected_and_the_body_removed(self, tmp_path):
        # A hostname in a shared namespace can answer for something adjacent.
        # Keeping the body would let a later run read it as this component's.
        component = _comp("svc", identifiers={"infores": "infores:svc"})
        candidate = Deployment(env="ci", url="https://svc.ci.transltr.io/")
        fetcher = FakeFetcher({
            "https://svc.ci.transltr.io/openapi.json":
                (200, self._openapi("infores:something-else"))})
        assert _confirm_derived(component, candidate, fetcher, tmp_path, 0) is None
        assert not (tmp_path / "openapi" / "svc" / "ci.json").exists()

    def test_no_recorded_infores_means_no_confirmation_is_possible(self, tmp_path):
        # An unverifiable guess is worth less than a gap, so it is dropped
        # rather than adopted on a bare 200.
        component = _comp("svc")
        candidate = Deployment(env="ci", url="https://svc.ci.transltr.io/")
        fetcher = FakeFetcher({
            "https://svc.ci.transltr.io/openapi.json": (200, self._openapi(None))})
        assert _confirm_derived(component, candidate, fetcher, tmp_path, 0) is None

    def test_an_unreachable_candidate_is_dropped(self, tmp_path):
        component = _comp("svc", identifiers={"infores": "infores:svc"})
        candidate = Deployment(env="ci", url="https://svc.ci.transltr.io/")
        assert _confirm_derived(component, candidate, FakeFetcher({}),
                                tmp_path, 0) is None

    def test_a_body_that_is_not_json_is_rejected(self, tmp_path):
        # Several Translator hosts answer 200 with an HTML error page.
        component = _comp("svc", identifiers={"infores": "infores:svc"})
        candidate = Deployment(env="ci", url="https://svc.ci.transltr.io/")
        fetcher = FakeFetcher({
            "https://svc.ci.transltr.io/openapi.json": (200, b"<html>nope</html>")})
        assert _confirm_derived(component, candidate, fetcher, tmp_path, 0) is None


class TestNegativeCaching:
    """Most derived hostnames do not resolve. Do not keep asking."""

    def _smartapi(self, servers):
        return json.dumps({"hits": [{"_id": "abc", "servers": servers}]}).encode()

    def _component(self):
        return _comp("svc", identifiers={
            "smartapi": "abc", "infores": "infores:svc"})

    def test_a_fresh_rejection_is_not_reprobed(self, tmp_path):
        (tmp_path / "derived.json").write_text(json.dumps({
            "confirmed": {},
            "rejected": {"svc": {"test": {
                "url": "https://svc.test.transltr.io/",
                "checked_at": _now_iso(),
            }}},
        }))
        fetcher = FakeFetcher({SMARTAPI_QUERY: (200, self._smartapi(
            [{"url": "https://svc.ci.transltr.io/", "x-maturity": "staging"}]))})
        sync([self._component()], tmp_path, fetcher=fetcher, max_age=9999)
        assert not [u for u in fetcher.urls if "svc.test.transltr.io" in u]
        # ...and the rejection is carried forward rather than dropped.
        after = json.loads((tmp_path / "derived.json").read_text())
        assert "test" in after["rejected"]["svc"]

    def test_a_stale_rejection_is_reprobed(self, tmp_path):
        (tmp_path / "derived.json").write_text(json.dumps({
            "confirmed": {},
            "rejected": {"svc": {"test": {
                "url": "https://svc.test.transltr.io/",
                "checked_at": "2020-01-01T00:00:00+00:00",
            }}},
        }))
        fetcher = FakeFetcher({SMARTAPI_QUERY: (200, self._smartapi(
            [{"url": "https://svc.ci.transltr.io/", "x-maturity": "staging"}]))})
        sync([self._component()], tmp_path, fetcher=fetcher, max_age=60)
        assert [u for u in fetcher.urls if "svc.test.transltr.io" in u]

    def test_a_rejection_for_a_different_url_is_reprobed(self, tmp_path):
        # The component moved host. The old answer says nothing about the new
        # one, so it must not suppress the probe.
        (tmp_path / "derived.json").write_text(json.dumps({
            "confirmed": {},
            "rejected": {"svc": {"test": {
                "url": "https://elsewhere.test.transltr.io/",
                "checked_at": _now_iso(),
            }}},
        }))
        fetcher = FakeFetcher({SMARTAPI_QUERY: (200, self._smartapi(
            [{"url": "https://svc.ci.transltr.io/", "x-maturity": "staging"}]))})
        sync([self._component()], tmp_path, fetcher=fetcher, max_age=9999)
        assert [u for u in fetcher.urls if "svc.test.transltr.io" in u]

    def test_a_confirmed_url_survives_being_recorded(self, tmp_path):
        # Once a discovered URL is written into a component file it stops being
        # derived, so this run derives nothing for it. Dropping the old entry
        # would look like the deployment had disappeared.
        (tmp_path / "derived.json").write_text(json.dumps({
            "confirmed": {"svc": {"ci": {"url": "https://svc.ci.transltr.io/"}}},
            "rejected": {},
        }))
        fetcher = FakeFetcher({SMARTAPI_QUERY: (200, self._smartapi([]))})
        sync([_comp("svc")], tmp_path, fetcher=fetcher, max_age=0)
        after = json.loads((tmp_path / "derived.json").read_text())
        assert after["confirmed"]["svc"]["ci"]["url"] == "https://svc.ci.transltr.io/"

    def test_an_unreadable_derived_file_does_not_stop_the_run(self, tmp_path):
        (tmp_path / "derived.json").write_text("{not json")
        fetcher = FakeFetcher({SMARTAPI_QUERY: (200, self._smartapi([]))})
        sync([_comp("svc")], tmp_path, fetcher=fetcher, max_age=0)
        assert json.loads((tmp_path / "derived.json").read_text())["confirmed"] == {}


class TestStillFresh:
    def test_a_recent_check_is_fresh(self):
        assert _still_fresh({"checked_at": _now_iso()}, 3600)

    def test_an_old_check_is_not(self):
        assert not _still_fresh({"checked_at": "2020-01-01T00:00:00+00:00"}, 60)

    def test_max_age_zero_never_reuses(self):
        assert not _still_fresh({"checked_at": _now_iso()}, 0)

    def test_a_malformed_timestamp_is_not_fresh(self):
        # Re-probing costs a DNS lookup; trusting a bad record costs a wrong page.
        assert not _still_fresh({"checked_at": "yesterday"}, 3600)
        assert not _still_fresh({}, 3600)
        assert not _still_fresh(None, 3600)


def test_sync_writes_derived_json_even_when_nothing_is_found(tmp_path):
    # The dashboard reads this file unconditionally; a missing one would make
    # "nothing was discovered" indistinguishable from "discovery never ran".
    fetcher = FakeFetcher({SMARTAPI_QUERY: (200, json.dumps({"hits": []}).encode())})
    sync([_comp("svc")], tmp_path, fetcher=fetcher, max_age=0)
    assert json.loads((tmp_path / "derived.json").read_text()) == {
        "confirmed": {}, "rejected": {}}


def test_fetch_result_ok_requires_both_a_200_and_no_error():
    assert FetchResult(url="u", path="p", status=200).ok
    assert not FetchResult(url="u", path="p", status=200, error="boom").ok
    assert not FetchResult(url="u", path="p", status=500).ok
