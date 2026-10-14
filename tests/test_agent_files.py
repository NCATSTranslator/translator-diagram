"""The agent notes are AGENTS.md files, and a CLAUDE.md anywhere would hide them.

Claude Code reads AGENTS.md natively (from v2.1.277; every session type
from v2.1.281), but only while there is no CLAUDE.md: one in the working
directory or above it switches it to reading CLAUDE.md files alone, and one
in a subdirectory stops that directory's AGENTS.md loading. So a CLAUDE.md
added anywhere in the repository -- even a one-line `@AGENTS.md`, the usual
bridge, which is what the root one was -- would silently drop notes from
every session that starts there. See
https://code.claude.com/docs/en/memory#agents-md.
"""

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _tracked(name: str) -> list[str]:
    """Every committed or staged file with this basename, at any depth."""
    out = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard",
         name, f"**/{name}"],
        cwd=ROOT, capture_output=True, text=True, check=True,
    ).stdout
    return sorted(set(out.split()))


def test_no_claude_md_anywhere():
    # CLAUDE.local.md counts too: the docs list it beside CLAUDE.md and
    # .claude/CLAUDE.md (which "**/CLAUDE.md" already matches) as the files
    # whose presence turns AGENTS.md off.
    assert _tracked("CLAUDE.md") + _tracked("CLAUDE.local.md") == [], (
        "a CLAUDE.md stops Claude Code reading the AGENTS.md files: "
        "put the notes in AGENTS.md instead"
    )


def test_the_agent_notes_are_where_agents_md_says():
    # Guards the test above against checking nothing: if git ls-files stopped
    # matching, both lists would be empty and the first test would pass.
    assert _tracked("AGENTS.md") == [
        "AGENTS.md",
        "catalog/AGENTS.md",
        "src/translator_diagram/AGENTS.md",
        "src/translator_diagram/web/AGENTS.md",
    ]
