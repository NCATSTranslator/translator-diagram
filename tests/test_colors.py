"""Tests for translator_diagram.colors."""

import itertools
from pathlib import Path

import click
import pytest

from translator_diagram.colors import (
    CONFIG_OWNER_COLORS_PATH,
    FALLBACK_COLORS,
    HEX_COLOR_RE,
    PACKAGED_OWNER_COLORS,
    ColorAssigner,
    delta_e,
    load_owner_colors,
    metallic_stops,
    owner_styles,
    text_color_for,
)

PALETTE = Path(__file__).resolve().parent.parent / "config" / "owner-colors.csv"


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


def _contrast(bg_hex, fg):
    """WCAG 2.1 contrast ratio between a hex background and black or white."""
    channels = [int(bg_hex.lstrip("#")[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    linear = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
              for c in channels]
    bg = 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]
    text = 0.0 if fg == "black" else 1.0
    lighter, darker = max(bg, text), min(bg, text)
    return (lighter + 0.05) / (darker + 0.05)


class TestOwnerChipsAreReadable:
    # Owner colours are chip backgrounds and `text_color_for` picks black or
    # white over them, so a colour chosen for its hue can land on a pair that
    # nobody can read. The chip text is 0.75rem bold, which is not WCAG "large
    # text", so the bar is 4.5:1 and not 3:1. Two colours sat below it for as
    # long as the palette existed, and the way that was found was somebody
    # looking rather than anything failing.
    def test_every_owner_colour_clears_wcag_aa(self):
        root = Path(__file__).resolve().parent.parent
        failures = {
            owner: round(_contrast(color, text_color_for(color)), 2)
            for owner, color in load_owner_colors(
                root / "config" / "owner-colors.csv"
            ).items()
            if _contrast(color, text_color_for(color)) < 4.5
        }
        assert not failures, (
            f"owner chips below WCAG AA (4.5:1) against the text colour "
            f"text_color_for picks for them: {failures}"
        )


def _lightness(hex_color):
    """HSL lightness, 0-100, computed independently of the module under test."""
    channels = [int(hex_color.lstrip("#")[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    return (max(channels) + min(channels)) / 2 * 100


class TestMetallicStops:
    def test_four_hex_stops_with_the_base_second(self):
        stops = metallic_stops("#8E99A4")
        assert len(stops) == 4
        assert all(HEX_COLOR_RE.match(stop) for stop in stops), stops
        assert stops[1] == "#8E99A4"

    def test_lightness_runs_highlight_return_base_shadow(self):
        # +26, base, -10, +14: the two highlights sit above the base and the
        # shadow below it, which is what makes the gradient read as brushed
        # metal rather than as a flat swatch with noise on it.
        highlight, base, shadow, ret = metallic_stops("#8E99A4")
        assert (
            _lightness(highlight) > _lightness(ret) > _lightness(base)
            > _lightness(shadow)
        )

    @pytest.mark.parametrize("owner_color", ["#FFFFFF", "#000000", "#E8E8E8"])
    def test_an_extreme_colour_is_clamped_rather_than_flattened(self, owner_color):
        # `None` is #E8E8E8, and without the clamps its highlight would run off
        # the end of the scale and come back as white four times over. A stop
        # can land a rounding step outside 4-96 because the clamp is applied in
        # HSL and the answer is then quantised to eight bits per channel.
        step = 100 / 255
        stops = metallic_stops(owner_color)
        assert all(HEX_COLOR_RE.match(stop) for stop in stops), stops
        assert all(-step <= _lightness(stop) <= 100 + step for stop in stops)
        assert 4 - step <= _lightness(stops[0]) <= 96 + step
        assert 4 - step <= _lightness(stops[2]) <= 96 + step
        # Three at the extremes rather than four: at white the highlight and
        # the return both clamp to the same stop, which is the honest outcome.
        assert len(set(stops)) >= 3, stops


class TestOwnerStyles:
    def test_every_owner_gets_a_base_a_text_colour_and_four_metal_stops(self):
        styles = owner_styles({"CATRAX": "#8E99A4", "UI": "#C2185B"})
        assert set(styles) == {"CATRAX", "UI"}
        assert styles["CATRAX"] == {
            "base": "#8E99A4",
            "text": text_color_for("#8E99A4"),
            "metal": list(metallic_stops("#8E99A4")),
        }
        assert len(styles["UI"]["metal"]) == 4

    def test_an_empty_palette_is_an_empty_mapping(self):
        assert owner_styles({}) == {}


class TestPaletteSeparation:
    # The contrast test below asks whether one chip is readable. This asks
    # whether two chips are distinguishable, which is a different failure and
    # the one the palette actually has: nine owners share the blue-to-magenta
    # arc left after the reserved hues, and two of them converging is a page
    # where a reader cannot tell DOGSURF from UI. dE 24 in CIE76 is roughly
    # "obviously a different colour at a glance", well above the ~2.3 nobody
    # can see and below the ~31 the palette held before CATRAX moved.
    FLOOR = 24.0

    def test_every_pair_of_owners_is_separated(self):
        colors = load_owner_colors(PALETTE)
        distances = sorted(
            (delta_e(colors[a], colors[b]), a, b)
            for a, b in itertools.combinations(colors, 2)
        )
        worst, owner_a, owner_b = distances[0]
        assert worst >= self.FLOOR, (
            f"{owner_a} and {owner_b} are {worst:.1f} dE apart, below the "
            f"{self.FLOOR} floor in docs/owner-colours.md. Two owner chips "
            f"that close read as the same team."
        )


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

    def test_a_subdirectory_of_the_checkout_still_finds_it(
        self, tmp_path, monkeypatch
    ):
        # The .env holding GOOGLE_SHEET_ID is found with
        # find_dotenv(usecwd=True), which walks parents. If this lookup did
        # not, running from data/ — the scratch directory AGENTS.md points
        # agents at — would take the sheet ID from the checkout but the
        # colours from the packaged copy, with nothing said.
        config = tmp_path / "config"
        config.mkdir()
        (config / "owner-colors.csv").write_text(
            "owner,color\nOnlyHere,#123456\n", encoding="utf-8"
        )
        scratch = tmp_path / "data"
        scratch.mkdir()
        monkeypatch.chdir(scratch)
        assert load_owner_colors() == {"OnlyHere": "#123456"}

    def test_the_build_ships_the_file_the_fallback_reads(self):
        # There is one owner-colors.csv, at config/owner-colors.csv, and the
        # build maps it into the wheel so an installed generate-diagram with no
        # config/ to read still finds it. Nothing checks that at import time --
        # in a source checkout the packaged path genuinely is not there -- so
        # this asserts the packaging instead: the force-include has to name the
        # same member `load_owner_colors` asks importlib.resources for, or the
        # fallback resolves to a file the wheel does not contain.
        import tomllib

        root = Path(__file__).resolve().parent.parent
        with (root / "pyproject.toml").open("rb") as f:
            include = tomllib.load(f)["tool"]["hatch"]["build"]["targets"][
                "wheel"
            ]["force-include"]
        package, member = PACKAGED_OWNER_COLORS
        source, = [s for s, d in include.items() if d == f"{package}/{member}"]
        assert Path(source) == CONFIG_OWNER_COLORS_PATH
        assert (root / source).is_file(), f"{source} is what the build ships"

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
