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
UNKNOWN_PATH = ROOT / "unknown.yaml"
UNKNOWN_SCHEMA_PATH = ROOT / "schema" / "unknown.schema.json"
ENRICHED_EXAMPLE_PATH = ROOT / "docs" / "examples" / "name-lookup-enriched.yaml"

COMPONENT_FILES = sorted(COMPONENTS_DIR.glob("*.yaml"))


def _load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def unknown() -> dict:
    return _load(UNKNOWN_PATH)


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
            connections = data.get("connections") or {}
            refs = connections.get("gets_results_from", []) + connections.get(
                "calls", []
            )
            for ref in refs:
                target = ref.lstrip("~")
                assert target in known, f"{cid} references unknown id {target!r}"

    def test_no_component_references_itself(self, components):
        for cid, data in components.items():
            connections = data.get("connections") or {}
            refs = connections.get("gets_results_from", []) + connections.get(
                "calls", []
            )
            assert cid not in {r.lstrip("~") for r in refs}


class TestDiagram:
    # `connections:` keeps its empty lists, because `gets_results_from: []`
    # is a claim -- checked, there are none -- under the same absent-vs-null
    # convention as the rest of the format. A `diagram:` flag at its default
    # claims nothing the schema does not already say, so it should not be
    # written at all. All 26 files carried `ubiquitous: false` and
    # `hide: false` before that distinction was drawn.
    DEFAULTS = {"ubiquitous": False, "hide": False}

    def test_no_file_writes_a_flag_at_its_default(self, components):
        for cid, data in components.items():
            diagram = data.get("diagram") or {}
            for flag, default in self.DEFAULTS.items():
                if flag not in diagram:
                    continue
                assert diagram[flag] != default, (
                    f"{cid} writes diagram.{flag}: {default}, which is the "
                    f"schema default -- omit it, and omit diagram: entirely "
                    f"once it is empty"
                )

    def test_a_present_block_says_something(self, components):
        for cid, data in components.items():
            if "diagram" in data:
                assert data["diagram"], f"{cid} has an empty diagram: block"


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


class TestUnknown:
    """unknown.yaml — the holding pen for identifiers no component claims."""

    def test_validates(self, unknown):
        schema = json.loads(UNKNOWN_SCHEMA_PATH.read_text(encoding="utf-8"))
        jsonschema.Draft202012Validator.check_schema(schema)
        errors = sorted(
            jsonschema.Draft202012Validator(schema).iter_errors(unknown),
            key=lambda e: list(e.path),
        )
        assert not errors, "\n".join(
            f"unknown.yaml: {'/'.join(str(p) for p in e.path)}: {e.message}"
            for e in errors
        )

    def test_otel_names_are_claimed_once(self, components, unknown):
        # An identifier claimed in two places is worse than one claimed
        # nowhere: the second claim is invisible, and whichever consumer reads
        # first wins.
        owners: dict[str, str] = {}
        for cid, data in components.items():
            for name in (data.get("identifiers") or {}).get("otel_services") or []:
                assert name not in owners, (
                    f"OTel service {name!r} claimed by both {owners[name]} and {cid}"
                )
                owners[name] = cid
        for entry in unknown.get("otel_services") or []:
            name = entry["name"]
            assert name not in owners, (
                f"OTel service {name!r} is in unknown.yaml but is already "
                f"claimed by components/{owners[name]}.yaml — promote it by "
                f"deleting the unknown.yaml entry"
            )
            owners[name] = "unknown.yaml"

    def test_not_recorded_entries_really_have_no_file(self, components, unknown):
        # `not-recorded` means "a component we know of that has no file yet".
        # Once the file exists the entry is stale and should have been
        # promoted, so this fails rather than letting it rot.
        for entry in unknown.get("otel_services") or []:
            if entry["status"] != "not-recorded":
                continue
            assert entry["component"] not in components, (
                f"unknown.yaml: {entry['name']!r} is marked not-recorded but "
                f"components/{entry['component']}.yaml exists — move the name "
                f"into that file's identifiers.otel_services"
            )


class TestEnrichedExample:
    def test_recorded_block_matches_the_component_file(self):
        # The example's whole argument is that `pulled:` comes from `recorded:`
        # and nothing else. If the two drift, it argues for a file that does
        # not exist — which is how it went wrong once already, when
        # name-lookup gained otel_services and the example did not.
        example = _load(ENRICHED_EXAMPLE_PATH)["recorded"]
        component = _load(COMPONENTS_DIR / "name-lookup.yaml")
        assert example == component, (
            "docs/examples/name-lookup-enriched.yaml's `recorded:` block is no "
            "longer components/name-lookup.yaml verbatim"
        )
