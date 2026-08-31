"""Owner colours, and the palette constants the diagram is drawn from."""

import csv
import re
from importlib import resources
from pathlib import Path

import click

# Owner → fill color mapping lives in a CSV rather than in code so that
# non-Python edits can change it. Row order in the CSV doubles as legend order
# in the diagram.
#
# Looked for in the working directory first, so a checkout's own colours win;
# the packaged copy is the fallback that makes an installed generate-diagram
# work from anywhere. --owner-colors overrides both.
CONFIG_OWNER_COLORS_PATH = Path("config") / "owner-colors.csv"
PACKAGED_OWNER_COLORS = ("translator_diagram", "data/owner-colors.csv")


FALLBACK_COLORS = [
    "#B0BEC5", "#BCAAA4", "#CE93D8", "#80CBC4",
    "#EF9A9A", "#FFCC80", "#C5E1A5", "#80DEEA",
]


GHOST_BORDER_COLOR = "#999999"


GHOST_FILL_COLOR = "#D3D3D3"


GHOST_FONT_COLOR = "#666666"


# Warm amber for external-entity nodes (sources and sinks) so they stand out
# clearly against the component fill colors.
EXTERNAL_FILL_COLOR = "#FFE082"


# owner-colors.csv is hand-edited, so its values are checked rather than trusted:
# text_color_for needs exactly six hex digits, and graphviz would silently render
# a typo'd color as black.
HEX_COLOR_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")


class ColorAssigner:
    """Assigns fill colors to owners, falling back to a rotating palette."""

    def __init__(self, base_colors: dict[str, str], fallback_colors: list[str]):
        self.color_map: dict[str, str] = dict(base_colors)
        self.fallback_colors = fallback_colors
        self.next_fallback = 0
        self._used: set[str] = set()

    def get(self, owner: str) -> str:
        if owner not in self.color_map:
            self.color_map[owner] = self.fallback_colors[
                self.next_fallback % len(self.fallback_colors)
            ]
            self.next_fallback += 1
        self._used.add(owner)
        return self.color_map[owner]

    @property
    def used_colors(self) -> dict[str, str]:
        """Color map restricted to owners actually rendered, in original order."""
        return {k: v for k, v in self.color_map.items() if k in self._used}


def text_color_for(fill_hex: str) -> str:
    """Return "black" or "white" for adequate contrast against a hex fill."""
    h = fill_hex.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    # Rec. 709 perceptual luminance
    luminance = 0.2126 * r + 0.7152 * g + 0.0722 * b
    return "black" if luminance > 0.5 else "white"


def load_owner_colors(path: Path | None = None) -> dict[str, str]:
    """Load the owner→color mapping from a CSV with columns owner,color.

    Order is preserved from the file; that order also determines legend order.

    With no path, config/owner-colors.csv under the working directory wins, and
    the copy shipped inside the package is the fallback. The packaged copy is
    reached through importlib.resources rather than __file__, which need not be
    a real filesystem path in a non-editable install.
    """
    if path is not None:
        return _read_owner_colors(path)
    if CONFIG_OWNER_COLORS_PATH.exists():
        return _read_owner_colors(CONFIG_OWNER_COLORS_PATH)
    package, member = PACKAGED_OWNER_COLORS
    with resources.as_file(resources.files(package) / member) as packaged:
        return _read_owner_colors(packaged)


def _read_owner_colors(path: Path) -> dict[str, str]:
    """Parse one owner-colors CSV, checking every colour on the way through."""
    if not path.exists():
        raise click.ClickException(f"Owner-colors file not found: {path}")
    with path.open(newline="", encoding="utf-8-sig") as f:
        # restval="" so a short row reports a bad colour rather than raising
        # AttributeError on None.strip() — see load_components.
        reader = csv.DictReader(f, restval="")
        missing_cols = {"owner", "color"} - set(reader.fieldnames or [])
        if missing_cols:
            raise click.ClickException(
                f"{path} is missing required columns: "
                + ", ".join(sorted(missing_cols))
            )
        colors = {}
        for row in reader:
            owner, color = row["owner"].strip(), row["color"].strip()
            if not HEX_COLOR_RE.match(color):
                raise click.ClickException(
                    f"{path}: owner '{owner}' has color '{color}', which is not "
                    f"a six-digit hex colour like #EF5350."
                )
            colors[owner] = color
        return colors
