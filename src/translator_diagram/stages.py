"""The order the overview is read in, from `config/flow-steps.yaml`.

The bands are hand-written rather than computed. A plausible-looking order
derived from the recorded edges is worse than an honest one someone chose,
because the edges are incomplete — and a component the file does not place
falls to `UNPLACED_TITLE` rather than being quietly dropped.
"""

from pathlib import Path
from typing import Any

import click

from .components import ComponentFile, read_yaml
from .flow import in_flow_order

CONFIG_STAGES_PATH = Path("config/flow-steps.yaml")


UNPLACED_TITLE = "Not yet placed"


def _find_stages() -> Path | None:
    """config/flow-steps.yaml in the working directory or the nearest parent."""
    cwd = Path.cwd()
    for directory in (cwd, *cwd.parents):
        candidate = directory / CONFIG_STAGES_PATH
        if candidate.exists():
            return candidate
    return None


def load_stages(path: Path | None = None) -> list[dict[str, Any]]:
    """The platform's stages, in the order the page shows them.

    This file is the row order, not a set of labels on a computed one. The
    recorded `gets_results_from` / `calls` edges are too sparse to order 26
    components — nothing records the UI calling Name Lookup, so Name Lookup
    sorted near the sources, and nothing records the ARS calling Answer
    Appraiser, so Answer Appraiser sorted above everything. A hand-written
    order is more honest than a plausible-looking one derived from data that
    is missing.

    The trailing entry is the components no stage claims, named in the file's
    `unplaced` block so a new component cannot quietly sort last.

    With no path, the file is looked for in the working directory and every
    directory above it — the same walk `load_owner_colors` and `load_policy`
    do, so building from a subdirectory of the checkout behaves the same way.
    A missing file is an error rather than an empty list: `in_stage_order`
    falls back to data-flow order, which is the ordering this file exists to
    replace, so degrading quietly would publish the wrong page and say
    nothing. An empty file is still allowed — that one is somebody's decision.
    """
    found = path if path is not None else _find_stages()
    if found is None:
        raise click.ClickException(
            f"No stage file at {CONFIG_STAGES_PATH}. It sets the row order, "
            f"and without it the page falls back to data-flow order. Run from "
            f"the repository root."
        )
    if not found.exists():
        raise click.ClickException(f"Stage file not found: {found}")
    loaded = read_yaml(found)
    if not loaded:
        return []
    stages = [
        {
            "title": stage.get("title") or "",
            "description": stage.get("description") or "",
            "components": list(stage.get("components") or []),
        }
        for stage in (loaded.get("stages") or [])
    ]
    unplaced = loaded.get("unplaced") or {}
    stages.append(
        {
            "title": UNPLACED_TITLE,
            "description": unplaced.get("description") or "",
            "components": list(unplaced.get("components") or []),
            "unplaced": True,
        }
    )
    return stages


def in_stage_order(
    components: list[ComponentFile], stages: list[dict[str, Any]]
) -> list[tuple[ComponentFile, int, dict[str, Any]]]:
    """Each component with the stage it belongs to and that stage's number.

    Components are shown in the order their stage lists them: within a stage
    that order is a judgement too, and alphabetising it would throw the
    judgement away. Anything no stage names falls to the end in data-flow
    order, which is the best guess available for something nobody has placed.
    """
    if not stages:
        return [(component, 1, {}) for component in in_flow_order(components)]
    by_id = {component.id.lower(): component for component in components}
    ordered: list[tuple[ComponentFile, int, dict[str, Any]]] = []
    seen: set[str] = set()
    for number, stage in enumerate(stages, 1):
        for cid in stage["components"]:
            component = by_id.get(cid.lower())
            if component and component.id not in seen:
                seen.add(component.id)
                ordered.append((component, number, stage))
    trailing = stages[-1]
    for component in in_flow_order(components):
        if component.id not in seen:
            ordered.append((component, len(stages), trailing))
    return ordered


def stage_blocks(
    stages: list[dict[str, Any]], rows: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """The bands the page draws, built from the rows that survived the policy.

    Built *from the rows*, which is what keeps a published build honest without
    a second privacy pass: a band can only name a component whose row is still
    here. A stage with no kept rows is absent rather than empty — the
    Engineering stage holds jaeger and test-harness and nothing else, and a
    published build shows no heading for it rather than a heading over a gap.

    `step` is the stage's position in `config/flow-steps.yaml`, so the stages
    that remain keep the numbers they have locally: a published page runs 1–8
    and skips 9, rather than renumbering and disagreeing with the full build
    about which step Shepherd is.

    The roster is in row order, so the page's bands and its table list the same
    components in the same order without either having to sort.
    """
    rostered: dict[int, list[str]] = {}
    for row in rows:
        rostered.setdefault(row.get("step"), []).append(row["id"])
    blocks = []
    for number, stage in enumerate(stages, 1):
        members = rostered.get(number)
        if not members:
            continue
        blocks.append(
            {
                "step": number,
                "title": stage.get("title") or "",
                "description": stage.get("description") or "",
                "components": members,
                # Explicit on every block, not only the trailing one: a reader
                # of the payload should not have to know that a missing key
                # means False.
                "unplaced": bool(stage.get("unplaced")),
            }
        )
    return blocks
