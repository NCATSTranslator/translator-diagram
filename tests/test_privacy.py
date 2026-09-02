"""Withholding rows and fields from a build that will be published."""

import json
import pathlib

import click
import pytest

from translator_diagram.components import ComponentFile
from translator_diagram.dashboard import SyncedData, build_payload, build_rows
from translator_diagram.privacy import (
    Policy,
    Redaction,
    apply,
    load_policy,
    verify,
)


def _policy(components=(), fields=(), environment_fields=()):
    return Policy(
        components=tuple(Redaction(name) for name in components),
        fields=tuple(Redaction(name) for name in fields),
        environment_fields=tuple(Redaction(name) for name in environment_fields),
    )


def _rows():
    return [
        {
            "id": "keep",
            "helm_images": ["img:1"],
            "helm_version": "0.1.0",
            "environments": {"ci": {"deployed": True, "uptime": "pass"}},
        },
        {
            "id": "drop",
            "helm_images": ["img:2"],
            "helm_version": "0.2.0",
            "environments": {"ci": {"deployed": True, "uptime": "fail"}},
        },
    ]


class TestApply:
    def test_a_withheld_component_leaves_the_rows(self):
        kept, report = apply(_rows(), _policy(components=["drop"]))
        assert [row["id"] for row in kept] == ["keep"]
        assert report.components == ("drop",)

    def test_a_withheld_field_is_emptied_not_deleted(self):
        """overview.json's shape is a contract: a null reads as "not
        available", a missing key breaks whoever is parsing it."""
        kept, _ = apply(_rows(), _policy(fields=["helm_images", "helm_version"]))
        assert kept[0]["helm_images"] == []
        assert kept[0]["helm_version"] is None
        assert "helm_images" in kept[0] and "helm_version" in kept[0]

    def test_environment_fields_are_emptied_in_every_cell(self):
        kept, report = apply(_rows(), _policy(environment_fields=["uptime"]))
        assert kept[0]["environments"]["ci"]["uptime"] is None
        assert report.environment_fields == ("uptime",)

    def test_a_cell_reading_its_version_from_a_withheld_field_loses_it(self):
        """Emptying `helm_version` on the row is not enough: the number it
        supplied is also sitting in the table with a Helm badge on it."""
        rows = [
            {
                "id": "keep",
                "helm_images": [],
                "helm_version": "0.1.0",
                "environments": {
                    "ci": {
                        "deployed": True,
                        "version": "0.1.0",
                        "version_source": "helm",
                        "uptime": "pass",
                    },
                    "prod": {
                        "deployed": True,
                        "version": "2.0.0",
                        "version_source": "openapi",
                        "uptime": "pass",
                    },
                },
            }
        ]
        kept, _ = apply(rows, _policy(fields=["helm_version"]))
        ci = kept[0]["environments"]["ci"]
        assert ci["version"] is None and ci["version_source"] is None
        # A version read from somewhere else is untouched.
        assert kept[0]["environments"]["prod"]["version"] == "2.0.0"

    def test_nothing_happens_under_an_empty_policy(self):
        kept, report = apply(_rows(), Policy())
        assert [row["id"] for row in kept] == ["keep", "drop"]
        assert not report


class TestThePolicyMustStillMatchTheData:
    """The failure this module exists to avoid is withholding nothing.

    A renamed component, or a renamed payload key, would leave the policy
    pointing at something that no longer exists — and the next publish would
    quietly include what it was meant to hold back.
    """

    def test_an_unknown_component_id_is_an_error(self):
        with pytest.raises(click.ClickException, match="do not exist"):
            apply(_rows(), _policy(components=["renamed-away"]))

    def test_an_unknown_field_is_an_error(self):
        with pytest.raises(click.ClickException, match="no row has"):
            apply(_rows(), _policy(fields=["helm_imagez"]))

    def test_an_unknown_environment_field_is_an_error(self):
        with pytest.raises(click.ClickException, match="no cell has"):
            apply(_rows(), _policy(environment_fields=["uptimes"]))


class TestLoading:
    def test_a_policy_round_trips(self, tmp_path):
        path = tmp_path / "privacy.yaml"
        path.write_text(
            "components:\n"
            "  - id: jaeger\n"
            "    reason: The tracing console.\n"
            "fields:\n"
            "  - name: helm_images\n"
            "environment_fields: []\n"
        )
        policy = load_policy(path)
        assert policy.component_ids == ("jaeger",)
        assert policy.components[0].reason == "The tracing console."
        assert policy.field_names == ("helm_images",)

    def test_a_missing_file_is_an_error_not_an_empty_policy(self, tmp_path):
        """The whole point of defaulting to redaction: "no policy found" must
        stop a publishing build, never produce a full-fidelity one."""
        with pytest.raises(click.ClickException, match="not found"):
            load_policy(tmp_path / "absent.yaml")

    def test_a_mistyped_section_is_an_error(self, tmp_path):
        """The one way a policy can withhold nothing with every other check
        passing: `component:` parses, yields no entries, and there is then
        nothing left for `apply` or `verify` to object to."""
        path = tmp_path / "privacy.yaml"
        path.write_text("component:\n  - id: jaeger\n    reason: singular\n")
        with pytest.raises(click.ClickException, match="unknown section"):
            load_policy(path)

    def test_an_entry_without_a_name_is_an_error(self, tmp_path):
        path = tmp_path / "privacy.yaml"
        path.write_text("fields:\n  - reason: forgot the name\n")
        with pytest.raises(click.ClickException, match="needs a `name`"):
            load_policy(path)

    def test_the_repositorys_own_policy_is_valid(self):
        """config/privacy.yaml parses, and says why for everything it holds."""
        policy = load_policy()
        assert policy.component_ids
        assert all(item.reason for item in policy.components)
        assert all(item.reason for item in policy.fields)


class TestInThePayload:
    """The reason the filter is applied where it is."""

    @pytest.fixture
    def components(self):
        return [
            ComponentFile(
                id=cid,
                name=cid,
                owner="DOGSLED",
                refactor_status="New in Refactor",
            )
            for cid in ("alpha", "hidden", "omega")
        ]

    @pytest.fixture
    def synced(self, tmp_path):
        (tmp_path / "manifest.json").write_text(
            json.dumps({"finished_at": "2026-09-01T00:00:00+00:00", "counts": {}})
        )
        return SyncedData(tmp_path)

    def test_the_tiles_cannot_disagree_with_the_table(self, components, synced):
        """source_tally and unregistered_count are computed from the rows the
        policy left behind, not from the rows before it ran."""
        payload = build_payload(components, synced, _policy(components=["hidden"]))
        assert [row["id"] for row in payload["rows"]] == ["alpha", "omega"]
        cells = [
            cell
            for row in payload["rows"]
            for cell in row["environments"].values()
            if cell.get("deployed")
        ]
        assert sum(payload["source_tally"].values()) == len(cells)

    def test_a_published_build_is_the_full_build_minus_rows(
        self, components, synced
    ):
        """Depths and order come from the whole platform, so a withheld
        component cannot move the components that remain."""
        full = build_payload(components, synced)
        held = build_payload(components, synced, _policy(components=["hidden"]))
        kept = {row["id"]: row for row in full["rows"] if row["id"] != "hidden"}
        assert [row["id"] for row in held["rows"]] == list(kept)
        for row in held["rows"]:
            assert row["depth"] == kept[row["id"]]["depth"]
            assert row["step"] == kept[row["id"]]["step"]

    def test_the_payload_says_something_was_withheld(self, components, synced):
        payload = build_payload(
            components, synced, _policy(components=["hidden"], fields=["notes"])
        )
        assert payload["redacted"] == {
            "components": 1,
            "fields": ["notes"],
            "environment_fields": [],
        }

    def test_a_full_build_carries_no_redaction_block(self, components, synced):
        assert "redacted" not in build_payload(components, synced)
        assert "redacted" not in build_payload(components, synced, Policy())

    def test_the_withheld_row_is_gone_from_the_json_entirely(
        self, components, synced
    ):
        """Not hidden by CSS, not filtered in the browser: absent from the
        payload, which is what the page inlines and what Pages serves."""
        payload = build_payload(components, synced, _policy(components=["hidden"]))
        assert "hidden" not in json.dumps(payload)


class TestVerify:
    """The check that does not depend on knowing the payload's shape."""

    def test_a_clean_payload_passes(self):
        kept, _ = apply(_rows(), _policy(components=["drop"], fields=["helm_images"]))
        verify({"rows": kept}, _policy(components=["drop"], fields=["helm_images"]))

    def test_a_withheld_id_surviving_anywhere_is_caught(self):
        """The case `apply` cannot see: a field added later that mentions a
        withheld component by id, in a row that was itself kept."""
        payload = {"rows": [{"id": "keep", "referenced_by": ["drop"]}]}
        with pytest.raises(click.ClickException, match="still appear"):
            verify(payload, _policy(components=["drop"]))

    def test_a_short_id_inside_a_longer_word_is_not_a_leak(self):
        """The false alarm that would make the check unrunnable: withholding
        `ars` must not fail a build over the `ars` in `parsers`, and the only
        way to clear a false alarm is to stop checking."""
        payload = {"rows": [{"id": "keep", "notes": "Two parsers and a guide."}]}
        verify(payload, _policy(components=["ars"]))
        verify(payload, _policy(components=["ui"]))

    def test_a_short_id_as_a_word_still_is(self):
        """Every shape a stray reference actually takes: a hostname, a path
        segment, a list entry, a sentence."""
        for value in ("https://ars.transltr.io/", "/ars/status", "the ars is down"):
            with pytest.raises(click.ClickException, match="still appear"):
                verify({"rows": [{"id": "keep", "notes": value}]},
                       _policy(components=["ars"]))

    def test_a_hyphenated_id_is_found_whole(self):
        payload = {"rows": [{"id": "keep", "referenced_by": ["test-harness"]}]}
        with pytest.raises(click.ClickException, match="still appear"):
            verify(payload, _policy(components=["test-harness"]))

    def test_a_field_that_survived_emptying_is_caught(self):
        payload = {"rows": [{"id": "keep", "helm_version": "0.1.0"}]}
        with pytest.raises(click.ClickException, match="still set on row"):
            verify(payload, _policy(fields=["helm_version"]))

    def test_an_environment_field_that_survived_is_caught(self):
        payload = {
            "rows": [{"id": "keep", "environments": {"ci": {"uptime": "pass"}}}]
        }
        with pytest.raises(click.ClickException, match="still set on"):
            verify(payload, _policy(environment_fields=["uptime"]))

    def test_the_real_public_build_verifies(self):
        """What `build-dashboard` does before it writes, on real data."""
        from translator_diagram.components import load_components
        from translator_diagram.dashboard import SyncedData

        sync_dir = pathlib.Path("data/sync")
        if not (sync_dir / "manifest.json").exists():
            pytest.skip("no local sync; run sync-components")
        policy = load_policy()
        payload = build_payload(
            load_components(pathlib.Path("components")), SyncedData(sync_dir), policy
        )
        verify(payload, policy)


def test_build_rows_is_unchanged_by_the_policy_argument(tmp_path):
    """build_rows itself never redacts — the filter sits above it, so every
    existing test of row-building keeps testing the whole platform."""
    (tmp_path / "manifest.json").write_text(json.dumps({"counts": {}}))
    components = [
        ComponentFile(
            id="one",
            name="one",
            owner="DOGSLED",
            refactor_status="New in Refactor",
        )
    ]
    rows = build_rows(components, SyncedData(tmp_path))
    assert [row["id"] for row in rows] == ["one"]
