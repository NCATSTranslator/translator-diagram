"""Generate dependency diagrams for Translator platform components."""

import csv
import json
import os
import urllib.request
from pathlib import Path

import click
import graphviz
from dotenv import load_dotenv

# Refactor status values that indicate active components
DEFAULT_STATUSES = ["Continues into Refactor", "New in Refactor"]

# Owner → pastel fill color mapping (soft colors work well on white backgrounds)
OWNER_COLORS = {
    "DOGSURF": "#AED6F1",
    "DINGO": "#A9DFBF",
    "Core Components WG": "#F9E79F",
    "NCATS": "#F1948A",
    "Retriever": "#D7BDE2",
    "Shepherd": "#FAD7A0",
    "DOGSLED": "#A8D8EA",
    "CATRAX": "#C8E6C9",
    "UI": "#FFDDC1",
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


def parse_id_list(field: str) -> list[str]:
    """Split a comma-separated field into a list of stripped, non-empty strings."""
    if not field or not field.strip():
        return []
    return [part.strip() for part in field.split(",") if part.strip()]


def load_components(csv_path: Path) -> list[dict]:
    with csv_path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = []
        for row in reader:
            row["_depends_on"] = parse_id_list(row.get("Depends on", ""))
            row["_uses"] = parse_id_list(row.get("Uses", ""))
            rows.append(row)
    return rows


def validate(components: list[dict]) -> bool:
    """Print warnings for any reference issues. Returns False if any warnings."""
    id_lower_map = {c["id"].lower(): c["id"] for c in components}
    ok = True
    for comp in components:
        comp_id = comp["id"]
        for ref in comp["_depends_on"] + comp["_uses"]:
            ref_lower = ref.lower()
            if ref_lower not in id_lower_map:
                click.echo(
                    f"WARNING: '{comp_id}' references unknown id '{ref}' "
                    f"in Depends on/Uses",
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
        row["uses"] = comp["_uses"]
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

    # Collect ghost ids: referenced by active components but not in active_set
    ghost_ids: set[str] = set()
    for comp in components:
        if comp["id"] not in active_set:
            continue
        for ref in comp["_depends_on"] + comp["_uses"]:
            canonical = id_lower_map.get(ref.lower(), {}).get("id", ref)
            if canonical not in active_set:
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

    # Group active nodes by owner, emit as clusters
    owners: dict[str, list[dict]] = {}
    for comp in components:
        if comp["id"] not in active_set:
            continue
        owner = comp.get("Owner", "None") or "None"
        owners.setdefault(owner, []).append(comp)

    for owner, members in sorted(owners.items()):
        fill = get_owner_color(owner, color_map)
        with dot.subgraph(name=f"cluster_{owner}") as sub:
            sub.attr(
                label=owner,
                style="rounded",
                color="#888888",
                fontname="Helvetica",
                fontsize="12",
            )
            for comp in members:
                is_new = comp["Refactor status"] == "New in Refactor"
                label = f"{comp['Apps']}\n{comp['id']}"
                sub.node(
                    comp["id"],
                    label=label,
                    fillcolor=fill,
                    penwidth="2.0" if is_new else "1.0",
                )

    # Ghost nodes (outside clusters, muted style)
    for ghost_id in sorted(ghost_ids):
        comp = id_lower_map.get(ghost_id.lower())
        apps_name = comp["Apps"] if comp else ghost_id
        label = f"{apps_name}\n{ghost_id}\n(excluded)"
        dot.node(
            ghost_id,
            label=label,
            fillcolor="#D3D3D3",
            style="filled,rounded,dashed",
            fontcolor="#666666",
            color="#999999",
        )

    # Edges — resolve ids case-insensitively
    for comp in components:
        if comp["id"] not in active_set:
            continue
        for ref in comp["_depends_on"]:
            target = id_lower_map.get(ref.lower(), {}).get("id", ref)
            if target in active_set or target in ghost_ids:
                dot.edge(target, comp["id"])  # B → A: B must run for A
        for ref in comp["_uses"]:
            target = id_lower_map.get(ref.lower(), {}).get("id", ref)
            if target in active_set or target in ghost_ids:
                dot.edge(target, comp["id"], style="dashed")  # B → A: A uses B

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
    default="LR",
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
        urllib.request.urlretrieve(url, download_path)
        input_path = download_path
    elif not input_path.exists():
        raise click.ClickException(f"Input file not found: {input_path}")

    click.echo(f"Loading {input_path} ...")
    components = load_components(input_path)
    click.echo(f"Loaded {len(components)} components.")

    click.echo("Validating references ...")
    validate(components)

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
