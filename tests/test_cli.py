"""Tests for translator_diagram.cli."""

import os
import urllib.error

import graphviz
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


class TestOwnerColorsFlag:
    def test_the_flag_reaches_the_rendered_graph(self, tmp_path, monkeypatch):
        # The resolution order is unit-tested in test_colors.py; this covers
        # the wiring from the option to ColorAssigner, which is the part a
        # refactor breaks silently. graphviz.Digraph.render is stubbed so the
        # test needs no dot binary — the .dot is written before rendering.
        monkeypatch.setattr(graphviz.Digraph, "render", lambda self, **kw: "")
        csv_path = tmp_path / "components.csv"
        csv_path.write_text(
            "id,Name,Owner,Refactor status\nars,ARS,NCATS,New in Refactor\n",
            encoding="utf-8",
        )
        colors = tmp_path / "mine.csv"
        colors.write_text("owner,color\nNCATS,#010203\n", encoding="utf-8")
        out = tmp_path / "out"
        result = CliRunner().invoke(main, [
            "--input", str(csv_path),
            "--output-dir", str(out),
            "--owner-colors", str(colors),
        ])
        assert result.exit_code == 0, result.output
        assert "#010203" in (out / "diagram.dot").read_text()

    def test_a_missing_file_is_rejected_by_click(self, tmp_path):
        csv_path = tmp_path / "components.csv"
        csv_path.write_text("id,Name\nars,ARS\n", encoding="utf-8")
        result = CliRunner().invoke(main, [
            "--input", str(csv_path),
            "--output-dir", str(tmp_path / "out"),
            "--owner-colors", str(tmp_path / "nope.csv"),
        ])
        assert result.exit_code != 0
        assert "nope.csv" in result.output
