"""The components/*.yaml files, and the schema they must satisfy.

These files do not feed the generator yet — loading.py still reads the sheet
CSV. The checks here are what stops them drifting into a second, wrong source
of truth in the meantime.
"""

import csv
import json
from pathlib import Path

import jsonschema
import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
COMPONENTS_DIR = ROOT / "components"
SCHEMA_PATH = ROOT / "schema" / "component.schema.json"

COMPONENT_FILES = sorted(COMPONENTS_DIR.glob("*.yaml"))


def _load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def components() -> dict[str, dict]:
    return {path.stem: _load(path) for path in COMPONENT_FILES}


def test_there_are_components():
    # A glob that quietly matches nothing would make every test below pass.
    assert COMPONENT_FILES, f"no *.yaml under {COMPONENTS_DIR}"


class TestSchema:
    def test_schema_is_itself_valid(self, schema):
        jsonschema.Draft202012Validator.check_schema(schema)

    @pytest.mark.parametrize("path", COMPONENT_FILES, ids=lambda p: p.stem)
    def test_file_validates(self, path, schema):
        errors = sorted(
            jsonschema.Draft202012Validator(schema).iter_errors(_load(path)),
            key=lambda e: list(e.path),
        )
        assert not errors, "\n".join(
            f"{path.name}: {'/'.join(str(p) for p in e.path) or '<root>'}: {e.message}"
            for e in errors
        )


class TestIdentity:
    @pytest.mark.parametrize("path", COMPONENT_FILES, ids=lambda p: p.stem)
    def test_id_matches_filename(self, path):
        # The filename is how a human finds the file and how every reference
        # resolves; letting the two drift would give one component two names.
        assert _load(path)["id"] == path.stem

    def test_ids_are_unique_case_insensitively(self, components):
        # validation.validate matches references case-insensitively, and a
        # case-insensitive filesystem cannot hold both spellings anyway.
        seen: dict[str, str] = {}
        for cid in components:
            clash = seen.setdefault(cid.lower(), cid)
            assert clash == cid, f"{cid} and {clash} differ only by case"


class TestReferences:
    def test_every_reference_has_a_file(self, components):
        # The file set must be closed: the generator hard-errors on an unknown
        # id, and a referenced-but-filtered component still needs a file so it
        # can be drawn as a ghost node.
        known = set(components)
        for cid, data in components.items():
            diagram = data["diagram"]
            refs = diagram.get("gets_results_from", []) + diagram.get("calls", [])
            for ref in refs:
                target = ref.lstrip("~")
                assert target in known, f"{cid} references unknown id {target!r}"

    def test_no_component_references_itself(self, components):
        for cid, data in components.items():
            diagram = data["diagram"]
            refs = diagram.get("gets_results_from", []) + diagram.get("calls", [])
            assert cid not in {r.lstrip("~") for r in refs}


class TestOwners:
    def test_every_owner_has_a_colour(self, components):
        # A new owner arriving without a colour would silently take a fallback
        # from the palette, and the legend would stop matching the sheet.
        with (ROOT / "config" / "owner-colors.csv").open(encoding="utf-8-sig") as f:
            known = {row["owner"] for row in csv.DictReader(f)}
        for cid, data in components.items():
            assert data["owner"] in known, (
                f"{cid}: owner {data['owner']!r} is not in config/owner-colors.csv"
            )


class TestEndpoints:
    @pytest.mark.parametrize("path", COMPONENT_FILES, ids=lambda p: p.stem)
    def test_endpoint_paths_are_relative(self, path):
        # `endpoints` are joined onto an environment's base URL. An absolute
        # URL here would silently win over the base and pin every environment
        # to whichever one it happened to name.
        for kind, value in (_load(path).get("endpoints") or {}).items():
            if value is None:
                continue
            assert not value.startswith(("http://", "https://", "/")), (
                f"{path.name}: endpoints.{kind} must be relative, got {value!r}"
            )
