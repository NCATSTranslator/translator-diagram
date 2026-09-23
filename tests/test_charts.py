"""Tests for translator_diagram.charts."""

from translator_diagram.charts import chart_matches
from translator_diagram.components import parse_component

MINIMAL = {"id": "svc", "name": "Service", "owner": "DOGSLED",
           "refactor_status": "New in Refactor"}


def _parse(**overrides):
    return parse_component({**MINIMAL, **overrides})


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
