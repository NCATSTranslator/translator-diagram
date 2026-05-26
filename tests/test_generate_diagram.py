"""Tests for the pure functions in generate_diagram."""

import textwrap

import click
import pytest

from generate_diagram import (
    Component,
    ColorAssigner,
    FALLBACK_COLORS,
    index_by_id,
    load_components,
    load_owner_colors,
    parse_id_list,
    text_color_for,
    validate,
)


# --- parse_id_list ---------------------------------------------------------


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


# --- ColorAssigner ---------------------------------------------------------


class TestColorAssigner:
    def test_known_owner_returns_base_color(self):
        base = {"FooTeam": "#ABCDEF", "BarTeam": "#012345"}
        ca = ColorAssigner(base, FALLBACK_COLORS)
        assert ca.get("FooTeam") == "#ABCDEF"
        assert ca.get("BarTeam") == "#012345"

    def test_unknown_owner_gets_first_fallback(self):
        ca = ColorAssigner({}, FALLBACK_COLORS)
        assert ca.get("MysteryTeam") == FALLBACK_COLORS[0]

    def test_unknown_owners_rotate_through_fallback_palette(self):
        ca = ColorAssigner({}, FALLBACK_COLORS)
        assigned = [ca.get(f"team{i}") for i in range(len(FALLBACK_COLORS) + 2)]
        # First N pick palette in order, then wrap around.
        assert assigned[: len(FALLBACK_COLORS)] == FALLBACK_COLORS
        assert assigned[len(FALLBACK_COLORS)] == FALLBACK_COLORS[0]
        assert assigned[len(FALLBACK_COLORS) + 1] == FALLBACK_COLORS[1]

    def test_same_unknown_owner_keeps_same_color(self):
        ca = ColorAssigner({}, FALLBACK_COLORS)
        first = ca.get("teamA")
        _ = ca.get("teamB")
        assert ca.get("teamA") == first

    def test_state_does_not_leak_between_instances(self):
        # Regression: a previous version used a module-level _color_index
        # global, which leaked state across runs.
        ca1 = ColorAssigner({}, FALLBACK_COLORS)
        _ = ca1.get("teamA")
        _ = ca1.get("teamB")
        ca2 = ColorAssigner({}, FALLBACK_COLORS)
        assert ca2.get("teamC") == FALLBACK_COLORS[0]


# --- text_color_for --------------------------------------------------------


class TestTextColorFor:
    def test_pure_white_picks_black(self):
        assert text_color_for("#FFFFFF") == "black"

    def test_pure_black_picks_white(self):
        assert text_color_for("#000000") == "white"

    def test_light_yellow_picks_black(self):
        # D4E157 (lime) is very light
        assert text_color_for("#D4E157") == "black"

    def test_dark_brown_picks_white(self):
        # 8D6E63 (brown) is moderately dark
        assert text_color_for("#8D6E63") == "white"

    def test_accepts_hex_without_hash(self):
        assert text_color_for("FFFFFF") == "black"


# --- index_by_id -----------------------------------------------------------


def _comp(id_: str, **kwargs) -> Component:
    """Build a Component with sensible defaults for the optional fields."""
    return Component(
        id=id_,
        name=kwargs.get("name", id_),
        owner=kwargs.get("owner", "None"),
        itrb=kwargs.get("itrb", ""),
        refactor_status=kwargs.get("refactor_status", "Continues into Refactor"),
        notes=kwargs.get("notes", ""),
        depends_on=kwargs.get("depends_on", []),
        depends_on_planned=kwargs.get("depends_on_planned", []),
        uses=kwargs.get("uses", []),
        uses_planned=kwargs.get("uses_planned", []),
    )


class TestIndexById:
    def test_lookup_is_case_insensitive(self):
        index = index_by_id([_comp("Foo"), _comp("bar")])
        assert index["foo"].id == "Foo"
        assert index["bar"].id == "bar"

    def test_missing_returns_none(self):
        index = index_by_id([_comp("foo")])
        assert index.get("nope") is None


# --- validate --------------------------------------------------------------


class TestValidate:
    def test_clean_input_returns_true(self):
        components = [
            _comp("a", depends_on=["b"]),
            _comp("b"),
        ]
        assert validate(components) is True

    def test_unknown_ref_is_hard_error(self, capsys):
        components = [_comp("a", depends_on=["ghost"])]
        assert validate(components) is False
        assert "unknown id 'ghost'" in capsys.readouterr().err

    def test_unknown_planned_ref_is_hard_error(self):
        components = [_comp("a", depends_on_planned=["ghost"])]
        assert validate(components) is False

    def test_duplicate_id_is_hard_error(self, capsys):
        components = [_comp("foo"), _comp("foo")]
        assert validate(components) is False
        assert "duplicate id" in capsys.readouterr().err

    def test_case_insensitive_duplicate_is_hard_error(self):
        components = [_comp("Foo"), _comp("foo")]
        assert validate(components) is False

    def test_case_mismatch_is_warning_not_error(self, capsys):
        # case-mismatch is informational only — build_graph resolves
        # case-insensitively. The return must stay True.
        components = [
            _comp("foo"),
            _comp("a", depends_on=["FOO"]),
        ]
        assert validate(components) is True
        assert "case mismatch" in capsys.readouterr().err


# --- Component -------------------------------------------------------------


class TestComponent:
    def test_display_name_falls_back_to_id_when_name_empty(self):
        c = _comp("foo", name="")
        assert c.display_name == "foo"

    def test_display_name_uses_name_when_present(self):
        c = _comp("foo", name="Foo Service")
        assert c.display_name == "Foo Service"

    def test_all_refs_concatenates_all_four_lists(self):
        c = _comp(
            "x",
            depends_on=["a"],
            depends_on_planned=["b"],
            uses=["c"],
            uses_planned=["d"],
        )
        assert c.all_refs() == ["a", "b", "c", "d"]


# --- load_components -------------------------------------------------------


CSV_FIXTURE = textwrap.dedent("""\
    id,Name,Owner,Component in ITRB,Refactor status,Gets results from,Calls,Notes
    bbb,Beta,DOGSLED,cat,Continues into Refactor,aaa,~ccc,
    aaa,Alpha,NCATS,cat,New in Refactor,,,first note
""")


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


# --- load_owner_colors -----------------------------------------------------


class TestLoadOwnerColors:
    def test_parses_owner_color_csv(self, tmp_path):
        path = tmp_path / "owner-colors.csv"
        path.write_text(
            "owner,color\nNCATS,#EF5350\nUI,#EC407A\n",
            encoding="utf-8",
        )
        assert load_owner_colors(path) == {
            "NCATS": "#EF5350",
            "UI": "#EC407A",
        }

    def test_preserves_row_order(self, tmp_path):
        path = tmp_path / "owner-colors.csv"
        path.write_text(
            "owner,color\nzeta,#111\nalpha,#222\nbeta,#333\n",
            encoding="utf-8",
        )
        # Order matters for legend layout — must match CSV order, not sorted.
        assert list(load_owner_colors(path)) == ["zeta", "alpha", "beta"]

    def test_strips_whitespace(self, tmp_path):
        path = tmp_path / "owner-colors.csv"
        path.write_text(
            "owner,color\n  NCATS  ,  #EF5350  \n",
            encoding="utf-8",
        )
        assert load_owner_colors(path) == {"NCATS": "#EF5350"}

    def test_missing_file_raises_clickexception(self, tmp_path):
        with pytest.raises(click.ClickException, match="not found"):
            load_owner_colors(tmp_path / "missing.csv")

    def test_missing_column_raises_clickexception(self, tmp_path):
        path = tmp_path / "owner-colors.csv"
        path.write_text("owner,hue\nNCATS,red\n", encoding="utf-8")
        with pytest.raises(click.ClickException, match="missing required columns"):
            load_owner_colors(path)

    def test_default_file_loads(self):
        # The repo-shipped owner-colors.csv must always be loadable.
        result = load_owner_colors()
        assert "NCATS" in result
        assert result["NCATS"].startswith("#")
