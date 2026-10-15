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


# --- The sync cache's layout -------------------------------------------------
#
# Every file `sync-components` writes under `data/sync/`, named in one place so
# the code that writes a file and the code that reads it back cannot disagree
# about where it is. `tests/test_files.py` pins the literal layout; nothing
# else spells it out.

MANIFEST = "manifest.json"
SMARTAPI = "smartapi.json"
DERIVED = "derived.json"
INFORES_CATALOG = "infores_catalog.yaml"
HELM_INDEX = "helm/index.json"

# The per-deployment files, in the order `cells._probe_statuses` walks them:
# the root probe of the deployment URL itself, then the two documents.
PROBE_KINDS = ("root", "openapi", "status")


def manifest_path(root: Path) -> Path:
    """Every attempt this run made, failed ones included."""
    return root / MANIFEST


def smartapi_path(root: Path) -> Path:
    """The SmartAPI registry's answer, as it came back."""
    return root / SMARTAPI


def derived_path(root: Path) -> Path:
    """The conventional hostnames probed: confirmed and rejected, with verdicts."""
    return root / DERIVED


def infores_catalog_path(root: Path) -> Path:
    return root / INFORES_CATALOG


def helm_index_path(root: Path) -> Path:
    """The translator-devops `helm/` directory listing."""
    return root / HELM_INDEX


def endpoint_key(kind: str, component_id: str, env: str) -> str:
    """The manifest's `path` for one deployment's root probe or document.

    The one relative-string form: endpoints and root probes are looked up in
    the manifest by this key (the 200 gate), where everything else is reached
    by path alone.
    """
    return f"{kind}/{component_id}/{env}.json"


def endpoint_path(root: Path, kind: str, component_id: str, env: str) -> Path:
    return root / endpoint_key(kind, component_id, env)


def otel_path(root: Path, env: str) -> Path:
    """One OpenTelemetry collector's service list."""
    return root / "otel" / f"{env}.json"


def releases_path(root: Path, repo: str) -> Path:
    """One source repository's GitHub releases; `repo` is `owner/name`."""
    return root / "releases" / f"{repo}.json"


def repo_meta_path(root: Path, repo: str) -> Path:
    """One source repository's own GitHub document; `repo` is `owner/name`."""
    return root / "repos" / f"{repo}.json"


def helm_file_path(root: Path, chart: str, name: str) -> Path:
    """One file out of one chart: `Chart.yaml`, `values.yaml` or the images list."""
    return root / "helm" / chart / name


def chart_commit_path(root: Path, chart: str) -> Path:
    """The last commit touching one chart's directory."""
    return root / "helm" / chart / "commit.json"
