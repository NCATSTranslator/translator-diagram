"""Tests for translator_diagram.render."""

from tests.helpers import _comp, _source_for


class TestSvgNodeAttributes:
    def test_node_gets_a_stable_id_matching_its_component_id(self):
        # The Pages view addresses nodes by id, not graphviz's node1/node2.
        source = _source_for([_comp("ars", refactor_status="New in Refactor")])
        assert "id=ars" in source

    def test_url_becomes_a_graphviz_url_attribute(self):
        comp = _comp("ars", refactor_status="New in Refactor")
        comp.url = "https://example.org/ars"
        source = _source_for([comp])
        assert 'URL="https://example.org/ars"' in source
        assert "target=_blank" in source

    def test_no_url_attribute_when_the_column_is_empty(self):
        source = _source_for([_comp("ars", refactor_status="New in Refactor")])
        assert "URL=" not in source

    def test_tooltip_carries_owner_status_and_notes(self):
        comp = _comp(
            "ars",
            owner="NCATS",
            refactor_status="New in Refactor",
            notes="Runs the queries",
        )
        source = _source_for([comp])
        assert "Owner: NCATS" in source
        assert "Status: New in Refactor" in source
        assert "Runs the queries" in source


class TestExternalNodes:
    def test_a_name_used_both_ways_emits_one_node(self):
        a = _comp("a", refactor_status="New in Refactor")
        a.externals = [("in", "User")]
        b = _comp("b", refactor_status="New in Refactor")
        b.externals = [("out", "User")]
        source = _source_for([a, b])
        # One node declaration, and no rank constraint at all — rank=min and
        # rank=max on the same node contradict each other.
        lines = source.splitlines()
        assert len([ln for ln in lines
                    if "ext__user" in ln and "label=User" in ln]) == 1
        ranked = {lines[i + 1].strip() for i, ln in enumerate(lines)
                  if ln.strip() in ("rank=min", "rank=max")}
        assert "ext__user" not in ranked

    def test_names_that_sanitise_alike_stay_separate(self):
        a = _comp("a", refactor_status="New in Refactor")
        a.externals = [("in", "User agent"), ("in", "User/agent")]
        source = _source_for([a])
        assert "ext__user_agent " in source or "ext__user_agent\t" in source
        assert "ext__user_agent_2" in source


class TestUbiquitousFiltering:
    def test_excluded_ubiquitous_target_is_not_rendered(self):
        u = _comp("u", refactor_status="Removed in Refactor", ubiquitous=True)
        a = _comp("a", refactor_status="New in Refactor", uses=["u"])
        source = _source_for([a, u])
        assert "a__u" not in source


class TestEdgeStyles:
    def test_implemented_call_suppresses_a_planned_call_to_the_same_target(self):
        # "Calls: b, ~b" is contradictory data. Draw the implemented edge only,
        # mirroring how depends_on outranks depends_on_planned — two dashed
        # edges between one pair merge under concentrate=true anyway.
        components = [
            _comp("a", refactor_status="New in Refactor",
                  uses=["b"], uses_planned=["b"]),
            _comp("b", refactor_status="New in Refactor"),
        ]
        edges = [ln for ln in _source_for(components).splitlines()
                 if "a -> b" in ln]
        assert len(edges) == 1
        assert "color=red" not in edges[0]

    def test_planned_call_renders_when_there_is_no_implemented_one(self):
        components = [
            _comp("a", refactor_status="New in Refactor", uses_planned=["b"]),
            _comp("b", refactor_status="New in Refactor"),
        ]
        edges = [ln for ln in _source_for(components).splitlines()
                 if "a -> b" in ln]
        assert len(edges) == 1
        assert "color=red" in edges[0]

    def test_solid_edge_suppresses_a_dashed_one_in_the_same_direction(self):
        # a gets results from b  → solid b -> a.
        # b calls a              → dashed b -> a, same direction, suppressed
        #                          so --concentrate can't merge away the solid.
        components = [
            _comp("a", refactor_status="New in Refactor", depends_on=["b"]),
            _comp("b", refactor_status="New in Refactor", uses=["a"]),
        ]
        edges = [ln for ln in _source_for(components).splitlines()
                 if "b -> a" in ln]
        assert len(edges) == 1
        assert "dashed" not in edges[0]

    def test_solid_suppresses_dashed_when_the_target_sorts_last(self):
        # Mirror of the test above with the ids swapped: the solid edge is
        # registered by z, which the iteration reaches after a.
        components = [
            _comp("a", refactor_status="New in Refactor", uses=["z"]),
            _comp("z", refactor_status="New in Refactor", depends_on=["a"]),
        ]
        edges = [ln for ln in _source_for(components).splitlines()
                 if "a -> z" in ln]
        assert len(edges) == 1
        assert "dashed" not in edges[0]
