"""Tests for generate_diagram.

Grouped by subject, in rough pipeline order: parsing a cell, loading a
CSV, validating it, building the graph, writing the output files, and the
CLI on top. Put a new test with the others on its subject rather than at
the end — git log is where the chronology lives.
"""

import json
import os
import textwrap
import urllib.error

import click
import pytest
from click.testing import CliRunner

import generate_diagram
from generate_diagram import (
    Component,
    ColorAssigner,
    FALLBACK_COLORS,
    _layer_filenames,
    _parse_bool,
    _svg_id,
    _unique_svg_id,
    _valid_url,
    build_graph,
    external_svg_ids,
    index_by_id,
    load_components,
    load_owner_colors,
    main,
    parse_externals,
    parse_id_list,
    text_color_for,
    validate,
    write_json,
)


# --- Shared helpers ---------------------------------------------------------


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


def _source_for(components, **kwargs) -> str:
    colors = ColorAssigner({"None": "#E8E8E8"}, FALLBACK_COLORS)
    return build_graph(
        components, {"New in Refactor"}, "TB", colors, **kwargs
    ).source


CSV_FIXTURE = textwrap.dedent("""\
    id,Name,Owner,Component in ITRB,Refactor status,Gets results from,Calls,Notes
    bbb,Beta,DOGSLED,cat,Continues into Refactor,aaa,~ccc,
    aaa,Alpha,NCATS,cat,New in Refactor,,,first note
""")


URL_CSV_HEADER = "id,Name,Refactor status,URL\n"


# --- Cell parsing -----------------------------------------------------------


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


# --- Owner colours ----------------------------------------------------------


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


# --- Component and lookup ---------------------------------------------------


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


class TestIndexById:
    def test_lookup_is_case_insensitive(self):
        index = index_by_id([_comp("Foo"), _comp("bar")])
        assert index["foo"].id == "Foo"
        assert index["bar"].id == "bar"

    def test_missing_returns_none(self):
        index = index_by_id([_comp("foo")])
        assert index.get("nope") is None


# --- Loading the CSV --------------------------------------------------------


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


# --- Validation -------------------------------------------------------------


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


class TestLabelCollisionWarnings:
    def test_part_of_labels_differing_only_in_punctuation_warn(self, capsys):
        a, b = _comp("a"), _comp("b")
        a.part_of, b.part_of = "Core Bits", "Core/Bits"
        # A warning, not an error — both groups are still drawn.
        assert validate([a, b]) is True
        assert "Part of names 'Core Bits' and 'Core/Bits'" in capsys.readouterr().err

    def test_external_names_differing_only_in_punctuation_warn(self, capsys):
        a = _comp("a")
        a.externals = [("in", "User agent"), ("out", "User/agent")]
        assert validate([a]) is True
        assert "Externals names" in capsys.readouterr().err

    def test_the_same_label_on_two_components_does_not_warn(self, capsys):
        a, b = _comp("a"), _comp("b")
        a.part_of = b.part_of = "Core Bits"
        a.externals = b.externals = [("in", "User")]
        assert validate([a, b]) is True
        assert capsys.readouterr().err == ""


# --- SVG ids ----------------------------------------------------------------


class TestSvgIds:
    def test_punctuated_id_becomes_a_valid_xml_id(self):
        assert _svg_id("ARS 2.0") == "ars_2_0"

    def test_leading_digit_is_prefixed(self):
        # XML IDs may not start with a digit, so getElementById would fail.
        assert _svg_id("2fast").startswith("n_")

    def test_node_id_attribute_is_sanitised(self):
        source = _source_for([_comp("ARS 2.0", refactor_status="New in Refactor")])
        assert "id=ars_2_0" in source

    def test_ids_differing_only_in_punctuation_are_an_error(self, capsys):
        assert validate([_comp("ARS 2.0"), _comp("ARS/2/0")]) is False
        assert "SVG id" in capsys.readouterr().err

    def test_unique_svg_id_separates_colliding_labels(self):
        taken: dict[str, str] = {}
        assert _unique_svg_id("User agent", taken) == "user_agent"
        assert _unique_svg_id("User/agent", taken) == "user_agent_2"
        # Re-asking for one already assigned returns the same id.
        assert _unique_svg_id("User agent", taken) == "user_agent"


def _ubiquitous_pair():
    """A caller, a ubiquitous target, and a component whose id collides.

    "ARS" calling ubiquitous "LOG" used to clone into the SVG id "ars_log",
    which is also what the separate component "ARS LOG" sanitises to.
    """
    return [
        _comp("ARS", refactor_status="New in Refactor", uses=["LOG"]),
        _comp("ARS LOG", refactor_status="New in Refactor"),
        _comp("LOG", refactor_status="New in Refactor", ubiquitous=True),
    ]


class TestSvgIdNamespace:
    def test_clone_id_does_not_collide_with_a_component_id(self):
        source = _source_for(_ubiquitous_pair())
        assert "id=ars__log" in source
        assert "id=ars_log" in source
        assert validate(_ubiquitous_pair()) is True

    def test_a_component_claiming_another_ones_anchor_id_is_an_error(self, capsys):
        # Graphviz wraps a tooltip-carrying node in <g id="a_{node id}">, so
        # "A Foo" would claim the wrapper graphviz emits around "Foo".
        assert validate([_comp("Foo"), _comp("A Foo")]) is False
        err = capsys.readouterr().err
        assert "a_foo" in err
        # Reported once, not once for the node and again for its wrapper.
        assert err.count("ERROR") == 1

    def test_an_external_colliding_with_a_clone_is_an_error(self, capsys):
        # Component "ext" calling ubiquitous "log" clones into "ext__log",
        # which is also the id of an external entity named "log".
        zz = _comp("zz", refactor_status="New in Refactor")
        zz.externals = [("in", "log")]
        components = [
            _comp("ext", refactor_status="New in Refactor", uses=["log"]),
            _comp("log", refactor_status="New in Refactor", ubiquitous=True),
            zz,
        ]
        assert validate(components) is False
        assert "ext__log" in capsys.readouterr().err

    def test_hidden_components_do_not_claim_an_id(self):
        # Nothing is emitted for a hidden row, so its id is free.
        hidden = _comp("ARS/2/0")
        hidden.hide = True
        assert validate([_comp("ARS 2.0"), hidden]) is True

    def test_external_ids_are_stable_across_the_status_filter(self):
        # The layer sub-figures and the main diagram must agree on them.
        a = _comp("a", refactor_status="New in Refactor")
        a.externals = [("in", "User")]
        b = _comp("b", refactor_status="Removed after Refactor")
        b.externals = [("out", "User")]
        assert external_svg_ids([a, b])["User"] == "ext__user"


# --- Graph output -----------------------------------------------------------


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


class TestExternalNodes:
    def test_a_name_used_both_ways_emits_one_node(self):
        a = _comp("a", refactor_status="New in Refactor")
        a.externals = [("in", "User")]
        b = _comp("b", refactor_status="New in Refactor")
        b.externals = [("out", "User")]
        source = _source_for([a, b])
        # One node declaration, and no rank constraint at all — rank=min and
        # rank=max on the same node contradict each other.
        lines = source.splitlines()
        assert len([ln for ln in lines
                    if "ext__user" in ln and "label=User" in ln]) == 1
        ranked = {lines[i + 1].strip() for i, ln in enumerate(lines)
                  if ln.strip() in ("rank=min", "rank=max")}
        assert "ext__user" not in ranked

    def test_names_that_sanitise_alike_stay_separate(self):
        a = _comp("a", refactor_status="New in Refactor")
        a.externals = [("in", "User agent"), ("in", "User/agent")]
        source = _source_for([a])
        assert "ext__user_agent " in source or "ext__user_agent\t" in source
        assert "ext__user_agent_2" in source


class TestUbiquitousFiltering:
    def test_excluded_ubiquitous_target_is_not_rendered(self):
        u = _comp("u", refactor_status="Removed in Refactor", ubiquitous=True)
        a = _comp("a", refactor_status="New in Refactor", uses=["u"])
        source = _source_for([a, u])
        assert "a__u" not in source


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

    def test_solid_suppresses_dashed_when_the_target_sorts_last(self):
        # Mirror of the test above with the ids swapped: the solid edge is
        # registered by z, which the iteration reaches after a.
        components = [
            _comp("a", refactor_status="New in Refactor", uses=["z"]),
            _comp("z", refactor_status="New in Refactor", depends_on=["a"]),
        ]
        edges = [ln for ln in _source_for(components).splitlines()
                 if "a -> z" in ln]
        assert len(edges) == 1
        assert "dashed" not in edges[0]


# --- components.json and per-layer filenames --------------------------------


class TestComponentsJson:
    def _written(self, tmp_path, components):
        out = tmp_path / "components.json"
        write_json(components, out)
        return json.loads(out.read_text(encoding="utf-8"))

    def test_ubiquitous_node_ids_list_the_clones_that_exist(self, tmp_path):
        # A ubiquitous component has no central node, so a single node_id
        # pointed at an element getElementById would never find.
        components = [
            _comp("ARA", refactor_status="New in Refactor", uses=["LOG"]),
            _comp("ARS", refactor_status="New in Refactor", uses=["LOG"]),
            _comp("LOG", refactor_status="New in Refactor", ubiquitous=True),
        ]
        by_id = {c["id"]: c for c in self._written(tmp_path, components)}
        assert by_id["LOG"]["node_ids"] == ["ara__log", "ars__log"]
        assert by_id["ARS"]["node_ids"] == ["ars"]
        source = _source_for(components)
        for node_id in by_id["LOG"]["node_ids"]:
            assert f"id={node_id}" in source

    def test_an_unreferenced_ubiquitous_component_lists_no_nodes(self, tmp_path):
        components = [_comp("LOG", ubiquitous=True)]
        assert self._written(tmp_path, components)[0]["node_ids"] == []

    def test_hidden_components_are_not_exported(self, tmp_path):
        # components.json is what the public Pages view fetches, and a hidden
        # row carries its Notes verbatim.
        hidden = _comp("secret", notes="do not publish")
        hidden.hide = True
        exported = self._written(tmp_path, [_comp("ars"), hidden])
        assert [c["id"] for c in exported] == ["ars"]
        assert "do not publish" not in json.dumps(exported)

    def test_a_clone_of_a_hidden_component_is_not_listed(self, tmp_path):
        hidden = _comp("log", ubiquitous=True)
        hidden.hide = True
        components = [_comp("ars", uses=["log"]), hidden]
        assert [c["id"] for c in self._written(tmp_path, components)] == ["ars"]


class TestLayerFilenames:
    def test_labels_that_reduce_to_one_stem_get_separate_files(self, capsys):
        stems = _layer_filenames(["Tier 1", "Tier-1", "Tier 2"])
        assert stems == {"Tier 1": "tier_1", "Tier-1": "tier_1_2", "Tier 2": "tier_2"}
        assert "both give the filename 'tier_1'" in capsys.readouterr().err

    def test_distinct_labels_are_left_alone(self, capsys):
        assert _layer_filenames(["Tier 1", "Tier 2"]) == {
            "Tier 1": "tier_1", "Tier 2": "tier_2",
        }
        assert capsys.readouterr().err == ""


# --- The CLI ----------------------------------------------------------------


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
            generate_diagram.urllib.request, "urlopen", fake_urlopen
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
            generate_diagram.urllib.request, "urlopen", fake_urlopen
        )
        result = CliRunner().invoke(
            main, ["--google-sheet", "--output-dir", str(tmp_path / "out")]
        )
        assert "from_cwd" not in result.output
