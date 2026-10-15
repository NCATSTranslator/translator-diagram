"""The agent notes are AGENTS.md files, and a CLAUDE.md anywhere would hide them.

Claude Code reads AGENTS.md natively (from v2.1.277; every session type
from v2.1.281), but only while there is no CLAUDE.md: one in the working
directory or above it switches it to reading CLAUDE.md files alone, and one
in a subdirectory stops that directory's AGENTS.md loading. So a CLAUDE.md
added anywhere in the repository -- even a one-line `@AGENTS.md`, the usual
bridge, which is what the root one was -- would silently drop notes from
every session that starts there. See
https://code.claude.com/docs/en/memory#agents-md.

These tests walk the checkout on disk rather than asking git. The file most
likely to turn up is a personal CLAUDE.local.md, and that is usually
gitignored, which `git ls-files --exclude-standard` would hide; a walk also
needs no git at all, so it runs from a ZIP download.
"""

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Not this repository's notes: data/ is scratch space that holds clones of
# other repositories, and .venv/ holds installed packages.
SKIPPED = {ROOT / "data", ROOT / ".venv", ROOT / ".git"}


def _found(name: str) -> list[str]:
    """Every file with this basename in the checkout, as a POSIX path from ROOT.

    Committed, untracked and ignored files all count, because Claude Code
    reads whatever is on disk. Directories in SKIPPED are left out, and so is
    any directory holding its own .git: a nested clone or a worktree is
    another checkout, whose notes are its own.
    """
    found = []
    for dirpath, dirnames, filenames in os.walk(ROOT):
        here = Path(dirpath)
        dirnames[:] = [
            d for d in dirnames
            if here / d not in SKIPPED and not (here / d / ".git").exists()
        ]
        if name in filenames:
            found.append((here / name).relative_to(ROOT).as_posix())
    return sorted(found)


def test_no_claude_md_anywhere():
    # CLAUDE.local.md counts too: the docs list it beside CLAUDE.md and
    # .claude/CLAUDE.md (which the walk already finds) as the files whose
    # presence turns AGENTS.md off.
    assert _found("CLAUDE.md") + _found("CLAUDE.local.md") == [], (
        "a CLAUDE.md stops Claude Code reading the AGENTS.md files: "
        "put the notes in AGENTS.md instead"
    )


def test_the_walk_finds_the_agent_notes():
    # Guards the test above against checking nothing: if the walk stopped
    # finding files, both lists would be empty and that test would pass. Only
    # the root file is required, so a new per-directory AGENTS.md needs no
    # change here.
    assert "AGENTS.md" in _found("AGENTS.md")
