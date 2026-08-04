"""Tests for the pure functions in generate_diagram."""

import textwrap

import click
import pytest

from generate_diagram import (
    Component,
    ColorAssigner,
    FALLBACK_COLORS,
    _parse_bool,
    build_graph,
    index_by_id,
    load_components,
    load_owner_colors,
    parse_externals,
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
        ubiquitous=kwargs.get("ubiquitous", False),
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
            "owner,color\nzeta,#111111\nalpha,#222222\nbeta,#333333\n",
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

    @pytest.mark.parametrize("color", ["#fff", "red", "EF5350", "#GGGGGG", ""])
    def test_non_hex_color_raises_clickexception(self, tmp_path, color):
        # The file is hand-edited by non-Python folk; text_color_for needs six
        # hex digits and used to die with a raw ValueError traceback.
        path = tmp_path / "owner-colors.csv"
        path.write_text(f"owner,color\nNCATS,{color}\n", encoding="utf-8")
        with pytest.raises(click.ClickException, match="six-digit hex"):
            load_owner_colors(path)

    def test_default_file_loads(self):
        # The repo-shipped owner-colors.csv must always be loadable.
        result = load_owner_colors()
        assert "NCATS" in result
        assert result["NCATS"].startswith("#")


# --- _parse_bool -----------------------------------------------------------


class TestParseBool:
    @pytest.mark.parametrize("value", ["TRUE", "true", "True", "yes", "Y", "1"])
    def test_truthy_values(self, value):
        assert _parse_bool(value) is True

    @pytest.mark.parametrize("value", ["FALSE", "false", "no", "", "0", "  "])
    def test_falsy_values(self, value):
        assert _parse_bool(value) is False

    def test_strips_whitespace(self):
        assert _parse_bool("  TRUE  ") is True


# --- Ubiquitous column in load_components ----------------------------------


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


# --- parse_externals -------------------------------------------------------


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


# --- URL column ------------------------------------------------------------


URL_CSV_HEADER = "id,Name,Refactor status,URL\n"


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


# --- blank rows ------------------------------------------------------------


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


# --- SVG node attributes ---------------------------------------------------


def _source_for(components, **kwargs) -> str:
    colors = ColorAssigner({"None": "#E8E8E8"}, FALLBACK_COLORS)
    return build_graph(
        components, {"New in Refactor"}, "TB", colors, **kwargs
    ).source


class TestSvgNodeAttributes:
    def test_node_gets_a_stable_id_matching_its_component_id(self):
        # The Pages view addresses nodes by id, not graphviz's node1/node2.
        source = _source_for([_comp("ars", refactor_status="New in Refactor")])
        assert "id=ars" in source

    def test_url_becomes_a_graphviz_url_attribute(self):
        comp = _comp("ars", refactor_status="New in Refactor")
        comp.url = "https://example.org/ars"
        source = _source_for([comp])
        assert 'URL="https://example.org/ars"' in source
        assert "target=_blank" in source

    def test_no_url_attribute_when_the_column_is_empty(self):
        source = _source_for([_comp("ars", refactor_status="New in Refactor")])
        assert "URL=" not in source

    def test_tooltip_carries_owner_status_and_notes(self):
        comp = _comp(
            "ars",
            owner="NCATS",
            refactor_status="New in Refactor",
            notes="Runs the queries",
        )
        source = _source_for([comp])
        assert "Owner: NCATS" in source
        assert "Status: New in Refactor" in source
        assert "Runs the queries" in source


# --- edge styles -----------------------------------------------------------


class TestEdgeStyles:
    def test_implemented_call_suppresses_a_planned_call_to_the_same_target(self):
        # "Calls: b, ~b" is contradictory data. Draw the implemented edge only,
        # mirroring how depends_on outranks depends_on_planned — two dashed
        # edges between one pair merge under concentrate=true anyway.
        components = [
            _comp("a", refactor_status="New in Refactor",
                  uses=["b"], uses_planned=["b"]),
            _comp("b", refactor_status="New in Refactor"),
        ]
        edges = [ln for ln in _source_for(components).splitlines()
                 if "a -> b" in ln]
        assert len(edges) == 1
        assert "color=red" not in edges[0]

    def test_planned_call_renders_when_there_is_no_implemented_one(self):
        components = [
            _comp("a", refactor_status="New in Refactor", uses_planned=["b"]),
            _comp("b", refactor_status="New in Refactor"),
        ]
        edges = [ln for ln in _source_for(components).splitlines()
                 if "a -> b" in ln]
        assert len(edges) == 1
        assert "color=red" in edges[0]

    def test_solid_edge_suppresses_a_dashed_one_in_the_same_direction(self):
        # a gets results from b  → solid b -> a.
        # b calls a              → dashed b -> a, same direction, suppressed
        #                          so --concentrate can't merge away the solid.
        components = [
            _comp("a", refactor_status="New in Refactor", depends_on=["b"]),
            _comp("b", refactor_status="New in Refactor", uses=["a"]),
        ]
        edges = [ln for ln in _source_for(components).splitlines()
                 if "b -> a" in ln]
        assert len(edges) == 1
        assert "dashed" not in edges[0]
