"""Parsing components/*.yaml into ComponentFile."""

import yaml

from translator_diagram.components import (
    DEFAULT_ENDPOINT_PATHS,
    ENVIRONMENTS,
    Deployment,
    chart_matches,
    derive_deployments,
    endpoint_url_in,
    github_repo,
    index_by_id,
    load_components,
    merge_deployments,
    parse_component,
    smartapi_record_for,
)

MINIMAL = {"id": "svc", "name": "Service", "owner": "DOGSLED",
           "refactor_status": "New in Refactor"}


def _parse(**overrides):
    return parse_component({**MINIMAL, **overrides})


class TestParsing:
    def test_a_minimal_file(self):
        component = _parse()
        assert (component.id, component.name, component.owner) == (
            "svc", "Service", "DOGSLED")
        assert component.identifiers == {} and component.environments == {}

    def test_name_falls_back_to_id(self):
        assert parse_component({**MINIMAL, "name": None}).name == "svc"

    def test_owner_falls_back_to_none(self):
        # Matches loading.py, so both sides of the repo agree on the key that
        # config/owner-colors.csv is looked up by.
        assert parse_component({**MINIMAL, "owner": ""}).owner == "None"

    def test_identifier_accessors(self):
        component = _parse(identifiers={
            "infores": "infores:x", "smartapi": "abc", "helm_chart": "chart",
            "otel_services": ["A", "B"]})
        assert component.infores == "infores:x"
        assert component.smartapi_id == "abc"
        assert component.helm_chart == "chart"
        assert component.otel_services == ["A", "B"]

    def test_missing_identifiers_are_none_not_errors(self):
        component = _parse()
        assert component.infores is None and component.otel_services == []

    def test_helm_charts_normalises_a_string_a_list_and_nothing(self):
        # nodenorm-es is two charts, most components are one, and most files
        # record nothing. `helm_chart` keeps returning a string either way,
        # because it is a payload key with consumers.
        one = _parse(identifiers={"helm_chart": "shepherd"})
        assert one.helm_charts == ["shepherd"] and one.helm_chart == "shepherd"
        two = _parse(identifiers={"helm_chart": [
            "node-normalization-web-server", "node-normalization-loader"]})
        assert two.helm_charts == [
            "node-normalization-web-server", "node-normalization-loader"]
        assert two.helm_chart == "node-normalization-web-server"
        none = _parse()
        assert none.helm_charts == [] and none.helm_chart is None

    def test_the_wiki_page_is_a_name_not_a_url(self):
        component = _parse(identifiers={"translator_all_wiki": "RTX-KG2"})
        assert component.translator_all_wiki == "RTX-KG2"
        assert _parse().translator_all_wiki is None

    def test_repository_selects_by_role(self):
        component = _parse(repositories=[
            {"url": "https://chart", "role": "helm-chart"},
            {"url": "https://src", "role": "source"},
        ])
        assert component.repository("source") == "https://src"
        assert component.repository("helm-chart") == "https://chart"
        assert component.repository("data") is None


class TestEdges:
    def test_both_edge_kinds_are_upstream(self):
        component = _parse(
            connections={"gets_results_from": ["a"], "calls": ["b"]})
        assert set(component.upstream) == {"a", "b"}

    def test_a_planned_edge_keeps_its_target(self):
        component = _parse(connections={"calls": ["~a"]})
        assert component.upstream == ["a"]

    def test_externals_are_direction_and_name(self):
        component = _parse(connections={"externals": [
            {"direction": "in", "name": "Sources"}]})
        assert component.externals == [("in", "Sources")]
        assert component.fed_by_external

    def test_an_outward_external_does_not_feed_in(self):
        component = _parse(connections={"externals": [
            {"direction": "out", "name": "User"}]})
        assert not component.fed_by_external

    def test_planned_and_implemented_edges_stay_apart(self):
        # `upstream` flattens all four into one list because a data-flow
        # ordering does not care how a call was made. The map does care: a
        # planned edge is a claim about intent and is drawn differently.
        component = _parse(connections={
            "gets_results_from": ["a", "~b"], "calls": ["c", "~d"]})
        assert component.connection_ids() == {
            "gets_results_from": ["a"],
            "calls": ["c"],
            "planned_gets_results_from": ["b"],
            "planned_calls": ["d"],
        }

    def test_the_tilde_is_not_part_of_the_id(self):
        # node-annotator records `~jaeger`. Leaving the marker on the id means
        # the reference resolves to nothing, and every consumer downstream —
        # the edge builder, the privacy pruner — has to strip it again.
        component = _parse(connections={"calls": ["~jaeger"]})
        assert component.connection_ids()["planned_calls"] == ["jaeger"]

    def test_an_absent_list_is_an_empty_one(self):
        # All four keys, always: a consumer indexing `connections["calls"]`
        # should not have to know which components happen to record any.
        assert _parse().connection_ids() == {
            "gets_results_from": [],
            "calls": [],
            "planned_gets_results_from": [],
            "planned_calls": [],
        }


class TestEndpointUrls:
    def _deployment(self, **kwargs):
        return Deployment(env="ci", url="https://svc.ci/", **kwargs)

    def test_a_relative_path_joins_onto_the_base(self):
        component = _parse(endpoints={"openapi": "webapp/openapi.json"})
        assert endpoint_url_in(component, self._deployment(), "openapi") == (
            "https://svc.ci/webapp/openapi.json")

    def test_a_base_with_a_path_keeps_it(self):
        # arax registers .../api/arax/v1.4 as its base. urljoin would discard
        # everything after the last slash and fetch the wrong document.
        component = _parse(endpoints={"openapi": "openapi.json"})
        deployment = Deployment(env="ci", url="https://arax.ci/api/arax/v1.4")
        assert endpoint_url_in(component, deployment, "openapi") == (
            "https://arax.ci/api/arax/v1.4/openapi.json")

    def test_a_per_environment_override_wins(self):
        # node-annotator's prod serves openapi.json where ci and test serve
        # webapp/openapi.json.
        component = _parse(endpoints={"openapi": "webapp/openapi.json"})
        deployment = self._deployment(endpoints={"openapi": "openapi.json"})
        assert endpoint_url_in(component, deployment, "openapi") == (
            "https://svc.ci/openapi.json")

    def test_an_absent_path_falls_through_to_the_default(self):
        component = _parse()
        assert endpoint_url_in(component, self._deployment(), "openapi") == (
            "https://svc.ci/" + DEFAULT_ENDPOINT_PATHS["openapi"])

    def test_an_explicit_null_beats_the_default(self):
        # The distinction the whole format rests on: absent means nobody has
        # looked, null means someone did and there is nothing there.
        component = _parse(endpoints={"openapi": None})
        assert endpoint_url_in(component, self._deployment(), "openapi") is None

    def test_a_per_environment_null_beats_a_component_path(self):
        component = _parse(endpoints={"openapi": "openapi.json"})
        deployment = self._deployment(endpoints={"openapi": None})
        assert endpoint_url_in(component, deployment, "openapi") is None

    def test_status_has_no_default(self):
        # Defaulting it would manufacture a 404 per environment and call it data.
        assert "status" not in DEFAULT_ENDPOINT_PATHS
        assert endpoint_url_in(_parse(), self._deployment(), "status") is None

    def test_the_method_only_sees_recorded_environments(self):
        component = _parse(endpoints={"openapi": "openapi.json"})
        assert component.endpoint_url("ci", "openapi") is None


class TestMergeDeployments:
    def test_recorded_beats_discovered(self):
        # _parse goes through parse_component, so environments arrive in the
        # raw YAML shape rather than as Deployment objects.
        component = _parse(environments={"ci": {"url": "https://right/"}})
        merged = merge_deployments(
            component, {"ci": Deployment(env="ci", url="https://wrong/")})
        assert merged["ci"].url == "https://right/"

    def test_discovered_fills_the_gaps(self):
        component = _parse()
        merged = merge_deployments(
            component, {"prod": Deployment(env="prod", url="https://p/")})
        assert set(merged) == {"prod"}

    def test_the_result_is_in_ladder_order(self):
        component = _parse()
        merged = merge_deployments(component, {
            env: Deployment(env=env, url=f"https://{env}/")
            for env in reversed(ENVIRONMENTS)
        })
        assert list(merged) == list(ENVIRONMENTS)

    def test_an_unknown_environment_name_is_dropped(self):
        component = _parse()
        merged = merge_deployments(
            component, {"staging": Deployment(env="staging", url="https://s/")})
        assert merged == {}


class TestDeriveDeployments:
    def test_the_other_maturities_follow_from_one(self):
        # answer-appraiser registers only production, and is deployed to ci and
        # test as well. Knowing one host is knowing where to look for the rest.
        known = {"prod": Deployment(env="prod", url="https://answerappraiser.transltr.io")}
        assert {e: d.url for e, d in derive_deployments(known).items()} == {
            "ci": "https://answerappraiser.ci.transltr.io/",
            "test": "https://answerappraiser.test.transltr.io/",
        }

    def test_a_path_on_the_base_survives(self):
        # arax registers .../api/arax/v1.4; a sibling host without that path
        # would 404 and be silently dropped.
        known = {"ci": Deployment(env="ci", url="https://arax.ci.transltr.io/api/arax/v1.4")}
        assert derive_deployments(known)["prod"].url == (
            "https://arax.transltr.io/api/arax/v1.4/")

    def test_known_environments_are_left_alone(self):
        known = {
            "ci": Deployment(env="ci", url="https://x.ci.transltr.io"),
            "prod": Deployment(env="prod", url="https://x.transltr.io"),
        }
        assert set(derive_deployments(known)) == {"test"}

    def test_dev_is_never_derived(self):
        # Development deployments live at RENCI, at BioThings, and elsewhere.
        # There is no convention, so there is nothing to derive.
        known = {"prod": Deployment(env="prod", url="https://x.transltr.io")}
        assert "dev" not in derive_deployments(known)

    def test_the_commonest_stem_wins_when_hosts_disagree(self):
        # Three known hosts under one namespace, one stem used twice: the odd
        # one out is not the shape to derive the missing environment from,
        # however early on the ladder it sits.
        known = {
            "dev": Deployment(env="dev", url="https://renamed.transltr.io/"),
            "ci": Deployment(env="ci", url="https://svc.ci.transltr.io/"),
            "test": Deployment(env="test", url="https://svc.test.transltr.io/"),
        }
        assert derive_deployments(known)["prod"].url == "https://svc.transltr.io/"

    def test_a_tie_is_broken_by_the_ladder_not_the_alphabet(self):
        # One each. Sorting the stems and taking the first made the choice by
        # spelling; the environment nearer the start of the ladder is at least
        # a property of the deployments.
        known = {
            "ci": Deployment(env="ci", url="https://zulu.ci.transltr.io/"),
            "test": Deployment(env="test", url="https://alpha.test.transltr.io/"),
        }
        assert derive_deployments(known)["prod"].url == "https://zulu.transltr.io/"

    def test_a_non_itrb_host_yields_nothing(self):
        known = {"dev": Deployment(env="dev", url="https://x.renci.org/")}
        assert derive_deployments(known) == {}

    def test_nothing_known_derives_nothing(self):
        assert derive_deployments({}) == {}


class TestGithubRepo:
    def test_a_plain_repository_url(self):
        assert github_repo("https://github.com/RTXteam/RTX") == "RTXteam/RTX"

    def test_a_trailing_slash_or_dot_git(self):
        assert github_repo("https://github.com/a/b/") == "a/b"
        assert github_repo("https://github.com/a/b.git") == "a/b"

    def test_a_path_into_a_repository_is_not_one(self):
        # Every helm-chart entry looks like this. Its releases belong to the
        # devops repository, not to the component, so it must not match.
        assert github_repo(
            "https://github.com/helxplatform/translator-devops"
            "/tree/develop/helm/shepherd"
        ) is None

    def test_a_non_github_url_or_none(self):
        assert github_repo("https://gitlab.com/a/b") is None
        assert github_repo(None) is None
        assert github_repo("") is None


class TestLoading:
    def test_files_load_sorted_case_insensitively(self, tmp_path):
        for cid in ("Zebra", "apple"):
            (tmp_path / f"{cid}.yaml").write_text(
                yaml.safe_dump({**MINIMAL, "id": cid}))
        assert [c.id for c in load_components(tmp_path)] == ["apple", "Zebra"]

    def test_an_empty_directory_loads_nothing(self, tmp_path):
        assert load_components(tmp_path) == []

    def test_index_is_case_insensitive(self):
        assert "svc" in index_by_id([_parse(id="SVC")])


class TestChartMatches:
    """Fifty charts against twenty-six components, in five rules."""

    def _match(self, chart, components, meta=None):
        return chart_matches([chart], {chart: meta or {}}, components)[chart]

    def test_a_recorded_chart_beats_every_other_rule(self):
        # The component that wrote it down wins even where a second component's
        # id is the chart's name: a rule further down must never re-attribute a
        # chart somebody decided about.
        recorder = _parse(id="dogpark-tier-0", identifiers={"helm_chart": "gandalf"})
        namesake = _parse(id="gandalf")
        found = self._match("gandalf", [namesake, recorder])
        assert found["component"] == "dogpark-tier-0"
        assert found["confidence"] == "recorded"
        assert "identifiers.helm_chart" in found["evidence"]

    def test_a_chart_named_for_the_component_id(self):
        found = self._match("name-lookup", [_parse(id="name-lookup")])
        assert (found["component"], found["confidence"]) == ("name-lookup", "strong")
        assert "component id" in found["evidence"]

    def test_a_chart_named_for_an_otel_service_ignoring_case(self):
        # How gandalf finds dogpark-tier-0. Case folds here because a chart
        # directory and a service name are written by different hands, unlike
        # the collector join in the dashboard, where two real services differ
        # only by case.
        component = _parse(
            id="dogpark-tier-0", identifiers={"otel_services": ["Gandalf"]}
        )
        found = self._match("gandalf", [component])
        assert (found["component"], found["confidence"]) == (
            "dogpark-tier-0", "strong")
        assert "Gandalf" in found["evidence"]

    def test_an_infores_anywhere_in_the_values(self):
        # Two charts write it under two different keys, so the whole document
        # is walked rather than one path being guessed at.
        component = _parse(id="dogpark-tier-0",
                           identifiers={"infores": "infores:dogpark-tier0"})
        meta = {"values": {"datasetDesc": {"provenanceTag": "infores:dogpark-tier0"}}}
        found = self._match("gandalf", [component], meta)
        assert (found["component"], found["confidence"]) == (
            "dogpark-tier-0", "strong")
        assert "infores:dogpark-tier0" in found["evidence"]

    def test_an_image_repository_naming_the_source_repository(self):
        # ghcr.io/ncatstranslator/nameresolution ↔ NCATSTranslator/NameResolution:
        # the registry host is dropped and the two names are compared folded.
        component = _parse(id="name-lookup", repositories=[
            {"url": "https://github.com/NCATSTranslator/NameResolution",
             "role": "source"}])
        meta = {"images": {
            "nameLookup": {"image": "ghcr.io/ncatstranslator/nameresolution",
                           "version": "v1.5.2"}}}
        found = self._match("some-chart", [component], meta)
        assert (found["component"], found["confidence"]) == (
            "name-lookup", "plausible")
        assert "NCATSTranslator/NameResolution" in found["evidence"]

    def test_an_image_with_no_owner_matches_nothing(self):
        # `solr` and `busybox` name no repository, and half a match is worse
        # than none.
        component = _parse(id="solr", repositories=[
            {"url": "https://github.com/apache/solr", "role": "source"}])
        meta = {"values": {"solr": {"image": {"repository": "solr"}}}}
        assert self._match("some-chart", [component], meta)["component"] is None

    def test_a_chart_nothing_claims(self):
        found = self._match("robokop", [_parse(id="svc")])
        assert found == {
            "component": None, "components": [], "confidence": "none",
            "evidence": "",
        }

    def test_a_chart_three_components_share_lists_all_three(self):
        # The shepherd chart deploys three components. `component` stays one id
        # because most callers want one answer, and `components` is what keeps
        # the page honest about the other two.
        shepherds = [
            _parse(id=cid, identifiers={"helm_chart": "shepherd"})
            for cid in ("shepherd-aragorn", "shepherd-arax", "shepherd-bte")
        ]
        found = self._match("shepherd", shepherds)
        assert found["components"] == [
            "shepherd-aragorn", "shepherd-arax", "shepherd-bte"]
        assert found["component"] == "shepherd-aragorn"

    def test_a_chart_with_no_cached_values_falls_through_quietly(self):
        # Only claimed charts have a values.yaml, so the last two rules cannot
        # fire for the forty-odd others. That is the cache being proportional,
        # not a crash.
        component = _parse(id="svc", identifiers={"infores": "infores:svc"})
        found = chart_matches(
            ["robokop"], {"robokop": {"chart": None, "values": None, "images": None}},
            [component],
        )["robokop"]
        assert found["confidence"] == "none"

    def test_every_chart_asked_about_gets_an_answer(self):
        found = chart_matches(["a", "b"], {}, [])
        assert set(found) == {"a", "b"}


class TestSmartapiRecordFor:
    """Which registry record belongs to a component, and how we know."""

    def _hit(self, api_id, infores=None, title=None):
        record = {"_id": api_id, "info": {"title": title or api_id}}
        if infores:
            record["info"]["x-translator"] = {"infores": infores}
        return record

    def test_a_recorded_id_is_believed(self):
        hits = [self._hit("abc"), self._hit("def")]
        record, matched_by, candidates = smartapi_record_for(
            _parse(identifiers={"smartapi": "def"}), hits)
        assert record["_id"] == "def"
        assert (matched_by, candidates) == ("id", [])

    def test_one_record_claiming_the_infores(self):
        hits = [self._hit("abc", "infores:other"), self._hit("def", "infores:svc")]
        record, matched_by, candidates = smartapi_record_for(
            _parse(identifiers={"infores": "infores:svc"}), hits)
        assert (record["_id"], matched_by, candidates) == ("def", "infores", [])

    def test_several_records_claiming_it_attach_nothing(self):
        # Three infores in the registry today are claimed by more than one
        # record. Picking one would hang a version, a TRAPI level and an uptime
        # result on a coin toss, so the row shows the candidates instead.
        hits = [self._hit("abc", "infores:svc", "One"),
                self._hit("def", "infores:svc", "Two")]
        record, matched_by, candidates = smartapi_record_for(
            _parse(identifiers={"infores": "infores:svc"}), hits)
        assert (record, matched_by) == (None, None)
        assert candidates == [
            {"smartapi_id": "abc", "title": "One"},
            {"smartapi_id": "def", "title": "Two"},
        ]

    def test_nothing_matches_at_all(self):
        assert smartapi_record_for(
            _parse(identifiers={"infores": "infores:svc"}),
            [self._hit("abc", "infores:other")],
        ) == (None, None, [])

    def test_a_component_with_no_pointers_matches_nothing(self):
        assert smartapi_record_for(_parse(), [self._hit("abc")]) == (None, None, [])

    def test_a_title_is_never_matched_on(self):
        # "ARAX" is a component, an OpenTelemetry service and the first word of
        # several registry titles.
        hits = [self._hit("abc", title="svc")]
        assert smartapi_record_for(_parse(id="svc"), hits) == (None, None, [])


def test_the_real_files_all_parse():
    # The fixtures above are small on purpose; this is the check that the
    # actual repository data still fits the parser.
    from pathlib import Path

    components = load_components(Path(__file__).resolve().parent.parent / "components")
    assert components
    assert all(c.id and c.name and c.owner for c in components)


def test_the_real_files_fill_the_fields_the_dashboard_reads():
    # Every accessor here reads a key through .get(), so a field that moves in
    # the YAML does not raise -- it comes back empty, and a page of blank cells
    # is a passing test suite. This is the check that noticed nothing when
    # `diagram:` was split, so it now asserts on the data rather than the
    # shape: each of these is recorded for at least half the components, and a
    # zero means the parser and the files have stopped agreeing.
    from pathlib import Path

    components = load_components(Path(__file__).resolve().parent.parent / "components")
    populated = {
        "refactor_status": sum(1 for c in components if c.refactor_status),
        "layer": sum(1 for c in components if c.layer),
        "hosted_at": sum(1 for c in components if c.hosted_at),
        "itrb_app": sum(1 for c in components if c.itrb_app),
        "upstream": sum(1 for c in components if c.upstream),
    }
    half = len(components) // 2
    assert all(n > half for n in populated.values()), populated
