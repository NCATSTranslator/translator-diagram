"""Tests for translator_diagram.export."""

import json

from tests.helpers import _comp, _source_for
from translator_diagram.export import write_json


class TestComponentsJson:
    def _written(self, tmp_path, components):
        out = tmp_path / "components.json"
        write_json(components, out)
        return json.loads(out.read_text(encoding="utf-8"))

    def test_ubiquitous_node_ids_list_the_clones_that_exist(self, tmp_path):
        # A ubiquitous component has no central node, so a single node_id
        # pointed at an element getElementById would never find.
        components = [
            _comp("ARA", refactor_status="New in Refactor", uses=["LOG"]),
            _comp("ARS", refactor_status="New in Refactor", uses=["LOG"]),
            _comp("LOG", refactor_status="New in Refactor", ubiquitous=True),
        ]
        by_id = {c["id"]: c for c in self._written(tmp_path, components)}
        assert by_id["LOG"]["node_ids"] == ["ara__log", "ars__log"]
        assert by_id["ARS"]["node_ids"] == ["ars"]
        source = _source_for(components)
        for node_id in by_id["LOG"]["node_ids"]:
            assert f"id={node_id}" in source

    def test_an_unreferenced_ubiquitous_component_lists_no_nodes(self, tmp_path):
        components = [_comp("LOG", ubiquitous=True)]
        assert self._written(tmp_path, components)[0]["node_ids"] == []

    def test_hidden_components_are_not_exported(self, tmp_path):
        # components.json is what the public Pages view fetches, and a hidden
        # row carries its Notes verbatim.
        hidden = _comp("secret", notes="do not publish")
        hidden.hide = True
        exported = self._written(tmp_path, [_comp("ars"), hidden])
        assert [c["id"] for c in exported] == ["ars"]
        assert "do not publish" not in json.dumps(exported)

    def test_a_clone_of_a_hidden_component_is_not_listed(self, tmp_path):
        hidden = _comp("log", ubiquitous=True)
        hidden.hide = True
        components = [_comp("ars", uses=["log"]), hidden]
        assert [c["id"] for c in self._written(tmp_path, components)] == ["ars"]
