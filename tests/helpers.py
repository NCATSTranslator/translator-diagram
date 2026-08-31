"""Shared fixtures and builders for the test modules."""

import textwrap

from translator_diagram.colors import FALLBACK_COLORS, ColorAssigner
from translator_diagram.model import Component
from translator_diagram.render import build_graph

# The fields Component requires but most tests do not care about. Everything
# else is forwarded straight to Component, so a field this file has never
# heard of — hide, part_of, layer — reaches it, and a misspelled one raises
# TypeError instead of being silently dropped and passing the test vacuously.
_COMP_DEFAULTS = {
    "owner": "None",
    "itrb": "",
    "refactor_status": "Continues into Refactor",
    "notes": "",
}


def _comp(id_: str, **kwargs) -> Component:
    """Build a Component, defaulting the required fields tests rarely set."""
    return Component(id=id_, **{"name": id_, **_COMP_DEFAULTS, **kwargs})


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
