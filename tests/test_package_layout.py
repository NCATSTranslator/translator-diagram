"""The import direction from AGENTS.md, enforced rather than described.

Nine modules only stay nine modules if imports keep running one way. A wrong
turn — legend reaching back into render, say — still works at runtime right up
until it doesn't, and by then the layering exists only in prose.

ruff cannot express this: flake8-tidy-imports bans an API everywhere, not
per-module, so it can say "nobody imports cli" but not "colors imports
nothing". Twenty lines of ast does say it.
"""

import ast
from pathlib import Path

import pytest

PACKAGE = Path(__file__).resolve().parent.parent / "src" / "translator_diagram"

# Each module, and the package modules it is allowed to import. Adding an entry
# is a deliberate act: test_the_layering_is_acyclic below still has to pass, so
# this cannot be widened into a cycle to make a failure go away.
ALLOWED = {
    "model": set(),
    "colors": set(),
    "naming": {"model"},
    "loading": {"model"},
    "validation": {"model", "naming"},
    "export": {"model", "naming"},
    "legend": {"colors"},
    "render": {"colors", "legend", "model", "naming"},
    "cli": {
        "colors", "export", "legend", "loading",
        "model", "naming", "render", "validation",
    },
    # The dashboard side. It shares colors with the diagram — owners are one
    # palette across both — but nothing else: components.py parses the YAML
    # files, model.py parses the sheet, and neither knows about the other.
    "components": set(),
    "flow": {"components"},
    "sync": {"components"},
    # privacy is a leaf: it filters plain dictionaries, so it needs to know
    # nothing about where they came from, and dashboard can apply it without
    # anything in the graph moving.
    "privacy": set(),
    "dashboard": {"colors", "components", "flow", "privacy"},
    "dashboard_cli": {"components", "dashboard", "flow", "privacy", "sync"},
}

# Neither entry point may be imported: a module that pulls in a CLI drags
# click's option parsing into a library import path.
ENTRY_POINTS = {"cli", "dashboard_cli"}


def _package_imports(module: str) -> set[str]:
    """The package modules `module` imports, however it spells the import."""
    tree = ast.parse((PACKAGE / f"{module}.py").read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.level and node.module:            # from .naming import ...
                found.add(node.module.split(".")[0])
            elif node.module == "translator_diagram":  # from translator_diagram import x
                found.update(a.name for a in node.names)
            elif node.module and node.module.startswith("translator_diagram."):
                found.add(node.module.split(".")[1])
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("translator_diagram."):
                    found.add(alias.name.split(".")[1])
    return found - {module}


def test_every_module_is_accounted_for():
    # A new module must be placed in the layering, not left outside it.
    on_disk = {p.stem for p in PACKAGE.glob("*.py")} - {"__init__"}
    assert on_disk == set(ALLOWED)


@pytest.mark.parametrize("module", sorted(ALLOWED))
def test_imports_run_in_the_recorded_direction(module):
    stray = _package_imports(module) - ALLOWED[module]
    assert not stray, (
        f"{module}.py imports {sorted(stray)}, which the layering in AGENTS.md "
        f"does not allow. Move the shared code down the graph rather than "
        f"widening ALLOWED — that is how colors.py came to hold the palette "
        f"constants that render and legend both need."
    )


def test_the_layering_is_acyclic():
    # Guards the map itself: widening ALLOWED to silence the test above must
    # not be able to introduce a cycle.
    reachable = {m: set(deps) for m, deps in ALLOWED.items()}
    for _ in range(len(ALLOWED)):
        for deps in reachable.values():
            deps |= {d for dep in list(deps) for d in reachable[dep]}
    cyclic = sorted(m for m, deps in reachable.items() if m in deps)
    assert not cyclic, f"these modules can reach themselves: {cyclic}"


def test_nothing_imports_an_entry_point():
    # The CLIs sit on top: they wire the others together, and importing one
    # from below would drag click's command object into a library module.
    # Both are checked, not just cli.py — an exemption for the second would
    # make the rule advice rather than a guarantee.
    offenders = {
        module: sorted(_package_imports(module) & ENTRY_POINTS)
        for module in ALLOWED
        if _package_imports(module) & ENTRY_POINTS
    }
    assert not offenders, f"{offenders} import an entry point, which sits on top"
