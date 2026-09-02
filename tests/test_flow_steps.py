"""config/flow-steps.yaml — the stages, and the row order they define.

Named for the file rather than for a module, like test_component_files.py.
`load_stages` is tested in test_dashboard.py; what is checked here is the data:
that the stages still account for every component, and in a way that fails
loudly rather than quietly.

The file is the order now, which makes one failure mode worth catching above
all others: a new component file that no stage names would simply appear at the
bottom under "Not yet placed", which looks deliberate. It is not, and these
tests are what says so.
"""

from pathlib import Path

import click
import pytest
import yaml

from translator_diagram.components import load_components
from translator_diagram.dashboard import UNPLACED_TITLE, in_stage_order, load_stages

ROOT = Path(__file__).resolve().parent.parent
STAGES_PATH = ROOT / "config" / "flow-steps.yaml"

FIX_IT = (
    "Place it in a stage in config/flow-steps.yaml, or name it under "
    "`unplaced` if it genuinely belongs to none yet."
)


@pytest.fixture(scope="module")
def raw():
    return yaml.safe_load(STAGES_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def stages():
    return load_stages(STAGES_PATH)


@pytest.fixture(scope="module")
def components():
    return load_components(ROOT / "components")


@pytest.fixture(scope="module")
def listed(stages):
    return [cid for stage in stages for cid in stage["components"]]


def test_every_component_is_accounted_for(components, listed):
    missing = sorted({c.id for c in components} - set(listed))
    assert not missing, f"Components in no stage: {missing}. {FIX_IT}"


def test_nothing_is_listed_twice(listed):
    # Two stages claiming one component would show it twice, in two places,
    # each looking authoritative.
    duplicated = sorted({cid for cid in listed if listed.count(cid) > 1})
    assert not duplicated, f"Components claimed by more than one stage: {duplicated}"


def test_every_listed_component_exists(components, listed):
    # A typo here is invisible on the page: the id simply never matches, and
    # the component it meant to place falls to the bottom instead.
    unknown = sorted(set(listed) - {c.id for c in components})
    assert not unknown, f"Ids with no components/<id>.yaml: {unknown}"


def test_the_stages_are_the_page_order(components, stages):
    ordered = in_stage_order(components, stages)
    numbers = [number for _, number, _ in ordered]
    assert numbers == sorted(numbers), "Stages must come out in file order"
    assert [c.id for c, _, _ in ordered][: len(stages[0]["components"])] == list(
        stages[0]["components"]
    ), "Components must keep the order their stage lists them in"


def test_every_stage_says_what_it_is_and_what_it_is_for(stages):
    blank = [
        stage.get("title") or "(untitled)"
        for stage in stages
        if not (stage["title"].strip() and stage["description"].strip())
    ]
    assert not blank, f"Stages missing a title or a description: {blank}"


def test_a_title_is_a_name_not_a_sentence(stages):
    # The title sits in small caps beside "Step 3"; the sentence goes in the
    # description, which is styled to be read as one.
    long = [
        stage["title"] for stage in stages
        if len(stage["title"]) > 40 or stage["title"].endswith(".")
    ]
    assert not long, f"Titles that should be descriptions: {long}"


def test_the_unplaced_block_is_last_and_named(stages):
    assert stages[-1]["unplaced"] is True
    assert stages[-1]["title"] == UNPLACED_TITLE
    assert not any(stage.get("unplaced") for stage in stages[:-1])


def test_unplaced_is_a_deliberate_list_not_a_leftover(raw):
    # Same contract as unknown.yaml: an entry leaves by being placed, and
    # something arriving here by accident fails the test above instead.
    assert (raw.get("unplaced") or {}).get("description")


def test_a_missing_file_is_refused(components, tmp_path):
    # Not an empty list: in_stage_order falls back to data-flow order, which
    # is the ordering this file exists to replace, so a build that cannot find
    # it must stop rather than publish that page.
    with pytest.raises(click.ClickException):
        load_stages(tmp_path / "absent.yaml")
    ordered = in_stage_order(components, [])
    assert len(ordered) == len(components)
    assert {number for _, number, _ in ordered} == {1}
