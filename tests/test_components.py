"""Parsing components/*.yaml into ComponentFile."""

import yaml

from translator_diagram.components import (
    DEFAULT_ENDPOINT_PATHS,
    ENVIRONMENTS,
    Deployment,
    derive_deployments,
    endpoint_url_in,
    github_repo,
    index_by_id,
    load_components,
    merge_deployments,
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

    def test_the_private_block_is_not_parsed(self):
        # The guarantee that nothing under `private:` reaches overview.json is
        # structural: the dashboard stack reads ComponentFile, and ComponentFile
        # has no such field. content.py re-reads the YAML for it instead. Adding
        # the field here would make the guarantee a matter of nobody copying
        # it, which is a weaker one.
        component = parse_component(
            {**MINIMAL, "private": {"contacts": ["PRIVATE"], "notes": "x"}}
        )
        assert "private" not in vars(component)

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
