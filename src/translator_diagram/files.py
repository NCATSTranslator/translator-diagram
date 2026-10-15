"""The filesystem both commands share: finding a hand-edited file from any
working directory, and reading JSON or YAML that may be missing or malformed.

A leaf: it imports nothing else in the package, so anything may use it. The
readers were in `components.py`, which `fetch.py` imported for nothing else.
"""

import json
from pathlib import Path
from typing import Any

import yaml

# libyaml's loader where it is installed: the infores catalog alone takes
# 0.14 s through the pure-Python one and 0.02 s through it.
_YAML_LOADER = getattr(yaml, "CSafeLoader", yaml.SafeLoader)


def find_upward(relative: Path, start: Path | None = None) -> Path | None:
    """`relative` in `start` (the working directory by default) or the nearest
    directory above it, or None.

    How `catalog/owner-colors.csv`, `catalog/flow-steps.yaml` and
    `config/privacy.yaml` are found, so a command run from a subdirectory of
    the checkout behaves the same way as one run from its root. The `.env`
    lookup (`find_dotenv(usecwd=True)`) walks the parents too, and this keeps
    the two in step: without it, running from a subdirectory took the sheet ID
    from the repo's `.env` and the colours from the packaged copy.
    """
    start = Path.cwd() if start is None else start
    for directory in (start, *start.parents):
        candidate = directory / relative
        if candidate.exists():
            return candidate
    return None


def read_json(path: Path) -> Any:
    """A cached JSON body, or None when it is missing or is not JSON.

    Shared by `sync` and the dashboard, which both read the sync cache. Several
    Translator endpoints answer 200 with an HTML error page and a throttled
    GitHub call answers with an object where a list was asked for, so callers
    still check the shape they get back.
    """
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None


def read_yaml(path: Path) -> dict[str, Any] | None:
    """A YAML mapping, or None when it is missing, malformed or not a mapping."""
    try:
        loaded = yaml.load(path.read_text(encoding="utf-8"), Loader=_YAML_LOADER)
    except (OSError, yaml.YAMLError, UnicodeDecodeError):
        return None
    return loaded if isinstance(loaded, dict) else None
