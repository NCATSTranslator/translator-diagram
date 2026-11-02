"""`tools/shoot.py`: the decisions it makes without a browser.

CI installs no Chromium, so what the tool does to a page is checked by running
it, as web/AGENTS.md describes. What is here is what must hold regardless: the
flags it refuses, and what an overflow of a given size at a given width means.
Playwright is imported inside `main`, so none of this needs the `shots` group.
"""

import importlib.util
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

SHOOT_PY = Path(__file__).resolve().parent.parent / "tools" / "shoot.py"


@pytest.fixture(scope="module")
def shoot():
    spec = importlib.util.spec_from_file_location("shoot", SHOOT_PY)
    module = importlib.util.module_from_spec(spec)
    sys.modules["shoot"] = module
    spec.loader.exec_module(module)
    yield module
    del sys.modules["shoot"]


@pytest.mark.parametrize("flag", [
    ["--path", "?view=map"],
    ["--theme", "dark"],
    ["--full"],
    ["--hover", ".mp-node"],
    ["--click", "button"],
    ["--out", "data/elsewhere"],
])
def test_measure_refuses_a_flag_it_would_ignore(shoot, flag, capsys):
    with pytest.raises(SystemExit) as raised:
        shoot.parse_args(["--measure", *flag])
    assert raised.value.code == 2
    assert flag[0] in capsys.readouterr().err


def test_measure_keeps_the_flags_it_uses(shoot):
    args = shoot.parse_args(["--measure", "--width", "1200", "--build-dir", "data/x"])
    assert args.width == [1200]


@pytest.mark.parametrize("path", ["view=map", "/index.html", ""])
def test_a_path_must_be_a_query(shoot, path, capsys):
    """Without the `?` it is appended to `index.html` and asks for a 404."""
    with pytest.raises(SystemExit) as raised:
        shoot.parse_args(["--path", path])
    assert raised.value.code == 2
    assert "must start with '?'" in capsys.readouterr().err


def test_no_flags_mean_every_surface(shoot):
    args = shoot.parse_args([])
    assert args.path is None and args.theme is None and args.out is None


def test_a_table_that_fits_is_ok(shoot):
    assert shoot.verdict(1700, 1652, 1652) == ("ok", False)


def test_overflow_below_the_floor_is_expected(shoot):
    assert shoot.verdict(shoot.OVERFLOW_FLOOR - 1, 1500, 900) == ("scrolls (expected)", False)


def test_overflow_at_the_floor_fails(shoot):
    assert shoot.verdict(shoot.OVERFLOW_FLOOR, 1001, 1000)[1] is True


def test_the_known_band_passes_as_far_over_as_it_was_measured(shoot):
    width = shoot.KNOWN_OVERFLOW.start
    text, failed = shoot.verdict(width, width + shoot.KNOWN_OVERFLOW_MAX, width)
    assert not failed and "known" in text


def test_the_known_band_fails_once_it_runs_further_over(shoot):
    """Tolerating the width alone would pass a column that went 300px over."""
    width = shoot.KNOWN_OVERFLOW.start
    assert shoot.verdict(width, width + shoot.KNOWN_OVERFLOW_MAX + 1, width) == ("OVERFLOW", True)


def test_the_known_band_fails_just_outside_it(shoot):
    for width in (shoot.KNOWN_OVERFLOW.start - 1, shoot.KNOWN_OVERFLOW.stop):
        assert shoot.verdict(width, width + 1, width) == ("OVERFLOW", True)


def test_the_sweep_sees_the_band_widen_by_a_pixel(shoot):
    band = shoot.KNOWN_OVERFLOW
    assert band.start - 1 in shoot.MEASURE_WIDTHS and band.stop in shoot.MEASURE_WIDTHS


def test_the_clock_is_frozen_at_the_sync(shoot, tmp_path):
    (tmp_path / "overview.json").write_text('{"synced_at": "2026-09-02T18:17:07+00:00"}')
    assert shoot.frozen_now(tmp_path) == datetime(2026, 9, 2, 18, 17, 7, tzinfo=UTC)


@pytest.mark.parametrize("body", [None, "{}", '{"synced_at": ""}', "not json"])
def test_a_build_with_no_sync_gets_a_fixed_clock(shoot, tmp_path, body):
    """Falling back to the wall clock would bring back the PNGs that differ."""
    if body is not None:
        (tmp_path / "overview.json").write_text(body)
    assert shoot.frozen_now(tmp_path) == shoot.UNSYNCED_NOW
