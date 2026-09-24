"""Assembling the payload and rendering the page, from a fixture directory."""

import base64
import json
import re
from pathlib import Path

import click
import pytest

from tests.dashboard_helpers import _comp, _row
from translator_diagram import dashboard
from translator_diagram.dashboard import (
    build_catalog_edges,
    build_edges,
    build_externals,
    build_payload,
    render_html,
    source_tally,
    verify_references,
    write_dashboard,
)
from translator_diagram.rows import build_rows
from translator_diagram.synced_data import SyncedData


class TestPayload:
    def test_the_tally_counts_every_deployment(self, component, synced):
        rows = build_rows([component], synced)
        tally = source_tally(rows)
        assert sum(tally.values()) == 3  # ci, test, prod
        assert tally["openapi"] == 3

    def test_uptime_comes_from_the_registry(self, component, synced):
        assert build_rows([component], synced)[0]["uptime"] == "pass"

    def test_payload_carries_the_sync_timestamp(self, component, synced):
        payload = build_payload([component], synced)
        assert payload["generated_at"] == "2026-08-31T00:01:00+00:00"
        assert payload["sync_counts"]["failed"] == 1

    def test_both_badge_vocabularies_reach_the_page(self, component, synced):
        # The page renders a badge by looking its key up in these; a key the
        # payload does not carry renders as the raw key, which is how "openapi"
        # or "registry" would end up in the table in lower case.
        payload = build_payload([component], synced)
        assert payload["source_labels"]["openapi"] == "OpenAPI"
        assert set(payload["updated_labels"]) == {"release", "registry"}

    def test_owner_styles_reach_the_payload(self, component, synced):
        # Derived once here rather than in each renderer: a page and a legend
        # working out the same gradient separately is how the two come to
        # disagree about what colour a team is.
        styles = build_payload([component], synced)["owner_styles"]
        assert set(styles) == set(build_payload([component], synced)["owner_colors"])
        one = styles["DOGSLED"]
        assert one["text"] in ("black", "white")
        assert len(one["metal"]) == 4
        assert one["base"].startswith("#")

    def test_unclaimed_charts_and_suggestions_reach_the_payload(self, synced):
        # The two lists a data PR is written from: charts nothing accounts for,
        # and registry records we attached ourselves that want an id recording.
        root = synced.root
        (root / "helm").mkdir(exist_ok=True)
        (root / "helm" / "index.json").write_text(json.dumps([
            {"name": "my-chart", "type": "dir"},
            {"name": "robokop", "type": "dir"},
            {"name": "README.md", "type": "file"},
        ]))
        for chart, description in (
            ("my-chart", "A Helm chart for Kubernetes"),
            ("robokop", "The ROBOKOP user interface"),
        ):
            (root / "helm" / chart).mkdir()
            (root / "helm" / chart / "Chart.yaml").write_text(
                f"name: {chart}\ndescription: {description}\n"
            )
        (root / "smartapi.json").write_text(json.dumps({"hits": [{
            "_id": "xyz",
            "info": {"title": "Service API",
                     "x-translator": {"infores": "infores:svc"}},
            "servers": [{"url": "https://svc.ci/", "x-maturity": "staging"}],
        }]}))
        component = _comp("svc", identifiers={
            "infores": "infores:svc", "helm_chart": "my-chart"})
        payload = build_payload([component], SyncedData(root))
        assert payload["unclaimed_charts"] == [
            {"name": "robokop", "description": "The ROBOKOP user interface"}]
        assert payload["smartapi_suggestions"] == [{
            "component": "svc", "smartapi_id": "xyz", "title": "Service API"}]

    def test_a_chart_a_withheld_component_claims_is_not_unclaimed(
        self, synced, tmp_path
    ):
        # `unclaimed_charts` is matched against every component rather than the
        # kept rows, and this is why: asking the rows would publish `jaeger` by
        # name on the one build that must not say it.
        from translator_diagram.privacy import Policy, Redaction

        root = synced.root
        (root / "helm").mkdir(exist_ok=True)
        (root / "helm" / "index.json").write_text(
            json.dumps([{"name": "jaeger", "type": "dir"}])
        )
        (root / "helm" / "jaeger").mkdir()
        (root / "helm" / "jaeger" / "Chart.yaml").write_text("name: jaeger\n")
        components = [
            _comp("svc", identifiers={"smartapi": "abc"}),
            _comp("jaeger", identifiers={"helm_chart": "jaeger"}),
        ]
        payload = build_payload(
            components, SyncedData(root), Policy(components=(Redaction("jaeger"),))
        )
        assert payload["unclaimed_charts"] == []

    def test_every_row_carries_what_a_band_needs(self, component, synced):
        # Adding a key to the payload is safe and renaming one is not: the JS
        # reads these three by name to draw a band, and a row missing any of
        # them silently loses its heading.
        row = build_payload([component], synced)["rows"][0]
        for key in ("step", "step_label", "step_title", "step_description"):
            assert key in row


    def test_the_component_page_gets_the_schema_the_repo_url_and_unknown(
        self, component, synced
    ):
        payload = build_payload([component], synced)
        assert payload["repo_url"] == dashboard.REPO_URL
        assert "properties" in payload["component_schema"]
        assert isinstance(payload["unknown"], list)
        assert "recorded" in payload["rows"][0]


class TestVerifyReferences:
    """Every id the payload points at must be a row it carries."""

    def _payload(self, **overrides):
        payload = {
            "rows": [
                {"id": "a", "connections": {"calls": ["B"], "gets_results_from": []}},
                {"id": "b", "connections": {}},
            ],
            "edges": [
                {"from": "a", "to": "b", "kind": "calls", "planned": False},
                {"from": "Source", "to": "a", "kind": "external_in", "planned": False},
                {"from": "b", "to": "User", "kind": "external_out", "planned": False},
            ],
            "externals": [
                {"name": "Source", "direction": "in"},
                {"name": "User", "direction": "out"},
            ],
            "catalog_edges": [{"from": "a", "to": "b", "kind": "catalog"}],
            "stages": [{"step": 1, "title": "One", "components": ["a", "b"]}],
        }
        payload.update(overrides)
        return payload

    def test_a_consistent_payload_passes(self):
        verify_references(self._payload())

    def test_references_resolve_case_insensitively_and_through_the_tilde(self):
        payload = self._payload()
        payload["rows"][0]["connections"]["calls"] = ["~B"]
        verify_references(payload)

    def test_a_dangling_edge_is_an_error(self):
        payload = self._payload()
        payload["edges"].append({"from": "a", "to": "ghost", "kind": "calls", "planned": False})
        with pytest.raises(click.ClickException, match="'ghost' in edges"):
            verify_references(payload)

    def test_an_external_name_is_not_an_id(self):
        # The external end of an external edge is a name, and is skipped; the
        # component end is still checked.
        payload = self._payload()
        payload["edges"].append(
            {"from": "Elsewhere", "to": "ghost", "kind": "external_in", "planned": False}
        )
        with pytest.raises(click.ClickException, match="'ghost'"):
            verify_references(payload)

    def test_a_dangling_stage_roster_or_connection_is_an_error(self):
        payload = self._payload()
        payload["stages"][0]["components"].append("nobody")
        payload["rows"][1]["connections"] = {"calls": ["nobody"]}
        with pytest.raises(click.ClickException) as raised:
            verify_references(payload)
        assert "stage 'One'" in str(raised.value)
        assert "b.connections.calls" in str(raised.value)

    def test_the_real_build_has_no_dangling_reference(self, component, synced):
        verify_references(build_payload([component], synced))


class TestCatalogEdges:
    """The catalog's own dataflow graph, between components the page shows."""

    def _catalog_row(self, cid, infores, **catalog):
        return _row(
            cid,
            infores=infores,
            catalog={"consumes": [], "consumed_by": [], **catalog},
        )

    def test_consumes_points_from_the_consumed_to_the_consumer(self):
        rows = [
            self._catalog_row("ars", "infores:ars", consumes=["infores:arax"]),
            self._catalog_row("arax", "infores:arax"),
        ]
        assert build_catalog_edges(rows) == [
            {"from": "arax", "to": "ars", "kind": "catalog"}]

    def test_consumed_by_gives_the_mirror(self):
        rows = [
            self._catalog_row("arax", "infores:arax", consumed_by=["infores:ars"]),
            self._catalog_row("ars", "infores:ars"),
        ]
        assert build_catalog_edges(rows) == [
            {"from": "arax", "to": "ars", "kind": "catalog"}]

    def test_the_two_statements_are_deduped(self):
        # The catalog records most of these from both ends.
        rows = [
            self._catalog_row("ars", "infores:ars", consumes=["infores:arax"]),
            self._catalog_row("arax", "infores:arax", consumed_by=["infores:ars"]),
        ]
        assert build_catalog_edges(rows) == [
            {"from": "arax", "to": "ars", "kind": "catalog"}]

    def test_an_infores_with_no_row_is_dropped(self):
        # arax consumes forty-odd knowledge sources, and none of them is a
        # component here. A withheld component has no row either, which is what
        # keeps a published build's catalog graph honest without a second pass.
        rows = [self._catalog_row(
            "arax", "infores:arax", consumes=["infores:automat-cohd"])]
        assert build_catalog_edges(rows) == []

    def test_a_row_with_no_catalog_entry_contributes_nothing(self):
        assert build_catalog_edges([_row("svc")]) == []


class TestOtelTile:
    def _synced(self, tmp_path, bodies):
        (tmp_path / "manifest.json").write_text('{"fetches": []}')
        (tmp_path / "smartapi.json").write_text('{"hits": []}')
        (tmp_path / "otel").mkdir()
        for env, body in bodies.items():
            (tmp_path / "otel" / f"{env}.json").write_text(json.dumps(body))
        return SyncedData(tmp_path)

    def test_the_total_is_distinct_across_collectors(self, tmp_path, component):
        # Only a couple of services report to all three, so summing the three
        # counts would count most of them twice over.
        synced = self._synced(tmp_path, {
            "ci": {"data": ["a", "b"]},
            "test": {"data": ["b", "c"]},
            "prod": {"data": ["c"]},
        })
        payload = build_payload([component], synced)
        assert payload["otel_service_counts"] == {"ci": 2, "test": 2, "prod": 1}
        assert payload["otel_service_total"] == 3

    def test_a_collector_answering_with_objects_costs_the_tile_not_the_build(
        self, tmp_path, component
    ):
        # `data` is an array of service names today. An array of objects would
        # be unhashable, and taking the whole build down over a footnote tile
        # is not a trade worth making.
        synced = self._synced(tmp_path, {
            "ci": {"data": [{"name": "a"}, "b"]},
            "test": {"data": "not-a-list"},
            "prod": {},
        })
        payload = build_payload([component], synced)
        assert payload["otel_service_counts"] == {"ci": 1, "test": 0, "prod": 0}
        assert payload["otel_service_total"] == 1


class TestRendering:
    def test_every_component_appears(self, component, synced):
        html = render_html(build_payload([component], synced))
        assert "svc" in html

    def test_the_inlined_payload_matches_the_written_json(self, component, synced, tmp_path):
        payload = build_payload([component], synced)
        html_path, json_path = write_dashboard(payload, tmp_path / "out")
        html = html_path.read_text()
        start = html.index('id="payload">') + len('id="payload">')
        inline = html[start:html.index("</script>", start)].replace("<\\/", "</")
        assert json.loads(inline) == json.loads(json_path.read_text())

    def test_a_closing_script_tag_in_the_data_cannot_escape(self, tmp_path, synced):
        # Notes come from a spreadsheet. An unescaped </script> there would end
        # the block early and break the page for everyone.
        component = _comp("svc", identifiers={"smartapi": "abc"}, notes="</script><b>x")
        html = render_html(build_payload([component], synced))
        body = html[html.index('id="payload">'):]
        assert "</script><b>" not in body[: body.index("</script>")]

    def test_the_page_is_self_contained(self, component, synced):
        """No external resources: it must open from file://, with no network.

        The rule is what a `<link>` points *at*, not whether there is one. It
        used to be "no <link at all", which was the same thing while the page
        had none — and stopped being the same thing the moment the favicon
        arrived, because an icon inlined as a data URI is not a resource and
        fetches nothing. So every link is checked for a data: href, and a
        stylesheet from a CDN fails here exactly as it did before.
        """
        html = render_html(build_payload([component], synced))
        links = re.findall(r"<link[^>]*>", html)
        assert links, "the favicon link is gone: this test now checks nothing"
        for tag in links:
            assert 'href="data:' in tag, tag
        assert "script src=" not in html

    def test_the_page_carries_the_icon_it_ships(self, component, synced):
        # The bytes in web/favicon.ico, not a placeholder and not a re-encode:
        # what goes into the page has to be the file the repository holds.
        raw = (
            Path(dashboard.__file__).parent / "web" / dashboard.FAVICON_FILE
        ).read_bytes()
        html = render_html(build_payload([component], synced))
        expected = base64.b64encode(raw).decode("ascii")
        assert f'href="data:image/x-icon;base64,{expected}"' in html

    def test_the_page_asks_not_to_be_indexed(self, component, synced):
        """Reachable by link, not by search. A deliberate decision that should
        be removed on purpose rather than lost in a template edit — see the
        public/private split in issue #7."""
        html = render_html(build_payload([component], synced))
        assert '<meta name="robots" content="noindex, nofollow">' in html


class TestEdges:
    def test_a_results_edge_points_the_way_data_moves(self):
        # `gets_results_from` is written from the caller's side. An arrow on a
        # map points where the data goes, so the recorded direction is
        # reversed: A gets results from B means the data leaves B.
        rows = [_row("a", connections={"gets_results_from": ["b"]}), _row("b")]
        assert build_edges(rows) == [
            {"from": "b", "to": "a", "kind": "results", "planned": False}]

    def test_a_calls_edge_is_not_reversed(self):
        # The request leaves the caller, so this one is already pointing the
        # way the arrow should. Reversing both would send half of them upstream.
        rows = [_row("a", connections={"calls": ["b"]}), _row("b")]
        assert build_edges(rows) == [
            {"from": "a", "to": "b", "kind": "calls", "planned": False}]

    def test_a_planned_edge_is_marked(self):
        # And coexists with the implemented one: they are different claims —
        # this is wired, and this is meant to be — and the map draws them apart.
        rows = [
            _row("a", connections={"calls": ["b"], "planned_calls": ["b"]}),
            _row("b"),
        ]
        assert build_edges(rows) == [
            {"from": "a", "to": "b", "kind": "calls", "planned": False},
            {"from": "a", "to": "b", "kind": "calls", "planned": True},
        ]

    def test_an_external_in_and_an_external_out(self):
        rows = [
            _row("a", externals=[{"direction": "in", "name": "External Data Sources"}]),
            _row("b", externals=[{"direction": "out", "name": "User"}]),
        ]
        assert build_edges(rows) == [
            {"from": "External Data Sources", "to": "a",
             "kind": "external_in", "planned": False},
            {"from": "b", "to": "User", "kind": "external_out", "planned": False},
        ]

    def test_an_edge_to_a_missing_row_is_dropped(self):
        # What makes a published build's graph smaller rather than holed: nine
        # component files call jaeger, and jaeger has no row.
        rows = [_row("a", connections={"calls": ["gone"], "gets_results_from": ["gone"]})]
        assert build_edges(rows) == []

    def test_a_reference_resolves_case_insensitively(self):
        # The same rule references follow everywhere else here; the edge
        # carries the id as the component file spells it.
        rows = [_row("a", connections={"calls": ["B"]}), _row("b")]
        assert build_edges(rows)[0]["to"] == "b"

    def test_externals_are_unique_and_first_seen(self):
        rows = [
            _row("a", externals=[{"direction": "in", "name": "Sources"}]),
            _row("b", externals=[
                {"direction": "out", "name": "User"},
                {"direction": "in", "name": "Sources"},
            ]),
        ]
        assert build_externals(rows) == [
            {"name": "Sources", "direction": "in"},
            {"name": "User", "direction": "out"},
        ]
