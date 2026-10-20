"""Screenshot the built dashboard, and measure whether its table overflows.

    uv run --group shots python tools/shoot.py                 # every default surface
    uv run --group shots python tools/shoot.py --measure       # widths only, no PNGs
    uv run --group shots python tools/shoot.py --path '?view=map' --theme dark --width 1200
    uv run --group shots python tools/shoot.py --path '?expand=name-lookup' --hover 'button.fg'
    uv run --group shots python tools/shoot.py --click 'details.axes > summary' --width 1700

Runs headless Chromium through Playwright, which drives the page's own
`matchMedia` queries: `--theme dark` and the reduced-motion preference are
set on the browser context, so there is no stub to inject and no copy of
`index.html` to make. The build directory is served over HTTP on a free port
for the run, because a `file://` origin blocks the Map's export and the
page's history handling.

Every combination of `--path`, `--theme` and `--width` becomes one PNG under
`--out`, named `<path-slug>-<theme>-<width>.png`, so two builds shot with the
same arguments can be compared by name — `cmp` says whether a change moved a
pixel, which is the check CONTRIBUTING.md asks for on a refactor.

`--measure` reports the Overview table's `scrollWidth` against its
`clientWidth` at each width and exits 1 if it overflows at 1000px or wider:
the overflow that issue #31 was is invisible in a screenshot, so it is
measured rather than looked for. At 900px and below the table is meant to
scroll sideways, and is not counted.

The browser is installed once with
`uv run --group shots playwright install chromium`; without it this says
so and exits 2. `src/translator_diagram/web/AGENTS.md` has the hand-driven
recipe this replaces, kept for a machine without Playwright.
"""

from __future__ import annotations

import argparse
import functools
import http.server
import re
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PATHS = ("?", "?view=map", "?view=component&sel=arax")
DEFAULT_WIDTHS = (1700, 1200, 760)
HEIGHT = 1400
# Below this the environment columns are meant to run past the window and the
# wrap scrolls; see web/AGENTS.md.
OVERFLOW_FLOOR = 1000


def slug(path: str) -> str:
    """A filename out of a query string: `?view=component&sel=arax` → `component-arax`."""
    body = re.sub(r"[^a-z0-9]+", "-", path.lower().lstrip("?")).strip("-")
    return re.sub(r"(^|-)(view|sel)-", r"\1", body) or "overview"


class _Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args: object) -> None:  # one line per request is noise here
        pass


def serve(directory: Path) -> tuple[http.server.ThreadingHTTPServer, str]:
    handler = functools.partial(_Quiet, directory=str(directory))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}/index.html"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--build-dir", type=Path, default=ROOT / "data" / "dashboard",
                        help="the directory build-dashboard wrote (default data/dashboard)")
    parser.add_argument("--out", type=Path, default=ROOT / "data" / "shots",
                        help="where the PNGs go (default data/shots)")
    parser.add_argument("--path", action="append", metavar="QUERY",
                        help="a query string to shoot, e.g. '?view=map'; repeatable")
    parser.add_argument("--theme", choices=("light", "dark", "both"), default="both")
    parser.add_argument("--width", action="append", type=int, metavar="PX",
                        help="a window width; repeatable (default 1700, 1200, 760)")
    parser.add_argument("--full", action="store_true", help="full-page shots, not the first screen")
    parser.add_argument("--hover", metavar="SELECTOR",
                        help="mouseover the first visible match before each shot (opens a tooltip)")
    parser.add_argument("--click", metavar="SELECTOR",
                        help="click the first visible match before each shot (opens a <details>, a row)")
    parser.add_argument("--measure", action="store_true",
                        help="report the table's scroll width per width, and take no PNGs")
    args = parser.parse_args()

    if not (args.build_dir / "index.html").exists():
        print(f"No index.html in {args.build_dir}; run `uv run build-dashboard` first.", file=sys.stderr)
        return 2
    try:
        from playwright.sync_api import Error as PlaywrightError
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("Playwright is not installed: run with `uv run --group shots`.", file=sys.stderr)
        return 2

    paths = args.path or list(DEFAULT_PATHS)
    themes = ("light", "dark") if args.theme == "both" else (args.theme,)
    widths = args.width or list(DEFAULT_WIDTHS)
    server, base = serve(args.build_dir)
    overflowed = False
    try:
        with sync_playwright() as playwright:
            try:
                browser = playwright.chromium.launch()
            except PlaywrightError as error:
                print(str(error).splitlines()[0], file=sys.stderr)
                print("Install it once: uv run --group shots playwright install chromium", file=sys.stderr)
                return 2
            for theme in themes:
                context = browser.new_context(color_scheme=theme, reduced_motion="reduce")
                for width in widths:
                    page = context.new_page()
                    page.set_viewport_size({"width": width, "height": HEIGHT})
                    for path in (["?"] if args.measure else paths):
                        page.goto(base + path)
                        page.wait_for_timeout(600)
                        if args.measure:
                            scroll, client = page.evaluate(
                                "() => { const w = document.querySelector('div.tablewrap');"
                                " return w ? [w.scrollWidth, w.clientWidth] : [0, 0]; }")
                            over = scroll > client
                            if over and width >= OVERFLOW_FLOOR:
                                overflowed = True
                            print(f"{theme:5} {width:5}px  table {scroll} in {client}  "
                                  f"{'OVERFLOW' if over else 'ok'}")
                            continue
                        if args.click:
                            page.evaluate(
                                "(sel) => { const el = [...document.querySelectorAll(sel)]"
                                ".find((e) => e.offsetParent); if (el) el.click(); }", args.click)
                            page.wait_for_timeout(300)
                        if args.hover:
                            page.evaluate(
                                "(sel) => { const el = [...document.querySelectorAll(sel)]"
                                ".find((e) => e.offsetParent); if (el) el.dispatchEvent("
                                "new MouseEvent('mouseover', { bubbles: true })); }", args.hover)
                            page.wait_for_timeout(300)
                        args.out.mkdir(parents=True, exist_ok=True)
                        target = args.out / f"{slug(path)}-{theme}-{width}.png"
                        page.screenshot(path=str(target), full_page=args.full)
                        print(target.relative_to(ROOT) if target.is_relative_to(ROOT) else target)
                    page.close()
                context.close()
            browser.close()
    finally:
        server.shutdown()
    if overflowed:
        print(f"The table overflows its window at {OVERFLOW_FLOOR}px or wider.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
