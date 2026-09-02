"""Data-flow ordering: does the recorded dependency graph produce a sane order?"""

import pytest

from translator_diagram.components import ComponentFile
from translator_diagram.flow import (
    NO_EDGES_DEPTH,
    flow_depths,
    in_flow_order,
    isolated,
    neighbours,
    order_conflicts,
)


def _comp(cid, *, gets=(), calls=(), externals=(), layer=None):
    return ComponentFile(
        id=cid,
        name=cid,
        owner="None",
        refactor_status="New in Refactor",
        layer=layer,
        connections={
            "gets_results_from": list(gets),
            "calls": list(calls),
            "externals": [{"direction": d, "name": n} for d, n in externals],
        },
    )


class TestFlowDepths:
    def test_a_chain_orders_source_to_sink(self):
        chain = [
            _comp("a", externals=[("in", "Upstream")]),
            _comp("b", gets=["a"]),
            _comp("c", gets=["b"]),
        ]
        depths = flow_depths(chain)
        assert depths["a"] < depths["b"] < depths["c"]

    def test_an_external_source_starts_one_step_in(self):
        # Otherwise a component fed from outside sorts level with the shared
        # services nothing feeds, and the table claims they are peers.
        components = [_comp("fed", externals=[("in", "Upstream")]), _comp("plain", calls=["fed"])]
        assert flow_depths(components)["fed"] == 1

    def test_longest_path_wins_over_shortest(self):
        # `d` is reachable in one hop from `a` and in three via b and c. It must
        # sort after everything it depends on, so the long path is the one that
        # counts.
        components = [
            _comp("a", externals=[("in", "Upstream")]),
            _comp("b", gets=["a"]),
            _comp("c", gets=["b"]),
            _comp("d", gets=["a", "c"]),
        ]
        depths = flow_depths(components)
        assert depths["d"] > depths["c"]

    def test_calls_count_as_upstream_too(self):
        components = [_comp("dep"), _comp("user", calls=["dep"])]
        assert flow_depths(components)["user"] > flow_depths(components)["dep"]

    def test_planned_edges_count(self):
        # A '~' edge is planned, not absent; it still says who supplies whom.
        components = [_comp("dep"), _comp("user", calls=["~dep"])]
        assert flow_depths(components)["user"] > flow_depths(components)["dep"]

    def test_a_cycle_terminates(self):
        # validation.validate does not reject cycles (issue #11), so one can
        # reach this code. A table that renders in some order beats one that
        # hangs.
        components = [_comp("a", gets=["b"]), _comp("b", gets=["a"])]
        depths = flow_depths(components)
        assert set(depths) == {"a", "b"}

    def test_unknown_references_are_ignored(self):
        # The dashboard may be pointed at a subset of the component files, so a
        # dangling id must not invent a phantom upstream. The component is then
        # genuinely edgeless, and sorts as isolated rather than as a source.
        components = [_comp("a", gets=["not-a-file"])]
        assert flow_depths(components)["a"] == NO_EDGES_DEPTH

    def test_a_known_reference_still_connects_when_another_is_unknown(self):
        components = [_comp("real"), _comp("a", gets=["not-a-file", "real"])]
        assert flow_depths(components)["a"] == 1

    def test_self_reference_does_not_deepen_forever(self):
        # A self-edge is dropped rather than followed, so the component has no
        # upstream at all and lands with the other edgeless ones.
        components = [_comp("a", calls=["a"])]
        assert flow_depths(components)["a"] == NO_EDGES_DEPTH


class TestIsolated:
    def test_a_component_with_no_edges_sorts_last(self):
        # Not first: a component nothing feeds and nothing consumes is a hole
        # in the data, and putting it at the top of a flow-ordered table would
        # assert it is a data source.
        components = [_comp("lonely"), _comp("a"), _comp("b", gets=["a"])]
        assert flow_depths(components)["lonely"] == NO_EDGES_DEPTH
        assert in_flow_order(components)[-1].id == "lonely"

    def test_isolated_lists_only_the_unconnected(self):
        components = [_comp("lonely"), _comp("a"), _comp("b", gets=["a"])]
        assert isolated(components) == ["lonely"]

    def test_an_external_edge_is_still_an_edge(self):
        # A component wired only to something outside the diagram is connected.
        components = [_comp("sink", externals=[("out", "User")])]
        assert isolated(components) == []


class TestOrdering:
    def test_ties_break_on_layer_then_id(self):
        components = [
            _comp("z", externals=[("in", "U")], layer="A"),
            _comp("y", externals=[("in", "U")], layer="A"),
            _comp("x", externals=[("in", "U")], layer="B"),
        ]
        assert [c.id for c in in_flow_order(components)] == ["y", "z", "x"]

    def test_order_is_stable_regardless_of_input_order(self):
        forwards = [_comp("a"), _comp("b", gets=["a"]), _comp("c", gets=["b"])]
        backwards = list(reversed(forwards))
        assert [c.id for c in in_flow_order(forwards)] == [
            c.id for c in in_flow_order(backwards)
        ]


@pytest.mark.parametrize("edge_field", ["gets_results_from", "calls"])
def test_either_edge_field_alone_is_enough(edge_field):
    upstream = _comp("up")
    downstream = ComponentFile(
        id="down", name="down", owner="None",
        refactor_status="New in Refactor",
        connections={edge_field: ["up"]},
    )
    depths = flow_depths([upstream, downstream])
    assert depths["down"] > depths["up"]



class TestNeighbours:
    def test_both_directions_of_one_edge(self):
        n = neighbours([_comp("a"), _comp("b", gets=["a"])])
        assert [e.id for e in n["b"].gets_results_from] == ["a"]
        assert [(i.id, i.kind) for i in n["a"].used_by] == [
            ("b", "gets_results_from")]

    def test_the_two_kinds_stay_apart_in_both_directions(self):
        n = neighbours([_comp("svc"), _comp("a", gets=["svc"]), _comp("b", calls=["svc"])])
        assert [(i.id, i.kind) for i in n["svc"].used_by] == [
            ("a", "gets_results_from"), ("b", "calls")]

    def test_the_files_order_survives_and_the_inversion_is_sorted(self):
        # Outgoing keeps the author's order; inbound is somebody else's list,
        # so it gets a stable one instead of an arbitrary one.
        n = neighbours([
            _comp("z"), _comp("a"), _comp("m"),
            _comp("hub", calls=["z", "a", "m"]),
        ])
        assert [e.id for e in n["hub"].calls] == ["z", "a", "m"]
        assert [i.id for i in n["a"].used_by] == ["hub"]

    def test_ids_resolve_to_the_file_that_exists(self):
        n = neighbours([_comp("NameRes"), _comp("a", calls=["nameres"])])
        assert [e.id for e in n["a"].calls] == ["NameRes"]
        assert [i.id for i in n["NameRes"].used_by] == ["a"]

    def test_an_unknown_target_is_dropped(self):
        n = neighbours([_comp("a", gets=["not-a-file"])])
        assert n["a"].gets_results_from == ()

    def test_a_self_edge_is_dropped(self):
        n = neighbours([_comp("a", calls=["a"])])
        assert not n["a"]

    def test_a_planned_edge_is_planned_from_both_ends(self):
        n = neighbours([_comp("dep"), _comp("a", calls=["~dep"])])
        assert n["a"].calls[0].planned
        assert n["dep"].used_by[0].planned

    def test_one_neighbour_named_twice_is_one_inbound_edge(self):
        # Both keys naming the same target is one relationship to the reader,
        # and the results edge is the stronger claim.
        n = neighbours([_comp("svc"), _comp("a", gets=["svc"], calls=["svc"])])
        assert [(i.id, i.kind) for i in n["svc"].used_by] == [
            ("a", "gets_results_from")]

    def test_the_left_bar_and_the_chips_agree(self):
        # The property the single traversal exists for: a row is isolated
        # exactly when it has no neighbours in either direction.
        components = [
            _comp("a"), _comp("b", gets=["a"]), _comp("lonely"),
            _comp("outward", externals=[("out", "User")]),
        ]
        n = neighbours(components)
        stranded = set(isolated(components))
        for component in components:
            if component.externals:
                continue
            assert (component.id in stranded) is (not n[component.id])


class TestOrderConflicts:
    def test_a_results_edge_from_a_later_stage_is_a_conflict(self):
        components = [_comp("early", gets=["late"]), _comp("late")]
        assert order_conflicts(components, {"early": 1, "late": 2}) == [
            ("early", "late", False)]

    def test_the_right_way_round_is_not(self):
        components = [_comp("late", gets=["early"]), _comp("early")]
        assert order_conflicts(components, {"early": 1, "late": 2}) == []

    def test_two_in_the_same_stage_do_not_conflict(self):
        # Within-stage listing order is a judgement, not a rule, so it is not
        # checked. Only a later stage feeding an earlier one is a contradiction.
        components = [_comp("a", gets=["b"]), _comp("b")]
        assert order_conflicts(components, {"a": 3, "b": 3}) == []

    def test_a_call_backwards_is_not_a_conflict(self):
        # The whole design: nine components call the tracing service, which
        # sits at the end of the page. That is a shared service, not a stage.
        components = [_comp("worker", calls=["tracing"]), _comp("tracing")]
        assert order_conflicts(components, {"worker": 2, "tracing": 9}) == []

    def test_a_planned_edge_conflicts_and_says_so(self):
        components = [_comp("early", gets=["~late"]), _comp("late")]
        assert order_conflicts(components, {"early": 1, "late": 2}) == [
            ("early", "late", True)]

    def test_a_component_the_order_does_not_place_is_skipped(self):
        components = [_comp("placed", gets=["unplaced"]), _comp("unplaced")]
        assert order_conflicts(components, {"placed": 1}) == []

    def test_conflicts_come_back_in_a_stable_order(self):
        components = [
            _comp("z", gets=["late"]), _comp("a", gets=["late"]), _comp("late")]
        assert [c[0] for c in order_conflicts(
            components, {"a": 1, "z": 1, "late": 2})] == ["a", "z"]
