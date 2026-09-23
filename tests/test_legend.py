"""Tests for translator_diagram.legend."""

import re

import graphviz

from translator_diagram.colors import ColorAssigner
from translator_diagram.legend import (
    _add_legend,
    _build_edge_legend_graph,
    _build_owners_graph,
    _owner_legend_html,
)


def _colors(*used: str) -> ColorAssigner:
    colors = ColorAssigner(
        {"NCATS": "#EF5350", "UI": "#EC407A", "DOGSLED": "#AB47BC"}, ["#999999"]
    )
    for owner in used:
        colors.get(owner)
    return colors


class TestOwnerLegend:
    def test_only_owners_on_the_diagram_are_listed(self):
        # The colour file names every team; a key listing teams the picture
        # does not contain is a key to a different picture.
        label = _owner_legend_html(_colors("UI"))
        assert "UI" in label
        assert "NCATS" not in label

    def test_rows_follow_the_colour_file_not_the_order_owners_were_met(self):
        label = _owner_legend_html(_colors("DOGSLED", "NCATS"))
        assert label.index("NCATS") < label.index("DOGSLED")

    def test_an_owner_colored_by_the_fallback_palette_is_listed(self):
        label = _owner_legend_html(_colors("Somebody New"))
        assert '<TD BGCOLOR="#999999"' in label
        assert "Somebody New" in label

    def test_owner_names_are_escaped(self):
        # The label is HTML-like: a bare & or < in a team name is a graphviz
        # syntax error, not a typo on the picture.
        label = _owner_legend_html(_colors("R&D <lab>"))
        assert "R&amp;D &lt;lab&gt;" in label

    def test_the_label_is_wrapped_as_html_like(self):
        # The outer angle brackets are how python-graphviz knows not to quote it.
        label = _owner_legend_html(_colors("UI"))
        assert label.startswith("<<TABLE") and label.endswith("</TABLE>>")


class TestEmbeddedLegend:
    def test_both_clusters_are_added_and_the_owner_key_is_pinned_to_the_bottom(self):
        dot = graphviz.Digraph()
        _add_legend(dot, _colors("UI"))
        assert "subgraph cluster_legend_owners" in dot.source
        assert "subgraph cluster_legend " in dot.source
        assert re.search(r"\{\s*rank=max\s*_leg_owners\s*\}", dot.source)


class TestStandaloneLegends:
    # --split-legends writes each key to its own file, so each must carry only
    # its own cluster.

    def test_the_owners_graph_has_no_edge_key(self):
        source = _build_owners_graph(_colors("UI")).source
        assert "cluster_legend_owners" in source
        assert "subgraph cluster_legend " not in source

    def test_the_edge_graph_has_no_owner_key(self):
        source = _build_edge_legend_graph().source
        assert "subgraph cluster_legend " in source
        assert "cluster_legend_owners" not in source
