"""Tests for translator_diagram.content: the repository's Markdown and CSV view.

Three properties matter here. The sheet CSV must round-trip through the
diagram's own loader, or it is not a replacement for the sheet. The private
block must reach exactly one place — the component's own page — and never
the payload the published dashboard is built from. And a rebuild that changes
nothing must write nothing, which is the whole basis of the refresh workflow.
"""

import json
from pathlib import Path

import pytest

from translator_diagram import loading, validation
from translator_diagram.components import ComponentFile, Deployment
from translator_diagram.components import load_components as load_files
from translator_diagram.content import (
    LIVE_MARKER,
    SHEET_COLUMNS,
    dashboard_markdown,
    deployment_rows,
    read_private,
    sheet_row,
    static_half,
    write_components_csv,
    write_content,
)
from translator_diagram.dashboard import (
    UNPLACED_TITLE,
    SyncedData,
    build_payload,
    load_stages,
)

ROOT = Path(__file__).resolve().parent.parent
COMPONENTS = ROOT / "components"
CONTENT = ROOT / "content"


def _comp(cid, **kwargs):
    kwargs.setdefault("refactor_status", "New in Refactor")
    return ComponentFile(id=cid, name=kwargs.pop("name", cid), owner="DOGSLED", **kwargs)


@pytest.fixture
def synced(tmp_path):
    """A manifest and nothing else: every cell resolves to "no version"."""
    sync = tmp_path / "sync"
    sync.mkdir()
    (sync / "manifest.json").write_text(
        json.dumps({"finished_at": "2026-09-01T00:00:00+00:00", "counts": {}})
    )
    return SyncedData(sync)


@pytest.fixture
def sample():
    """Three hand-built files covering every cell shape the sheet can hold."""
    return [
        _comp(
            "alpha",
            name="Alpha",
            connections={
                "gets_results_from": ["beta", "~gamma"],
                "calls": ["~beta"],
                "externals": [
                    {"direction": "in", "name": "Upstream, service"},
                    {"direction": "out", "name": "User"},
                ],
            },
            diagram={"hide": True},
            layer="Tier 1",
            itrb={"group": None},
            notes='Says "hi", twice',
            repositories=[{"url": "https://github.com/x/alpha", "role": "source"}],
        ),
        _comp(
            "beta",
            diagram={"ubiquitous": True},
            itrb={"group": "Group B"},
            part_of="Pack",
            hosted_at="RENCI",
            documentation=[{"url": "https://docs.example/beta", "kind": "wiki"}],
            environments={"ci": Deployment(env="ci", url="https://beta.ci/")},
        ),
        _comp("gamma"),
    ]


class TestSheetCsv:
    def test_columns_are_the_sheets(self):
        assert SHEET_COLUMNS[0] == "id" and SHEET_COLUMNS[-1] == "Tier"

    def test_round_trips_through_the_diagram_loader(self, sample, tmp_path):
        path = tmp_path / "components.csv"
        write_components_csv(sample, path)
        loaded = {c.id: c for c in loading.load_components(path, layer_column="Tier")}

        alpha = loaded["alpha"]
        assert alpha.name == "Alpha"
        assert (alpha.depends_on, alpha.depends_on_planned) == (["beta"], ["gamma"])
        assert (alpha.uses, alpha.uses_planned) == ([], ["beta"])
        assert alpha.externals == [("in", "Upstream, service"), ("out", "User")]
        assert alpha.hide is True and alpha.ubiquitous is False
        assert alpha.layer == "Tier 1"
        assert alpha.itrb == ""
        assert alpha.notes == 'Says "hi", twice'
        assert alpha.url == "https://github.com/x/alpha"

        beta = loaded["beta"]
        assert beta.ubiquitous is True and beta.hide is False
        assert beta.itrb == "Group B"
        assert (beta.part_of, beta.hosted_at) == ("Pack", "RENCI")
        # No source repository, so the first documentation link is the URL.
        assert beta.url == "https://docs.example/beta"

        assert loaded["gamma"].url == ""

    def test_the_real_files_round_trip_and_validate(self, tmp_path):
        files = load_files(COMPONENTS)
        path = tmp_path / "components.csv"
        write_components_csv(files, path)
        loaded = {c.id: c for c in loading.load_components(path, layer_column="Tier")}
        assert set(loaded) == {c.id for c in files}
        for component in files:
            edges = loaded[component.id]
            assert edges.depends_on + edges.uses == [
                ref for ref in component.upstream
                if not any(
                    raw.startswith("~") and raw[1:] == ref
                    for kind in ("gets_results_from", "calls")
                    for raw in component.connections.get(kind) or []
                )
            ]
        # What generate-diagram --input content/components.csv would check.
        assert validation.validate(list(loaded.values())) is True

    def test_no_carriage_returns(self, sample, tmp_path):
        path = tmp_path / "components.csv"
        write_components_csv(sample, path)
        assert b"\r" not in path.read_bytes()

    def test_a_blank_value_is_blank_not_none(self):
        assert sheet_row(_comp("solo"))["Part of"] == ""


class TestPrivate:
    def test_reads_only_files_with_a_block(self, tmp_path):
        (tmp_path / "a.yaml").write_text("id: a\nprivate:\n  notes: SENTINEL\n")
        (tmp_path / "b.yaml").write_text("id: b\n")
        assert read_private(tmp_path) == {"a": {"notes": "SENTINEL"}}

    def test_the_demo_blocks_exist(self):
        # The demo for issue #7 puts a block on three files. If this fails
        # because the blocks were removed on purpose, delete the test too.
        assert len(read_private(COMPONENTS)) >= 1

    def test_private_blocks_never_reach_the_payload(self, synced):
        """The guarantee the whole split rests on, checked on the real files.

        Data-driven: every string under every private: block is looked for in
        the serialised full payload — the one --include-private builds — so
        the test keeps holding when real values replace PRIVATE.
        """
        payload = build_payload(load_files(COMPONENTS), synced, None)

        def keys(value):
            if isinstance(value, dict):
                for key, inner in value.items():
                    yield key
                    yield from keys(inner)
            elif isinstance(value, list):
                for inner in value:
                    yield from keys(inner)

        assert "private" not in set(keys(payload))
        blob = json.dumps(payload)
        for cid, block in read_private(COMPONENTS).items():
            for leaf in _leaves(block):
                assert leaf not in blob, f"{cid}'s private {leaf!r} is in the payload"


def _leaves(value):
    if isinstance(value, dict):
        for inner in value.values():
            yield from _leaves(inner)
    elif isinstance(value, list):
        for inner in value:
            yield from _leaves(inner)
    elif isinstance(value, str) and value:
        yield value


class TestContentTree:
    def test_a_static_build_writes_what_a_checkout_determines(self, sample, tmp_path):
        written = write_content(sample, None, {}, tmp_path / "content")
        names = {p.relative_to(tmp_path / "content").as_posix() for p in written}
        assert names == {
            "components.csv",
            "components/README.md",
            "components/alpha.md",
            "components/beta.md",
            "components/gamma.md",
        }
        page = (tmp_path / "content" / "components" / "beta.md").read_text()
        assert LIVE_MARKER in page
        assert "No live data" in page
        # The file's own facts are all there.
        assert "https://beta.ci/" in page and "Group B" in page

    def test_a_full_build_adds_the_live_files(self, sample, synced, tmp_path):
        payload = build_payload(sample, synced, None)
        written = write_content(sample, payload, {}, tmp_path / "content")
        names = {p.name for p in written}
        assert {"dashboard.md", "deployments.csv"} <= names
        page = (tmp_path / "content" / "components" / "beta.md").read_text()
        assert "## Deployments" in page
        assert "No live data" not in page

    def test_deployments_has_a_row_per_component_and_environment(self, sample, synced):
        payload = build_payload(sample, synced, None)
        rows = deployment_rows(payload)
        assert len(rows) == len(sample) * 4
        deployed = [r for r in rows if r["deployed"]]
        assert [(r["id"], r["env"], r["url"]) for r in deployed] == [
            ("beta", "ci", "https://beta.ci/")
        ]

    def test_dashboard_has_one_band_per_stage_in_order(self, synced):
        files = load_files(COMPONENTS)
        payload = build_payload(files, synced, None)
        text = dashboard_markdown(payload)
        headings = [line[3:] for line in text.splitlines() if line.startswith("## ")]
        stages = load_stages()
        expected = [
            f"Step {n}: {stage['title']}"
            for n, stage in enumerate(stages, 1)
            if not stage.get("unplaced")
        ]
        # Every stage once, in file order; the unplaced band, if anything is
        # in it, comes last and is not numbered.
        assert headings[: len(expected)] == expected
        assert headings[len(expected) :] in ([], [UNPLACED_TITLE])

    def test_output_is_identical_across_runs_and_input_order(
        self, sample, synced, tmp_path
    ):
        payload = build_payload(sample, synced, None)
        first = tmp_path / "one"
        second = tmp_path / "two"
        write_content(sample, payload, {}, first)
        write_content(list(reversed(sample)), payload, {}, second)
        for path in sorted(first.rglob("*")):
            if path.is_file():
                twin = second / path.relative_to(first)
                assert path.read_bytes() == twin.read_bytes(), path.name

    def test_a_removed_component_loses_its_page(self, sample, tmp_path):
        out = tmp_path / "content"
        write_content(sample, None, {}, out)
        assert (out / "components" / "gamma.md").exists()
        write_content(sample[:2], None, {}, out)
        assert not (out / "components" / "gamma.md").exists()
        # The index is regenerated, not deleted.
        assert (out / "components" / "README.md").exists()

    def test_private_text_lands_on_exactly_one_page(self, sample, synced, tmp_path):
        payload = build_payload(sample, synced, None)
        out = tmp_path / "content"
        private = {"alpha": {"contacts": ["SENTINEL-CONTACT"], "notes": "SENTINEL-NOTE"}}
        write_content(sample, payload, private, out)
        carrying = sorted(
            p.relative_to(out).as_posix()
            for p in out.rglob("*")
            if p.is_file() and "SENTINEL" in p.read_text()
        )
        assert carrying == ["components/alpha.md"]
        page = (out / "components" / "alpha.md").read_text()
        assert page.index("## Private") < page.index(LIVE_MARKER)

