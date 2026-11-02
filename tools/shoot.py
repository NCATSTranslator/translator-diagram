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

`--path` has to start with `?`, and the page has to do what it asks: it
quietly ignores a view, a component or a tab it does not know, so the tool
checks, and a path the page ignored is an error rather than a shot of the
wrong thing. `--hover` and `--click` act on the first *visible* match, through
Playwright's own pointer, so the target is scrolled into view and CSS `:hover`
applies. A selector that matches nothing
visible, or a hover that opens no tooltip, is an error too. Not every
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
fail; an overflow anywhere else does. It takes no
`--path`, `--theme`, `--full`, `--hover`, `--click` or `--out`, and refuses
them rather than measuring something other than what they ask for.

Exit status: 0 when it did what was asked, 1 when `--measure` found an overflow
it should fail on, 2 when it could not do what was asked (no build, no browser,
a bad flag, a page that would not load or do as its path said, an action that
timed out).

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
HEIGHT = 1400
# Playwright's own 30s only makes a typo slower to report.
ACTION_TIMEOUT_MS = 10_000
# Below this the environment columns are meant to run past the window and the
# wrap scrolls; see web/AGENTS.md.
OVERFLOW_FLOOR = 1000
# ponytail: the 1490–1535px band where a column returns before there is room
# for it (up to 30px over, measured on 3466bac; web/AGENTS.md, issue #31). It
# is tolerated so `--measure` passes on main and still fails if the band
# widens; delete it once the column is fixed, and any overflow fails.
KNOWN_OVERFLOW = range(1490, 1536)
MEASURE_WIDTHS = tuple(range(1000, 1701, 10))

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

# The parts of a query the page did not act on. Everything it understands comes
# back out of `TD.url.serialize` unless it is the default, which covers an
# unknown view, sort or edge kind. A selected component or an expanded row stays
# in the state even when no such row exists, so those ask for the row, and a tab
# has to be the one showing. `sel` asks for the row and not for an open drawer
# because a selection does not need a drawer to mean something.
IGNORED = """(query) => {
  const asked = new URLSearchParams(query);
  const kept = new URLSearchParams(TD.url.serialize(TD.state));
  const ignored = [...asked]
    .filter(([name, value]) => name !== "tab" && kept.get(name) !== value
      && String(TD.url.DEFAULTS[name] ?? "") !== value)
    .map(([name, value]) => `${name}=${value}`);
  if (asked.get("sel") && !TD.row.byId(asked.get("sel"))) ignored.push(`sel=${asked.get("sel")}`);
  const tab = asked.get("tab");
  const shown = document.querySelector('.dw-tabs [aria-selected="true"]')?.dataset.id;
  if (tab && shown !== tab) ignored.push(`tab=${tab}`);
  for (const id of TD.state.expand) if (!TD.row.byId(id)) ignored.push(`expand=${id}`);
  return ignored;
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


def new_context(browser, **options):
    """A browser context with motion off and a timeout a typo does not wait out."""
    context = browser.new_context(reduced_motion="reduce", **options)
    context.set_default_timeout(ACTION_TIMEOUT_MS)
    return context


def arrive(page, url: str) -> None:
    """Load `url` and let it settle; an error page is not a page to shoot."""
    response = page.goto(url)
    if response is None or not response.ok:
        raise Missing(f"{url} answered {response.status if response else 'nothing'}")
    page.evaluate(SETTLE)


def first_visible(page, selector: str):
    """The first match of `selector` that is rendered, SVG elements included."""
    match = page.locator(selector).filter(visible=True).first
    if not match.count():
        raise Missing(f"{selector!r} matches nothing visible on {page.url}")
    return match


def shoot(page, base: str, path: str, width: int, args: argparse.Namespace, target: Path) -> None:
    from playwright.sync_api import TimeoutError as PlaywrightTimeout

    page.set_viewport_size({"width": width, "height": HEIGHT})
    arrive(page, base + path)
    ignored = page.evaluate(IGNORED, path)
    if ignored:
        raise Missing(f"the page ignored {', '.join(ignored)}: no such view, component or tab in this build")
    if args.click:
        first_visible(page, args.click).click()
        page.evaluate(SETTLE)
    if args.hover:
        first_visible(page, args.hover).hover()
        try:
            page.wait_for_selector("#td-tip:not([hidden])", timeout=2000)
        except PlaywrightTimeout:
            raise Missing(f"hovering {args.hover!r} on {page.url} opened no tooltip") from None
        page.evaluate(SETTLE)
    target.parent.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(target), full_page=args.full)
    print(target.relative_to(ROOT) if target.is_relative_to(ROOT) else target)


def measure(page, base: str, widths: list[int]) -> bool:
    """Print the table's overflow per width; True if any of it fails."""
    failed = False
    for width in widths:
        page.set_viewport_size({"width": width, "height": HEIGHT})
        arrive(page, base + "?")
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


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--build-dir", type=Path, default=ROOT / "data" / "dashboard",
                        help="the directory build-dashboard wrote (default data/dashboard)")
    parser.add_argument("--out", type=Path,
                        help="where the PNGs go (default data/shots)")
    parser.add_argument("--path", action="append", metavar="QUERY",
                        help="a query string to shoot, starting with '?', e.g. '?view=map'; repeatable")
    parser.add_argument("--theme", choices=("light", "dark", "both"),
                        help="the colour scheme (default both)")
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
    args = parser.parse_args(argv)

    if args.measure:
        given = [flag for flag, value in (("--path", args.path), ("--theme", args.theme), ("--full", args.full),
                                          ("--hover", args.hover), ("--click", args.click), ("--out", args.out))
                 if value]
        if given:
            parser.error(f"--measure measures the plain Overview and takes no PNGs, so it cannot use {', '.join(given)}")
    for path in args.path or ():
        if not path.startswith("?"):
            parser.error(f"--path {path!r} must start with '?': it is added straight after index.html")
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
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
    themes = ("light", "dark") if args.theme in (None, "both") else (args.theme,)
    widths = args.width or list(MEASURE_WIDTHS if args.measure else DEFAULT_WIDTHS)
    out = args.out or ROOT / "data" / "shots"
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
                    context = new_context(browser)
                    overflowed = measure(context.new_page(), base, widths)
                    context.close()
                for theme in ([] if args.measure else themes):
                    context = new_context(browser, color_scheme=theme)
                    for width in widths:
                        page = context.new_page()
                        for path in paths:
                            shoot(page, base, path, width, args, out / f"{slug(path)}{actions}-{theme}-{width}.png")
                        page.close()
                    context.close()
            except (Missing, PlaywrightError) as error:
                # A PlaywrightError here is an action that timed out or a page
                # that would not load. Its call log names what intercepted the
                # pointer, which is the useful part, and exit 1 means overflow.
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
