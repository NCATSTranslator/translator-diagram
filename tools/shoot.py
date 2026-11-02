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
`--out`, named `<path-slug>[-hover-<selector>][-click-<selector>][-full]-<theme>-<width>.png`.
Two builds compare by name, so give each its own `--out` (the same one
overwrites the first run) and let `diff` say whether a change moved a pixel,
which is the check CONTRIBUTING.md asks for on a refactor:

    uv run build-dashboard --output-dir data/dashboard-before
    # ... make the change ...
    uv run build-dashboard --output-dir data/dashboard-after
    uv run --group shots python tools/shoot.py --build-dir data/dashboard-before --out data/shots/before
    uv run --group shots python tools/shoot.py --build-dir data/dashboard-after --out data/shots/after
    diff -rq data/shots/before data/shots/after

So that this holds across a wait, the page's clock is frozen at the moment of
the build's sync: the top bar reads "synced just now" and every age is counted
from that sync, whenever the shot is taken. Each shot waits for the page to
settle (load, fonts, every running animation finished, two frames) rather than
for a fixed time.

`--path` has to start with `?`, and the page has to do what it asks: it
quietly ignores a view, a component or a tab it does not know, so the tool
checks, and a path the page ignored is an error rather than a shot of the
wrong thing. `--hover` and `--click` act on the first *visible* match, through
Playwright's own pointer, so the target is scrolled into view and CSS `:hover`
applies. After a `--click` the pointer moves away and any tooltip is closed,
so the shot shows what the click opened. A selector that matches nothing
visible, or a hover that opens no tooltip, is an error too. Not every
`[data-tip]` has a tooltip (an environment cell with nothing deployed has
none), and the Map has no table rows, so name the `--path` a selector is for.
`--full` grows the window until nothing scrolls, so every row is in the shot.

`--measure` reports the Overview table's `scrollWidth` against its
`clientWidth`, once per width (the theme does not change a width), and exits
1 if it overflows at 1000px or wider: the overflow that issue #31 was is
invisible in a screenshot, so it is measured rather than looked for. It
measures with a classic 15px scrollbar, the worst case, which is what a reader
on Windows or Linux has. With no `--width` it sweeps 1000–1700px in 10px steps,
because the overflow lives between breakpoints and three fixed widths walk past
it, and in 1px steps around the known band so that a band that widens by less
than a step still shows. Below 1000px the table is meant to scroll sideways,
and is not counted. The one band where it is known still to overflow,
`KNOWN_OVERFLOW` below, is reported but does not fail unless it runs further
over than `KNOWN_OVERFLOW_MAX`; an overflow anywhere else fails. It takes no
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
import json
import re
import sys
import threading
from datetime import UTC, datetime
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
# ponytail: the band where a column returns (`@media (min-width: 1500px)`)
# before there is room for it, measured at every width with a classic scrollbar
# on 761a9ba; web/AGENTS.md, issue #31. It is tolerated so `--measure` passes
# on main and still fails if the band widens or runs further over; delete both
# once the column is fixed, and any overflow fails.
KNOWN_OVERFLOW = range(1500, 1545)
KNOWN_OVERFLOW_MAX = 45
# ponytail: 1px steps everywhere would take 30s, so only the known band's edges
# get them. A new band narrower than 10px elsewhere can slip between the steps;
# `--width` looks at one directly.
MEASURE_WIDTHS = tuple(sorted({*range(1000, 1701, 10),
                               *range(KNOWN_OVERFLOW.start - 10, KNOWN_OVERFLOW.stop + 10)}))

# The classic scrollbar `--measure` measures with. Chromium takes the room for
# a styled scrollbar on every platform; just not hiding scrollbars
# (`--hide-scrollbars`, a Playwright default) does nothing on macOS, where they
# are overlays, and the sweep there passes while Windows readers overflow.
SCROLLBAR_PX = 15
SCROLLBAR_CSS = f".tablewrap::-webkit-scrollbar {{ width: {SCROLLBAR_PX}px; height: {SCROLLBAR_PX}px; }}"
# Short enough that the table scrolls, or the wrap has no scrollbar to measure.
MEASURE_HEIGHT = 800

# When a build with no sync behind it thinks it is. Any fixed moment will do.
UNSYNCED_NOW = datetime(2026, 1, 1, tzinfo=UTC)
# `--full` adds height until nothing scrolls. It takes more than one pass where
# a scroller is sized from the window: 30vh with the drawer open on a narrow
# window gains only 0.3px per pixel added.
FULL_PASSES = 40

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

# Freezes `Date` and nothing else. Not Playwright's `clock.set_fixed_time`,
# which also replaces `requestAnimationFrame`: SETTLE's two frames then pass
# without a real one, and about one drawer shot in three caught the table with
# its columns 1px from where they end up, so two runs of one build differed.
FREEZE_DATE = """{
  const now = %d;
  globalThis.Date = new Proxy(Date, {
    construct: (real, args, target) => Reflect.construct(real, args.length ? args : [now], target),
    get: (real, name) => (name === "now" ? () => now : Reflect.get(real, name)),
  });
}"""

# The parts of a query the page did not act on. Everything it understands comes
# back out of `TD.url.serialize` unless it is the default, which covers an
# unknown view, sort or edge kind. A selected component or an expanded row stays
# in the state even when no such row exists, so those are checked against the
# build's own list of rows, and a tab has to be the one showing. The list comes
# from `overview.json` rather than from `TD.row` or `TD.drawer` because this has
# to run on any build, and the page's internals are not the same on all of them:
# an older build is what a before-and-after compares against, and `TD.row` came
# and `TD.drawer` is going. `overview.json` is a contract, so its rows stay put.
IGNORED = """({query, rows}) => {
  const asked = new URLSearchParams(query);
  const kept = new URLSearchParams(TD.url.serialize(TD.state));
  const ignored = [...asked]
    .filter(([name, value]) => name !== "tab" && kept.get(name) !== value
      && String(TD.url.DEFAULTS[name] ?? "") !== value)
    .map(([name, value]) => `${name}=${value}`);
  if (asked.get("sel") && !rows.includes(asked.get("sel"))) ignored.push(`sel=${asked.get("sel")}`);
  const tab = asked.get("tab");
  const shown = document.querySelector('.dw-tabs [aria-selected="true"]')?.dataset.id;
  if (tab && shown !== tab) ignored.push(`tab=${tab}`);
  for (const id of TD.state.expand) if (!rows.includes(id)) ignored.push(`expand=${id}`);
  return ignored;
}"""

# How much the tallest scroller on the page still has out of sight.
OVERHANG = """() => Math.max(0, ...[...document.querySelectorAll('*')]
  .filter((e) => /auto|scroll/.test(getComputedStyle(e).overflowY))
  .map((e) => e.scrollHeight - e.clientHeight))"""


def slug(path: str) -> str:
    """A filename out of a query string: `?view=map&sel=arax` → `map-arax`."""
    body = re.sub(r"[^a-z0-9]+", "-", path.lower().lstrip("?")).strip("-")
    return re.sub(r"(^|-)(view|sel)-", r"\1", body) or "overview"


def row_ids(build_dir: Path) -> list[str]:
    """Every component this build has a row for, from its `overview.json`."""
    path = build_dir / "overview.json"
    try:
        return [row["id"] for row in json.loads(path.read_text())["rows"]]
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise Missing(f"cannot read the rows from {path} ({error!r}); "
                      "run `uv run build-dashboard` first.") from None


def frozen_now(build_dir: Path) -> datetime:
    """The moment the page is told it is: when this build's data was synced.

    Not the wall clock, or a shot says "synced 12 minutes ago" and the same
    build shot two minutes later is a different PNG. Not a constant either, or
    every age on the page reads as however long ago that constant is from the
    sync. `synced_at` is empty for a build with no sync behind it.
    """
    try:
        return datetime.fromisoformat(json.loads((build_dir / "overview.json").read_text())["synced_at"])
    except (OSError, ValueError, KeyError):
        return UNSYNCED_NOW


def verdict(width: int, scroll: int, client: int) -> tuple[str, bool]:
    """What a table `scroll` wide in a `client`-wide wrap means: (text, failed)."""
    over = scroll - client
    if over <= 0:
        return "ok", False
    if width < OVERFLOW_FLOOR:
        return "scrolls (expected)", False
    if width in KNOWN_OVERFLOW and over <= KNOWN_OVERFLOW_MAX:
        return "OVERFLOW (known; issue #31)", False
    return "OVERFLOW", True


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


def new_context(browser, now: datetime, **options):
    """A browser context with motion off and the page's clock frozen at `now`."""
    context = browser.new_context(reduced_motion="reduce", **options)
    context.set_default_timeout(ACTION_TIMEOUT_MS)
    context.add_init_script(FREEZE_DATE % round(now.timestamp() * 1000))
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


def grow_to_fit(page, width: int) -> None:
    """Make the window tall enough that no element on the page still scrolls.

    Playwright's `full_page` does nothing here: the page root is `height: 100%;
    overflow: hidden` and the table scrolls inside `.tablewrap`, so the document
    is exactly as tall as the window and the rows below the fold stay cut off.
    """
    height = HEIGHT
    for _ in range(FULL_PASSES):
        over = page.evaluate(OVERHANG)
        if over <= 1:
            return
        height += over
        page.set_viewport_size({"width": width, "height": height})
        page.evaluate(SETTLE)
    raise Missing(f"{page.url} still scrolls at {width}x{height}; --full cannot fit it")


def shoot(page, base: str, path: str, width: int, args: argparse.Namespace, target: Path) -> None:
    from playwright.sync_api import Error as PlaywrightError
    from playwright.sync_api import TimeoutError as PlaywrightTimeout

    # The page is reused between paths, and a pointer left over a tooltip's
    # target by the last --hover would open that tooltip on this one too.
    page.mouse.move(0, 0)
    page.set_viewport_size({"width": width, "height": HEIGHT})
    arrive(page, base + path)
    try:
        ignored = page.evaluate(IGNORED, {"query": path, "rows": row_ids(args.build_dir)})
    except PlaywrightError as error:
        raise Missing(f"{page.url} cannot say what it did with {path!r} ({error.message.splitlines()[0]}), "
                      f"so {args.build_dir} may not be a dashboard build; "
                      "try `uv run build-dashboard`.") from None
    if ignored:
        raise Missing(f"the page ignored {', '.join(ignored)}: no such view, component or tab in this build")
    if args.click:
        first_visible(page, args.click).click()
        # A click focuses its target and focus opens a tooltip 240ms later: the
        # settle below is shorter than that on a quiet machine and longer on a
        # busy one. The target may also be gone by now, re-rendered, in which
        # case no mouseout would ever cancel it, so close it outright.
        page.mouse.move(0, 0)
        page.evaluate("TD.ui.tooltip.hide()")
        page.evaluate(SETTLE)
    if args.full:
        grow_to_fit(page, width)
    if args.hover:
        first_visible(page, args.hover).hover()
        try:
            page.wait_for_selector("#td-tip:not([hidden])", timeout=2000)
        except PlaywrightTimeout:
            raise Missing(f"hovering {args.hover!r} on {page.url} opened no tooltip") from None
        page.evaluate(SETTLE)
    target.parent.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(target))
    print(target.relative_to(ROOT) if target.is_relative_to(ROOT) else target)


def measure(page, base: str, widths: list[int]) -> bool:
    """Print the table's overflow per width; True if any of it fails."""
    failed = False
    for width in widths:
        page.set_viewport_size({"width": width, "height": MEASURE_HEIGHT})
        arrive(page, base + "?")
        page.add_style_tag(content=SCROLLBAR_CSS)
        page.evaluate(SETTLE)
        size = page.evaluate(
            "() => { const w = document.querySelector('div.tablewrap');"
            " return w && [w.scrollWidth, w.clientWidth, w.offsetWidth]; }")
        if not size:
            raise Missing(f"no div.tablewrap on {page.url}; the measurement has nothing to measure")
        scroll, client, outer = size
        if outer - client != SCROLLBAR_PX:
            raise Missing(f"div.tablewrap on {page.url} has no {SCROLLBAR_PX}px scrollbar at {width}px "
                          f"({outer - client}px), so this would not measure what it says")
        text, overflowed = verdict(width, scroll, client)
        failed = failed or overflowed
        print(f"{width:5}px  table {scroll} in {client}  {text}")
    return failed


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--build-dir", type=Path, default=ROOT / "data" / "dashboard",
                        help="the directory build-dashboard wrote (default data/dashboard)")
    parser.add_argument("--out", type=Path,
                        help="where the PNGs go (default data/shots); give each build its own to compare them")
    parser.add_argument("--path", action="append", metavar="QUERY",
                        help="a query string to shoot, starting with '?', e.g. '?view=map'; repeatable")
    parser.add_argument("--theme", choices=("light", "dark", "both"),
                        help="the colour scheme (default both)")
    parser.add_argument("--width", action="append", type=int, metavar="PX",
                        help="a window width; repeatable (default 1700, 1200, 760; "
                             "with --measure, 1000-1700 in 10px steps and 1px around the known band)")
    parser.add_argument("--full", action="store_true",
                        help="grow the window until nothing on the page scrolls, so every row is in the shot")
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
                      if sel) + ("-full" if args.full else "")
    now = frozen_now(args.build_dir)
    server, base = serve(args.build_dir)
    overflowed = False
    try:
        with sync_playwright() as playwright:
            try:
                # Shots keep scrollbars hidden, so a PNG does not depend on the
                # machine that took it; --measure wants them, see SCROLLBAR_CSS.
                browser = playwright.chromium.launch(
                    ignore_default_args=["--hide-scrollbars"] if args.measure else None)
            except PlaywrightError as error:
                print(str(error).splitlines()[0], file=sys.stderr)
                print("Install it once: uv run --group shots playwright install chromium", file=sys.stderr)
                return 2
            try:
                if args.measure:
                    context = new_context(browser, now)
                    overflowed = measure(context.new_page(), base, widths)
                    context.close()
                for theme in ([] if args.measure else themes):
                    context = new_context(browser, now, color_scheme=theme)
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
        print(f"The table overflows its window at {OVERFLOW_FLOOR}px or wider, beyond the known band.",
              file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
