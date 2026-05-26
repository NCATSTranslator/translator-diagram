"""Generate dependency diagrams for Translator platform components."""

import csv
import json
import os
import urllib.error
import urllib.request
from pathlib import Path

import click
import graphviz
from dotenv import load_dotenv

# Refactor status values that indicate active components
DEFAULT_STATUSES = ["Continues into Refactor", "New in Refactor"]

# Owner → fill color mapping
OWNER_COLORS = {
    # Main customers: bright and prominent
    "NCATS": "#EF5350",          # vivid red
    "UI": "#EC407A",             # vivid pink
    # Three main teams: distinct solid colors
    "DOGSLED": "#42A5F5",        # blue
    "DOGSURF": "#66BB6A",        # green
    "CATRAX": "#FFA726",         # amber
    # Specialized cross-team groups: distinct from the teams above
    "Core Components WG": "#AB47BC",  # purple
    "DINGO": "#26C6DA",          # cyan
    "Shepherd": "#D4E157",       # lime
    "Retriever": "#8D6E63",      # brown
    "None": "#E8E8E8",
}
FALLBACK_COLORS = [
    "#B0BEC5", "#BCAAA4", "#CE93D8", "#80CBC4",
    "#EF9A9A", "#FFCC80", "#C5E1A5", "#80DEEA",
]
_color_index = 0


def get_owner_color(owner: str, color_map: dict) -> str:
    global _color_index
    if owner not in color_map:
        color_map[owner] = FALLBACK_COLORS[_color_index % len(FALLBACK_COLORS)]
        _color_index += 1
    return color_map[owner]


def parse_id_list(field: str) -> tuple[list[str], list[str]]:
    """Split a comma-separated field into (implemented_ids, planned_ids).

    IDs prefixed with '~' are planned-but-not-yet-implemented.
    """
    implemented, planned = [], []
    for part in field.split(","):
        part = part.strip()
        if not part:
            continue
        if part.startswith("~"):
            planned.append(part[1:].strip())
        else:
            implemented.append(part)
    return implemented, planned


def load_components(csv_path: Path) -> list[dict]:
    # utf-8-sig strips a UTF-8 BOM if present (Excel-resaved or Windows-edited files),
    # otherwise the first header would read as "﻿id" and KeyError on c["id"].
    with csv_path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        rows = []
        for row in reader:
            impl, planned = parse_id_list(row.get("Gets results from", ""))
            row["_depends_on"] = impl
            row["_depends_on_planned"] = planned
            impl, planned = parse_id_list(row.get("Calls", ""))
            row["_uses"] = impl
            row["_uses_planned"] = planned
            rows.append(row)
    return rows


def validate(components: list[dict]) -> bool:
    """Print messages for any reference issues.

    Returns False on hard errors (duplicate ids, unknown referenced ids).
    Case-mismatch references are informational and do not flip the return
    value, because the case-insensitive lookup in build_graph still resolves
    them to the canonical component.
    """
    ok = True

    # Hard error: duplicate ids (case-insensitive). The id_lower_map below
    # would silently keep only the last duplicate, so detect them up front.
    seen: dict[str, str] = {}
    for comp in components:
        key = comp["id"].lower()
        if key in seen:
            click.echo(
                f"ERROR: duplicate id (case-insensitive): "
                f"'{seen[key]}' and '{comp['id']}'",
                err=True,
            )
            ok = False
        else:
            seen[key] = comp["id"]

    id_lower_map = {c["id"].lower(): c["id"] for c in components}
    for comp in components:
        comp_id = comp["id"]
        all_refs = (
            comp["_depends_on"] + comp["_depends_on_planned"]
            + comp["_uses"] + comp["_uses_planned"]
        )
        for ref in all_refs:
            ref_lower = ref.lower()
            if ref_lower not in id_lower_map:
                click.echo(
                    f"ERROR: '{comp_id}' references unknown id '{ref}' "
                    f"in Gets results from/Calls",
                    err=True,
                )
                ok = False
            elif id_lower_map[ref_lower] != ref:
                click.echo(
                    f"WARNING: '{comp_id}' references '{ref}' but the actual id "
                    f"is '{id_lower_map[ref_lower]}' (case mismatch)",
                    err=True,
                )
    return ok


def write_json(components: list[dict], out_path: Path) -> None:
    exportable = []
    for comp in components:
        row = {k: v for k, v in comp.items() if not k.startswith("_")}
        row["depends_on"] = comp["_depends_on"]
        row["depends_on_planned"] = comp["_depends_on_planned"]
        row["uses"] = comp["_uses"]
        row["uses_planned"] = comp["_uses_planned"]
        exportable.append(row)
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(exportable, f, indent=2, ensure_ascii=False)
    click.echo(f"Wrote {out_path}")


def build_graph(
    components: list[dict],
    active_statuses: set[str] | None,
    direction: str,
    color_map: dict,
) -> graphviz.Digraph:
    id_lower_map = {c["id"].lower(): c for c in components}

    if active_statuses is None:
        active_set = {c["id"] for c in components}
    else:
        active_set = {c["id"] for c in components if c["Refactor status"] in active_statuses}

    def resolve(ref: str) -> str | None:
        """Resolve a ref string to its canonical component id, or None if unknown.

        Unknown refs return None rather than falling back to the raw ref so they
        do not render as phantom ghost nodes; validate() is responsible for
        surfacing them as errors before we reach here.
        """
        match = id_lower_map.get(ref.lower())
        return match["id"] if match else None

    # Collect ghost ids: referenced by active components but not in active_set
    ghost_ids: set[str] = set()
    for comp in components:
        if comp["id"] not in active_set:
            continue
        all_refs = (
            comp["_depends_on"] + comp["_depends_on_planned"]
            + comp["_uses"] + comp["_uses_planned"]
        )
        for ref in all_refs:
            canonical = resolve(ref)
            if canonical is not None and canonical not in active_set:
                ghost_ids.add(canonical)

    dot = graphviz.Digraph(
        name="translator_components",
        graph_attr={
            "rankdir": direction,
            "fontname": "Helvetica",
            "fontsize": "12",
            "splines": "ortho",
            "nodesep": "0.5",
            "ranksep": "1.0",
        },
        node_attr={
            "fontname": "Helvetica",
            "fontsize": "11",
            "style": "filled,rounded",
            "shape": "box",
        },
        edge_attr={"fontname": "Helvetica", "fontsize": "9"},
    )

    # Add active nodes (no owner clustering — owner is shown in the label)
    for comp in components:
        if comp["id"] not in active_set:
            continue
        owner = comp.get("Owner", "None") or "None"
        fill = get_owner_color(owner, color_map)
        is_new = comp["Refactor status"] == "New in Refactor"
        label = f"{comp['Name']}\n{comp['id']}\n{owner}"
        dot.node(
            comp["id"],
            label=label,
            fillcolor=fill,
            penwidth="2.0" if is_new else "1.0",
        )

    # Ghost nodes (outside clusters, muted style)
    for ghost_id in sorted(ghost_ids):
        comp = id_lower_map.get(ghost_id.lower())
        name = comp["Name"] if comp else ghost_id
        owner = (comp.get("Owner", "") or "") if comp else ""
        label = f"{name}\n{ghost_id}\n{owner}\n(excluded)" if owner else f"{name}\n{ghost_id}\n(excluded)"
        dot.node(
            ghost_id,
            label=label,
            fillcolor="#D3D3D3",
            style="filled,rounded,dashed",
            fontcolor="#666666",
            color="#999999",
        )

    # Edges — resolve ids case-insensitively; unknown refs are skipped (validate() flagged them)
    PLANNED_COLOR = "#999999"

    def edge_target(ref: str) -> str | None:
        target = resolve(ref)
        if target is None:
            return None
        if target in active_set or target in ghost_ids:
            return target
        return None

    for comp in components:
        if comp["id"] not in active_set:
            continue
        for ref in comp["_depends_on"]:
            target = edge_target(ref)
            if target is not None:
                dot.edge(target, comp["id"])  # B → A: B provides results to A
        for ref in comp["_depends_on_planned"]:
            target = edge_target(ref)
            if target is not None:
                dot.edge(target, comp["id"], style="dashed", color=PLANNED_COLOR)
        for ref in comp["_uses"]:
            target = edge_target(ref)
            if target is not None:
                dot.edge(comp["id"], target, style="dotted")  # A ··→ B: A sends request to B
        for ref in comp["_uses_planned"]:
            target = edge_target(ref)
            if target is not None:
                dot.edge(comp["id"], target, style="dotted", color=PLANNED_COLOR)

    # Entry/exit terminal nodes — only added when the components they connect
    # to are present in the diagram. Without the gate, hardcoded edges to
    # missing ids would silently create default-styled phantom nodes.
    terminal_attrs = dict(
        style="filled",
        fillcolor="#CFD8DC",
        fontname="Helvetica",
        fontsize="11",
        penwidth="1.5",
    )

    ENTRY_TARGET = "kgx-storage-pipeline"
    if ENTRY_TARGET in active_set or ENTRY_TARGET in ghost_ids:
        dot.node("_external_sources", label="External\ndata sources",
                 shape="cylinder", **terminal_attrs)
        with dot.subgraph() as src_rank:
            src_rank.attr(rank="min")
            src_rank.node("_external_sources")
        dot.edge("_external_sources", ENTRY_TARGET)

    EXIT_SOURCE = "ui"
    if EXIT_SOURCE in active_set or EXIT_SOURCE in ghost_ids:
        dot.node("_user", label="User", shape="oval",
                 peripheries="2", **terminal_attrs)
        with dot.subgraph() as sink_rank:
            sink_rank.attr(rank="max")
            sink_rank.node("_user")
        dot.edge(EXIT_SOURCE, "_user")

    # Legend
    with dot.subgraph(name="cluster_legend") as leg:
        leg.attr(
            label="Legend",
            style="filled,rounded",
            fillcolor="#FAFAFA",
            color="#AAAAAA",
            fontname="Helvetica",
            fontsize="11",
            margin="12",
            rank="min",
        )
        leg.node("_leg_a1", label="Producer", fillcolor="white", penwidth="1.0")
        leg.node("_leg_b1", label="Consumer", fillcolor="white", penwidth="1.0")
        leg.edge("_leg_a1", "_leg_b1", xlabel="Results")
        leg.node("_leg_a2", label="Component", fillcolor="white", penwidth="1.0")
        leg.node("_leg_b2", label="Service", fillcolor="white", penwidth="1.0")
        leg.edge("_leg_a2", "_leg_b2", xlabel="API call", style="dotted")

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
         "Reads GOOGLE_SHEET_ID from .env in the script directory.",
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
    type=click.Choice(["pdf", "svg", "png"]),
    help="Additional output formats (PNG always produced). Can be repeated.",
)
@click.option(
    "--direction",
    default="TB",
    show_default=True,
    type=click.Choice(["LR", "TB"]),
    help="Graph layout direction.",
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
) -> None:
    """Validate components CSV and generate a Graphviz dependency diagram."""
    output_dir.mkdir(parents=True, exist_ok=True)

    if google_sheet:
        env_path = Path(__file__).parent / ".env"
        load_dotenv(env_path)
        sheet_id = os.environ.get("GOOGLE_SHEET_ID", "").strip()
        if not sheet_id:
            raise click.ClickException(
                f"GOOGLE_SHEET_ID is not set. Fill it in at {env_path}"
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
            with urllib.request.urlopen(url) as response:
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
    components = load_components(input_path)
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
        active_statuses = {s.strip() for s in refactor_status.split(",") if s.strip()}
        active_count = sum(1 for c in components if c["Refactor status"] in active_statuses)
        click.echo(
            f"Filtering to {active_count} components with status: "
            + ", ".join(sorted(active_statuses))
        )

    color_map = dict(OWNER_COLORS)
    dot = build_graph(components, active_statuses, direction, color_map)

    # Save .dot source
    dot_path = output_dir / f"{output_name}.dot"
    dot_path.write_text(dot.source, encoding="utf-8")
    click.echo(f"Wrote {dot_path}")

    # Render PNG (always)
    formats_to_render = {"png"} | set(extra_formats)
    for fmt in sorted(formats_to_render):
        rendered = dot.render(
            filename=str(output_dir / output_name),
            format=fmt,
            cleanup=False,
        )
        # graphviz appends format extension; rename away the extra copy
        expected = output_dir / f"{output_name}.{fmt}"
        click.echo(f"Wrote {expected}")


if __name__ == "__main__":
    main()
