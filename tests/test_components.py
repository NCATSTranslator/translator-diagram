"""Parsing components/*.yaml into ComponentFile."""

import yaml

from translator_diagram.components import (
    DEFAULT_ENDPOINT_PATHS,
    Deployment,
    endpoint_url_in,
    github_repo,
    index_by_id,
    load_components,
    parse_component,
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
