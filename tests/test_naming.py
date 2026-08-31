"""Tests for translator_diagram.naming.

The id-collision rules are enforced by validation.validate, but the
namespace they protect is this module's contract, so they are tested
here with the helpers that hand the names out.
"""

from tests.helpers import _comp, _source_for
from translator_diagram.naming import (
    _layer_filenames,
    _svg_id,
    _unique_svg_id,
    external_svg_ids,
)
from translator_diagram.validation import validate


class TestSvgIds:
    def test_punctuated_id_becomes_a_valid_xml_id(self):
        assert _svg_id("ARS 2.0") == "ars_2_0"

    def test_leading_digit_is_prefixed(self):
        # XML IDs may not start with a digit, so getElementById would fail.
        assert _svg_id("2fast").startswith("n_")

    def test_node_id_attribute_is_sanitised(self):
        source = _source_for([_comp("ARS 2.0", refactor_status="New in Refactor")])
        assert "id=ars_2_0" in source

    def test_ids_differing_only_in_punctuation_are_an_error(self, capsys):
        assert validate([_comp("ARS 2.0"), _comp("ARS/2/0")]) is False
        assert "SVG id" in capsys.readouterr().err

    def test_unique_svg_id_separates_colliding_labels(self):
        taken: dict[str, str] = {}
        assert _unique_svg_id("User agent", taken) == "user_agent"
        assert _unique_svg_id("User/agent", taken) == "user_agent_2"
        # Re-asking for one already assigned returns the same id.
        assert _unique_svg_id("User agent", taken) == "user_agent"


def _ubiquitous_pair():
    """A caller, a ubiquitous target, and a component whose id collides.

    "ARS" calling ubiquitous "LOG" used to clone into the SVG id "ars_log",
    which is also what the separate component "ARS LOG" sanitises to.
    """
    return [
        _comp("ARS", refactor_status="New in Refactor", uses=["LOG"]),
        _comp("ARS LOG", refactor_status="New in Refactor"),
        _comp("LOG", refactor_status="New in Refactor", ubiquitous=True),
    ]


class TestSvgIdNamespace:
    def test_clone_id_does_not_collide_with_a_component_id(self):
        source = _source_for(_ubiquitous_pair())
        assert "id=ars__log" in source
        assert "id=ars_log" in source
        assert validate(_ubiquitous_pair()) is True

    def test_a_component_claiming_another_ones_anchor_id_is_an_error(self, capsys):
        # Graphviz wraps a tooltip-carrying node in <g id="a_{node id}">, so
        # "A Foo" would claim the wrapper graphviz emits around "Foo".
        assert validate([_comp("Foo"), _comp("A Foo")]) is False
        err = capsys.readouterr().err
        assert "a_foo" in err
        # Reported once, not once for the node and again for its wrapper.
        assert err.count("ERROR") == 1

    def test_an_external_colliding_with_a_clone_is_an_error(self, capsys):
        # Component "ext" calling ubiquitous "log" clones into "ext__log",
        # which is also the id of an external entity named "log".
        zz = _comp("zz", refactor_status="New in Refactor")
        zz.externals = [("in", "log")]
        components = [
            _comp("ext", refactor_status="New in Refactor", uses=["log"]),
            _comp("log", refactor_status="New in Refactor", ubiquitous=True),
            zz,
        ]
        assert validate(components) is False
        assert "ext__log" in capsys.readouterr().err

    def test_hidden_components_do_not_claim_an_id(self):
        # Nothing is emitted for a hidden row, so its id is free.
        hidden = _comp("ARS/2/0")
        hidden.hide = True
        assert validate([_comp("ARS 2.0"), hidden]) is True

    def test_external_ids_are_stable_across_the_status_filter(self):
        # The layer sub-figures and the main diagram must agree on them.
        a = _comp("a", refactor_status="New in Refactor")
        a.externals = [("in", "User")]
        b = _comp("b", refactor_status="Removed after Refactor")
        b.externals = [("out", "User")]
        assert external_svg_ids([a, b])["User"] == "ext__user"


class TestLayerFilenames:
    def test_labels_that_reduce_to_one_stem_get_separate_files(self, capsys):
        stems = _layer_filenames(["Tier 1", "Tier-1", "Tier 2"])
        assert stems == {"Tier 1": "tier_1", "Tier-1": "tier_1_2", "Tier 2": "tier_2"}
        assert "both give the filename 'tier_1'" in capsys.readouterr().err

    def test_distinct_labels_are_left_alone(self, capsys):
        assert _layer_filenames(["Tier 1", "Tier 2"]) == {
            "Tier 1": "tier_1", "Tier 2": "tier_2",
        }
        assert capsys.readouterr().err == ""
