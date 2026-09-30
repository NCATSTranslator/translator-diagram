"""Tests for translator_diagram.fetch."""

import json

from tests.dashboard_helpers import FakeFetcher
from translator_diagram.fetch import FetchResult, _headers, fetch_to, probe_to


class TestFetchTo:
    def test_a_200_is_written(self, tmp_path):
        target = tmp_path / "out" / "body.json"
        result = fetch_to("https://x/", target, FakeFetcher({"https://x/": (200, b"{}")}),
                          max_age=0, root=tmp_path)
        assert result.ok and target.read_bytes() == b"{}"

    def test_a_404_is_recorded_and_writes_nothing(self, tmp_path):
        # ars and ploverdb 404 at every environment. That is a finding worth
        # keeping, not a crash, and it must not leave a bogus cached body.
        target = tmp_path / "body.json"
        result = fetch_to("https://x/", target, FakeFetcher({}), max_age=0, root=tmp_path)
        assert result.status == 404
        assert not result.ok
        assert not target.exists()

    def test_an_exception_is_recorded_rather_than_raised(self, tmp_path):
        fetcher = FakeFetcher({"https://x/": TimeoutError("timed out")})
        result = fetch_to("https://x/", tmp_path / "b.json", fetcher, max_age=0, root=tmp_path)
        assert result.status is None
        assert "TimeoutError" in result.error

    def test_a_fresh_file_is_not_refetched(self, tmp_path):
        target = tmp_path / "body.json"
        target.write_bytes(b"cached")
        fetcher = FakeFetcher({})
        result = fetch_to("https://x/", target, fetcher, max_age=9999, root=tmp_path)
        assert result.cached and fetcher.urls == []
        assert target.read_bytes() == b"cached"

    def test_max_age_zero_always_refetches(self, tmp_path):
        target = tmp_path / "body.json"
        target.write_bytes(b"stale")
        fetcher = FakeFetcher({"https://x/": (200, b"fresh")})
        fetch_to("https://x/", target, fetcher, max_age=0, root=tmp_path)
        assert target.read_bytes() == b"fresh"

    def test_the_recorded_path_is_relative_to_the_root(self, tmp_path):
        # The manifest is read back by the dashboard to look up HTTP statuses,
        # so an absolute path here would make every lookup miss.
        result = fetch_to("https://x/", tmp_path / "openapi" / "a" / "ci.json",
                          FakeFetcher({"https://x/": (200, b"{}")}),
                          max_age=0, root=tmp_path)
        assert result.path == "openapi/a/ci.json"


class TestProbeTo:
    """The root probe's writer: how a host answered, never what it said."""

    def test_the_saved_probe_is_a_summary_not_the_page(self, tmp_path):
        # The reason `probe_to` exists at all. A root probe answers with a
        # file browser, a login page or a single-page app's shell, and none of
        # those belongs under data/sync/, where every other reader expects a
        # document it can parse.
        fetcher = FakeFetcher(
            {"https://svc/": (200, b"<html><body>not a document</body></html>")}
        )
        target = tmp_path / "root" / "svc" / "ci.json"
        probe_to("https://svc/", target, fetcher, max_age=0, root=tmp_path)
        saved = json.loads(target.read_text())
        assert saved == {"status": 200, "content_type": None, "error": None}
        assert "html" not in target.read_text()

    def test_a_404_is_saved_rather_than_leaving_the_last_answer(self, tmp_path):
        # The other half of the difference from `fetch_to`, which keeps the
        # previous body on a non-200. A stale *status* is the lie the whole
        # manifest gate exists to stop.
        target = tmp_path / "root" / "svc" / "ci.json"
        target.parent.mkdir(parents=True)
        target.write_text(json.dumps({"status": 200, "content_type": None, "error": None}))
        probe_to("https://svc/", target, FakeFetcher({}), max_age=0, root=tmp_path)
        assert json.loads(target.read_text())["status"] == 404

    def test_a_failure_is_recorded_with_its_error(self, tmp_path):
        target = tmp_path / "root" / "svc" / "ci.json"
        fetcher = FakeFetcher({"https://svc/": OSError("nodename nor servname")})
        result = probe_to("https://svc/", target, fetcher, max_age=0, root=tmp_path)
        assert result.status is None and "OSError" in result.error
        saved = json.loads(target.read_text())
        assert saved["status"] is None and "OSError" in saved["error"]

    def test_a_cached_probe_reports_the_status_it_recorded(self, tmp_path):
        # `fetch_to` can report a cached hit as 200 because a body on disk got
        # there by being a 200. A probe summary is written whatever happened,
        # so reading 200 off its freshness would invent an answer.
        target = tmp_path / "root" / "svc" / "ci.json"
        target.parent.mkdir(parents=True)
        target.write_text(json.dumps(
            {"status": 503, "content_type": None, "error": None}
        ))
        fetcher = FakeFetcher({})
        result = probe_to("https://svc/", target, fetcher, max_age=9999, root=tmp_path)
        assert result.cached and result.status == 503 and fetcher.urls == []

    def test_a_content_type_is_kept_when_the_fetcher_reports_one(self, tmp_path):
        # The real fetcher answers with three parts; every fake in this file
        # answers with two, and both have to work.
        target = tmp_path / "root" / "svc" / "ci.json"
        probe_to("https://svc/", target,
                 lambda url: (200, b"<html>", "text/html"),
                 max_age=0, root=tmp_path)
        assert json.loads(target.read_text())["content_type"] == "text/html"


class TestHeaders:
    def test_a_token_reaches_github_and_nowhere_else(self, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", "s3cret")
        assert _headers("https://api.github.com/repos/a/b/releases")[
            "Authorization"] == "Bearer s3cret"
        assert "Authorization" not in _headers("https://smart-api.info/api/query")

    def test_no_token_is_no_header(self, monkeypatch):
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        assert "Authorization" not in _headers("https://api.github.com/repos/a/b")


def test_fetch_result_ok_requires_both_a_200_and_no_error():
    assert FetchResult(url="u", path="p", status=200).ok
    assert not FetchResult(url="u", path="p", status=200, error="boom").ok
    assert not FetchResult(url="u", path="p", status=500).ok
