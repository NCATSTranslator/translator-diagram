"""The owner and edge-style legends, embedded or standalone."""

import html

import graphviz

from .colors import EXTERNAL_FILL_COLOR, ColorAssigner

_LEGEND_CLUSTER_ATTRS = {
    "style": "filled,rounded",
    "fillcolor": "#FAFAFA",
    "color": "#AAAAAA",
    "fontname": "Helvetica",
    "fontsize": "11",
    "margin": "12",
}


def _owner_legend_html(colors: ColorAssigner) -> str:
    """Build an HTML-table label listing every owner and its fill color.

    Two-column layout: a colored swatch on the left, the owner name on a
    neutral background on the right. This keeps text contrast uniform
    regardless of how dark the swatch is.
    """
    rows = []
    for owner, fill in colors.used_colors.items():
        rows.append(
            f'<TR>'
            f'<TD BGCOLOR="{fill}" WIDTH="20"> </TD>'
            f'<TD ALIGN="LEFT">{html.escape(owner)}</TD>'
            f'</TR>'
        )
    table = (
        '<TABLE BORDER="0" CELLBORDER="1" CELLSPACING="0" CELLPADDING="4">'
        + "".join(rows)
        + '</TABLE>'
    )
    # Python graphviz treats labels starting with '<' as HTML-like — the
    # outer angle brackets are the marker, inner is the table.
    return f"<{table}>"


def _add_owner_cluster(dot: graphviz.Digraph, colors: ColorAssigner) -> None:
    """Add the owner-color key cluster to dot."""
    with dot.subgraph(name="cluster_legend_owners") as own:
        own.attr(label="Owner", **_LEGEND_CLUSTER_ATTRS)
        own.node("_leg_owners", label=_owner_legend_html(colors), shape="plain")


def _add_edge_cluster(dot: graphviz.Digraph) -> None:
    """Add the edge-style example cluster to dot."""
    with dot.subgraph(name="cluster_legend") as leg:
        leg.attr(label="Legend", **_LEGEND_CLUSTER_ATTRS)

        leg.node("_leg_p", label="Producer", fillcolor="white", penwidth="1.0")
        leg.node("_leg_c", label="Consumer", fillcolor="white", penwidth="1.0")
        leg.edge("_leg_p", "_leg_c", xlabel="Results", minlen="5")

        leg.node("_leg_a", label="Component", fillcolor="white", penwidth="1.0")
        leg.node("_leg_b", label="Service", fillcolor="white", penwidth="1.0")
        leg.edge("_leg_a", "_leg_b", xlabel="API call", style="dashed", minlen="5")

        _ext = {
            "fillcolor": EXTERNAL_FILL_COLOR, "style": "filled",
            "fontname": "Helvetica", "fontsize": "13", "penwidth": "2.5",
        }
        leg.node("_leg_src",  label="Database", shape="cylinder", **_ext)
        leg.node("_leg_sink", label="User/agent", shape="oval",
                 peripheries="2", **_ext)

        with leg.subgraph() as row1:
            row1.attr(rank="same")
            row1.node("_leg_p")
            row1.node("_leg_c")
        with leg.subgraph() as row2:
            row2.attr(rank="same")
            row2.node("_leg_a")
            row2.node("_leg_b")
        with leg.subgraph() as row3:
            row3.attr(rank="same")
            row3.node("_leg_src")
            row3.node("_leg_sink")
        leg.edge("_leg_p", "_leg_a",   style="invis")
        leg.edge("_leg_a", "_leg_src", style="invis")


def _add_legend(dot: graphviz.Digraph, colors: ColorAssigner) -> None:
    """Add both legend clusters to dot (for the combined main diagram)."""
    _add_owner_cluster(dot, colors)
    _add_edge_cluster(dot)

    # Pin the owner legend to the bottom; the edge-style legend floats freely
    # (its internal rank="same" rows keep it compact wherever it lands).
    with dot.subgraph() as s:
        s.attr(rank="max")
        s.node("_leg_owners")


def _build_owners_graph(colors: ColorAssigner) -> graphviz.Digraph:
    """Standalone diagram containing only the owner-color legend."""
    dot = graphviz.Digraph(
        name="owners_legend",
        graph_attr={"fontname": "Helvetica", "fontsize": "11", "dpi": "150"},
    )
    _add_owner_cluster(dot, colors)
    return dot


def _build_edge_legend_graph() -> graphviz.Digraph:
    """Standalone diagram containing only the edge-style legend."""
    dot = graphviz.Digraph(
        name="edge_legend",
        graph_attr={
            "fontname": "Helvetica", "fontsize": "11", "dpi": "150",
            "rankdir": "TB", "newrank": "true",
        },
        node_attr={
            "fontname": "Helvetica", "fontsize": "11",
            "style": "filled,rounded", "shape": "box",
        },
        edge_attr={"fontname": "Helvetica", "fontsize": "9"},
    )
    _add_edge_cluster(dot)
    return dot
