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
# Looked for in the working directory and the directories above it, so a
# checkout's own colours win from anywhere inside it; the packaged copy is the
# fallback that makes an installed generate-diagram work. --owner-colors
# overrides both.
#
# Walking the parents keeps this lookup in step with the .env lookup in
# loading.py, which uses find_dotenv(usecwd=True) and so walks them too.
# Without it, running from a subdirectory of the checkout took the sheet ID
# from the repo's .env but the colours from the packaged copy.
CONFIG_OWNER_COLORS_PATH = Path("config") / "owner-colors.csv"
# At the package root rather than under web/: this is a colour table the
# diagram generator reads, and nothing about it belongs to a browser.
PACKAGED_OWNER_COLORS = ("translator_diagram", "owner-colors.csv")


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


def metallic_stops(fill_hex: str) -> tuple[str, str, str, str]:
    """The four gradient stops every renderer of an owner colour draws with.

    Owner colours reach the page as brushed-metal coins and rails rather than
    flat swatches, and a brushed finish is four stops: a highlight, the colour
    itself, a shadow, and a softer second highlight where the light comes back
    round. All four are derived from the single hex in
    `config/owner-colors.csv`, and that is the point of the function. The
    alternative is a hand-written gradient per owner in the CSS and a matching
    set in the SVG legend — two files nobody edits together, whose failure mode
    is silent: the page and the diagram end up disagreeing about what colour a
    team is, and each looks fine on its own. Here the CSV stays the one source
    and a colour change is still a one-line edit.

    Lightness moves in HSL percentage points: +26 for the highlight, −10 for
    the shadow, +14 for the return. Every stop is held inside 4–96, so a
    nearly-white or nearly-black owner colour still yields a gradient with a
    visible direction rather than four copies of white. At the very ends the
    two highlights clamp to the same stop, which is the honest outcome: there
    is no headroom left above white to put one in.
    """
    hue, saturation, lightness = _to_hsl(fill_hex)
    return (
        _from_hsl(hue, saturation, lightness + 26),
        "#" + fill_hex.lstrip("#").upper(),
        _from_hsl(hue, saturation, lightness - 10),
        _from_hsl(hue, saturation, lightness + 14),
    )


def owner_styles(colors: dict[str, str]) -> dict[str, dict]:
    """Every owner's colour, its text colour and its metal, in one mapping.

    A renderer that needs an owner's appearance asks once and gets all of it,
    instead of each caller remembering to run `text_color_for` and
    `metallic_stops` over the same hex. That is what keeps the derivations in
    one place as new renderers appear.
    """
    return {
        owner: {
            "base": color,
            "text": text_color_for(color),
            "metal": list(metallic_stops(color)),
        }
        for owner, color in colors.items()
    }


def delta_e(hex_a: str, hex_b: str) -> float:
    """CIE76 colour difference between two hexes, for the palette test.

    Owner chips are read side by side, so two colours can each clear the
    contrast rule and still be the same colour to a reader. Distance in RGB
    does not answer that question — the space is not perceptual, and green
    swamps blue. Lab is roughly perceptually uniform, so one number in it means
    "how different do these look", which is what the palette floor is about.

    CIE76 rather than CIEDE2000: the floor being enforced is far above the
    region where the two formulas disagree, and the later one is a page of
    arithmetic that would not move any answer here.
    """
    la, aa, ba = _to_lab(hex_a)
    lb, ab, bb = _to_lab(hex_b)
    return ((la - lb) ** 2 + (aa - ab) ** 2 + (ba - bb) ** 2) ** 0.5


def _channels(fill_hex: str) -> tuple[float, float, float]:
    """The three sRGB channels of a hex colour, each 0–1. `#` optional."""
    h = fill_hex.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    return r, g, b


def _to_hsl(fill_hex: str) -> tuple[float, float, float]:
    """Hex to (hue 0–360, saturation 0–100, lightness 0–100).

    Written out here rather than pulled in from a colour library: this module
    imports nothing from the package by design, and the diagram half would have
    to carry the dependency too. Half a screen of arithmetic is the cheaper
    side of that trade.
    """
    r, g, b = _channels(fill_hex)
    high, low = max(r, g, b), min(r, g, b)
    lightness = (high + low) / 2
    if high == low:  # grey: hue is undefined, and saturation is what says so
        return 0.0, 0.0, lightness * 100
    span = high - low
    saturation = (
        span / (2 - high - low) if lightness > 0.5 else span / (high + low)
    )
    if high == r:
        hue = ((g - b) / span) % 6
    elif high == g:
        hue = (b - r) / span + 2
    else:
        hue = (r - g) / span + 4
    return hue * 60, saturation * 100, lightness * 100


def _from_hsl(hue: float, saturation: float, lightness: float) -> str:
    """(hue, saturation, lightness) back to `#RRGGBB`, lightness clamped 4–96.

    The clamp lives here rather than at each call site so no caller can ask for
    a stop outside the range and get `#FFFFFF` four times over.
    """
    h = (hue / 360) % 1.0
    s = min(max(saturation, 0.0), 100.0) / 100
    light = min(max(lightness, 4.0), 96.0) / 100
    if s == 0:
        channels = (light, light, light)
    else:
        q = light * (1 + s) if light < 0.5 else light + s - light * s
        p = 2 * light - q
        channels = tuple(
            _hue_to_channel(p, q, h + offset) for offset in (1 / 3, 0, -1 / 3)
        )
    return "#" + "".join(f"{round(c * 255):02X}" for c in channels)


def _hue_to_channel(p: float, q: float, t: float) -> float:
    """One channel of an HSL colour: the standard piecewise hue ramp."""
    t = t % 1.0
    if t < 1 / 6:
        return p + (q - p) * 6 * t
    if t < 1 / 2:
        return q
    if t < 2 / 3:
        return p + (q - p) * (2 / 3 - t) * 6
    return p


def _to_lab(fill_hex: str) -> tuple[float, float, float]:
    """Hex to CIE L*a*b* through XYZ under D65, the white point sRGB is defined at."""
    linear = [
        c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
        for c in _channels(fill_hex)
    ]
    r, g, b = linear
    x = (0.4124564 * r + 0.3575761 * g + 0.1804375 * b) / 0.95047
    y = 0.2126729 * r + 0.7151522 * g + 0.0721750 * b
    z = (0.0193339 * r + 0.1191920 * g + 0.9503041 * b) / 1.08883
    fx, fy, fz = (_lab_f(t) for t in (x, y, z))
    return 116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz)


def _lab_f(t: float) -> float:
    """The Lab transfer function, linear near black so the curve stays finite."""
    return t ** (1 / 3) if t > 216 / 24389 else (841 / 108) * t + 4 / 29


def load_owner_colors(path: Path | None = None) -> dict[str, str]:
    """Load the owner→color mapping from a CSV with columns owner,color.

    Order is preserved from the file; that order also determines legend order.

    With no path, config/owner-colors.csv in the working directory or any
    directory above it wins, and the copy shipped inside the package is the
    fallback. The packaged copy is reached through importlib.resources rather
    than __file__, which need not be a real filesystem path in a non-editable
    install.
    """
    if path is not None:
        return _read_owner_colors(path)
    found = _find_config_owner_colors()
    if found is not None:
        return _read_owner_colors(found)
    package, member = PACKAGED_OWNER_COLORS
    with resources.as_file(resources.files(package) / member) as packaged:
        return _read_owner_colors(packaged)


def _find_config_owner_colors() -> Path | None:
    """config/owner-colors.csv in the working directory or the nearest parent."""
    cwd = Path.cwd()
    for directory in (cwd, *cwd.parents):
        candidate = directory / CONFIG_OWNER_COLORS_PATH
        if candidate.exists():
            return candidate
    return None


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
