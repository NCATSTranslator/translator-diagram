"""files.py: finding a hand-edited file from anywhere in the checkout, and
reading JSON or YAML that may be missing or malformed."""

from pathlib import Path

from translator_diagram.files import find_upward, read_json, read_yaml


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
