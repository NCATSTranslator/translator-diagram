"""The generate-diagram command line."""

from pathlib import Path

import click

from .colors import FALLBACK_COLORS, ColorAssigner, load_owner_colors
from .export import write_json
from .legend import _build_edge_legend_graph, _build_owners_graph
from .loading import download_sheet_csv, load_components
from .model import index_by_id
from .naming import _layer_filenames
from .render import _compute_active_set, build_graph, build_layer_subgraph
from .validation import validate


# Refactor status values that indicate active components
DEFAULT_STATUSES = ["Continues into Refactor", "New in Refactor"]


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
    "--owner-colors", "owner_colors_path",
    default=None,
    type=click.Path(dir_okay=False, exists=True, path_type=Path),
    help="Owner-colour CSV to use, instead of config/owner-colors.csv in the "
         "current directory or the copy shipped with the package.",
)
@click.option(
    "--layer-column", "layer_column",
    default="",
    show_default=True,
    help="CSV column name to use for layer-based sub-figures (e.g. 'Layer'). "
         "When set, one PNG sub-figure is written per distinct value found in "
         "that column, showing in-layer nodes with a bold border and their "
         "direct neighbors from other layers at normal weight. "
         "Leave empty to skip.",
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
    owner_colors_path: Path | None,
    layer_column: str,
) -> None:
    """Validate components CSV and generate a Graphviz dependency diagram."""
    output_dir.mkdir(parents=True, exist_ok=True)

    if google_sheet:
        input_path = download_sheet_csv(sheet_gid, output_dir)
    elif not input_path.exists():
        raise click.ClickException(f"Input file not found: {input_path}")

    click.echo(f"Loading {input_path} ...")
    components = load_components(input_path, layer_column=layer_column)
    click.echo(f"Loaded {len(components)} components.")
    if not components:
        # Every row was id-less. Rendering the empty diagram that follows would
        # let a scheduled run overwrite good output with a blank picture.
        raise click.ClickException(
            f"No components found in {input_path}; every row is missing an id."
        )

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

    colors = ColorAssigner(load_owner_colors(owner_colors_path), FALLBACK_COLORS)
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
            stems = _layer_filenames(layers)
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
                stem = f"{output_name}_{stems[layer_value]}"
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
