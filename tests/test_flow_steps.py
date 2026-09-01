"""config/flow-steps.yaml — the prose the dashboard bands its rows with.

Named for the file rather than for a module, like test_component_files.py:
this asserts the data still describes the platform, which no amount of testing
`load_flow_steps` can.

The prose is keyed by the components a step contains, so it cannot be attached
to the wrong rows — but it can go missing, which is what these tests are for.
One new dependency edge can move a component into a different step, and the
sentence that used to describe that step is then a sentence about a group that
no longer exists. The dashboard degrades quietly in that case, naming the band
after its layers; these tests are the part that does not stay quiet.
"""

from itertools import groupby
from pathlib import Path

import pytest

from translator_diagram.components import load_components
from translator_diagram.dashboard import ISOLATED_STEP, load_flow_steps
from translator_diagram.flow import flow_steps, in_flow_order, isolated

ROOT = Path(__file__).resolve().parent.parent
FLOW_STEPS_PATH = ROOT / "config" / "flow-steps.yaml"

FIX_IT = (
    "Rewrite the entry in config/flow-steps.yaml to match, or add one. The "
    "dashboard falls back to naming the band after its layers until you do, "
    "which is a worse label rather than a wrong one."
)


@pytest.fixture(scope="module")
def components():
    return load_components(ROOT / "components")


@pytest.fixture(scope="module")
def prose():
    return load_flow_steps(FLOW_STEPS_PATH)


@pytest.fixture(scope="module")
def steps(components):
    """The current steps, as {frozenset of component ids: step number}."""
    numbers = flow_steps(components)
    stranded = set(isolated(components))
    ordered = in_flow_order(components)
    out = {}
    for number, group in groupby(ordered, key=lambda c: numbers[c.id]):
        members = frozenset(c.id for c in group)
        out[ISOLATED_STEP if members & stranded else members] = number
    return out


def test_the_file_is_readable(prose):
    assert prose, f"No prose loaded from {FLOW_STEPS_PATH}"


def test_every_step_has_prose(steps, prose):
    missing = {
        number: sorted(key) if key != ISOLATED_STEP else key
        for key, number in steps.items()
        if key not in prose
    }
    assert not missing, f"Steps with no entry: {missing}. {FIX_IT}"


def test_no_entry_describes_a_step_that_no_longer_exists(steps, prose):
    # The other direction, and the one that catches a rename: prose left
    # behind after its components moved is invisible on the page.
    orphaned = [
        sorted(key) if key != ISOLATED_STEP else key
        for key in prose
        if key not in steps
    ]
    assert not orphaned, f"Entries matching no current step: {orphaned}. {FIX_IT}"


def test_the_isolated_group_is_described(prose):
    # It is the one entry that is not a set of components — which components
    # have no edges changes with the data — so it is keyed by name instead.
    assert ISOLATED_STEP in prose


@pytest.mark.parametrize("field", ["title", "description"])
def test_every_entry_says_something(prose, field):
    blank = [key for key, entry in prose.items() if not entry[field].strip()]
    assert not blank, f"Entries with an empty {field}: {blank}"


def test_a_title_is_a_name_not_a_sentence(prose):
    # The title sits in small caps beside "Step 3"; the sentence goes in the
    # description, which is styled to be read as one.
    long = {
        key: entry["title"] for key, entry in prose.items()
        if len(entry["title"]) > 40 or entry["title"].endswith(".")
    }
    assert not long, f"Titles that should be descriptions: {long}"


def test_a_missing_file_is_not_an_error(tmp_path):
    # The file is optional: without it every band is named after its layers.
    assert load_flow_steps(tmp_path / "nothing.yaml") == {}
