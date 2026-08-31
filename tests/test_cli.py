"""Tests for translator_diagram.cli."""

import os
import urllib.error

import pytest
from click.testing import CliRunner

from translator_diagram import loading
from translator_diagram.cli import main


class TestGoogleSheetEnv:
    @pytest.fixture(autouse=True)
    def _no_sheet_id_in_the_environment(self):
        # load_dotenv writes straight into os.environ and won't override a key
        # that is already there, so the variable has to start out absent.
        before = os.environ.pop("GOOGLE_SHEET_ID", None)
        yield
        os.environ.pop("GOOGLE_SHEET_ID", None)
        if before is not None:
            os.environ["GOOGLE_SHEET_ID"] = before

    def test_dotenv_in_the_working_directory_wins(self, tmp_path, monkeypatch):
        # A bare load_dotenv() resolves relative to generate_diagram.py, so it
        # read the repo's .env — and its sheet id — for anyone running the tool
        # from a directory with a .env of their own.
        (tmp_path / ".env").write_text("GOOGLE_SHEET_ID=from_cwd\n", encoding="utf-8")
        monkeypatch.chdir(tmp_path)
        requested = []

        def fake_urlopen(url, timeout=None):
            requested.append(url)
            raise urllib.error.URLError("no network in tests")

        monkeypatch.setattr(
            loading.urllib.request, "urlopen", fake_urlopen
        )
        result = CliRunner().invoke(
            main, ["--google-sheet", "--output-dir", str(tmp_path / "out")]
        )
        assert result.exit_code != 0
        assert requested and "/from_cwd/export" in requested[0]

    def test_the_sheet_id_stays_out_of_the_error_message(self, tmp_path, monkeypatch):
        (tmp_path / ".env").write_text("GOOGLE_SHEET_ID=from_cwd\n", encoding="utf-8")
        monkeypatch.chdir(tmp_path)

        def fake_urlopen(url, timeout=None):
            raise urllib.error.URLError("no network in tests")

        monkeypatch.setattr(
            loading.urllib.request, "urlopen", fake_urlopen
        )
        result = CliRunner().invoke(
            main, ["--google-sheet", "--output-dir", str(tmp_path / "out")]
        )
        assert "from_cwd" not in result.output
