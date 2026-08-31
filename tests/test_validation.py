"""Tests for translator_diagram.validation."""

from tests.helpers import _comp
from translator_diagram.render import build_graph
from translator_diagram.validation import validate


class TestValidate:
    def test_clean_input_returns_true(self):
        components = [
            _comp("a", depends_on=["b"]),
            _comp("b"),
        ]
        assert validate(components) is True

    def test_unknown_ref_is_hard_error(self, capsys):
        components = [_comp("a", depends_on=["ghost"])]
        assert validate(components) is False
        assert "unknown id 'ghost'" in capsys.readouterr().err

    def test_unknown_planned_ref_is_hard_error(self):
        components = [_comp("a", depends_on_planned=["ghost"])]
        assert validate(components) is False

    def test_duplicate_id_is_hard_error(self, capsys):
        components = [_comp("foo"), _comp("foo")]
        assert validate(components) is False
        assert "duplicate id" in capsys.readouterr().err

    def test_case_insensitive_duplicate_is_hard_error(self):
        components = [_comp("Foo"), _comp("foo")]
        assert validate(components) is False

    def test_case_mismatch_is_warning_not_error(self, capsys):
        # case-mismatch is informational only — build_graph resolves
        # case-insensitively. The return must stay True.
        components = [
            _comp("foo"),
            _comp("a", depends_on=["FOO"]),
        ]
        assert validate(components) is True
        assert "case mismatch" in capsys.readouterr().err


class TestLabelCollisionWarnings:
    def test_part_of_labels_differing_only_in_punctuation_warn(self, capsys):
        a, b = _comp("a"), _comp("b")
        a.part_of, b.part_of = "Core Bits", "Core/Bits"
        # A warning, not an error — both groups are still drawn.
        assert validate([a, b]) is True
        assert "Part of names 'Core Bits' and 'Core/Bits'" in capsys.readouterr().err

    def test_external_names_differing_only_in_punctuation_warn(self, capsys):
        a = _comp("a")
        a.externals = [("in", "User agent"), ("out", "User/agent")]
        assert validate([a]) is True
        assert "Externals names" in capsys.readouterr().err

    def test_the_same_label_on_two_components_does_not_warn(self, capsys):
        a, b = _comp("a"), _comp("b")
        a.part_of = b.part_of = "Core Bits"
        a.externals = b.externals = [("in", "User")]
        assert validate([a, b]) is True
        assert capsys.readouterr().err == ""
