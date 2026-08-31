"""The fetchers, driven by an injected fetcher so nothing here reaches the network."""

import json

from translator_diagram.components import ComponentFile, Deployment
from translator_diagram.sync import (
    SMARTAPI_QUERY,
    FetchResult,
    _confirm_derived,
    deployments_from_smartapi,
    fetch_to,
    sync,
)


def _comp(cid, **kwargs):
    kwargs.setdefault("diagram", {"refactor_status": "New in Refactor"})
    return ComponentFile(id=cid, name=cid, owner="None", **kwargs)


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


def test_sync_writes_derived_json_even_when_nothing_is_found(tmp_path):
    # The dashboard reads this file unconditionally; a missing one would make
    # "nothing was discovered" indistinguishable from "discovery never ran".
    fetcher = FakeFetcher({SMARTAPI_QUERY: (200, json.dumps({"hits": []}).encode())})
    sync([_comp("svc")], tmp_path, fetcher=fetcher, max_age=0)
    assert json.loads((tmp_path / "derived.json").read_text()) == {}


def test_fetch_result_ok_requires_both_a_200_and_no_error():
    assert FetchResult(url="u", path="p", status=200).ok
    assert not FetchResult(url="u", path="p", status=200, error="boom").ok
    assert not FetchResult(url="u", path="p", status=500).ok
