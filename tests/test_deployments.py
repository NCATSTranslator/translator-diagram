"""Tests for translator_diagram.deployments."""

from translator_diagram.components import ENVIRONMENTS, Deployment, parse_component
from translator_diagram.deployments import (
    deployments_from_smartapi,
    derive_deployments,
    merge_deployments,
    smartapi_record_for,
)

MINIMAL = {"id": "svc", "name": "Service", "owner": "DOGSLED",
           "refactor_status": "New in Refactor"}


def _parse(**overrides):
    return parse_component({**MINIMAL, **overrides})


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

    def test_a_stale_recorded_id_does_not_fall_back_to_the_infores(self):
        hits = [self._hit("new", "infores:svc")]
        assert smartapi_record_for(
            _parse(identifiers={"smartapi": "gone", "infores": "infores:svc"}), hits
        ) == (None, None, [])

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
