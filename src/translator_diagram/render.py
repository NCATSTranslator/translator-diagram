"""The diagram itself: the main graph and the per-layer sub-figures.

build_graph and build_layer_subgraph live together on purpose. They
duplicate the edge-suppression rules, and a file boundary between them
would make the next drift easier to miss — see AGENTS.md.
"""

import html

import graphviz

from .colors import (
    EXTERNAL_FILL_COLOR,
    GHOST_BORDER_COLOR,
    GHOST_FILL_COLOR,
    GHOST_FONT_COLOR,
    ColorAssigner,
    text_color_for,
)
from .legend import _add_legend
from .model import Component, index_by_id
from .naming import (
    _clone_svg_id,
    _layer_filename,
    _svg_id,
    _unique_svg_id,
    external_svg_ids,
)

# Emoji labels for non-default hosting locations (ITRB is the default and shown as nothing).
HOSTED_AT_EMOJI: dict[str, str] = {"RENCI": "🌐", "Scripps": "🌐", "Local": "💻", "Unknown": "❓"}


# Bold border penwidth for in-layer nodes in per-layer sub-figures.
IN_LAYER_PENWIDTH = "4.0"


def _compute_active_set(
    components: list[Component],
    active_statuses: set[str] | None,
) -> set[str]:
    if active_statuses is None:
        return {c.id for c in components if not c.hide}
    return {c.id for c in components if c.refactor_status in active_statuses and not c.hide}


def _compute_ghost_ids(
    components: list[Component],
    index: dict[str, Component],
    active_set: set[str],
) -> set[str]:
    ghost: set[str] = set()
    for comp in components:
        if comp.id not in active_set or comp.ubiquitous:
            continue
        for ref in comp.all_refs():
            match = index.get(ref.lower())
            if match is None or match.ubiquitous or match.hide:
                # Ubiquitous targets render as per-caller clones, never as ghosts.
                # Hidden components are suppressed entirely — not even as ghosts.
                continue
            if match.id not in active_set:
                ghost.add(match.id)
    return ghost


def _node_tooltip(comp: Component) -> str:
    """Hover text for a component node in SVG output.

    Carries the fields that don't fit in the label — owner, status, and notes —
    so a reader gets them without leaving the diagram.
    """
    lines = [f"{comp.display_name} ({comp.id})"]
    if comp.owner and comp.owner != "None":
        lines.append(f"Owner: {comp.owner}")
    if comp.refactor_status:
        lines.append(f"Status: {comp.refactor_status}")
    if comp.notes:
        lines.append(comp.notes)
    return "\n".join(lines)


def _emit_component_node(
    dot: graphviz.Digraph,
    comp: Component,
    node_id: str,
    colors: ColorAssigner,
    penwidth: str | None = None,
    svg_id: str | None = None,
) -> None:
    """Render a Component as a graphviz node at the given id.

    Used both for primary node placement and for per-caller ubiquitous clones,
    whose node_id is already an SVG id (see _clone_svg_id) and is passed
    through as svg_id rather than sanitised a second time.
    penwidth overrides the default (2.0 for "New in Refactor", 1.0 otherwise).
    """
    fill = colors.get(comp.owner)
    is_new = comp.refactor_status == "New in Refactor"
    # Owner is encoded by node color and shown in the legend, not in the label.
    label = f"{comp.display_name}\n{comp.id}"
    if comp.hosted_at and comp.hosted_at != "ITRB":
        emoji = HOSTED_AT_EMOJI.get(comp.hosted_at, "")
        suffix = f" {emoji}" if emoji else ""
        label += f"\nHosted at: {comp.hosted_at}{suffix}"
    # id gives every node a stable, predictable handle in the SVG (<g id="...">)
    # instead of graphviz's default node1/node2 counter, so the planned GitHub
    # Pages view can address nodes from components.json without re-parsing DOT.
    # URL makes graphviz wrap the node in <a xlink:href=...> in SVG output, which
    # is clickable component documentation with no JavaScript at all. Both are
    # inert in PNG output, so this changes nothing about today's diagrams.
    extra: dict[str, str] = {
        "id": svg_id if svg_id is not None else _svg_id(node_id),
        "tooltip": _node_tooltip(comp),
    }
    if comp.url:
        extra["URL"] = comp.url
        extra["target"] = "_blank"
    dot.node(
        node_id,
        label=label,
        fillcolor=fill,
        fontcolor=text_color_for(fill),
        penwidth=penwidth if penwidth is not None else ("2.0" if is_new else "1.0"),
        **extra,
    )


def _compute_groups(
    components: list[Component],
    active_set: set[str],
    ghost_ids: set[str],
) -> dict[str, list[str]]:
    """Map Part-of label → node ids for active (non-ubiquitous) and ghost nodes."""
    groups: dict[str, list[str]] = {}
    for comp in components:
        if not comp.part_of or comp.ubiquitous:
            continue
        if comp.id in active_set or comp.id in ghost_ids:
            groups.setdefault(comp.part_of, []).append(comp.id)
    return groups


def _add_active_nodes(
    dot: graphviz.Digraph,
    components: list[Component],
    active_set: set[str],
    colors: ColorAssigner,
    skip_ids: set[str] | None = None,
) -> None:
    for comp in components:
        if comp.id not in active_set or comp.ubiquitous:
            # Ubiquitous components don't get a central node — they're emitted
            # per-caller from _add_edges.
            continue
        if skip_ids and comp.id in skip_ids:
            continue
        _emit_component_node(dot, comp, comp.id, colors)


def _emit_ghost_node(
    dot: graphviz.Digraph,
    ghost_id: str,
    index: dict[str, Component],
) -> None:
    """Render one excluded-but-referenced component as a dimmed node.

    Called both for free-standing ghosts and for ghosts inside a Part-of
    cluster, so the two stay in step.
    """
    comp = index.get(ghost_id.lower())
    name = comp.display_name if comp else ghost_id
    dot.node(
        ghost_id,
        label=f"{name}\n{ghost_id}\n(excluded)",
        fillcolor=GHOST_FILL_COLOR,
        style="filled,rounded,dashed",
        fontcolor=GHOST_FONT_COLOR,
        color=GHOST_BORDER_COLOR,
        id=_svg_id(ghost_id),
        tooltip=f"{name} ({ghost_id}) — excluded by the current filter",
    )


def _add_ghost_nodes(
    dot: graphviz.Digraph,
    ghost_ids: set[str],
    index: dict[str, Component],
    skip_ids: set[str] | None = None,
) -> None:
    for ghost_id in sorted(ghost_ids):
        if skip_ids and ghost_id in skip_ids:
            continue
        _emit_ghost_node(dot, ghost_id, index)


def _add_group_clusters(
    dot: graphviz.Digraph,
    groups: dict[str, list[str]],
    components: list[Component],
    active_set: set[str],
    ghost_ids: set[str],
    index: dict[str, Component],
    colors: ColorAssigner,
) -> None:
    """Wrap each Part-of group in a labeled dotted-border cluster subgraph."""
    taken: dict[str, str] = {}
    for group_label, node_ids in sorted(groups.items()):
        safe = _unique_svg_id(group_label, taken)
        with dot.subgraph(name=f"cluster_group_{safe}") as sg:
            tab_label = (
                f'<<TABLE BGCOLOR="#555555" BORDER="0" CELLPADDING="3">'
                f'<TR><TD>'
                f'<FONT COLOR="white" POINT-SIZE="12"><B>{html.escape(group_label)}</B></FONT>'
                f'</TD></TR></TABLE>>'
            )
            sg.attr(
                label=tab_label,
                labelloc="t",
                style="filled",
                fillcolor="#DDDDDD",
                color="#555555",
                fontname="Helvetica",
                penwidth="1.5",
                bgcolor="transparent",
            )
            for node_id in sorted(node_ids):
                comp = index.get(node_id.lower())
                if comp and node_id in active_set:
                    _emit_component_node(sg, comp, node_id, colors)
                elif node_id in ghost_ids:
                    _emit_ghost_node(sg, node_id, index)


def _add_edges(
    dot: graphviz.Digraph,
    components: list[Component],
    index: dict[str, Component],
    active_set: set[str],
    ghost_ids: set[str],
    colors: ColorAssigner,
) -> None:
    emitted_clones: set[str] = set()
    # Track (src, dst) pairs that already have a solid edge so that a
    # dashed edge between the same two nodes — which concentrate=true
    # would merge, losing the solid style — is suppressed in favour of solid.
    solid_edges: set[tuple[str, str]] = set()
    # Same idea one level down: an implemented "Calls" edge outranks a planned
    # one to the same target, mirroring how depends_on outranks
    # depends_on_planned above. Two dashed edges between one pair would merge
    # under concentrate=true and lose the planned-vs-implemented distinction.
    dashed_edges: set[tuple[str, str]] = set()

    def edge_target(caller_id: str, ref: str) -> str | None:
        """Return the graphviz node id to draw an edge to, or None to skip.

        For ubiquitous targets, emit (idempotently) a per-caller clone node and
        return its synthetic id. The clone uses the same visual style as the
        original so callers can recognise it.
        """
        match = index.get(ref.lower())
        if match is None:
            return None
        if match.hide:
            return None
        if match.ubiquitous:
            # Ubiquitous components are in active_set when their status passes
            # the filter; they're just drawn per-caller instead of centrally.
            # Without this check an excluded one still renders, at full colour.
            if match.id not in active_set:
                return None
            clone_id = _clone_svg_id(caller_id, match.id)
            if clone_id not in emitted_clones:
                _emit_component_node(dot, match, clone_id, colors, svg_id=clone_id)
                emitted_clones.add(clone_id)
            return clone_id
        if match.id in active_set or match.id in ghost_ids:
            return match.id
        return None

    # Two passes: a solid edge is registered by its *target* component but
    # suppresses a dashed edge emitted by its *source*, so a single pass only
    # dedupes when the target happens to sort first. edge_target is idempotent.
    for comp in components:
        if comp.id not in active_set or comp.ubiquitous:
            continue
        for ref in comp.depends_on:
            t = edge_target(comp.id, ref)
            if t is not None:
                solid_edges.add((t, comp.id))

    for comp in components:
        if comp.id not in active_set or comp.ubiquitous:
            continue
        for ref in comp.depends_on:
            t = edge_target(comp.id, ref)
            if t is not None:
                dot.edge(t, comp.id)  # B → A: B provides results to A
        for ref in comp.depends_on_planned:
            t = edge_target(comp.id, ref)
            if t is not None and (t, comp.id) not in solid_edges:
                # Planned/in-development "Gets results from" — solid red to stand out
                dot.edge(t, comp.id, style="solid", color="red")
        for ref in comp.uses:
            t = edge_target(comp.id, ref)
            if t is not None and (comp.id, t) not in solid_edges:
                dot.edge(comp.id, t, style="dashed")  # A --→ B: API call
                dashed_edges.add((comp.id, t))
        for ref in comp.uses_planned:
            t = edge_target(comp.id, ref)
            if (
                t is not None
                and (comp.id, t) not in solid_edges
                and (comp.id, t) not in dashed_edges
            ):
                # Planned/in-development "Calls" — dashed red to stand out
                dot.edge(comp.id, t, style="dashed", color="red")


def _add_external_nodes_and_edges(
    dot: graphviz.Digraph,
    components: list[Component],
    active_set: set[str],
) -> None:
    """Emit external-entity nodes and their edges from the Externals column.

    Sources (direction "in") become cylinder nodes at rank=min; sinks
    (direction "out") become double-oval nodes at rank=max.  Multiple
    components can reference the same external name — one node is emitted
    and one edge per referencing component is drawn.

    A name used in *both* directions gets a single sink-shaped node and no rank
    constraint, since rank=min and rank=max on one node contradict each other.
    """
    ext_dirs: dict[str, set[str]] = {}       # display name → {"in", "out"}
    in_edges: list[tuple[str, str]] = []     # (external name, comp_id)
    out_edges: list[tuple[str, str]] = []    # (comp_id, external name)

    for comp in components:
        if comp.id not in active_set or comp.ubiquitous:
            continue
        for direction, name in comp.externals:
            ext_dirs.setdefault(name, set()).add(direction)
            if direction == "in":
                in_edges.append((name, comp.id))
            else:
                out_edges.append((comp.id, name))

    if not ext_dirs:
        return

    # Ids come from the unfiltered component list, so an external keeps the
    # same id in the main diagram and in every layer sub-figure.
    ext_ids = external_svg_ids(components)

    ext_attrs = {
        "style": "filled",
        "fillcolor": EXTERNAL_FILL_COLOR,
        "fontname": "Helvetica",
        "fontsize": "13",
        "penwidth": "2.5",
    }

    for name, dirs in ext_dirs.items():
        nid = ext_ids[name]
        if dirs == {"in"}:
            dot.node(nid, label=name, shape="cylinder", id=nid, tooltip=name, **ext_attrs)
        else:
            dot.node(
                nid, label=name, shape="oval", peripheries="2",
                id=nid, tooltip=name, **ext_attrs,
            )

    for rank, wanted in (("min", {"in"}), ("max", {"out"})):
        ranked = [ext_ids[n] for n, dirs in ext_dirs.items() if dirs == wanted]
        if ranked:
            with dot.subgraph() as s:
                s.attr(rank=rank)
                for nid in ranked:
                    s.node(nid)

    for name, dst in in_edges:
        dot.edge(ext_ids[name], dst)
    for src, name in out_edges:
        dot.edge(src, ext_ids[name])


def build_graph(
    components: list[Component],
    active_statuses: set[str] | None,
    direction: str,
    colors: ColorAssigner,
    concentrate: bool = False,
    include_legend: bool = True,
) -> graphviz.Digraph:
    """Assemble the full graph from the parsed component list."""
    index = index_by_id(components)
    active_set = _compute_active_set(components, active_statuses)
    ghost_ids = _compute_ghost_ids(components, index, active_set)

    dot = graphviz.Digraph(
        name="translator_components",
        graph_attr={
            "rankdir": direction,
            "fontname": "Helvetica",
            "fontsize": "12",
            # splines=true gives graphviz freedom to route edges as smooth
            # curves around nodes; concentrate merges partially-parallel edges
            # to pack the layout tighter (disable if mixed solid/dashed edges
            # render incorrectly merged).
            "splines": "true",
            "concentrate": "true" if concentrate else "false",
            "nodesep": "0.3",
            "ranksep": "0.5",
            # Required for rank=same to work correctly across cluster
            # boundaries (e.g. keeping both legend clusters level).
            "newrank": "true",
            "dpi": "150",
        },
        node_attr={
            "fontname": "Helvetica",
            "fontsize": "11",
            "style": "filled,rounded",
            "shape": "box",
        },
        edge_attr={"fontname": "Helvetica", "fontsize": "9"},
    )

    groups = _compute_groups(components, active_set, ghost_ids)
    grouped_ids = {nid for ids in groups.values() for nid in ids}

    _add_group_clusters(dot, groups, components, active_set, ghost_ids, index, colors)
    _add_active_nodes(dot, components, active_set, colors, skip_ids=grouped_ids)
    _add_ghost_nodes(dot, ghost_ids, index, skip_ids=grouped_ids)
    _add_edges(dot, components, index, active_set, ghost_ids, colors)
    _add_external_nodes_and_edges(dot, components, active_set)
    if include_legend:
        _add_legend(dot, colors)

    return dot


def build_layer_subgraph(
    components: list[Component],
    layer_value: str,
    active_set: set[str],
    index: dict[str, Component],
    direction: str,
    colors: ColorAssigner,
) -> graphviz.Digraph:
    """Build a legend-free sub-diagram showing one layer and its direct neighbors."""
    in_layer = {
        c.id for c in components
        if c.id in active_set and c.layer == layer_value and not c.ubiquitous and not c.hide
    }

    # Direct neighbors (both directions) that are outside this layer
    out_of_layer: set[str] = set()
    for comp in components:
        if comp.id not in in_layer:
            continue
        for ref in comp.all_refs():
            match = index.get(ref.lower())
            if (
                match
                and match.id not in in_layer
                and match.id in active_set
                and not match.ubiquitous
                and not match.hide
            ):
                out_of_layer.add(match.id)
    for comp in components:
        if comp.ubiquitous or comp.hide or comp.id in in_layer or comp.id not in active_set:
            continue
        for ref in comp.all_refs():
            match = index.get(ref.lower())
            if match and match.id in in_layer:
                out_of_layer.add(comp.id)
                break

    visible = in_layer | out_of_layer

    dot = graphviz.Digraph(
        name=f"layer_{_layer_filename(layer_value)}",
        graph_attr={
            "rankdir": direction,
            "fontname": "Helvetica",
            "fontsize": "12",
            "splines": "true",
            "concentrate": "false",
            "nodesep": "0.3",
            "ranksep": "0.5",
            "newrank": "true",
            "dpi": "150",
        },
        node_attr={
            "fontname": "Helvetica",
            "fontsize": "11",
            "style": "filled,rounded",
            "shape": "box",
        },
        edge_attr={"fontname": "Helvetica", "fontsize": "9"},
    )

    # Clusters for in-layer nodes that have a Part-of group
    groups: dict[str, list[str]] = {}
    for comp in components:
        if not comp.part_of or comp.ubiquitous or comp.id not in in_layer:
            continue
        groups.setdefault(comp.part_of, []).append(comp.id)
    grouped_in_layer = {nid for ids in groups.values() for nid in ids}

    taken: dict[str, str] = {}
    for group_label, node_ids in sorted(groups.items()):
        safe = _unique_svg_id(group_label, taken)
        with dot.subgraph(name=f"cluster_group_{safe}") as sg:
            tab_label = (
                f'<<TABLE BGCOLOR="#555555" BORDER="0" CELLPADDING="3">'
                f"<TR><TD>"
                f'<FONT COLOR="white" POINT-SIZE="12"><B>{html.escape(group_label)}</B></FONT>'
                f"</TD></TR></TABLE>>"
            )
            sg.attr(
                label=tab_label,
                labelloc="t",
                style="filled",
                fillcolor="#DDDDDD",
                color="#555555",
                fontname="Helvetica",
                penwidth="1.5",
                bgcolor="transparent",
            )
            for node_id in sorted(node_ids):
                comp = index.get(node_id.lower())
                if comp:
                    _emit_component_node(sg, comp, node_id, colors, penwidth=IN_LAYER_PENWIDTH)

    # Ungrouped in-layer nodes
    for comp in components:
        if comp.id not in in_layer or comp.ubiquitous or comp.id in grouped_in_layer:
            continue
        _emit_component_node(dot, comp, comp.id, colors, penwidth=IN_LAYER_PENWIDTH)

    # Out-of-layer neighbors — full owner colors, default border weight
    for ool_id in sorted(out_of_layer):
        comp = index.get(ool_id.lower())
        if comp:
            _emit_component_node(dot, comp, ool_id, colors)

    # Edges — only those with at least one in-layer endpoint
    emitted_clones: set[str] = set()
    solid_edges: set[tuple[str, str]] = set()
    dashed_edges: set[tuple[str, str]] = set()

    def _sub_target(caller_id: str, ref: str) -> str | None:
        match = index.get(ref.lower())
        if match is None or match.hide:
            return None
        if match.ubiquitous:
            # active_set, not visible: visible excludes ubiquitous components
            # by construction, but the status filter still has to apply.
            if match.id not in active_set:
                return None
            if caller_id in in_layer:
                clone_id = _clone_svg_id(caller_id, match.id)
                if clone_id not in emitted_clones:
                    _emit_component_node(dot, match, clone_id, colors, svg_id=clone_id)
                    emitted_clones.add(clone_id)
                return clone_id
            return None
        return match.id if match.id in visible else None

    # Collected in a first pass for the same reason as in _add_edges: the
    # suppression below is otherwise sensitive to component order.
    for comp in components:
        if comp.id not in visible or comp.ubiquitous:
            continue
        for ref in comp.depends_on:
            t = _sub_target(comp.id, ref)
            if t is not None and (t in in_layer or comp.id in in_layer):
                solid_edges.add((t, comp.id))

    for comp in components:
        if comp.id not in visible or comp.ubiquitous:
            continue
        for ref in comp.depends_on:
            t = _sub_target(comp.id, ref)
            if t is not None and (t in in_layer or comp.id in in_layer):
                dot.edge(t, comp.id)
        for ref in comp.depends_on_planned:
            t = _sub_target(comp.id, ref)
            if t is not None and (t in in_layer or comp.id in in_layer) and (t, comp.id) not in solid_edges:
                dot.edge(t, comp.id, style="solid", color="red")
        for ref in comp.uses:
            t = _sub_target(comp.id, ref)
            if t is not None and (comp.id in in_layer or t in in_layer) and (comp.id, t) not in solid_edges:
                dot.edge(comp.id, t, style="dashed")
                # Recorded in dashed_edges, not solid_edges — the two sets
                # suppress different things and mixing them drops the wrong
                # edge. See _add_edges, which this must stay in step with.
                dashed_edges.add((comp.id, t))
        for ref in comp.uses_planned:
            t = _sub_target(comp.id, ref)
            if (
                t is not None
                and (comp.id in in_layer or t in in_layer)
                and (comp.id, t) not in solid_edges
                and (comp.id, t) not in dashed_edges
            ):
                dot.edge(comp.id, t, style="dashed", color="red")

    _add_external_nodes_and_edges(dot, components, in_layer)

    return dot
