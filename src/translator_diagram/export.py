"""components.json — the machine-readable view of the sheet."""

import json
from pathlib import Path

import click

from .model import Component
from .naming import _svg_node_ids


def write_json(components: list[Component], out_path: Path) -> None:
    """Serialise components to JSON, preserving the original CSV column names.

    Rows with Hide=TRUE are left out. "Hide" means the component is suppressed
    entirely, and this file is what the planned Pages view fetches from a
    public site — exporting a hidden row would publish its Notes verbatim.
    """
    node_ids = _svg_node_ids(components)
    exportable = [
        {
            "id": c.id,
            # The SVG <g id="..."> values for this component, so a consumer can
            # find its node(s) without re-deriving the sanitising rule. A list
            # because a ubiquitous component is drawn once per caller — see
            # _svg_node_ids.
            "node_ids": node_ids[c.id],
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
        for c in components if not c.hide
    ]
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(exportable, f, indent=2, ensure_ascii=False)
    click.echo(f"Wrote {out_path}")
