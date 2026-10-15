"""Every name the tool hands out: SVG ids, and output filename stems.

Four families of node share the SVG id namespace — components, the
per-caller clones of ubiquitous components, external entities, and the
"a_"-prefixed <g> graphviz wraps around each of them. validation.validate
owns the check that no two of them collide; this module hands out the names.
"""

import re
from collections.abc import Iterator

import click

from .model import Component, index_by_id

# Graphviz accepts any node name, but the SVG "id" attribute it lands in must be
# a valid XML ID — no spaces or slashes, and no leading digit — or the planned
# Pages view can't retrieve the node with getElementById. See _svg_id.
_ID_UNSAFE_RE = re.compile(r"[^0-9A-Za-z]+")


def _svg_id(text: str) -> str:
    """Lowercase, XML-ID-safe handle for text, for use as an SVG <g id="...">."""
    safe = _ID_UNSAFE_RE.sub("_", text.lower()).strip("_")
    return safe if safe[:1].isalpha() else f"n_{safe}"


# Escaping the "a_" prefix inside _svg_id instead of validating against it
# looks tempting and does not work: any escape has to be something _svg_id can
# produce, so it collides in turn ("A Foo" -> "a__foo" is what a component "A"
# cloning ubiquitous "foo" already gets), and "n_"-prefixing just moves the
# clash to "N A Foo". validate() owning the whole namespace is the way out.
def _clone_svg_id(caller_id: str, target_id: str) -> str:
    """SVG id for the per-caller clone of a ubiquitous component.

    Built by joining two already-sanitised ids with a double underscore, which
    _svg_id itself can never produce (it collapses runs of punctuation to one
    "_"), so a clone can never claim a component's id — the ids "ARS", "LOG"
    and "ARS LOG" used to give the clone and the component both "ars_log".
    validate() still checks the whole namespace, for the cases that survive.
    """
    return f"{_svg_id(caller_id)}__{_svg_id(target_id)}"


def _unique_svg_id(text: str, taken: dict[str, str]) -> str:
    """_svg_id(text), suffixed if a *different* string already claimed that id.

    Free-text labels sanitise alike more often than ids do ("User/agent" and
    "User agent" both give "user_agent"), and without this the second one
    silently merges into the first's node or cluster. taken maps each id
    handed out to the text that claimed it, and callers share one dict.
    """
    return _dedupe(_svg_id(text), text, taken)


def _dedupe(base: str, owner: str, taken: dict[str, str]) -> str:
    """`base`, or `base_2`, `base_3`, ... — the first not held by a different owner.

    `taken` maps each name handed out to whoever claimed it, so the same
    owner asking twice gets the same answer and a different owner gets the
    next free suffix. Shared by the SVG ids and the layer filename stems,
    which collide the same way for the same reason.
    """
    candidate, n = base, 1
    while taken.setdefault(candidate, owner) != owner:
        n += 1
        candidate = f"{base}_{n}"
    return candidate


def external_svg_ids(components: list[Component]) -> dict[str, str]:
    """External display name -> SVG node id, for every external in the sheet.

    Computed over all components rather than the filtered set, so an external
    keeps one id across the main diagram, every layer sub-figure and
    validate(). The "ext__" prefix is safe from component ids for the same
    reason as _clone_svg_id's joiner.
    """
    taken: dict[str, str] = {}
    names = dict.fromkeys(n for c in components for _, n in c.externals)
    return {name: f"ext__{_unique_svg_id(name, taken)}" for name in names}


def _svg_node_ids(components: list[Component]) -> dict[str, list[str]]:
    """Component id -> the SVG node ids that component is drawn under.

    One id for an ordinary component. A ubiquitous one has no central node —
    it is cloned next to each caller — so it gets one id per caller, and none
    at all if nothing references it. Hidden components get none: they are not
    drawn. Computed over every row, unfiltered, to match components.json; a
    component the refactor-status filter excludes has no node in that
    particular rendering, and a consumer has to tolerate a missing element.
    """
    index = index_by_id(components)
    ids = {
        c.id: ([] if c.ubiquitous else [_svg_id(c.id)])
        for c in components if not c.hide
    }
    for caller, target in ubiquitous_clones(components, index):
        clone = _clone_svg_id(caller.id, target.id)
        if clone not in ids[target.id]:
            ids[target.id].append(clone)
    return ids


def ubiquitous_clones(
    components: list[Component], index: dict[str, Component]
) -> Iterator[tuple[Component, Component]]:
    """Every (caller, ubiquitous target) pair a clone is drawn for.

    A ubiquitous component has no node of its own: a clone sits beside each
    caller that references it. Hidden components appear on neither side, and
    a ubiquitous caller has no node to put a clone beside. A caller that
    references the same target twice yields it twice; whoever names the
    clone dedupes, since the id is the same both times.
    """
    for caller in components:
        if caller.hide or caller.ubiquitous:
            continue
        for ref in caller.all_refs():
            target = index.get(ref.lower())
            if target is not None and target.ubiquitous and not target.hide:
                yield caller, target


def _layer_filename(layer: str) -> str:
    """Convert a layer label to a safe filename stem."""
    safe = re.sub(r"[^\w\s-]", "", layer.lower())
    safe = re.sub(r"[\s-]+", "_", safe).strip("_")
    return safe or "layer"


def _layer_filenames(layers: list[str]) -> dict[str, str]:
    """Layer label -> unique filename stem, warning on labels that collide.

    "Tier 1" and "Tier-1" both reduce to "tier_1", and the second sub-figure
    silently overwrote the first — three layers announced, two files on disk.
    """
    taken: dict[str, str] = {}
    stems: dict[str, str] = {}
    for layer in layers:
        base = _layer_filename(layer)
        stem = _dedupe(base, layer, taken)
        if stem != base:
            click.echo(
                f"WARNING: layer names '{taken[base]}' and '{layer}' both give "
                f"the filename '{base}'; writing the second as '{stem}'",
                err=True,
            )
        stems[layer] = stem
    return stems
