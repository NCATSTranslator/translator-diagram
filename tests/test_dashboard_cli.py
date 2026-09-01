"""Tests for translator_diagram.dashboard_cli.

Mostly one question: which way round the privacy flag defaults. That is the
safety property of the whole filter — a forgotten flag must cost information
rather than publish it — and it lives in the CLI rather than in privacy.py, so
nothing in test_privacy.py can hold it in place.
"""

import json

import pytest
from click.testing import CliRunner

from translator_diagram.dashboard_cli import build_main


@pytest.fixture
def workspace(tmp_path):
    """A components directory, a sync cache, a policy and colours, under tmp."""
    components = tmp_path / "components"
    components.mkdir()
    for cid in ("keeper", "secret"):
        (components / f"{cid}.yaml").write_text(
            f"id: {cid}\n"
            f"name: {cid}\n"
            "owner: DOGSLED\n"
            "environments:\n"
            "  ci:\n"
            "    url: https://example.invalid/\n"
            "refactor_status: New in Refactor\n"
        )
    sync = tmp_path / "sync"
    sync.mkdir()
    (sync / "manifest.json").write_text(
        json.dumps({"finished_at": "2026-09-01T00:00:00+00:00", "counts": {}})
    )
    config = tmp_path / "config"
    config.mkdir()
    # owner-colors.csv lives only in config/ now, so a workspace without one
    # has no colours to find -- the same as any other checkout.
    (config / "owner-colors.csv").write_text("owner,color\nDOGSLED,#42A5F5\n")
    (config / "privacy.yaml").write_text(
        "components:\n"
        "  - id: secret\n"
        "    reason: Not for publication.\n"
        "fields:\n"
        "  - name: notes\n"
        "    reason: Free text.\n"
    )
    return tmp_path


def _run(workspace, *args):
    """Run build-dashboard from inside the workspace, so the policy is found
    by the same upward walk the real command uses."""
    runner = CliRunner()
    # Runs from a scratch directory inside the workspace, so load_policy's
    # upward walk finds workspace/config/privacy.yaml and nothing above it.
    with runner.isolated_filesystem(temp_dir=workspace):
        result = runner.invoke(
            build_main,
            [
                "--components", str(workspace / "components"),
                "--sync-dir", str(workspace / "sync"),
                "--output-dir", str(workspace / "out"),
                *args,
            ],
        )
    payload_path = workspace / "out" / "overview.json"
    payload = json.loads(payload_path.read_text()) if payload_path.exists() else None
    return result, payload


class TestTheFlagDefaultsToWithholding:
    def test_a_plain_build_applies_the_policy(self, workspace):
        result, payload = _run(workspace)
        assert result.exit_code == 0, result.output
        assert [row["id"] for row in payload["rows"]] == ["keeper"]
        assert payload["redacted"]["components"] == 1
        assert "secret" not in json.dumps(payload)

    def test_include_private_builds_everything(self, workspace):
        result, payload = _run(workspace, "--include-private")
        assert result.exit_code == 0, result.output
        assert [row["id"] for row in payload["rows"]] == ["keeper", "secret"]
        assert "redacted" not in payload

    def test_a_full_build_says_it_must_not_be_published(self, workspace):
        """The only warning a local operator gets before emailing the file on."""
        result, _ = _run(workspace, "--include-private")
        assert "Do not publish" in result.output

    def test_a_withholding_build_names_what_it_withheld(self, workspace):
        result, _ = _run(workspace)
        assert "Withheld 1 components (secret)" in result.output


class TestAMissingPolicyStopsTheBuild:
    def test_no_policy_and_no_flag_is_an_error(self, workspace):
        """Not an empty policy. "Cannot find the file" must never be the path
        that produces a publishable-looking full build."""
        (workspace / "config" / "privacy.yaml").unlink()
        result, _ = _run(workspace)
        assert result.exit_code != 0
        assert "No privacy policy" in result.output

    def test_no_policy_is_fine_with_the_flag(self, workspace):
        (workspace / "config" / "privacy.yaml").unlink()
        result, payload = _run(workspace, "--include-private")
        assert result.exit_code == 0, result.output
        assert len(payload["rows"]) == 2
