"""Parsing components/*.yaml into ComponentFile."""

import yaml

from translator_diagram.components import (
    DEFAULT_ENDPOINT_PATHS,
    ENVIRONMENTS,
    Deployment,
    endpoint_url_in,
    index_by_id,
    load_components,
    merge_deployments,
    parse_component,
)

MINIMAL = {"id": "svc", "name": "Service", "owner": "DOGSLED",
           "diagram": {"refactor_status": "New in Refactor"}}


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
        component = _parse(diagram={"refactor_status": "x",
                                    "gets_results_from": ["a"], "calls": ["b"]})
        assert set(component.upstream) == {"a", "b"}

    def test_a_planned_edge_keeps_its_target(self):
        component = _parse(diagram={"refactor_status": "x", "calls": ["~a"]})
        assert component.upstream == ["a"]

    def test_externals_are_direction_and_name(self):
        component = _parse(diagram={"refactor_status": "x", "externals": [
            {"direction": "in", "name": "Sources"}]})
        assert component.externals == [("in", "Sources")]
        assert component.fed_by_external

    def test_an_outward_external_does_not_feed_in(self):
        component = _parse(diagram={"refactor_status": "x", "externals": [
            {"direction": "out", "name": "User"}]})
        assert not component.fed_by_external


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
