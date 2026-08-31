"""Shared fixtures and builders for the test modules."""

import textwrap

from translator_diagram.colors import ColorAssigner, FALLBACK_COLORS
from translator_diagram.model import Component
from translator_diagram.render import build_graph


def _comp(id_: str, **kwargs) -> Component:
    """Build a Component with sensible defaults for the optional fields."""
    return Component(
        id=id_,
        name=kwargs.get("name", id_),
        owner=kwargs.get("owner", "None"),
        itrb=kwargs.get("itrb", ""),
        refactor_status=kwargs.get("refactor_status", "Continues into Refactor"),
        notes=kwargs.get("notes", ""),
        ubiquitous=kwargs.get("ubiquitous", False),
        depends_on=kwargs.get("depends_on", []),
        depends_on_planned=kwargs.get("depends_on_planned", []),
        uses=kwargs.get("uses", []),
        uses_planned=kwargs.get("uses_planned", []),
    )


def _source_for(components, **kwargs) -> str:
    colors = ColorAssigner({"None": "#E8E8E8"}, FALLBACK_COLORS)
    return build_graph(
        components, {"New in Refactor"}, "TB", colors, **kwargs
    ).source


CSV_FIXTURE = textwrap.dedent("""\
    id,Name,Owner,Component in ITRB,Refactor status,Gets results from,Calls,Notes
    bbb,Beta,DOGSLED,cat,Continues into Refactor,aaa,~ccc,
    aaa,Alpha,NCATS,cat,New in Refactor,,,first note
""")


URL_CSV_HEADER = "id,Name,Refactor status,URL\n"
