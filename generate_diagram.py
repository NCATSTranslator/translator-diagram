"""Generate dependency diagrams for Translator platform components."""

import csv
import html
import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

import click
import graphviz
from dotenv import load_dotenv

# Refactor status values that indicate active components
DEFAULT_STATUSES = ["Continues into Refactor", "New in Refactor"]

# Owner → fill color mapping lives in owner-colors.csv (alongside the script)
# so non-Python edits can change it without touching code. Row order in the
# CSV doubles as legend order in the diagram.
DEFAULT_OWNER_COLORS_PATH = Path(__file__).parent / "owner-colors.csv"

FALLBACK_COLORS = [
    "#B0BEC5", "#BCAAA4", "#CE93D8", "#80CBC4",
    "#EF9A9A", "#FFCC80", "#C5E1A5", "#80DEEA",
]
GHOST_BORDER_COLOR = "#999999"
GHOST_FILL_COLOR = "#D3D3D3"
GHOST_FONT_COLOR = "#666666"
# Warm amber for external-entity nodes (sources and sinks) so they stand out
# clearly against the component fill colors.
EXTERNAL_FILL_COLOR = "#FFE082"
# Emoji labels for non-default hosting locations (ITRB is the default and shown as nothing).
HOSTED_AT_EMOJI: dict[str, str] = {"RENCI": "🌐", "Scripps": "🌐", "Local": "💻", "Unknown": "❓"}
# Bold border penwidth for in-layer nodes in per-layer sub-figures.
IN_LAYER_PENWIDTH = "4.0"
# owner-colors.csv is hand-edited, so its values are checked rather than trusted:
# text_color_for needs exactly six hex digits, and graphviz would silently render
# a typo'd color as black.
HEX_COLOR_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")
# Node URLs come from the sheet and become live <a xlink:href> in the SVG. Only
# ordinary web links are allowed through — see _valid_url.
URL_SCHEMES = ("http://", "https://")


class ColorAssigner:
    """Assigns fill colors to owners, falling back to a rotating palette."""

    def __init__(self, base_colors: dict[str, str], fallback_colors: list[str]):
        self.color_map: dict[str, str] = dict(base_colors)
        self.fallback_colors = fallback_colors
        self.next_fallback = 0
        self._used: set[str] = set()

    def get(self, owner: str) -> str:
        if owner not in self.color_map:
            self.color_map[owner] = self.fallback_colors[
                self.next_fallback % len(self.fallback_colors)
            ]
            self.next_fallback += 1
        self._used.add(owner)
        return self.color_map[owner]

    @property
    def used_colors(self) -> dict[str, str]:
        """Color map restricted to owners actually rendered, in original order."""
        return {k: v for k, v in self.color_map.items() if k in self._used}


def text_color_for(fill_hex: str) -> str:
    """Return "black" or "white" for adequate contrast against a hex fill."""
    h = fill_hex.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    # Rec. 709 perceptual luminance
    luminance = 0.2126 * r + 0.7152 * g + 0.0722 * b
    return "black" if luminance > 0.5 else "white"


@dataclass
class Component:
    """A single row of the components CSV after parsing."""

    id: str
    name: str
    owner: str
    itrb: str
    refactor_status: str
    notes: str
    url: str = ""
    ubiquitous: bool = False
    hide: bool = False
    part_of: str = ""
    hosted_at: str = ""
    layer: str = ""
    externals: list[tuple[str, str]] = field(default_factory=list)
    depends_on: list[str] = field(default_factory=list)
    depends_on_planned: list[str] = field(default_factory=list)
    uses: list[str] = field(default_factory=list)
    uses_planned: list[str] = field(default_factory=list)

    @property
    def display_name(self) -> str:
        # Fall back to id when Name is missing — otherwise the label
        # starts with a blank line.
        return self.name or self.id

    def all_refs(self) -> list[str]:
        return (
            self.depends_on
            + self.depends_on_planned
            + self.uses
            + self.uses_planned
        )


def _parse_bool(value: str) -> bool:
    """Parse a CSV boolean cell — accepts TRUE/yes/1 (case-insensitive)."""
    return value.strip().lower() in ("true", "yes", "y", "1")


def parse_id_list(field_value: str) -> tuple[list[str], list[str]]:
    """Split a comma-separated field into (implemented_ids, planned_ids).

    IDs prefixed with '~' are planned-but-not-yet-implemented.
    """
    implemented, planned = [], []
    for part in field_value.split(","):
        part = part.strip()
        if not part:
            continue
        if part.startswith("~"):
            planned.append(part[1:].strip())
        else:
            implemented.append(part)
    return implemented, planned


def parse_externals(field_value: str, where: str = "") -> list[tuple[str, str]]:
    """Parse the Externals column into a list of (direction, name) pairs.

    Values are standard CSV (commas as separators, double-quotes for names
    that contain commas). Each token must start with '<' (external source
    that sends data *into* this component) or '>' (external sink that
    receives data *from* this component). A token with neither prefix has no
    direction to draw, so it is dropped with a warning rather than silently —
    otherwise a typo in the sheet just makes a node disappear.

    Examples
    --------
    ``<External data sources, >User``
    ``"<Upstream, service", >Researcher``
    """
    if not field_value.strip():
        return []
    result = []
    reader = csv.reader([field_value])
    for row in reader:
        for token in row:
            token = token.strip()
            if not token:
                continue
            if token.startswith("<"):
                result.append(("in", token[1:].strip()))
            elif token.startswith(">"):
                result.append(("out", token[1:].strip()))
            else:
                click.echo(
                    f"WARNING: external '{token}' in {where or 'Externals'} has "
                    f"no '<' or '>' prefix; ignoring it",
                    err=True,
                )
    return result


def load_owner_colors(path: Path = DEFAULT_OWNER_COLORS_PATH) -> dict[str, str]:
    """Load the owner→color mapping from a CSV with columns owner,color.

    Order is preserved from the file; that order also determines legend order.
    """
    if not path.exists():
        raise click.ClickException(f"Owner-colors file not found: {path}")
    with path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        missing_cols = {"owner", "color"} - set(reader.fieldnames or [])
        if missing_cols:
            raise click.ClickException(
                f"{path} is missing required columns: "
                + ", ".join(sorted(missing_cols))
            )
        colors = {}
        for row in reader:
            owner, color = row["owner"].strip(), row["color"].strip()
            if not HEX_COLOR_RE.match(color):
                raise click.ClickException(
                    f"{path}: owner '{owner}' has color '{color}', which is not "
                    f"a six-digit hex colour like #EF5350."
                )
            colors[owner] = color
        return colors


def _valid_url(url: str, comp_id: str) -> str:
    """Return url if it is a plain web link, else "" with a warning.

    Node URLs become live <a xlink:href> wrappers in the SVG, and the planned
    Pages view inlines that SVG — so a 'javascript:' URL pasted into the sheet
    would otherwise become executable on a public page.
    """
    if not url or url.startswith(URL_SCHEMES):
        return url
    click.echo(
        f"WARNING: '{comp_id}' has URL '{url}', which is not http(s); ignoring it",
        err=True,
    )
    return ""


def load_components(csv_path: Path, layer_column: str = "") -> list[Component]:
    """Parse the CSV into a sorted list of Components.

    Rows with a blank id are skipped: they are spacer or trailing rows from the
    sheet, and keeping them yields an unnamed graphviz node, or a baffling
    "duplicate id: '' and ''" error once there are two of them.

    Sorted by lowercase id for deterministic .dot / .json output across CSV
    row reorderings.
    """
    # utf-8-sig strips a UTF-8 BOM if present (Excel-resaved or Windows-edited
    # files), otherwise the first header would read as "﻿id" and KeyError.
    with csv_path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        rows: list[Component] = []
        for row in reader:
            comp_id = row.get("id", "").strip()
            if not comp_id:
                continue
            depends_on, depends_on_planned = parse_id_list(
                row.get("Gets results from", "")
            )
            uses, uses_planned = parse_id_list(row.get("Calls", ""))
            rows.append(Component(
                id=comp_id,
                name=row.get("Name", "").strip(),
                owner=(row.get("Owner") or "None").strip() or "None",
                itrb=row.get("Component in ITRB", "").strip(),
                refactor_status=row.get("Refactor status", "").strip(),
                notes=row.get("Notes", "").strip(),
                url=_valid_url(row.get("URL", "").strip(), comp_id),
                ubiquitous=_parse_bool(row.get("Ubiquitous", "")),
                hide=_parse_bool(row.get("Hide", "")),
                part_of=row.get("Part of", "").strip(),
                hosted_at=row.get("Hosted at", "").strip(),
                layer=row.get(layer_column, "").strip() if layer_column else "",
                externals=parse_externals(row.get("Externals", ""), comp_id),
                depends_on=depends_on,
                depends_on_planned=depends_on_planned,
                uses=uses,
                uses_planned=uses_planned,
            ))
    rows.sort(key=lambda c: c.id.lower())
    return rows


def index_by_id(components: list[Component]) -> dict[str, Component]:
    """Case-insensitive lookup from lower(id) to Component."""
    return {c.id.lower(): c for c in components}


def validate(components: list[Component]) -> bool:
    """Print messages for any reference issues.

    Returns False on hard errors (duplicate ids, unknown referenced ids).
    Case-mismatch references are informational and do not flip the return
    value, because the case-insensitive lookup in build_graph still resolves
    them to the canonical component.
    """
    ok = True

    # Hard error: duplicate ids (case-insensitive). The index below would
    # silently keep only the last duplicate, so detect them up front.
    seen: dict[str, str] = {}
    for comp in components:
        key = comp.id.lower()
        if key in seen:
            click.echo(
                f"ERROR: duplicate id (case-insensitive): "
                f"'{seen[key]}' and '{comp.id}'",
                err=True,
            )
            ok = False
        else:
            seen[key] = comp.id

    index = index_by_id(components)
    for comp in components:
        for ref in comp.all_refs():
            match = index.get(ref.lower())
            if match is None:
                click.echo(
                    f"ERROR: '{comp.id}' references unknown id '{ref}' "
                    f"in Gets results from/Calls",
                    err=True,
                )
                ok = False
            elif match.id != ref:
                click.echo(
                    f"WARNING: '{comp.id}' references '{ref}' but the actual id "
                    f"is '{match.id}' (case mismatch)",
                    err=True,
                )
    return ok


def write_json(components: list[Component], out_path: Path) -> None:
    """Serialise components to JSON, preserving the original CSV column names."""
    exportable = [
        {
            "id": c.id,
            "Name": c.name,
            "Owner": c.owner,
            "Component in ITRB": c.itrb,
            "Refactor status": c.refactor_status,
            "Notes": c.notes,
            "URL": c.url,
            "Ubiquitous": c.ubiquitous,
            "Hide": c.hide,
            "Part of": c.part_of,
            "Hosted at": c.hosted_at,
            "Layer": c.layer,
            "Externals": [{"direction": d, "name": n} for d, n in c.externals],
            "depends_on": c.depends_on,
            "depends_on_planned": c.depends_on_planned,
            "uses": c.uses,
            "uses_planned": c.uses_planned,
        }
        for c in components
    ]
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(exportable, f, indent=2, ensure_ascii=False)
    click.echo(f"Wrote {out_path}")


# --- Graph construction helpers --------------------------------------------


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
) -> None:
    """Render a Component as a graphviz node at the given id.

    Used both for primary node placement and for per-caller ubiquitous clones
    (which use a synthetic id like "{caller}__{target}").
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
    extra: dict[str, str] = {"id": node_id, "tooltip": _node_tooltip(comp)}
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
        id=ghost_id,
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
    for group_label, node_ids in sorted(groups.items()):
        safe = group_label.lower().replace(" ", "_").replace("/", "_")
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
            clone_id = f"{caller_id}__{match.id}"
            if clone_id not in emitted_clones:
                _emit_component_node(dot, match, clone_id, colors)
                emitted_clones.add(clone_id)
            return clone_id
        if match.id in active_set or match.id in ghost_ids:
            return match.id
        return None

    for comp in components:
        if comp.id not in active_set or comp.ubiquitous:
            continue
        for ref in comp.depends_on:
            t = edge_target(comp.id, ref)
            if t is not None:
                dot.edge(t, comp.id)  # B → A: B provides results to A
                solid_edges.add((t, comp.id))
        for ref in comp.depends_on_planned:
            t = edge_target(comp.id, ref)
            if t is not None and (t, comp.id) not in solid_edges:
                # Planned/in-development "Gets results from" — solid red to stand out
                dot.edge(t, comp.id, style="solid", color="red")
        for ref in comp.uses:
            t = edge_target(comp.id, ref)
            if t is not None and (comp.id, t) not in solid_edges:
                dot.edge(comp.id, t, style="dashed")  # A --→ B: API call
        for ref in comp.uses_planned:
            t = edge_target(comp.id, ref)
            if t is not None and (comp.id, t) not in solid_edges:
                # Planned/in-development "Calls" — dashed red to stand out
                dot.edge(comp.id, t, style="dashed", color="red")


def _ext_node_id(name: str) -> str:
    """Stable graphviz node ID derived from an external-entity name."""
    safe = "".join(c if c.isalnum() else "_" for c in name.lower())
    return f"_ext_{safe}"


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
    """
    in_nodes: dict[str, str] = {}            # node_id → display name
    out_nodes: dict[str, str] = {}           # node_id → display name
    in_edges: list[tuple[str, str]] = []     # (ext_id, comp_id)
    out_edges: list[tuple[str, str]] = []    # (comp_id, ext_id)

    for comp in components:
        if comp.id not in active_set or comp.ubiquitous:
            continue
        for direction, name in comp.externals:
            nid = _ext_node_id(name)
            if direction == "in":
                in_nodes[nid] = name
                in_edges.append((nid, comp.id))
            else:
                out_nodes[nid] = name
                out_edges.append((comp.id, nid))

    if not in_nodes and not out_nodes:
        return

    ext_attrs = dict(
        style="filled",
        fillcolor=EXTERNAL_FILL_COLOR,
        fontname="Helvetica",
        fontsize="13",
        penwidth="2.5",
    )

    for nid, name in in_nodes.items():
        dot.node(nid, label=name, shape="cylinder", id=nid, tooltip=name, **ext_attrs)
    for nid, name in out_nodes.items():
        dot.node(
            nid, label=name, shape="oval", peripheries="2",
            id=nid, tooltip=name, **ext_attrs,
        )

    if in_nodes:
        with dot.subgraph() as s:
            s.attr(rank="min")
            for nid in in_nodes:
                s.node(nid)
    if out_nodes:
        with dot.subgraph() as s:
            s.attr(rank="max")
            for nid in out_nodes:
                s.node(nid)

    for src, dst in in_edges:
        dot.edge(src, dst)
    for src, dst in out_edges:
        dot.edge(src, dst)


_LEGEND_CLUSTER_ATTRS = dict(
    style="filled,rounded",
    fillcolor="#FAFAFA",
    color="#AAAAAA",
    fontname="Helvetica",
    fontsize="11",
    margin="12",
)


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

        _ext = dict(
            fillcolor=EXTERNAL_FILL_COLOR, style="filled",
            fontname="Helvetica", fontsize="13", penwidth="2.5",
        )
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


def _layer_filename(layer: str) -> str:
    """Convert a layer label to a safe filename stem."""
    safe = re.sub(r"[^\w\s-]", "", layer.lower())
    safe = re.sub(r"[\s-]+", "_", safe).strip("_")
    return safe or "layer"


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

    for group_label, node_ids in sorted(groups.items()):
        safe = group_label.lower().replace(" ", "_").replace("/", "_")
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

    def _sub_target(caller_id: str, ref: str) -> str | None:
        match = index.get(ref.lower())
        if match is None or match.hide:
            return None
        if match.ubiquitous:
            if caller_id in in_layer:
                clone_id = f"{caller_id}__{match.id}"
                if clone_id not in emitted_clones:
                    _emit_component_node(dot, match, clone_id, colors)
                    emitted_clones.add(clone_id)
                return clone_id
            return None
        return match.id if match.id in visible else None

    for comp in components:
        if comp.id not in visible or comp.ubiquitous:
            continue
        for ref in comp.depends_on:
            t = _sub_target(comp.id, ref)
            if t is not None and (t in in_layer or comp.id in in_layer):
                dot.edge(t, comp.id)
                solid_edges.add((t, comp.id))
        for ref in comp.depends_on_planned:
            t = _sub_target(comp.id, ref)
            if t is not None and (t in in_layer or comp.id in in_layer) and (t, comp.id) not in solid_edges:
                dot.edge(t, comp.id, style="solid", color="red")
        for ref in comp.uses:
            t = _sub_target(comp.id, ref)
            if t is not None and (comp.id in in_layer or t in in_layer) and (comp.id, t) not in solid_edges:
                dot.edge(comp.id, t, style="dashed")
                # Deliberately not added to solid_edges: the set suppresses
                # dashed edges that duplicate a *solid* one, so recording a
                # dashed edge here would drop the planned (red) edge below and
                # diverge from _add_edges in the main diagram.
        for ref in comp.uses_planned:
            t = _sub_target(comp.id, ref)
            if t is not None and (comp.id in in_layer or t in in_layer) and (comp.id, t) not in solid_edges:
                dot.edge(comp.id, t, style="dashed", color="red")

    _add_external_nodes_and_edges(dot, components, in_layer)

    return dot


@click.command()
@click.option(
    "--input", "input_path",
    default="data/components.csv",
    show_default=True,
    type=click.Path(dir_okay=False, path_type=Path),
    help="CSV input file (used unless --google-sheet is set).",
)
@click.option(
    "--google-sheet", "google_sheet",
    is_flag=True,
    default=False,
    help="Download CSV from Google Sheet instead of reading a local file. "
         "Reads GOOGLE_SHEET_ID from .env (cwd, then the script directory).",
)
@click.option(
    "--sheet-gid", "sheet_gid",
    default=0,
    show_default=True,
    help="Google Sheet tab GID (0 = first tab).",
)
@click.option(
    "--output-dir", "output_dir",
    default="data",
    show_default=True,
    type=click.Path(file_okay=False, path_type=Path),
    help="Directory for output files.",
)
@click.option(
    "--output-name", "output_name",
    default="diagram",
    show_default=True,
    help="Base filename for output files (without extension).",
)
@click.option(
    "--refactor-status", "refactor_status",
    default=",".join(DEFAULT_STATUSES),
    show_default=True,
    help="Comma-separated list of Refactor status values to include.",
)
@click.option(
    "--all", "include_all",
    is_flag=True,
    default=False,
    help="Include all components regardless of Refactor status.",
)
@click.option(
    "--format", "extra_formats",
    multiple=True,
    type=click.Choice(["pdf", "svg"]),
    help="Additional output formats beyond PNG (PNG is always produced). "
         "Can be repeated.",
)
@click.option(
    "--direction",
    default="TB",
    show_default=True,
    type=click.Choice(["LR", "TB"]),
    help="Graph layout direction.",
)
@click.option(
    "--concentrate/--no-concentrate",
    default=False,
    show_default=True,
    help="Merge partially-parallel edges (concentrate=true). Disable if solid "
         "and dashed edges between nearby nodes render incorrectly merged.",
)
@click.option(
    "--split-legends/--no-split-legends", "split_legends",
    default=True,
    show_default=True,
    help="Write owner and edge-style legends as separate PNGs "
         "({output_name}_owners.png / {output_name}_legend.png) and omit "
         "them from the main diagram. Use --no-split-legends to embed them.",
)
@click.option(
    "--layer-column", "layer_column",
    default="",
    show_default=True,
    help="CSV column name to use for layer-based sub-figures (e.g. 'Layer'). "
         "When set, one PNG sub-figure is written per distinct value found in "
         "that column, showing in-layer nodes at full color and direct "
         "neighbors from other layers greyed out. Leave empty to skip.",
)
def main(
    input_path: Path,
    google_sheet: bool,
    sheet_gid: int,
    output_dir: Path,
    output_name: str,
    refactor_status: str,
    include_all: bool,
    extra_formats: tuple[str, ...],
    direction: str,
    concentrate: bool,
    split_legends: bool,
    layer_column: str,
) -> None:
    """Validate components CSV and generate a Graphviz dependency diagram."""
    output_dir.mkdir(parents=True, exist_ok=True)

    if google_sheet:
        # Look for .env in cwd first (standard dotenv behavior, walks up the
        # tree), then fall back to one next to the script for users who run
        # the tool from a different directory. override=False keeps the cwd
        # value winning when both files exist.
        load_dotenv()
        load_dotenv(Path(__file__).parent / ".env", override=False)
        sheet_id = os.environ.get("GOOGLE_SHEET_ID", "").strip()
        if not sheet_id:
            raise click.ClickException(
                "GOOGLE_SHEET_ID is not set. Add it to .env in the current "
                f"directory or next to {Path(__file__).name}."
            )
        url = (
            f"https://docs.google.com/spreadsheets/d/{sheet_id}"
            f"/export?format=csv&gid={sheet_gid}"
        )
        download_path = output_dir / "components.csv"
        click.echo(f"Downloading CSV from Google Sheet to {download_path} ...")
        # Use urlopen + content-type check rather than urlretrieve: a private
        # or missing sheet redirects to a 200 HTML login page, which would
        # otherwise be silently saved as components.csv.
        try:
            # timeout so a stalled request fails the run rather than hanging a
            # scheduled CI job forever.
            with urllib.request.urlopen(url, timeout=30) as response:
                content_type = response.headers.get("Content-Type", "")
                body = response.read()
        except urllib.error.URLError as exc:
            raise click.ClickException(
                f"Failed to download Google Sheet ({url}): {exc}"
            ) from exc
        if "text/csv" not in content_type.lower():
            raise click.ClickException(
                f"Google Sheet response was not CSV (Content-Type: "
                f"{content_type or 'unset'}). The sheet may be private, "
                f"the ID may be wrong, or the gid may not exist. URL: {url}"
            )
        download_path.write_bytes(body)
        input_path = download_path
    elif not input_path.exists():
        raise click.ClickException(f"Input file not found: {input_path}")

    click.echo(f"Loading {input_path} ...")
    components = load_components(input_path, layer_column=layer_column)
    click.echo(f"Loaded {len(components)} components.")

    click.echo("Validating references ...")
    if not validate(components):
        raise click.ClickException(
            "Validation failed; fix the errors above and re-run."
        )

    # Write JSON (all components, regardless of filter)
    json_path = output_dir / "components.json"
    write_json(components, json_path)

    # Determine active statuses
    active_statuses: set[str] | None
    if include_all:
        active_statuses = None
        click.echo("Including all components (no filter).")
    else:
        active_statuses = {
            s.strip() for s in refactor_status.split(",") if s.strip()
        }
        active_count = sum(
            # Must match _compute_active_set, which also drops hidden rows.
            1 for c in components
            if c.refactor_status in active_statuses and not c.hide
        )
        click.echo(
            f"Filtering to {active_count} components with status: "
            + ", ".join(sorted(active_statuses))
        )

    colors = ColorAssigner(load_owner_colors(), FALLBACK_COLORS)
    dot = build_graph(
        components, active_statuses, direction, colors,
        concentrate=concentrate, include_legend=not split_legends,
    )

    # Save .dot source
    dot_path = output_dir / f"{output_name}.dot"
    dot_path.write_text(dot.source, encoding="utf-8")
    click.echo(f"Wrote {dot_path}")

    # Render PNG (always) plus any extra formats. cleanup=True removes the
    # intermediate extension-less dot source that render() writes alongside
    # the rendered file — we already keep the canonical copy in {output_name}.dot.
    formats_to_render = {"png"} | set(extra_formats)
    for fmt in sorted(formats_to_render):
        dot.render(
            filename=str(output_dir / output_name),
            format=fmt,
            cleanup=True,
        )
        click.echo(f"Wrote {output_dir / f'{output_name}.{fmt}'}")

    # Separate legend files
    if split_legends:
        for legend_stem, legend_dot in [
            (f"{output_name}_owners", _build_owners_graph(colors)),
            (f"{output_name}_legend", _build_edge_legend_graph()),
        ]:
            legend_dot.render(
                filename=str(output_dir / legend_stem),
                format="png",
                cleanup=True,
            )
            click.echo(f"Wrote {output_dir / f'{legend_stem}.png'}")

    # Per-layer sub-figures
    if layer_column:
        _index = index_by_id(components)
        _active_set = _compute_active_set(components, active_statuses)
        layers = sorted({c.layer for c in components if c.layer})
        if not layers:
            click.echo(
                f"Note: no values found in '{layer_column}' column; "
                "no layer sub-figures written."
            )
        else:
            click.echo(
                f"Generating {len(layers)} layer sub-figure(s) "
                f"from '{layer_column}' column ..."
            )
            for layer_value in layers:
                in_layer_count = sum(
                    1 for c in components
                    if c.id in _active_set
                    and c.layer == layer_value
                    and not c.ubiquitous
                    and not c.hide
                )
                if in_layer_count == 0:
                    click.echo(
                        f"  Skipping '{layer_value}' "
                        "(no active non-ubiquitous components)."
                    )
                    continue
                layer_dot = build_layer_subgraph(
                    components, layer_value, _active_set, _index, direction, colors
                )
                stem = f"{output_name}_{_layer_filename(layer_value)}"
                layer_dot_path = output_dir / f"{stem}.dot"
                layer_dot_path.write_text(layer_dot.source, encoding="utf-8")
                layer_dot.render(
                    filename=str(output_dir / stem),
                    format="png",
                    cleanup=True,
                )
                click.echo(f"  Wrote {output_dir / f'{stem}.png'}")


if __name__ == "__main__":
    main()
