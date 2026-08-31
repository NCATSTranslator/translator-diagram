"""Reference and id checks run before anything is drawn."""

import click

from .model import Component, index_by_id
from .naming import _clone_svg_id, _svg_id, external_svg_ids


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

    # Everything the SVG can carry an id for shares one namespace: component
    # nodes, the per-caller clones of ubiquitous components, external-entity
    # nodes, and the "a_"-prefixed <g> graphviz wraps around each of them (they
    # all carry a tooltip). Two of those claiming one id is a duplicate XML id,
    # and getElementById then silently returns whichever graphviz emitted
    # first — so this is a hard error, like the duplicate ids above.
    claimed: dict[str, str] = {}

    def claim(svg_id: str, what: str) -> bool:
        nonlocal ok
        first = claimed.setdefault(svg_id, what)
        if first == what:
            return True
        click.echo(
            f"ERROR: {first} and {what} both become the SVG id "
            f"'{svg_id}'; make them differ by more than punctuation",
            err=True,
        )
        ok = False
        return False

    def claim_node(svg_id: str, what: str) -> None:
        # Graphviz wraps every node carrying a tooltip or URL in
        # <g id="a_{node id}">, so claiming "foo" also spoken for is "a_foo" —
        # exactly what a component named "A Foo" sanitises to. The wrapper is
        # claimed only if the node id itself was free, so one collision is
        # reported once rather than twice.
        if claim(svg_id, what):
            claim(f"a_{svg_id}", f"the <a> wrapper around {what}")

    # Hidden components are skipped: nothing is emitted for them, so an id
    # they would have claimed is free, and flagging it would block a run over
    # a collision that never reaches the SVG.
    for comp in components:
        if not comp.hide:
            claim_node(_svg_id(comp.id), f"component '{comp.id}'")
    for comp in components:
        if comp.hide or comp.ubiquitous:
            # Ubiquitous components never call out from a node of their own.
            continue
        for ref in comp.all_refs():
            match = index.get(ref.lower())
            if match is not None and match.ubiquitous and not match.hide:
                claim_node(
                    _clone_svg_id(comp.id, match.id),
                    f"the '{match.id}' clone beside '{comp.id}'",
                )
    for name, ext_id in external_svg_ids(components).items():
        claim_node(ext_id, f"external '{name}'")

    # Free-text labels get the same treatment, but only as a warning: they are
    # kept as separate clusters/nodes (the later one takes a _2 suffix), which
    # is the right outcome if they really are two things and a legible symptom
    # if one is a typo. Warned here rather than in _unique_svg_id, which runs
    # again for every layer sub-figure.
    for kind, labels in (
        ("Part of", [c.part_of for c in components]),
        ("Externals", [n for c in components for _, n in c.externals]),
    ):
        by_label_id: dict[str, str] = {}
        for label in dict.fromkeys(labels):
            if not label:
                continue
            clash = by_label_id.setdefault(_svg_id(label), label)
            if clash != label:
                click.echo(
                    f"WARNING: {kind} names '{clash}' and '{label}' differ only "
                    f"in punctuation; keeping both, but check for a typo",
                    err=True,
                )

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
