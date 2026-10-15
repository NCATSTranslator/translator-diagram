"""Tests for translator_diagram.dashboard_cli.

Mostly one question: which way round the privacy flag defaults. That is the
safety property of the whole filter — a forgotten flag must cost information
rather than publish it — and it lives in the CLI rather than in privacy.py, so
nothing in test_privacy.py can hold it in place.
"""

import json
import os
from pathlib import Path

import pytest
from click.testing import CliRunner

from translator_diagram import dashboard_cli
from translator_diagram.dashboard_cli import DEFAULT_COMPONENTS, build_main, sync_main


@pytest.fixture
def workspace(tmp_path):
    """A catalog, a sync cache and a policy, under tmp."""
    catalog = tmp_path / "catalog"
    components = catalog / "components"
    components.mkdir(parents=True)
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
    # owner-colors.csv lives only in catalog/, so a workspace without one
    # has no colours to find -- the same as any other checkout.
    (catalog / "owner-colors.csv").write_text("owner,color\nDOGSLED,#42A5F5\n")
    # A checkout has one of these too, and build-dashboard now refuses to
    # guess at the row order without it.
    (catalog / "flow-steps.yaml").write_text(
        "stages:\n"
        "  - title: Serving\n"
        "    description: Answers questions.\n"
        "    components: [keeper, secret]\n"
        "unplaced:\n"
        "  description: Nothing is unplaced.\n"
        "  components: []\n"
    )
    config = tmp_path / "config"
    config.mkdir()
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
                "--components", str(workspace / "catalog" / "components"),
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


class TestTheOutputIsOnlyThePage:
    def test_a_build_writes_the_page_and_its_payload_and_nothing_else(self, workspace):
        """What write_dashboard writes is pinned in test_dashboard.py. This
        pins that the command adds nothing of its own beside it, since the
        command is what the Pages workflow runs before uploading the whole
        directory."""
        result, _ = _run(workspace)
        assert result.exit_code == 0, result.output
        written = {p.relative_to(workspace / "out").as_posix()
                   for p in (workspace / "out").rglob("*")}
        assert written == {"index.html", "overview.json"}
        assert "not written by this build" not in result.output

    def test_a_build_names_what_it_found_there_and_did_not_write(self, workspace):
        """A leftover is served beside the page by a preview, so the build
        says so — and leaves it, since --output-dir can name any directory."""
        (workspace / "out" / "notes").mkdir(parents=True)
        (workspace / "out" / "notes" / "AGENTS.md").write_text("stale")
        result, _ = _run(workspace)
        assert result.exit_code == 0, result.output
        assert "not written by this build: notes/AGENTS.md." in result.output
        assert (workspace / "out" / "notes" / "AGENTS.md").exists()


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


class TestAMissingStageFileStopsTheBuild:
    def test_no_stages_and_no_walk_is_an_error(self, workspace):
        """The row order is a decision, not something to be derived. Without
        the file the page would silently show data-flow order instead."""
        (workspace / "catalog" / "flow-steps.yaml").unlink()
        result, _ = _run(workspace)
        assert result.exit_code != 0
        assert "No stage file" in result.output


class TestSyncReadsTheTokenFromDotEnv:
    """sync-components takes GITHUB_TOKEN from a .env, as generate-diagram
    takes GOOGLE_SHEET_ID. Without this, the GITHUB_TOKEN= line env.default
    offers would do nothing for the one command that sends it."""

    @pytest.fixture
    def token_seen(self, monkeypatch, workspace):
        # A copy of the environment, so whatever load_dotenv writes is gone
        # after the test rather than leaking a token into the next one.
        monkeypatch.setattr(os, "environ", dict(os.environ))
        os.environ.pop("GITHUB_TOKEN", None)
        seen = {}

        class Report:
            def to_dict(self):
                return {"counts": {"succeeded": 1, "attempted": 1, "cached": 0, "failed": 0}}

        def fake_sync(*args, **kwargs):
            seen["token"] = os.environ.get("GITHUB_TOKEN")
            return Report()

        monkeypatch.setattr(dashboard_cli, "sync", fake_sync)

        def run(dotenv):
            (workspace / ".env").write_text(dotenv)
            runner = CliRunner()
            with runner.isolated_filesystem(temp_dir=workspace):
                result = runner.invoke(sync_main, [
                    "--components", str(workspace / "catalog" / "components"),
                    "--output-dir", str(workspace / "sync"),
                ])
            assert result.exit_code == 0, result.output
            return seen["token"]

        return run

    def test_a_token_in_dotenv_reaches_the_fetches(self, token_seen):
        assert token_seen("GITHUB_TOKEN=from-the-file\n") == "from-the-file"

    def test_the_environment_wins_over_the_file(self, token_seen):
        # What keeps a CI runner's token in charge of a checkout that has a
        # .env lying about.
        os.environ["GITHUB_TOKEN"] = "from-the-environment"
        assert token_seen("GITHUB_TOKEN=from-the-file\n") == "from-the-environment"

    def test_the_empty_template_line_sends_no_token(self, token_seen):
        # env.default's `GITHUB_TOKEN=` copied as it is: an empty value, which
        # _headers treats as no token at all.
        assert not token_seen("GITHUB_TOKEN=\n")


def test_the_default_components_directory_is_the_catalogs():
    # Every other test here passes --components, so a default left pointing
    # at a directory that has moved would only surface when someone runs
    # sync-components or build-dashboard with no flags.
    root = Path(__file__).resolve().parent.parent
    assert list((root / DEFAULT_COMPONENTS).glob("*.yaml"))
