"""Tests for translator_diagram.colors."""

import click
import pytest

from translator_diagram.colors import ColorAssigner, FALLBACK_COLORS, load_owner_colors, text_color_for


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

    def test_the_checkouts_config_copy_wins(self, tmp_path, monkeypatch):
        config = tmp_path / "config"
        config.mkdir()
        (config / "owner-colors.csv").write_text(
            "owner,color\nOnlyHere,#123456\n", encoding="utf-8"
        )
        monkeypatch.chdir(tmp_path)
        assert load_owner_colors() == {"OnlyHere": "#123456"}

    def test_falls_back_to_the_packaged_copy(self, tmp_path, monkeypatch):
        # An installed generate-diagram run from anywhere has no config/ to
        # read, and resolving the packaged copy via __file__ would not survive
        # a non-editable install.
        monkeypatch.chdir(tmp_path)
        assert "NCATS" in load_owner_colors()

    def test_an_explicit_path_beats_both(self, tmp_path, monkeypatch):
        config = tmp_path / "config"
        config.mkdir()
        (config / "owner-colors.csv").write_text(
            "owner,color\nOnlyHere,#123456\n", encoding="utf-8"
        )
        explicit = tmp_path / "other.csv"
        explicit.write_text("owner,color\nChosen,#654321\n", encoding="utf-8")
        monkeypatch.chdir(tmp_path)
        assert load_owner_colors(explicit) == {"Chosen": "#654321"}
