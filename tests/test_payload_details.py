"""Tests for translator_diagram.payload_details.

The class this file exists for is TestHelmDetail: the module promises that a
Helm block never carries a container image, and the only check worth having on
that promise is one that reads the real cached charts and looks.
"""

import re
from pathlib import Path

import pytest
import yaml

from translator_diagram.payload_details import (
    BODY_EXCERPT,
    RELEASES_DETAILED,
    catalog_detail,
    helm_detail,
    releases_detail,
    repo_meta_detail,
    smartapi_detail,
    strip_html,
)

HELM_CACHE = Path(__file__).resolve().parent.parent / "data" / "sync" / "helm"


def _cached_charts() -> list[Path | None]:
    """Every chart directory `sync-components` left behind, or `[None]`.

    `data/` is gitignored scratch space, so a fresh checkout has no charts to
    read and this becomes one skipped case with a reason rather than a silent
    pass on nothing.
    """
    if not HELM_CACHE.is_dir():
        return [None]
    found = sorted(
        path
        for path in HELM_CACHE.iterdir()
        if (path / "Chart.yaml").is_file() and (path / "values.yaml").is_file()
    )
    return found or [None]


class TestStripHtml:
    def test_tags_come_out_and_text_stays(self):
        assert strip_html("<p>A <b>TRAPI</b> service</p>", limit=100) == (
            "A TRAPI service"
        )

    def test_entities_are_decoded(self):
        assert strip_html("R&amp;D &lt;team&gt; &#8212; ok", limit=100) == (
            "R&D <team> — ok"
        )

    def test_a_long_description_is_truncated_with_an_ellipsis(self):
        out = strip_html("word " * 400, limit=40)
        assert out.endswith("…")
        # The limit counts the returned string, ellipsis included, so a caller
        # sizing a panel gets the number it asked for.
        assert len(out) <= 40

    def test_malformed_html_costs_the_field_not_the_build(self, monkeypatch):
        # html.parser is tolerant enough that no fixture reliably makes it
        # raise, so the failure is injected: whatever a future parser does on a
        # document nobody has seen, the field goes and the build stands.
        class Exploding:
            def __init__(self):
                self.parts = []

            def feed(self, _data):
                raise ValueError("unparseable")

        monkeypatch.setattr(
            "translator_diagram.payload_details._TextOnly", Exploding
        )
        assert strip_html("<p>anything</p>", limit=100) is None

    def test_whitespace_is_collapsed(self):
        assert strip_html("<p>one\n\n  two\t\tthree</p>", limit=100) == (
            "one two three"
        )

    @pytest.mark.parametrize("value", [None, 42, [], {}, "", "   "])
    def test_a_non_string_is_none(self, value):
        assert strip_html(value, limit=100) is None


class TestSmartapiDetail:
    def test_the_underscore_spelling_of_the_biolink_version_is_read(self):
        # Retriever registers `biolink_version`; 98 of the other records spell
        # it `biolink-version`. Reading only the hyphen showed Retriever as
        # having no Biolink version at all, which reads as a finding about the
        # team rather than about our parser.
        record = {
            "_id": "abc",
            "info": {"x-translator": {"biolink_version": "4.3.2"}},
        }
        assert smartapi_detail(record)["biolink_version"] == "4.3.2"

    def test_the_hyphen_spelling_still_wins_where_both_appear(self):
        record = {
            "_id": "abc",
            "info": {
                "x-translator": {
                    "biolink-version": "4.2.6",
                    "biolink_version": "1.0.0",
                }
            },
        }
        assert smartapi_detail(record)["biolink_version"] == "4.2.6"

    def test_a_test_data_location_url_list_takes_the_first(self):
        record = {
            "_id": "abc",
            "info": {
                "x-trapi": {
                    "test_data_location": {
                        "default": {"url": ["https://a.example/one.json",
                                            "https://b.example/two.json"]}
                    }
                }
            },
        }
        assert smartapi_detail(record)["trapi"]["test_data_location"] == {
            "default": "https://a.example/one.json"
        }

    @pytest.mark.parametrize(
        "value",
        [
            "https://example.test/tests.json",
            ["https://example.test/tests.json"],
            {"default": "https://example.test/tests.json"},
            {"default": {"href": "https://example.test/tests.json"}},
            42,
        ],
    )
    def test_an_unseen_test_data_shape_is_dropped(self, value):
        record = {"_id": "abc", "info": {"x-trapi": {"test_data_location": value}}}
        assert smartapi_detail(record)["trapi"]["test_data_location"] is None

    def test_tags_become_names(self):
        record = {
            "_id": "abc",
            "tags": [{"name": "trapi"}, {"name": "query"}, {"no": "name"}, "loose"],
        }
        assert smartapi_detail(record)["tags"] == ["trapi", "query"]

    @pytest.mark.parametrize("record", [None, {}, [], "", 0])
    def test_an_empty_record_is_none(self, record):
        assert smartapi_detail(record) is None

    def test_the_registry_url_names_the_record(self):
        detail = smartapi_detail({"_id": "7a12feb2fbd8fe4af532a77ee19b7800"})
        assert detail["registry_url"] == (
            "https://smart-api.info/ui/7a12feb2fbd8fe4af532a77ee19b7800"
        )

    def test_a_record_with_no_id_has_no_registry_url(self):
        assert smartapi_detail({"info": {"title": "Nameless"}})["registry_url"] is None

    def test_missing_blocks_cost_their_fields_and_nothing_else(self):
        detail = smartapi_detail({"_id": "abc"})
        assert detail["title"] is None
        assert detail["team"] == []
        assert detail["servers"] == []
        assert detail["status"]["uptime_msg"] == []
        assert detail["matched_by"] == "id"


class TestHelmDetail:
    @pytest.mark.parametrize(
        "chart_dir",
        _cached_charts(),
        ids=lambda path: path.name if path is not None else "no-charts-cached",
    )
    def test_the_helm_block_carries_no_image(self, chart_dir):
        # The rule the module exists to hold, checked against the real charts
        # rather than against fixtures written to pass it. Image repositories
        # and tags belong to `helm_images`, which config/privacy.yaml withholds
        # from the published page: beside the version grid they are a CVE
        # inventory.
        if chart_dir is None:
            pytest.skip(
                "data/sync/helm/ holds no charts; run `uv run sync-components`"
            )
        detail = helm_detail(
            chart_dir.name,
            yaml.safe_load((chart_dir / "Chart.yaml").read_text(encoding="utf-8")),
            yaml.safe_load((chart_dir / "values.yaml").read_text(encoding="utf-8")),
            f"https://example.test/helm/{chart_dir.name}",
        )
        leaks = _image_leaks(detail)
        assert not leaks, (
            f"{chart_dir.name}: the Helm block must never carry a container "
            f"image, and this one does: " + "; ".join(leaks)
        )

    def test_the_image_scan_can_actually_fail(self):
        # Negative control for the scan above. A check that has never been seen
        # to fail is a check nobody can trust, and the charts it reads are all
        # expected to pass — so the detector is shown catching each of the
        # three things it looks for.
        assert _image_leaks({"services": [{"image": "busybox"}]})
        assert _image_leaks({"chart": "x", "tag": "latest"})
        assert _image_leaks({"a": {"repository": "ghcr.io/team/thing"}})
        assert _image_leaks({"note": "pulled from quay.io/team/thing"})
        assert not _image_leaks(
            {"dependencies": [{"repository": "https://charts.bitnami.com/bitnami"}]}
        )

    def test_a_chart_repository_dependency_is_not_an_image_repository(self):
        # The one `repository` allowed anywhere in the block. It names where
        # the subchart was packaged, not what runs.
        detail = helm_detail(
            "answer-appraiser",
            {
                "name": "answer-appraiser",
                "dependencies": [
                    {
                        "name": "redis",
                        "version": "17.9.3",
                        "repository": "https://charts.bitnami.com/bitnami",
                    }
                ],
            },
            {},
            None,
        )
        assert detail["dependencies"] == [
            {
                "name": "redis",
                "version": "17.9.3",
                "repository": "https://charts.bitnami.com/bitnami",
            }
        ]
        assert not _image_leaks(detail)

    def test_a_root_level_resources_block_is_a_service_named_for_the_chart(self):
        # answer-appraiser and test-harness both put the workload's resources
        # at the top of values.yaml, where there is no path to name it after.
        detail = helm_detail(
            "test-harness",
            {"name": "test-harness"},
            {"resources": {"requests": {"cpu": "800m", "memory": "8Gi"}}},
            None,
        )
        assert [s["name"] for s in detail["services"]] == ["test-harness"]
        assert detail["services"][0]["requests"] == {"cpu": "800m", "memory": "8Gi"}
        assert detail["services"][0]["limits"] is None

    def test_a_list_item_with_resources_is_not_a_service(self):
        # answer-appraiser's `redis.master.initContainers[0]` has a resources
        # block and is an init container. The walk enters mappings only.
        detail = helm_detail(
            "answer-appraiser",
            {"name": "answer-appraiser"},
            {
                "redis": {
                    "master": {
                        "resources": {"limits": {"cpu": 2, "memory": "20Gi"}},
                        "initContainers": [
                            {
                                "name": "download-db",
                                "resources": {"limits": {"cpu": 2, "memory": "20Gi"}},
                            }
                        ],
                    }
                }
            },
            None,
        )
        assert [s["name"] for s in detail["services"]] == ["redis.master"]

    def test_an_autoscaling_block_is_not_a_service(self):
        # Real: gandalf's `app.gandalf.autoscaling.replicaCount: 1` came out as
        # a workload of its own, beside the `app.gandalf` it configures. An
        # autoscaling block says what a workload would scale to; it is not one.
        detail = helm_detail(
            "gandalf",
            {"name": "gandalf"},
            {
                "app": {
                    "gandalf": {
                        "resources": {"requests": {"cpu": "2000m"}},
                        "autoscaling": {"enabled": False, "replicaCount": 1},
                    }
                }
            },
            None,
        )
        assert [s["name"] for s in detail["services"]] == ["app.gandalf"]

    def test_a_storage_mapping_is_not_a_size(self):
        # jaeger's `jaeger.storage` is a mapping of storage backends. Read as a
        # size it would publish a dictionary as a disk.
        detail = helm_detail(
            "jaeger",
            {"name": "jaeger"},
            {"jaeger": {"storage": {"cassandra": {"user": "user"}}}},
            None,
        )
        assert detail["storage"] == []

    def test_a_persistence_wrapper_is_dropped_from_the_name(self):
        detail = helm_detail(
            "shepherd",
            {"name": "shepherd"},
            {
                "redis": {"master": {"persistence": {"size": "20Gi"}}},
                "logs": {"persistentVolume": {"size": "3Gi"}},
                "solr": {"storage": "400Gi"},
            },
            None,
        )
        assert detail["storage"] == [
            {"name": "logs", "size": "3Gi"},
            {"name": "redis.master", "size": "20Gi"},
            {"name": "solr", "size": "400Gi"},
        ]

    def test_placeholder_ingress_hosts_are_dropped(self):
        # `ingress_HOST` published as a hostname is worse than an empty list:
        # it looks like a fact.
        detail = helm_detail(
            "shepherd",
            {"name": "shepherd"},
            {
                "ingress": {"host": "ingress_HOST"},
                "itrb": {"ingress": {"host": None}},
                "other": {"ingress": {"host": "  "}},
                "third": {"ingress": {"host": "fillthisin"}},
                "fourth": {"ingress": {"hosts": [{"host": "change-me"}]}},
            },
            None,
        )
        assert detail["ingress_hosts"] == []

    def test_real_ingress_hosts_survive_in_both_spellings(self):
        detail = helm_detail(
            "answer-appraiser",
            {"name": "answer-appraiser"},
            {
                "ingress": {"host": "answerappraiser.renci.org"},
                "extra": {"ingress": {"hosts": [{"host": "b.example"}, "loose"]}},
            },
            None,
        )
        assert detail["ingress_hosts"] == ["answerappraiser.renci.org", "b.example"]

    def test_quantities_keep_the_charts_spelling(self):
        detail = helm_detail(
            "shepherd",
            {"name": "shepherd"},
            {
                "arax_pathfinder": {
                    "resources": {
                        "requests": {"cpu": "5000m", "memory": "20Gi"},
                        "limits": {"cpu": 2, "memory": "22Gi"},
                    }
                }
            },
            None,
        )
        service = detail["services"][0]
        # Never parsed into cores and bytes: a reader who checks the number
        # against values.yaml must find the same characters there.
        assert service["requests"] == {"cpu": "5000m", "memory": "20Gi"}
        assert service["limits"] == {"cpu": "2", "memory": "22Gi"}

    def test_a_zero_replica_count_is_a_zero_not_a_gap(self):
        # answer-appraiser scales `redis.replica` to 0 on purpose. A falsy test
        # here would report it as "the chart does not say", which is a
        # different claim.
        detail = helm_detail(
            "answer-appraiser",
            {"name": "answer-appraiser"},
            {"redis": {"replica": {"replicaCount": 0}}},
            None,
        )
        assert detail["services"] == [
            {
                "name": "redis.replica",
                "replicas": 0,
                "requests": None,
                "limits": None,
            }
        ]

    @pytest.mark.parametrize("chart", [None, "", 0, False])
    def test_a_falsy_chart_is_none(self, chart):
        assert helm_detail(chart, {"name": "x"}, {}, None) is None

    def test_the_app_version_is_kept_apart_from_the_chart_version(self):
        detail = helm_detail(
            "name-lookup",
            {"name": "name-lookup", "version": "0.5.2", "appVersion": "1.5.2_2025sep1"},
            {},
            "https://example.test/helm/name-lookup",
        )
        assert detail["chart_version"] == "0.5.2"
        assert detail["app_version"] == "1.5.2_2025sep1"
        assert "version" not in detail

    def test_an_unquoted_app_version_survives_yaml_reading_it_as_a_number(self):
        detail = helm_detail("shepherd", {"appVersion": 1.0}, {}, None)
        assert detail["app_version"] == "1.0"

    def test_the_directory_name_stands_in_for_a_chart_with_no_name(self):
        assert helm_detail("shepherd", {}, {}, None)["chart"] == "shepherd"


class TestReleasesDetail:
    def test_at_most_ten_are_returned(self):
        entries = [
            {"tag_name": f"v{i}", "published_at": f"2026-01-{i + 1:02d}T00:00:00Z"}
            for i in range(RELEASES_DETAILED + 5)
        ]
        assert len(releases_detail(entries)) == RELEASES_DETAILED

    def test_drafts_do_not_use_up_the_ten_places(self):
        # The cut counts entries kept, not entries seen. Written the other way
        # round, two drafts at the top spend two places and the panel shows
        # eight releases in a list that says ten.
        drafts = [
            {"tag_name": f"draft{i}", "draft": True,
             "published_at": f"2026-03-{i + 1:02d}T00:00:00Z"}
            for i in range(3)
        ]
        real = [
            {"tag_name": f"v{i}", "published_at": f"2026-01-{i + 1:02d}T00:00:00Z"}
            for i in range(RELEASES_DETAILED)
        ]
        kept = releases_detail(drafts + real)
        assert len(kept) == RELEASES_DETAILED
        assert not [entry for entry in kept if entry["tag"].startswith("draft")]

    def test_published_order_beats_githubs_order(self):
        # GitHub orders by creation, so a release drafted in March and
        # published in September arrives ahead of everything published since.
        entries = [
            {"tag_name": "old-draft-now-out", "published_at": "2026-03-01T00:00:00Z"},
            {"tag_name": "newest", "published_at": "2026-09-01T00:00:00Z"},
            {"tag_name": "middle", "published_at": "2026-06-01T00:00:00Z"},
        ]
        assert [entry["tag"] for entry in releases_detail(entries)] == [
            "newest",
            "middle",
            "old-draft-now-out",
        ]

    def test_an_undated_release_sorts_last_rather_than_first(self):
        entries = [
            {"tag_name": "undated"},
            {"tag_name": "dated", "published_at": "2026-01-01T00:00:00Z"},
        ]
        assert [entry["tag"] for entry in releases_detail(entries)] == [
            "dated",
            "undated",
        ]

    def test_only_the_author_login_survives(self):
        entry = {
            "tag_name": "v1.0",
            "published_at": "2026-01-01T12:00:00Z",
            "author": {
                "login": "maximusunc",
                "avatar_url": "https://avatars.example/u/1",
                "gravatar_id": "",
                "url": "https://api.github.com/users/maximusunc",
                "id": 1,
            },
        }
        kept, = releases_detail([entry])
        assert kept["author"] == "maximusunc"
        assert kept["published"] == "2026-01-01"
        assert "avatar_url" not in repr(kept)

    @pytest.mark.parametrize(
        "answer",
        [
            {"message": "API rate limit exceeded", "documentation_url": "https://d"},
            None,
            "",
        ],
    )
    def test_a_rate_limited_object_is_not_a_release_list(self, answer):
        # The releases endpoint answers a JSON object when it throttles. That
        # is an answer we could not read, not a repository with no releases.
        assert releases_detail(answer) == []

    def test_a_body_is_excerpted_as_plain_text(self):
        entry = {
            "tag_name": "v1.0",
            "published_at": "2026-01-01T00:00:00Z",
            "body": "<h2>What's Changed</h2>\n\n<p>" + ("detail " * 200) + "</p>",
        }
        kept, = releases_detail([entry])
        assert kept["body_excerpt"].startswith("What's Changed detail")
        assert len(kept["body_excerpt"]) <= BODY_EXCERPT


class TestRepoMetaDetail:
    def test_a_repository_document_is_reduced_to_what_a_reader_asks(self):
        assert repo_meta_detail(
            {
                "description": "Translator Shepherd",
                "default_branch": "main",
                "pushed_at": "2026-09-02T15:14:32Z",
                "archived": False,
                "license": {"spdx_id": "MIT", "name": "MIT License"},
                "topics": ["translator", "trapi"],
                "open_issues_count": 7,
                "stargazers_count": 12,
                "homepage": "https://shepherd.example",
                "owner": {"login": "BioPack-team"},
            }
        ) == {
            "description": "Translator Shepherd",
            "default_branch": "main",
            "pushed_at": "2026-09-02T15:14:32Z",
            "archived": False,
            "license": "MIT",
            "topics": ["translator", "trapi"],
            "open_issues": 7,
            "stars": 12,
            "homepage": "https://shepherd.example",
        }

    @pytest.mark.parametrize("doc", [None, {}, [], "not a document"])
    def test_a_missing_document_is_none(self, doc):
        assert repo_meta_detail(doc) is None


class TestCatalogDetail:
    def test_a_catalog_entry_carries_the_platforms_own_description(self):
        assert catalog_detail(
            {
                "id": "infores:retriever",
                "name": "Retriever",
                "description": "Translator Knowledge Provider",
                "status": "released",
                "knowledge_level": "knowledge_assertion",
                "agent_type": "automated_agent",
                "xref": ["https://retriever.example"],
                "consumes": ["infores:biothings"],
                "consumed_by": ["infores:shepherd"],
            }
        ) == {
            "name": "Retriever",
            "description": "Translator Knowledge Provider",
            "status": "released",
            "knowledge_level": "knowledge_assertion",
            "agent_type": "automated_agent",
            "xref": ["https://retriever.example"],
            "consumes": ["infores:biothings"],
            "consumed_by": ["infores:shepherd"],
        }

    @pytest.mark.parametrize("entry", [None, {}, [], 0])
    def test_a_missing_entry_is_none(self, entry):
        assert catalog_detail(entry) is None


IMAGE_KEYS = {"image", "images", "tag"}

REGISTRY_HOST = re.compile(
    r"ghcr\.io|docker\.io|quay\.io|registry\.k8s\.io|containers\.renci\.org"
)


def _image_leaks(node, path=()) -> list[str]:
    """Every place a Helm detail block names a container image.

    Walks the finished dictionary rather than the chart, because the promise is
    about what leaves this module. `repository` is allowed in exactly one
    place — directly under a `dependencies` entry, where it is a chart
    repository like https://charts.bitnami.com/bitnami — and nowhere else.
    """
    where = ".".join(path) or "<root>"
    if isinstance(node, dict):
        found = []
        for key, value in node.items():
            if key in IMAGE_KEYS:
                found.append(f"{where}.{key} is an image key")
            if key == "repository" and path[-2:-1] != ("dependencies",):
                found.append(f"{where}.{key} is a repository outside dependencies")
            found += _image_leaks(value, path + (str(key),))
        return found
    if isinstance(node, list):
        return [
            leak
            for index, item in enumerate(node)
            for leak in _image_leaks(item, path + (str(index),))
        ]
    if isinstance(node, str) and REGISTRY_HOST.search(node):
        return [f"{where} names the registry {node!r}"]
    return []
