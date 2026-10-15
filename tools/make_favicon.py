"""Render the dashboard's favicon, src/translator_diagram/web/favicon.ico.

The icon is a "Tr" tile in the Translator UI's purple ($purpleOne, #662E6B,
from NCATSTranslator/ui-fe src/assets/styles/_variables.scss), the same mark
the page draws in its top bar (BRAND_MARK in web/app.js). It is deliberately
not the NIH or NCATS logo: this page is not an official NIH page, and a logo
that says it is would be read as a claim.

An .ico rather than an SVG favicon, because every browser takes an .ico and
not every one takes an SVG. Each size is rendered by headless Chromium rather
than scaled from one bitmap, so the 16px letters are hinted at 16px; the PNGs
are then packed into one .ico (PNG entries, which browsers have read since
Windows Vista). No Pillow, which this repository does not depend on.

    uv run python tools/make_favicon.py

Needs Playwright's headless Chromium shell, the one the screenshot recipe in
src/translator_diagram/web/CLAUDE.md uses. The letters are set in the system
UI face, so a re-render on another OS draws slightly different glyphs; commit
the .ico it writes only if you mean to change the icon.
"""

import glob
import os
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TARGET = ROOT / "src" / "translator_diagram" / "web" / "favicon.ico"
SIZES = (16, 32, 48)

SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32" width="{size}"
  height="{size}"><rect width="32" height="32" rx="6" fill="#662E6B"/><text x="16"
  y="22.6" text-anchor="middle" font-family="system-ui, -apple-system, 'Segoe UI',
  sans-serif" font-size="19" font-weight="700" letter-spacing="-0.6"
  fill="#FFFFFF">Tr</text></svg>"""

PAGE = """<!doctype html><meta charset="utf-8"><style>html,body{{margin:0;
background:transparent}}svg{{display:block}}</style>{svg}"""


def chrome() -> str:
    pattern = os.path.expanduser(
        "~/Library/Caches/ms-playwright/chromium_headless_shell-*/*/chrome-headless-shell"
    )
    found = sorted(glob.glob(pattern)) or sorted(
        glob.glob(os.path.expanduser(
            "~/.cache/ms-playwright/chromium_headless_shell-*/*/chrome-headless-shell"))
    )
    if not found:
        sys.exit("No Playwright headless Chromium shell found; see web/CLAUDE.md.")
    return found[-1]


def render(size: int, workdir: Path) -> bytes:
    page = workdir / f"icon-{size}.html"
    page.write_text(PAGE.format(svg=SVG.format(size=size)), encoding="utf-8")
    shot = workdir / f"icon-{size}.png"
    subprocess.run(
        [
            chrome(), "--headless", "--disable-gpu", "--hide-scrollbars",
            "--default-background-color=00000000", "--force-device-scale-factor=1",
            f"--window-size={size},{size}", f"--user-data-dir={workdir / 'profile'}",
            f"--screenshot={shot}", page.as_uri(),
        ],
        check=True, capture_output=True,
    )
    return shot.read_bytes()


def pack_ico(images: list[tuple[int, bytes]]) -> bytes:
    """An .ico whose entries are PNGs: ICONDIR, one ICONDIRENTRY each, data."""
    header = struct.pack("<HHH", 0, 1, len(images))
    offset = len(header) + 16 * len(images)
    entries, data = b"", b""
    for size, png in images:
        dim = 0 if size >= 256 else size  # 0 means 256 in an ICONDIRENTRY
        entries += struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32, len(png), offset)
        data += png
        offset += len(png)
    return header + entries + data


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        images = [(size, render(size, Path(tmp))) for size in SIZES]
    TARGET.write_bytes(pack_ico(images))
    print(f"Wrote {TARGET.relative_to(ROOT)} ({TARGET.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
