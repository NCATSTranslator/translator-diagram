"""The fetchers, driven by an injected fetcher so nothing here reaches the network."""

import json
from datetime import UTC, datetime

from translator_diagram.components import ComponentFile, Deployment
from translator_diagram.sync import (
    DEVOPS_HELM_INDEX,
    HELM_FILES,
    INFORES_CATALOG,
    SMARTAPI_QUERY,
    FetchResult,
    _chart_totals,
    _confirm_derived,
    _headers,
    _plan_catalog,
    _plan_chart_commits,
    _plan_chart_fetches,
    _plan_chart_index,
    _plan_index_chart_fetches,
    _plan_release_fetches,
    _plan_repo_meta,
    _plan_root_probes,
    _still_fresh,
    deployments_from_smartapi,
    fetch_to,
    probe_to,
    sync,
)


def _comp(cid, **kwargs):
    kwargs.setdefault("refactor_status", "New in Refactor")
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


class TestInferredMaturity:
    """A registry record that describes its servers instead of declaring them."""

    def _smartapi_shaped(self):
        # The smartapi component's own registration, as the registry serves it
        # today: two servers, prose descriptions, no x-maturity anywhere. It
        # used to yield no environments at all, so the one component that is
        # the registry had an empty row on a page about deployments.
        return {"servers": [
            {"description": "Production server", "url": "https://smart-api.info/api"},
            {"description": "Development server",
             "url": "https://dev.smart-api.info/api"},
        ]}

    def test_a_described_server_is_placed_and_marked(self):
        found = deployments_from_smartapi(self._smartapi_shaped())
        assert set(found) == {"prod", "dev"}
        assert found["prod"].url == "https://smart-api.info/api"
        assert all(d.inferred for d in found.values())

    def test_a_declared_maturity_is_not_marked_inferred(self):
        record = {"servers": [
            {"url": "https://x.ci/", "x-maturity": "staging",
             "description": "Production server"},
        ]}
        # Declared staging, described production. The field wins, and the cell
        # must not be labelled as a guess when nothing was guessed.
        found = deployments_from_smartapi(record)
        assert set(found) == {"ci"}
        assert found["ci"].inferred is False

    def test_a_declaration_is_never_overwritten_by_a_description(self):
        # Declaration first, description second, whatever order the servers are
        # listed in -- an ordering by position would let the later entry win.
        record = {"servers": [
            {"url": "https://described/", "description": "Production server"},
            {"url": "https://declared/", "x-maturity": "production"},
        ]}
        found = deployments_from_smartapi(record)
        assert found["prod"].url == "https://declared/"
        assert found["prod"].inferred is False

    def test_the_url_is_never_read_as_a_maturity(self):
        # `dev.smart-api.info` and `foo.ci.transltr.io` look like they name an
        # environment. Reading one would file a production host as dev on the
        # strength of a substring, which is the guess these files exist to
        # avoid: only prose somebody wrote counts.
        record = {"servers": [{"url": "https://dev.smart-api.info/api"}]}
        assert deployments_from_smartapi(record) == {}

    def test_a_description_naming_nothing_is_dropped(self):
        record = {"servers": [{"url": "https://x/", "description": "Main server"}]}
        assert deployments_from_smartapi(record) == {}

    def test_testing_is_not_read_as_test(self):
        # The alternation is ordered longest first, so "testing" cannot be
        # matched as "test" plus a suffix -- both map to the same environment
        # here, and would not if the vocabulary ever grew.
        record = {"servers": [{"url": "https://x/", "description": "Testing server"}]}
        assert set(deployments_from_smartapi(record)) == {"test"}

    def test_staging_is_ci_the_way_x_maturity_is(self):
        record = {"servers": [{"url": "https://x/", "description": "Staging server"}]}
        assert set(deployments_from_smartapi(record)) == {"ci"}


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
        #
        # The deployment's own URL is still probed, and that is the distinction
        # this test now draws: "this component serves no OpenAPI document" is
        # not "this host is not there", and the four UI environments spent a
        # release being reported as unreachable because the two were answered
        # with one request that was never made.
        hits = [{"_id": "abc", "servers": [
            {"url": "https://svc.ci/", "x-maturity": "staging"}]}]
        fetcher = FakeFetcher({SMARTAPI_QUERY: (200, self._smartapi_body(hits))})
        component = _comp("svc", identifiers={"smartapi": "abc"},
                          endpoints={"openapi": None})
        sync([component], tmp_path, fetcher=fetcher, max_age=0)
        assert not [u for u in fetcher.urls if "openapi.json" in u]
        assert fetcher.urls.count("https://svc.ci/") == 1

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


class TestRootProbe:
    """The deployment URL itself, contacted so `reachable` can mean something."""

    def test_every_deployment_is_probed(self, tmp_path):
        # Recorded, registered and confirmed-derived alike: the question is
        # whether a host answers, and how we came to know the host is beside
        # the point.
        hits = [{"_id": "abc", "servers": [
            {"url": "https://svc.ci/", "x-maturity": "staging"}]}]
        (tmp_path / "derived.json").write_text(json.dumps({"confirmed": {
            "svc": {"prod": {"url": "https://svc.prod/", "location": "ITRB"}}}}))
        component = _comp(
            "svc",
            identifiers={"smartapi": "abc"},
            environments={"test": Deployment(env="test", url="https://svc.test/")},
        )
        jobs = _plan_root_probes(
            [component],
            {"abc": hits[0]},
            {"svc": {"prod": Deployment(env="prod", url="https://svc.prod/")}},
            tmp_path,
        )
        assert [url for url, _ in jobs] == [
            "https://svc.ci/", "https://svc.test/", "https://svc.prod/"
        ]
        assert jobs[0][1] == tmp_path / "root" / "svc" / "ci.json"

    def test_a_component_with_no_deployment_is_not_probed(self, tmp_path):
        assert _plan_root_probes([_comp("svc")], {}, {}, tmp_path) == []

    def test_sync_probes_and_the_manifest_records_it(self, tmp_path):
        # The manifest promises every attempt this run made, and a probe is
        # one -- the Fetches tile counts more than the endpoints for exactly
        # this reason.
        hits = [{"_id": "abc", "servers": [
            {"url": "https://svc.ci/", "x-maturity": "staging"}]}]
        fetcher = FakeFetcher({
            SMARTAPI_QUERY: (200, self._body(hits)),
            "https://svc.ci/": (200, b"<html>a whole page</html>"),
        })
        report = sync([_comp("svc", identifiers={"smartapi": "abc"})],
                      tmp_path, fetcher=fetcher, max_age=0)
        assert "https://svc.ci/" in fetcher.urls
        assert any(f.path == "root/svc/ci.json" for f in report.fetches)
        manifest = json.loads((tmp_path / "manifest.json").read_text())
        assert any(f["path"] == "root/svc/ci.json" for f in manifest["fetches"])

    def test_the_saved_probe_is_a_summary_not_the_page(self, tmp_path):
        # The reason `probe_to` exists at all. A root probe answers with a
        # file browser, a login page or a single-page app's shell, and none of
        # those belongs under data/sync/, where every other reader expects a
        # document it can parse.
        fetcher = FakeFetcher(
            {"https://svc/": (200, b"<html><body>not a document</body></html>")}
        )
        target = tmp_path / "root" / "svc" / "ci.json"
        probe_to("https://svc/", target, fetcher, max_age=0, root=tmp_path)
        saved = json.loads(target.read_text())
        assert saved == {"status": 200, "content_type": None, "error": None}
        assert "html" not in target.read_text()

    def test_a_404_is_saved_rather_than_leaving_the_last_answer(self, tmp_path):
        # The other half of the difference from `fetch_to`, which keeps the
        # previous body on a non-200. A stale *status* is the lie the whole
        # manifest gate exists to stop.
        target = tmp_path / "root" / "svc" / "ci.json"
        target.parent.mkdir(parents=True)
        target.write_text(json.dumps({"status": 200, "content_type": None, "error": None}))
        probe_to("https://svc/", target, FakeFetcher({}), max_age=0, root=tmp_path)
        assert json.loads(target.read_text())["status"] == 404

    def test_a_failure_is_recorded_with_its_error(self, tmp_path):
        target = tmp_path / "root" / "svc" / "ci.json"
        fetcher = FakeFetcher({"https://svc/": OSError("nodename nor servname")})
        result = probe_to("https://svc/", target, fetcher, max_age=0, root=tmp_path)
        assert result.status is None and "OSError" in result.error
        saved = json.loads(target.read_text())
        assert saved["status"] is None and "OSError" in saved["error"]

    def test_a_cached_probe_reports_the_status_it_recorded(self, tmp_path):
        # `fetch_to` can report a cached hit as 200 because a body on disk got
        # there by being a 200. A probe summary is written whatever happened,
        # so reading 200 off its freshness would invent an answer.
        target = tmp_path / "root" / "svc" / "ci.json"
        target.parent.mkdir(parents=True)
        target.write_text(json.dumps(
            {"status": 503, "content_type": None, "error": None}
        ))
        fetcher = FakeFetcher({})
        result = probe_to("https://svc/", target, fetcher, max_age=9999, root=tmp_path)
        assert result.cached and result.status == 503 and fetcher.urls == []

    def test_a_content_type_is_kept_when_the_fetcher_reports_one(self, tmp_path):
        # The real fetcher answers with three parts; every fake in this file
        # answers with two, and both have to work.
        target = tmp_path / "root" / "svc" / "ci.json"
        probe_to("https://svc/", target,
                 lambda url: (200, b"<html>", "text/html"),
                 max_age=0, root=tmp_path)
        assert json.loads(target.read_text())["content_type"] == "text/html"

    def _body(self, hits):
        return json.dumps({"hits": hits}).encode()


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


class TestChartFetches:
    def test_one_chart_shared_by_three_components_is_fetched_once(self, tmp_path):
        # The three shepherds share one Helm chart. The loop this planner
        # replaced scheduled all three components, spending eighteen requests
        # on fifteen files and racing three threads over one destination.
        shepherds = [
            _comp(cid, identifiers={"helm_chart": "shepherd"})
            for cid in ("shepherd-arax", "shepherd-bte", "shepherd-aragorn")
        ]
        assert len(_plan_chart_fetches(shepherds, tmp_path)) == len(HELM_FILES)

    def test_a_component_with_no_chart_plans_nothing(self, tmp_path):
        assert _plan_chart_fetches([_comp("svc")], tmp_path) == []

    def test_every_chart_file_is_planned(self, tmp_path):
        jobs = _plan_chart_fetches(
            [_comp("svc", identifiers={"helm_chart": "my-chart"})], tmp_path
        )
        assert {destination.name for _, destination in jobs} == set(HELM_FILES)

    def test_a_component_deployed_by_two_charts_gets_both(self, tmp_path):
        # nodenorm-es is a web server chart and a loader chart. Planning only
        # the first would cache half the component and look complete doing it.
        jobs = _plan_chart_fetches(
            [_comp("svc", identifiers={"helm_chart": ["web-server", "loader"]})],
            tmp_path,
        )
        assert {d.parent.name for _, d in jobs} == {"web-server", "loader"}


class TestChartIndex:
    """One call names every chart in translator-devops; the rest is raw."""

    def _index(self, root, entries):
        (root / "helm").mkdir(parents=True, exist_ok=True)
        (root / "helm" / "index.json").write_text(json.dumps(entries))

    def test_it_is_planned_once_at_a_stable_path(self, tmp_path):
        # Stable, because the previous manifest's path-to-URL map is what
        # re-fetches a body whose URL moved. A path that varied would defeat it.
        assert _plan_chart_index(tmp_path) == [
            (DEVOPS_HELM_INDEX, tmp_path / "helm" / "index.json")
        ]

    def test_it_asks_for_the_branch_the_raw_fetches_use(self):
        assert "ref=develop" in DEVOPS_HELM_INDEX

    def test_every_directory_gets_a_chart_yaml(self, tmp_path):
        self._index(tmp_path, [
            {"name": "aragorn", "type": "dir"},
            {"name": "strider", "type": "dir"},
        ])
        jobs = _plan_index_chart_fetches(tmp_path)
        assert [d for _, d in jobs] == [
            tmp_path / "helm" / "aragorn" / "Chart.yaml",
            tmp_path / "helm" / "strider" / "Chart.yaml",
        ]
        assert jobs[0][0].endswith("/develop/helm/aragorn/Chart.yaml")

    def test_a_claimed_chart_is_not_planned_twice(self, tmp_path):
        # Two jobs in one pool writing one destination is the race that keying
        # _plan_chart_fetches by chart was meant to end.
        self._index(tmp_path, [
            {"name": "shepherd", "type": "dir"},
            {"name": "strider", "type": "dir"},
        ])
        claimed = _plan_chart_fetches(
            [_comp("svc", identifiers={"helm_chart": "shepherd"})], tmp_path
        )
        jobs = _plan_index_chart_fetches(tmp_path, [d for _, d in claimed])
        assert [d.parent.name for _, d in jobs] == ["strider"]

    def test_a_file_in_helm_is_not_a_chart(self, tmp_path):
        # helm/ holds loose files, and `redirects` is raw Ingress manifests
        # with no Chart.yaml — planning either would 404 every run.
        self._index(tmp_path, [
            {"name": "README.md", "type": "file"},
            {"name": "aragorn", "type": "dir"},
        ])
        assert [d.parent.name for _, d in _plan_index_chart_fetches(tmp_path)] == [
            "aragorn"
        ]

    def test_no_index_plans_nothing(self, tmp_path):
        assert _plan_index_chart_fetches(tmp_path) == []

    def test_an_index_of_the_wrong_shape_is_not_an_empty_repository(self, tmp_path):
        # A throttled contents call answers with an object carrying a message.
        for body in ({"message": "API rate limit exceeded"}, "nope"):
            self._index(tmp_path, body)
            assert _plan_index_chart_fetches(tmp_path) == []

    def test_sync_fetches_the_index_then_the_charts_it_names(self, tmp_path):
        fetcher = FakeFetcher({
            SMARTAPI_QUERY: (200, json.dumps({"hits": []}).encode()),
            DEVOPS_HELM_INDEX: (200, json.dumps(
                [{"name": "strider", "type": "dir"}]).encode()),
        })
        sync([_comp("svc")], tmp_path, fetcher=fetcher, max_age=0)
        assert DEVOPS_HELM_INDEX in fetcher.urls
        assert any(u.endswith("/helm/strider/Chart.yaml") for u in fetcher.urls)


class TestChartCommits:
    """The last commit on a chart directory — the intent to deploy, dated."""

    def test_one_plan_per_claimed_chart(self, tmp_path):
        jobs = _plan_chart_commits([
            _comp("a", identifiers={"helm_chart": "name-lookup"}),
            _comp("b", identifiers={"helm_chart": "jaeger"}),
        ], tmp_path)
        assert [d for _, d in jobs] == [
            tmp_path / "helm" / "jaeger" / "commit.json",
            tmp_path / "helm" / "name-lookup" / "commit.json",
        ]

    def test_one_chart_shared_by_three_components_is_asked_once(self, tmp_path):
        # An API call each, unlike the raw chart files: the three shepherds
        # spending three of GitHub's sixty on one answer is the budget going.
        shepherds = [
            _comp(cid, identifiers={"helm_chart": "shepherd"})
            for cid in ("shepherd-arax", "shepherd-bte", "shepherd-aragorn")
        ]
        assert len(_plan_chart_commits(shepherds, tmp_path)) == 1

    def test_the_url_names_the_chart_directory(self, tmp_path):
        (url, _), = _plan_chart_commits(
            [_comp("svc", identifiers={"helm_chart": "gandalf"})], tmp_path
        )
        assert "path=helm/gandalf" in url and "per_page=1" in url

    def test_a_component_with_no_chart_plans_nothing(self, tmp_path):
        assert _plan_chart_commits([_comp("svc")], tmp_path) == []

    def test_both_charts_of_a_two_chart_component(self, tmp_path):
        jobs = _plan_chart_commits(
            [_comp("svc", identifiers={"helm_chart": ["web-server", "loader"]})],
            tmp_path,
        )
        assert [d.parent.name for _, d in jobs] == ["loader", "web-server"]


class TestRepoMeta:
    """Repository descriptions, keyed by repository like the release lists."""

    def _repo(self, url, role="source"):
        return _comp("svc", repositories=[{"url": url, "role": role}])

    def test_a_source_repository_is_fetched(self, tmp_path):
        assert _plan_repo_meta(
            [self._repo("https://github.com/RTXteam/RTX")], tmp_path
        ) == [(
            "https://api.github.com/repos/RTXteam/RTX",
            tmp_path / "repos" / "RTXteam" / "RTX.json",
        )]

    def test_one_repository_shared_by_three_components_is_fetched_once(self, tmp_path):
        shepherds = [
            _comp(cid, repositories=[
                {"url": "https://github.com/BioPack-team/shepherd", "role": "source"}
            ])
            for cid in ("shepherd-arax", "shepherd-bte", "shepherd-aragorn")
        ]
        assert len(_plan_repo_meta(shepherds, tmp_path)) == 1

    def test_a_helm_chart_path_is_not_a_repository(self, tmp_path):
        # The same `github_repo` rule the release lists use: translator-devops'
        # own description is the devops team's, not this component's.
        assert _plan_repo_meta([self._repo(
            "https://github.com/helxplatform/translator-devops"
            "/tree/develop/helm/jaeger", role="helm-chart")], tmp_path) == []

    def test_only_the_source_role_counts(self, tmp_path):
        assert _plan_repo_meta(
            [self._repo("https://github.com/jaegertracing/jaeger", role="related")],
            tmp_path,
        ) == []

    def test_sync_fetches_them(self, tmp_path):
        fetcher = FakeFetcher({SMARTAPI_QUERY: (200, json.dumps({"hits": []}).encode())})
        sync([self._repo("https://github.com/a/b")], tmp_path,
             fetcher=fetcher, max_age=0)
        assert "https://api.github.com/repos/a/b" in fetcher.urls


class TestCatalog:
    def test_one_plan_at_a_stable_destination(self, tmp_path):
        assert _plan_catalog(tmp_path) == [
            (INFORES_CATALOG, tmp_path / "infores_catalog.yaml")
        ]

    def test_it_spends_nothing_from_the_github_api_budget(self):
        # raw.githubusercontent.com, so no Accept header, no token, no ceiling.
        assert INFORES_CATALOG.startswith("https://raw.githubusercontent.com/")
        assert "Authorization" not in _headers(INFORES_CATALOG)

    def test_sync_fetches_it(self, tmp_path):
        fetcher = FakeFetcher({
            SMARTAPI_QUERY: (200, json.dumps({"hits": []}).encode()),
            INFORES_CATALOG: (200, b"information_resources: []\n"),
        })
        sync([_comp("svc")], tmp_path, fetcher=fetcher, max_age=0)
        assert (tmp_path / "infores_catalog.yaml").exists()


class TestTheChartSummary:
    """How much of the chart repository the component files account for."""

    def test_it_counts_directories_against_distinct_claims(self, tmp_path):
        (tmp_path / "helm").mkdir()
        (tmp_path / "helm" / "index.json").write_text(json.dumps([
            {"name": "shepherd", "type": "dir"},
            {"name": "strider", "type": "dir"},
            {"name": "README.md", "type": "file"},
        ]))
        # Two components, one chart between them: the claim is counted once.
        shepherds = [
            _comp(cid, identifiers={"helm_chart": "shepherd"})
            for cid in ("shepherd-arax", "shepherd-bte")
        ]
        assert _chart_totals(shepherds, tmp_path) == (2, 1)

    def test_an_unreadable_index_counts_nothing_rather_than_guessing(self, tmp_path):
        assert _chart_totals([_comp("svc")], tmp_path) == (0, 0)

    def test_sync_says_both_numbers(self, tmp_path):
        lines: list[str] = []
        fetcher = FakeFetcher({
            SMARTAPI_QUERY: (200, json.dumps({"hits": []}).encode()),
            DEVOPS_HELM_INDEX: (200, json.dumps([
                {"name": "shepherd", "type": "dir"},
                {"name": "strider", "type": "dir"},
            ]).encode()),
        })
        sync([_comp("svc", identifiers={"helm_chart": "shepherd"})], tmp_path,
             fetcher=fetcher, max_age=0, echo=lines.append)
        assert any(
            "Helm charts in translator-devops: 2; claimed by component files: 1"
            in line for line in lines
        )


class TestTheMatchingSummary:
    """The two lines a data PR is written from."""

    def _sync(self, components, tmp_path, hits=(), charts=("shepherd", "strider")):
        lines: list[str] = []
        fetcher = FakeFetcher({
            SMARTAPI_QUERY: (200, json.dumps({"hits": list(hits)}).encode()),
            DEVOPS_HELM_INDEX: (200, json.dumps(
                [{"name": chart, "type": "dir"} for chart in charts]).encode()),
        })
        sync(components, tmp_path, fetcher=fetcher, max_age=0, echo=lines.append)
        return lines

    def _line(self, lines, prefix):
        return next(line for line in lines if line.startswith(prefix))

    def _hit(self, api_id, infores, title):
        return {
            "_id": api_id,
            "info": {"title": title, "x-translator": {"infores": infores}},
        }

    def test_it_names_the_charts_no_component_claims(self, tmp_path):
        # By name, the way throttled fetches are: a count alone leaves whoever
        # reads it with the same matching problem the line exists to answer.
        lines = self._sync(
            [_comp("svc", identifiers={"helm_chart": "shepherd"})],
            tmp_path,
            charts=("shepherd", "strider", "robokop"),
        )
        assert self._line(lines, "Charts matching no component:") == (
            "Charts matching no component: 2 (robokop, strider)"
        )

    def test_a_chart_matched_by_an_otel_service_is_accounted_for(self, tmp_path):
        # The gandalf rule: nobody recorded the chart, and it is still not
        # unclaimed.
        lines = self._sync(
            [_comp("dogpark-tier-0", identifiers={"otel_services": ["gandalf"]})],
            tmp_path,
            charts=("gandalf",),
        )
        assert self._line(lines, "Charts matching no component:") == (
            "Charts matching no component: 0"
        )

    def test_it_names_the_records_matched_by_infores(self, tmp_path):
        lines = self._sync(
            [_comp("svc", identifiers={"infores": "infores:svc"})],
            tmp_path,
            hits=[self._hit("xyz", "infores:svc", "Service API")],
        )
        assert self._line(
            lines, "SmartAPI records matching a component by infores"
        ) == (
            "SmartAPI records matching a component by infores that records no "
            "id: 1 (svc ← Service API)"
        )

    def test_a_component_that_already_records_an_id_is_not_suggested(self, tmp_path):
        # It is matched by that id, and a suggestion to record what is already
        # recorded is noise in a line somebody is meant to act on.
        lines = self._sync(
            [_comp("svc", identifiers={"smartapi": "xyz", "infores": "infores:svc"})],
            tmp_path,
            hits=[self._hit("xyz", "infores:svc", "Service API")],
        )
        assert self._line(
            lines, "SmartAPI records matching a component by infores"
        ).endswith(": 0")

    def test_an_ambiguous_infores_suggests_nothing(self, tmp_path):
        # Two records claiming one infores attach to nothing, so there is no
        # id for a data PR to record.
        lines = self._sync(
            [_comp("svc", identifiers={"infores": "infores:svc"})],
            tmp_path,
            hits=[self._hit("one", "infores:svc", "First"),
                  self._hit("two", "infores:svc", "Second")],
        )
        assert self._line(
            lines, "SmartAPI records matching a component by infores"
        ).endswith(": 0")

    def test_both_lines_are_printed_even_at_zero(self, tmp_path):
        # Unlike the throttling warning: "nothing is unaccounted for" is a
        # finding, and a line that appears only on bad news reads as a check
        # that did not run.
        lines = self._sync(
            [_comp("svc", identifiers={"helm_chart": "shepherd"})],
            tmp_path,
            charts=("shepherd",),
        )
        assert self._line(lines, "Charts matching no component:").endswith(": 0")
        assert self._line(
            lines, "SmartAPI records matching a component by infores"
        ).endswith(": 0")

    def test_it_reads_the_index_this_run_wrote(self, tmp_path):
        # The summary is computed from the freshly synced cache, not from a
        # list the planners happened to keep: a chart that appeared in
        # translator-devops during this run is in it.
        lines = self._sync([_comp("svc")], tmp_path, charts=("brand-new",))
        assert "brand-new" in self._line(lines, "Charts matching no component:")


class TestThrottling:
    def test_every_kind_of_github_call_is_counted_by_the_one_summary(self, tmp_path):
        # A silent 403 reads as "no releases", "no commits" and "no such
        # repository" — three findings, none of them true.
        lines: list[str] = []
        fetcher = FakeFetcher(
            {SMARTAPI_QUERY: (200, json.dumps({"hits": []}).encode())},
            default=(403, b'{"message": "API rate limit exceeded"}'),
        )
        component = _comp(
            "svc",
            identifiers={"helm_chart": "shepherd"},
            repositories=[{"url": "https://github.com/a/b", "role": "source"}],
        )
        report = sync([component], tmp_path, fetcher=fetcher, max_age=0,
                      echo=lines.append)
        throttled = [
            f for f in report.fetches
            if f.status == 403 and f.url.startswith("https://api.github.com/")
        ]
        # The index, the commit, the repository description and the releases.
        assert len(throttled) == 4
        assert any("rate-limited" in line for line in lines)
        assert report.finished_at  # and none of it failed the run


class TestSmartapiQuery:
    def test_every_field_the_dashboard_reads_is_requested(self):
        # A botched edit to this string fails silently: the request still
        # succeeds and the missing field looks like an upstream gap.
        for field in (
            "info.title", "info.version", "info.x-translator", "info.x-trapi",
            "servers", "_status", "_meta",
            "info.description", "info.contact", "tags",
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
        result, accepted = _confirm_derived(component, candidate, fetcher, tmp_path, 0)
        assert accepted and result is not None and result.ok
        assert (tmp_path / "openapi" / "svc" / "ci.json").exists()

    def test_a_different_infores_is_rejected_and_the_body_removed(self, tmp_path):
        # A hostname in a shared namespace can answer for something adjacent.
        # Keeping the body would let a later run read it as this component's.
        component = _comp("svc", identifiers={"infores": "infores:svc"})
        candidate = Deployment(env="ci", url="https://svc.ci.transltr.io/")
        fetcher = FakeFetcher({
            "https://svc.ci.transltr.io/openapi.json":
                (200, self._openapi("infores:something-else"))})
        result, accepted = _confirm_derived(component, candidate, fetcher, tmp_path, 0)
        assert not accepted
        # The request still happened, so the manifest still has to hear about it.
        assert result is not None and result.ok
        assert not (tmp_path / "openapi" / "svc" / "ci.json").exists()

    def test_no_recorded_infores_means_no_confirmation_is_possible(self, tmp_path):
        # An unverifiable guess is worth less than a gap, so it is dropped
        # rather than adopted on a bare 200 -- even a 200 that would have
        # matched, had there been anything to match it against.
        component = _comp("svc")
        candidate = Deployment(env="ci", url="https://svc.ci.transltr.io/")
        fetcher = FakeFetcher({
            "https://svc.ci.transltr.io/": (200, b"<html>something</html>"),
            "https://svc.ci.transltr.io/openapi.json": (200, self._openapi(None))})
        result, accepted = _confirm_derived(
            component, candidate, fetcher, tmp_path, 0)
        assert not accepted
        # The document is never asked for: there is no question it could
        # answer. The address is, so the rejection can say which kind of gap
        # this is -- a host that is not there reads differently from one
        # nobody looked for, and both used to arrive here as silence.
        assert "https://svc.ci.transltr.io/openapi.json" not in fetcher.urls
        assert result is not None and result.status == 200
        assert not (tmp_path / "openapi" / "svc" / "ci.json").exists()

    def test_a_candidate_that_does_not_resolve_records_the_failure(self, tmp_path):
        # Nine of the ten hostnames this repository derives do not resolve.
        # Recorded as an error, that is "no such host" in the cell; recorded as
        # nothing, it is indistinguishable from never having asked.
        component = _comp("svc")
        candidate = Deployment(env="ci", url="https://svc.ci.transltr.io/")
        fetcher = FakeFetcher(
            {}, default=OSError("nodename nor servname provided"))
        result, accepted = _confirm_derived(
            component, candidate, fetcher, tmp_path, 0)
        assert not accepted
        assert "OSError" in result.error

    def test_an_unreachable_candidate_is_dropped(self, tmp_path):
        component = _comp("svc", identifiers={"infores": "infores:svc"})
        candidate = Deployment(env="ci", url="https://svc.ci.transltr.io/")
        result, accepted = _confirm_derived(
            component, candidate, FakeFetcher({}), tmp_path, 0)
        assert not accepted and result is not None and not result.ok

    def test_a_body_that_is_not_json_is_rejected(self, tmp_path):
        # Several Translator hosts answer 200 with an HTML error page.
        component = _comp("svc", identifiers={"infores": "infores:svc"})
        candidate = Deployment(env="ci", url="https://svc.ci.transltr.io/")
        fetcher = FakeFetcher({
            "https://svc.ci.transltr.io/openapi.json": (200, b"<html>nope</html>")})
        assert _confirm_derived(component, candidate, fetcher, tmp_path, 0)[1] is False

    def test_json_of_an_unexpected_shape_is_rejected_not_raised(self, tmp_path):
        # Copilot: a guessed hostname answers with whatever it likes. All three
        # of these are valid JSON with no infores in them, and chaining `.get`
        # through any of them used to raise AttributeError and end the sync.
        component = _comp("svc", identifiers={"infores": "infores:svc"})
        candidate = Deployment(env="ci", url="https://svc.ci.transltr.io/")
        for body in (b"[]", b'{"info": null}', b'{"info": {"x-translator": 3}}'):
            fetcher = FakeFetcher({
                "https://svc.ci.transltr.io/openapi.json": (200, body)})
            assert _confirm_derived(
                component, candidate, fetcher, tmp_path, 0)[1] is False


class TestAMalformedRegistry:
    """The registry is whatever came back, and the run has to survive it."""

    def _smartapi(self, hits):
        return json.dumps({"hits": hits}).encode()

    def test_an_html_error_page_does_not_end_the_run(self, tmp_path):
        # Copilot: parsing this in the open ended the sync after the registries,
        # the charts and the release lists had all already succeeded.
        fetcher = FakeFetcher({SMARTAPI_QUERY: (200, b"<html>bad gateway</html>")})
        report = sync([_comp("svc")], tmp_path, fetcher=fetcher, max_age=0)
        assert (tmp_path / "manifest.json").exists()
        assert report.finished_at

    def test_a_registry_of_the_wrong_shape_is_ignored(self, tmp_path):
        for n, body in enumerate((b"[]", b'{"hits": "nope"}', b'{"hits": [1, 2]}')):
            root = tmp_path / f"run{n}"
            root.mkdir()
            fetcher = FakeFetcher({SMARTAPI_QUERY: (200, body)})
            sync([_comp("svc")], root, fetcher=fetcher, max_age=0)
            assert (root / "manifest.json").exists()


class TestTheManifestRecordsEveryAttempt:
    def test_a_rejected_probe_is_still_a_fetch(self, tmp_path):
        # Copilot: the counts omitted exactly the unsuccessful probes, against
        # this module's promise to record every attempt including the failures.
        component = _comp(
            "svc",
            identifiers={"infores": "infores:svc"},
            environments={"prod": Deployment(env="prod", url="https://svc.transltr.io/")},
        )
        fetcher = FakeFetcher({SMARTAPI_QUERY: (200, json.dumps({"hits": []}).encode())})
        report = sync([component], tmp_path, fetcher=fetcher, max_age=0)
        probes = [f for f in report.fetches if "transltr.io" in f.url]
        assert probes, "the derived probes should be in the manifest"
        assert all(not f.ok for f in probes)
        counts = report.to_dict()["counts"]
        assert counts["attempted"] == len(report.fetches)
        assert counts["failed"] >= len(probes)


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

    def test_a_rejection_this_run_beats_an_older_confirmation(self, tmp_path):
        # Copilot (suppressed): the carry-forward reinstated a confirmation the
        # same run had just probed and rejected, so a derived deployment stayed
        # published for good once it had been confirmed a single time.
        (tmp_path / "derived.json").write_text(json.dumps({
            "confirmed": {"svc": {"ci": {"url": "https://svc.ci.transltr.io/"}}},
            "rejected": {},
        }))
        fetcher = FakeFetcher({SMARTAPI_QUERY: (200, self._smartapi([]))})
        component = _comp(
            "svc",
            identifiers={"infores": "infores:svc"},
            environments={"prod": Deployment(env="prod", url="https://svc.transltr.io/")},
        )
        sync([component], tmp_path, fetcher=fetcher, max_age=0)
        after = json.loads((tmp_path / "derived.json").read_text())
        assert "ci" not in after["confirmed"].get("svc", {})
        assert "ci" in after["rejected"]["svc"]

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
