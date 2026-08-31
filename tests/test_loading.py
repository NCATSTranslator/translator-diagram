"""Tests for translator_diagram.loading — cell parsing and CSV loading."""

import click
import pytest

from translator_diagram.colors import load_owner_colors
from tests.helpers import CSV_FIXTURE, URL_CSV_HEADER, _comp
from translator_diagram.loading import _parse_bool, _valid_url, load_components, parse_externals, parse_id_list
from translator_diagram.model import Component
from translator_diagram.validation import validate


class TestParseIdList:
    def test_empty(self):
        assert parse_id_list("") == ([], [])

    def test_single_implemented(self):
        assert parse_id_list("foo") == (["foo"], [])

    def test_single_planned(self):
        assert parse_id_list("~foo") == ([], ["foo"])

    def test_mixed(self):
        assert parse_id_list("foo, ~bar, baz") == (["foo", "baz"], ["bar"])

    def test_strips_whitespace(self):
        assert parse_id_list("  foo  ,  ~ bar  ") == (["foo"], ["bar"])

    def test_skips_empty_entries(self):
        assert parse_id_list("foo,,bar,") == (["foo", "bar"], [])

    def test_tilde_followed_by_space(self):
        assert parse_id_list("~ foo") == ([], ["foo"])


class TestParseBool:
    @pytest.mark.parametrize("value", ["TRUE", "true", "True", "yes", "Y", "1"])
    def test_truthy_values(self, value):
        assert _parse_bool(value) is True

    @pytest.mark.parametrize("value", ["FALSE", "false", "no", "", "0", "  "])
    def test_falsy_values(self, value):
        assert _parse_bool(value) is False

    def test_strips_whitespace(self):
        assert _parse_bool("  TRUE  ") is True


class TestParseExternals:
    def test_empty(self):
        assert parse_externals("") == []
        assert parse_externals("   ") == []

    def test_source_and_sink(self):
        assert parse_externals("<Upstream, >User") == [
            ("in", "Upstream"),
            ("out", "User"),
        ]

    def test_quoted_name_containing_a_comma(self):
        # The column is parsed as CSV so a name may contain a comma if quoted.
        assert parse_externals('"<Upstream, service", >Researcher') == [
            ("in", "Upstream, service"),
            ("out", "Researcher"),
        ]

    def test_strips_whitespace_around_prefix_and_name(self):
        assert parse_externals("  <  DB  ") == [("in", "DB")]

    def test_undirected_token_is_dropped_with_a_warning(self, capsys):
        # A missing '<' or '>' is a typo in the sheet; dropping it silently
        # would just make the node vanish.
        assert parse_externals("User, >Sink", "comp-a") == [("out", "Sink")]
        err = capsys.readouterr().err
        assert "external 'User'" in err
        assert "comp-a" in err


class TestLoadComponents:
    def test_parses_csv_and_sorts_by_id(self, tmp_path):
        csv_path = tmp_path / "components.csv"
        csv_path.write_text(CSV_FIXTURE, encoding="utf-8")
        components = load_components(csv_path)
        assert [c.id for c in components] == ["aaa", "bbb"]
        assert components[0].name == "Alpha"
        assert components[0].refactor_status == "New in Refactor"
        assert components[1].depends_on == ["aaa"]
        assert components[1].uses_planned == ["ccc"]

    def test_tolerates_utf8_bom(self, tmp_path):
        # An Excel resave can prepend a UTF-8 BOM. With plain utf-8 the
        # first header would become "﻿id" and KeyError on c.id.
        csv_path = tmp_path / "components.csv"
        csv_path.write_bytes("﻿".encode("utf-8") + CSV_FIXTURE.encode("utf-8"))
        components = load_components(csv_path)
        assert components[0].id == "aaa"

    def test_empty_owner_becomes_none(self, tmp_path):
        csv_path = tmp_path / "components.csv"
        csv_path.write_text(
            "id,Name,Owner,Component in ITRB,Refactor status,"
            "Gets results from,Calls,Notes\n"
            "x,Ex,,,New in Refactor,,,\n",
            encoding="utf-8",
        )
        components = load_components(csv_path)
        assert components[0].owner == "None"

    def test_reads_url_column(self, tmp_path):
        csv_path = tmp_path / "components.csv"
        csv_path.write_text(
            "id,Name,URL,Refactor status\n"
            "x,Ex, https://example.org/x ,New in Refactor\n",
            encoding="utf-8",
        )
        assert load_components(csv_path)[0].url == "https://example.org/x"

    def test_missing_url_column_defaults_to_empty(self, tmp_path):
        # CSV_FIXTURE has no URL column — older exports of the sheet won't.
        csv_path = tmp_path / "components.csv"
        csv_path.write_text(CSV_FIXTURE, encoding="utf-8")
        assert all(c.url == "" for c in load_components(csv_path))


class TestUbiquitousColumn:
    def test_ubiquitous_column_parsed(self, tmp_path):
        csv_path = tmp_path / "components.csv"
        csv_path.write_text(
            "id,Name,Owner,Component in ITRB,Refactor status,"
            "Gets results from,Calls,Ubiquitous,Notes\n"
            "jaeger,Jaeger,DOGSLED,obs,Continues into Refactor,,,TRUE,\n"
            "ars,ARS,NCATS,svc,New in Refactor,,,,\n",
            encoding="utf-8",
        )
        components = load_components(csv_path)
        by_id = {c.id: c for c in components}
        assert by_id["jaeger"].ubiquitous is True
        assert by_id["ars"].ubiquitous is False

    def test_missing_ubiquitous_column_defaults_false(self, tmp_path):
        # Older sheets without the column should still parse cleanly.
        csv_path = tmp_path / "components.csv"
        csv_path.write_text(
            "id,Name,Owner,Component in ITRB,Refactor status,"
            "Gets results from,Calls,Notes\n"
            "foo,Foo,NCATS,svc,New in Refactor,,,\n",
            encoding="utf-8",
        )
        components = load_components(csv_path)
        assert components[0].ubiquitous is False

    def test_dataclass_default_is_false(self):
        assert _comp("foo").ubiquitous is False


class TestUrlValidation:
    def test_http_and_https_pass_through(self, tmp_path):
        csv_path = tmp_path / "components.csv"
        csv_path.write_text(
            URL_CSV_HEADER
            + "a,A,New in Refactor,http://example.org/a\n"
            + "b,B,New in Refactor,https://example.org/b\n",
            encoding="utf-8",
        )
        assert [c.url for c in load_components(csv_path)] == [
            "http://example.org/a",
            "https://example.org/b",
        ]

    def test_javascript_url_is_dropped_with_a_warning(self, tmp_path, capsys):
        # The Pages view inlines the SVG, so a javascript: href would be live
        # on a public page.
        csv_path = tmp_path / "components.csv"
        csv_path.write_text(
            URL_CSV_HEADER + "a,A,New in Refactor,javascript:alert(1)\n",
            encoding="utf-8",
        )
        assert load_components(csv_path)[0].url == ""
        assert "not http(s)" in capsys.readouterr().err

    def test_uppercase_scheme_is_accepted(self):
        assert _valid_url("HTTPS://example.org", "a") == "HTTPS://example.org"

    def test_javascript_url_is_dropped(self):
        assert _valid_url("javascript:alert(1)", "a") == ""


class TestBlankRows:
    def test_rows_without_an_id_are_skipped(self, tmp_path):
        # Spacer and trailing rows in the sheet export as empty rows. Keeping
        # them yielded an unnamed node, or "duplicate id: '' and ''" for two.
        csv_path = tmp_path / "components.csv"
        csv_path.write_text(
            "id,Name,Refactor status\n"
            ",,\n"
            ",,\n"
            "x,X,New in Refactor\n",
            encoding="utf-8",
        )
        components = load_components(csv_path)
        assert [c.id for c in components] == ["x"]
        assert validate(components) is True

    def test_blank_spacer_rows_are_skipped_quietly(self, tmp_path, capsys):
        csv_path = tmp_path / "components.csv"
        csv_path.write_text(
            "id,Name,Refactor status\n,,\nx,X,New in Refactor\n",
            encoding="utf-8",
        )
        load_components(csv_path)
        assert capsys.readouterr().err == ""

    def test_a_row_with_data_but_no_id_warns(self, tmp_path, capsys):
        # That one is a typo, not a spacer — skipping it silently would make
        # the component vanish from the diagram with no explanation.
        csv_path = tmp_path / "components.csv"
        csv_path.write_text(
            "id,Name,Refactor status\n,Forgotten,New in Refactor\n",
            encoding="utf-8",
        )
        assert load_components(csv_path) == []
        assert "Forgotten" in capsys.readouterr().err


class TestShortCsvRows:
    def test_row_missing_trailing_fields_parses(self, tmp_path):
        # csv.DictReader defaults absent trailing fields to None, not "".
        csv_path = tmp_path / "components.csv"
        csv_path.write_text("id,Name,Owner,Refactor status,Notes\na\n")
        comps = load_components(csv_path)
        assert [c.id for c in comps] == ["a"]
        assert comps[0].name == ""
        assert comps[0].owner == "None"

    def test_owner_colors_row_missing_the_colour_reports_it(self, tmp_path):
        path = tmp_path / "owner-colors.csv"
        path.write_text("owner,color\nRENCI\n")
        with pytest.raises(click.ClickException, match="not\n?\\s*a six-digit hex"):
            load_owner_colors(path)


class TestMissingIdColumn:
    def test_a_csv_without_an_id_column_is_an_error(self, tmp_path):
        # The wrong --sheet-gid returns a real CSV from the wrong tab, and
        # every row was then skipped as id-less, leaving a blank diagram.
        csv_path = tmp_path / "components.csv"
        csv_path.write_text("Name,Owner\nARS,NCATS\n", encoding="utf-8")
        with pytest.raises(click.ClickException, match="no 'id' column"):
            load_components(csv_path)

    def test_an_empty_file_is_an_error(self, tmp_path):
        csv_path = tmp_path / "components.csv"
        csv_path.write_text("", encoding="utf-8")
        with pytest.raises(click.ClickException, match="no columns at all"):
            load_components(csv_path)
