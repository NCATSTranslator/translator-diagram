"""Tests for translator_diagram.model."""

from tests.helpers import _comp
from translator_diagram.model import index_by_id


class TestComponent:
    def test_display_name_falls_back_to_id_when_name_empty(self):
        c = _comp("foo", name="")
        assert c.display_name == "foo"

    def test_display_name_uses_name_when_present(self):
        c = _comp("foo", name="Foo Service")
        assert c.display_name == "Foo Service"

    def test_all_refs_concatenates_all_four_lists(self):
        c = _comp(
            "x",
            depends_on=["a"],
            depends_on_planned=["b"],
            uses=["c"],
            uses_planned=["d"],
        )
        assert c.all_refs() == ["a", "b", "c", "d"]


class TestIndexById:
    def test_lookup_is_case_insensitive(self):
        index = index_by_id([_comp("Foo"), _comp("bar")])
        assert index["foo"].id == "Foo"
        assert index["bar"].id == "bar"

    def test_missing_returns_none(self):
        index = index_by_id([_comp("foo")])
        assert index.get("nope") is None
