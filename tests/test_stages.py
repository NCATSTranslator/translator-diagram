"""Ordering the overview by `config/flow-steps.yaml`.

`test_flow_steps.py` is the companion to this file: it checks the shipped data
file, while this checks the code that reads it -- the same split as
`test_component_files.py` beside `test_components.py`.
"""

import click
import pytest

from tests.dashboard_helpers import _comp, _row
from translator_diagram.dashboard import build_payload
from translator_diagram.rows import build_rows
from translator_diagram.stages import (
    UNPLACED_TITLE,
    in_stage_order,
    load_stages,
    stage_blocks,
)


class TestFlowStepsOnRows:
    def test_every_row_carries_a_step_and_a_label(self, synced):
        rows = build_rows([_comp("a"), _comp("b", diagram={
            "refactor_status": "New in Refactor", "gets_results_from": ["a"]})], synced)
        assert [r["step"] for r in rows] == sorted(r["step"] for r in rows)
        assert all(r["step_label"] for r in rows)

    def test_having_no_recorded_edges_no_longer_decides_the_band(self, synced):
        # It used to: the last band was "No recorded dependencies", computed
        # from the graph. Now the stages decide where a row sits and `isolated`
        # says only what it always meant — nothing records this component's
        # neighbours — which the left bar still shows.
        row = build_rows([_comp("lonely")], synced)[0]
        assert row["isolated"] is True
        assert row["step_label"] != "No recorded dependencies"


class TestStages:
    FILE = """
stages:
  - title: Ingest
    description: Pulls external sources in.
    components: [b, a]
  - title: Serving
    description: Answers questions.
    components: [c]
unplaced:
  description: Not yet placed anywhere.
  components: [d]
"""

    def _stages(self, tmp_path, text=None):
        path = tmp_path / "flow-steps.yaml"
        path.write_text(self.FILE if text is None else text)
        return load_stages(path)

    def _components(self, *ids):
        return [_comp(cid) for cid in ids]

    def test_the_file_is_the_order_not_the_alphabet(self, tmp_path):
        # b before a, because a stage lists its components in the order
        # someone decided they should be read in.
        ordered = in_stage_order(
            self._components("a", "b", "c", "d"), self._stages(tmp_path)
        )
        assert [c.id for c, _, _ in ordered] == ["b", "a", "c", "d"]
        assert [number for _, number, _ in ordered] == [1, 1, 2, 3]

    def test_each_component_carries_its_stage(self, tmp_path):
        ordered = in_stage_order(self._components("a", "c"), self._stages(tmp_path))
        assert [stage["title"] for _, _, stage in ordered] == ["Ingest", "Serving"]

    def test_a_component_no_stage_names_falls_to_the_end(self, tmp_path):
        # The failure this is here for: a new component file nobody has placed
        # must be visible as unplaced, not silently sorted last.
        ordered = in_stage_order(self._components("a", "z"), self._stages(tmp_path))
        component, number, stage = ordered[-1]
        assert component.id == "z"
        assert stage["title"] == UNPLACED_TITLE
        assert number == 3

    def test_an_id_no_component_file_matches_is_skipped(self, tmp_path):
        stages = self._stages(tmp_path, """
stages:
  - title: Ingest
    description: Pulls external sources in.
    components: [a, typo]
""")
        ordered = in_stage_order(self._components("a"), stages)
        assert [c.id for c, _, _ in ordered] == ["a"]

    def test_a_missing_file_is_refused_rather_than_worked_around(self, tmp_path):
        # in_stage_order does fall back to data-flow order, and that is what
        # makes the missing file worth refusing: the page would look finished
        # while showing the ordering this file exists to replace.
        with pytest.raises(click.ClickException):
            load_stages(tmp_path / "absent.yaml")
        ordered = in_stage_order(self._components("a", "b"), [])
        assert len(ordered) == 2

    def test_the_file_is_found_from_a_subdirectory(self, tmp_path, monkeypatch):
        # The same upward walk load_owner_colors and load_policy do: running
        # build-dashboard from anywhere inside a checkout finds the checkout's
        # stages, not nothing.
        (tmp_path / "config").mkdir()
        (tmp_path / "config" / "flow-steps.yaml").write_text(self.FILE)
        deep = tmp_path / "a" / "b"
        deep.mkdir(parents=True)
        monkeypatch.chdir(deep)
        assert [stage["title"] for stage in load_stages()][:2] == ["Ingest", "Serving"]

    def test_an_empty_file_is_not_an_error(self, tmp_path):
        assert self._stages(tmp_path, "") == []

    def test_a_file_with_no_stages_still_yields_the_unplaced_band(self, tmp_path):
        # Every component would land in it, which is a legible failure: the
        # page says "not yet placed" 26 times rather than showing no bands.
        stages = self._stages(tmp_path, """
unplaced:
  description: Nothing is placed.
  components: [a]
""")
        assert len(stages) == 1 and stages[0]["unplaced"] is True
        ordered = in_stage_order(self._components("a", "b"), stages)
        assert {number for _, number, _ in ordered} == {1}

    def test_the_rows_carry_the_stage_prose(self, synced, component):
        row = build_rows([component], synced)[0]
        assert "step" in row and "step_title" in row and "step_description" in row


class TestStagePayload:
    def _stages(self):
        return [
            {"title": "Ingest", "description": "Pulls sources in.",
             "components": ["a"]},
            {"title": "Serving", "description": "Answers.", "components": ["b"]},
            {"title": UNPLACED_TITLE, "description": "Nowhere yet.",
             "components": ["c"], "unplaced": True},
        ]

    def test_every_stage_carries_its_step(self):
        blocks = stage_blocks(
            self._stages(),
            [_row("a", step=1), _row("b", step=2), _row("c", step=3)],
        )
        assert [(b["step"], b["title"]) for b in blocks] == [
            (1, "Ingest"), (2, "Serving"), (3, UNPLACED_TITLE)]
        assert blocks[0]["description"] == "Pulls sources in."

    def test_a_stage_with_no_kept_rows_is_absent_not_empty(self):
        # The Engineering stage holds jaeger and test-harness and nothing else,
        # so a published build shows no heading for it rather than a heading
        # over a gap — and the stages that remain keep their numbers, so the
        # page runs 1–8 and skips 9 instead of renumbering.
        blocks = stage_blocks(self._stages(), [_row("a", step=1), _row("c", step=3)])
        assert [b["step"] for b in blocks] == [1, 3]
        assert all(b["components"] for b in blocks)

    def test_the_roster_matches_the_row_order(self):
        # Within a stage the order is a judgement recorded in the config file,
        # and the rows are already in it. Sorting here would throw it away and
        # make the band disagree with the table under it.
        rows = [_row("b", step=1), _row("a", step=1)]
        assert stage_blocks(self._stages(), rows)[0]["components"] == ["b", "a"]

    def test_the_unplaced_block_is_flagged(self):
        # Explicit on every block, not only the trailing one: a reader of the
        # payload should not have to know that a missing key means False.
        blocks = stage_blocks(self._stages(), [_row("a", step=1), _row("c", step=3)])
        assert [b["unplaced"] for b in blocks] == [False, True]

    def test_the_payload_carries_the_bands_and_the_graph(self, synced, component):
        payload = build_payload([component], synced)
        assert [stage["components"] for stage in payload["stages"]] == [["svc"]]
        assert payload["edges"] == [] and payload["externals"] == []
