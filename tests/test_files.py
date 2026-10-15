"""files.py: finding a hand-edited file from anywhere in the checkout, and
reading JSON or YAML that may be missing or malformed."""

from pathlib import Path

from translator_diagram.files import (
    PROBE_KINDS,
    chart_commit_path,
    derived_path,
    endpoint_key,
    endpoint_path,
    find_upward,
    helm_file_path,
    helm_index_path,
    infores_catalog_path,
    manifest_path,
    otel_path,
    read_json,
    read_yaml,
    releases_path,
    repo_meta_path,
    smartapi_path,
)


class TestFindUpward:
    def test_finds_the_file_in_the_start_directory(self, tmp_path):
        target = tmp_path / "config" / "privacy.yaml"
        target.parent.mkdir()
        target.write_text("")
        assert find_upward(Path("config/privacy.yaml"), tmp_path) == target

    def test_finds_the_file_in_a_parent(self, tmp_path):
        # Running from a subdirectory of the checkout behaves like running
        # from its root: the lookup walks up until it finds the file.
        target = tmp_path / "catalog" / "owner-colors.csv"
        target.parent.mkdir()
        target.write_text("")
        deep = tmp_path / "src" / "pkg"
        deep.mkdir(parents=True)
        assert find_upward(Path("catalog/owner-colors.csv"), deep) == target

    def test_the_nearest_copy_wins(self, tmp_path):
        for base in (tmp_path, tmp_path / "inner"):
            (base / "catalog").mkdir(parents=True)
            (base / "catalog" / "flow-steps.yaml").write_text("")
        found = find_upward(Path("catalog/flow-steps.yaml"), tmp_path / "inner")
        assert found == tmp_path / "inner" / "catalog" / "flow-steps.yaml"

    def test_none_when_no_directory_has_it(self, tmp_path):
        assert find_upward(Path("config/privacy.yaml"), tmp_path) is None

    def test_defaults_to_the_working_directory(self, tmp_path, monkeypatch):
        (tmp_path / "x.yaml").write_text("")
        monkeypatch.chdir(tmp_path)
        assert find_upward(Path("x.yaml")) == tmp_path / "x.yaml"


class TestReadJson:
    def test_reads_a_body(self, tmp_path):
        (tmp_path / "a.json").write_text('{"hits": []}')
        assert read_json(tmp_path / "a.json") == {"hits": []}

    def test_missing_is_none(self, tmp_path):
        assert read_json(tmp_path / "missing.json") is None

    def test_html_where_json_was_expected_is_none(self, tmp_path):
        # Several Translator hosts answer 200 with an error page.
        (tmp_path / "a.json").write_text("<html>502</html>")
        assert read_json(tmp_path / "a.json") is None

    def test_any_json_shape_comes_back(self, tmp_path):
        # The reader does not judge the shape; a throttled GitHub call answers
        # with an object where a list was asked for, and callers check.
        (tmp_path / "a.json").write_text("[1, 2]")
        assert read_json(tmp_path / "a.json") == [1, 2]


class TestReadYaml:
    def test_reads_a_mapping(self, tmp_path):
        (tmp_path / "a.yaml").write_text("name: x\n")
        assert read_yaml(tmp_path / "a.yaml") == {"name": "x"}

    def test_missing_malformed_or_not_a_mapping_is_none(self, tmp_path):
        assert read_yaml(tmp_path / "missing.yaml") is None
        (tmp_path / "bad.yaml").write_text("a: [unclosed\n")
        assert read_yaml(tmp_path / "bad.yaml") is None
        (tmp_path / "list.yaml").write_text("- a\n- b\n")
        assert read_yaml(tmp_path / "list.yaml") is None


class TestCacheLayout:
    """The one place the sync cache's layout is spelled out.

    Code and the test builders both go through these functions, so a change
    to a path here is the only way to move a file, and this is where it shows.
    """

    def test_the_fixed_files(self, tmp_path):
        assert manifest_path(tmp_path) == tmp_path / "manifest.json"
        assert smartapi_path(tmp_path) == tmp_path / "smartapi.json"
        assert derived_path(tmp_path) == tmp_path / "derived.json"
        assert infores_catalog_path(tmp_path) == tmp_path / "infores_catalog.yaml"
        assert helm_index_path(tmp_path) == tmp_path / "helm" / "index.json"

    def test_one_deployments_files_are_keyed_by_kind_component_and_env(self, tmp_path):
        assert endpoint_key("openapi", "svc", "ci") == "openapi/svc/ci.json"
        assert endpoint_key("root", "svc", "prod") == "root/svc/prod.json"
        assert endpoint_path(tmp_path, "status", "svc", "test") == (
            tmp_path / "status" / "svc" / "test.json"
        )
        assert PROBE_KINDS == ("root", "openapi", "status")

    def test_otel_collectors_are_keyed_by_env(self, tmp_path):
        assert otel_path(tmp_path, "ci") == tmp_path / "otel" / "ci.json"

    def test_github_files_are_keyed_by_the_owner_name_slug(self, tmp_path):
        # The slug keeps its slash, so a repository is a directory: the three
        # shepherds share `releases/TranslatorSRI/shepherd.json`.
        assert releases_path(tmp_path, "a/b") == tmp_path / "releases" / "a" / "b.json"
        assert repo_meta_path(tmp_path, "a/b") == tmp_path / "repos" / "a" / "b.json"

    def test_chart_files_sit_under_the_chart(self, tmp_path):
        assert helm_file_path(tmp_path, "arax", "Chart.yaml") == (
            tmp_path / "helm" / "arax" / "Chart.yaml"
        )
        assert chart_commit_path(tmp_path, "arax") == (
            tmp_path / "helm" / "arax" / "commit.json"
        )
