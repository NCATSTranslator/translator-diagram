"""Screenshot the built dashboard, and measure whether its table overflows.

    uv run --group shots python tools/shoot.py                 # every default surface
    uv run --group shots python tools/shoot.py --measure       # widths only, no PNGs
    uv run --group shots python tools/shoot.py --path '?view=map' --theme dark --width 1200
    uv run --group shots python tools/shoot.py --path '?view=map' --hover '.mp-node'
    uv run --group shots python tools/shoot.py --path '?' --hover '[data-tip="src"]' --width 1700
    uv run --group shots python tools/shoot.py --path '?' --click 'button[data-expand]' --width 1200

Runs headless Chromium through Playwright, which drives the page's own
`matchMedia` queries: `--theme dark` and the reduced-motion preference are
set on the browser context, so there is no stub to inject and no copy of
`index.html` to make. The build directory is served over HTTP on a free port
for the run, because a `file://` origin blocks the Map's export and the
page's history handling.

Every combination of `--path`, `--theme` and `--width` becomes one PNG under
`--out`, named `<path-slug>[-hover-<selector>][-click-<selector>]-<theme>-<width>.png`,
so two builds shot with the same arguments can be compared by name — `cmp`
says whether a change moved a pixel, which is the check CONTRIBUTING.md asks
for on a refactor. Each shot waits for the page to settle (load, fonts,
every running animation finished, two frames) rather than for a fixed time.
`--hover` and `--click` act on the first *visible* match, through
Playwright's own pointer, so the target is scrolled into view and CSS
`:hover` applies; a selector that matches nothing visible, or a hover that
opens no tooltip, is an error (exit 2) rather than a plain shot. Not every
`[data-tip]` has a tooltip (an environment cell with nothing deployed has
none), and the Map has no table rows, so name the `--path` a selector is for.

`--measure` reports the Overview table's `scrollWidth` against its
`clientWidth`, once per width (the theme does not change a width), and exits
1 if it overflows at 1000px or wider: the overflow that issue #31 was is
invisible in a screenshot, so it is measured rather than looked for. With no
`--width` it sweeps 1000–1700px in 10px steps, because the overflow lives
between breakpoints and three fixed widths walk past it. Below 1000px the
table is meant to scroll sideways, and is not counted. The one band where it
is known still to overflow, `KNOWN_OVERFLOW` below, is reported but does not
fail; an overflow anywhere else does.

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
DEFAULT_PATHS = ("?", "?view=map", "?sel=arax")
DEFAULT_WIDTHS = (1700, 1200, 760)
MEASURE_WIDTHS = tuple(range(1000, 1701, 10))
HEIGHT = 1400
# Below this the environment columns are meant to run past the window and the
# wrap scrolls; see web/AGENTS.md.
OVERFLOW_FLOOR = 1000
# ponytail: the 1490–1535px band where a column returns before there is room
# for it (up to 30px over, measured on 3466bac; web/AGENTS.md, issue #31). It
# is tolerated so `--measure` passes on main and still fails if the band
# widens; delete it once the column is fixed, and any overflow fails.
KNOWN_OVERFLOW = range(1490, 1536)

# Resolves once nothing on the page is still moving. With reduced motion set
# the page renders synchronously, so this is a few milliseconds; a fixed sleep
# was either slower than this or, on a loaded machine, too short.
SETTLE = """async () => {
  await document.fonts.ready;
  const finite = document.getAnimations()
    .filter((a) => a.effect?.getComputedTiming().endTime !== Infinity);
  await Promise.all(finite.map((a) => a.finished.catch(() => {})));
  await new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));
}"""


def slug(path: str) -> str:
    """A filename out of a query string: `?view=map&sel=arax` → `map-arax`."""
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


class Missing(Exception):
    """Something the run was asked to find or open is not on the page."""


def first_visible(page, selector: str):
    """The first match of `selector` that is rendered, SVG elements included."""
    match = page.locator(selector).filter(visible=True).first
    if not match.count():
        raise Missing(f"{selector!r} matches nothing visible on {page.url}")
    return match


def measure(page, base: str, widths: list[int]) -> bool:
    """Print the table's overflow per width; True if any of it fails."""
    failed = False
    for width in widths:
        page.set_viewport_size({"width": width, "height": HEIGHT})
        page.goto(base + "?")
        page.evaluate(SETTLE)
        size = page.evaluate(
            "() => { const w = document.querySelector('div.tablewrap');"
            " return w && [w.scrollWidth, w.clientWidth]; }")
        if not size:
            raise Missing(f"no div.tablewrap on {page.url}; the measurement has nothing to measure")
        scroll, client = size
        if scroll <= client:
            verdict = "ok"
        elif width < OVERFLOW_FLOOR:
            verdict = "scrolls (expected)"
        elif width in KNOWN_OVERFLOW:
            verdict = "OVERFLOW (known; issue #31)"
        else:
            verdict = "OVERFLOW"
            failed = True
        print(f"{width:5}px  table {scroll} in {client}  {verdict}")
    return failed


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
                        help="a window width; repeatable (default 1700, 1200, 760; "
                             "with --measure, 1000-1700 in 10px steps)")
    parser.add_argument("--full", action="store_true", help="full-page shots, not the first screen")
    parser.add_argument("--hover", metavar="SELECTOR",
                        help="hover the first visible match before each shot, and wait for its tooltip")
    parser.add_argument("--click", metavar="SELECTOR",
                        help="click the first visible match before each shot (opens a row, a tab)")
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
    widths = args.width or list(MEASURE_WIDTHS if args.measure else DEFAULT_WIDTHS)
    actions = "".join(f"-{verb}-{slug(sel)}" for verb, sel in (("hover", args.hover), ("click", args.click))
                      if sel)
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
            try:
                if args.measure:
                    context = browser.new_context(reduced_motion="reduce")
                    overflowed = measure(context.new_page(), base, widths)
                    context.close()
                for theme in ([] if args.measure else themes):
                    context = browser.new_context(color_scheme=theme, reduced_motion="reduce")
                    for width in widths:
                        page = context.new_page()
                        page.set_viewport_size({"width": width, "height": HEIGHT})
                        for path in paths:
                            page.goto(base + path)
                            page.evaluate(SETTLE)
                            if args.click:
                                first_visible(page, args.click).click()
                                page.evaluate(SETTLE)
                            if args.hover:
                                first_visible(page, args.hover).hover()
                                try:
                                    page.wait_for_selector("#td-tip:not([hidden])", timeout=2000)
                                except PlaywrightError:
                                    raise Missing(f"hovering {args.hover!r} on {page.url} opened no tooltip") from None
                                page.evaluate(SETTLE)
                            args.out.mkdir(parents=True, exist_ok=True)
                            target = args.out / f"{slug(path)}{actions}-{theme}-{width}.png"
                            page.screenshot(path=str(target), full_page=args.full)
                            print(target.relative_to(ROOT) if target.is_relative_to(ROOT) else target)
                        page.close()
                    context.close()
            except Missing as error:
                print(error, file=sys.stderr)
                return 2
            browser.close()
    finally:
        server.shutdown()
    if overflowed:
        print(f"The table overflows its window at {OVERFLOW_FLOOR}px or wider, outside the known band.",
              file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
