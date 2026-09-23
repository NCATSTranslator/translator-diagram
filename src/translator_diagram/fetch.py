"""Fetching one URL into data/sync/, and recording what happened either way.

The transport under `sync`: an injected `Fetcher` so tests never reach the
network, `http_fetch` as the real one, and the two writers a fetch can end
in — `fetch_to` saves the body, `probe_to` saves only how the host answered.
Nothing here knows what a Translator component is; `sync` decides what to ask
for and in what order.
"""

import json
import os
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from .components import read_json

GITHUB_API_PREFIX = "https://api.github.com/"

DEFAULT_TIMEOUT = 30
DEFAULT_MAX_AGE = 900  # seconds; 15 minutes
USER_AGENT = "translator-diagram sync (+https://github.com/NCATSTranslator/translator-diagram)"


@dataclass
class FetchResult:
    """One attempted fetch, successful or not."""

    url: str
    path: str
    status: int | None = None
    bytes: int = 0
    error: str | None = None
    cached: bool = False
    fetched_at: str = ""

    @property
    def ok(self) -> bool:
        return self.status == 200 and self.error is None


Fetcher = Callable[[str], tuple[int, bytes] | tuple[int, bytes, str | None]]
"""Given a URL, return (http status, body) — or (status, body, content type).

Injected so tests never fetch. The third element is optional and every reader
here goes through `_answer`, which fills it in as None: a fetcher written
before the root probe existed is still a fetcher, and every test fake in this
repository returns the pair. Only `probe_to` has any use for the content type,
because "what did this host answer with" is the whole of what it records.
"""


def _answer(fetcher: Fetcher, url: str) -> tuple[int, bytes, str | None]:
    """One fetcher's answer, in the three-part shape the callers read."""
    answer = fetcher(url)
    if len(answer) == 3:
        status, body, content_type = answer
        return status, body, content_type
    status, body = answer
    return status, body, None


def _headers(url: str) -> dict[str, str]:
    """Request headers for one URL.

    GitHub allows 60 unauthenticated calls an hour per address, which two
    back-to-back `--force` syncs can exhaust between them. A `GITHUB_TOKEN` in
    the environment raises that to 5000 and is sent to api.github.com and
    nowhere else — every other host here is public and wants no credential.
    """
    headers = {"User-Agent": USER_AGENT}
    if url.startswith(GITHUB_API_PREFIX):
        headers["Accept"] = "application/vnd.github+json"
        if token := os.environ.get("GITHUB_TOKEN"):
            headers["Authorization"] = f"Bearer {token}"
    return headers


def http_fetch(
    url: str, timeout: int = DEFAULT_TIMEOUT
) -> tuple[int, bytes, str | None]:
    """The real fetcher. urllib rather than requests: `loading.py` already
    reaches the network with the stdlib, and one HTTP client is enough.

    Returns the declared content type alongside the body. It is the header
    rather than a guess at the bytes, which is what makes it worth carrying: a
    single-page app answering `text/html` to a request for `openapi.json` is
    exactly the case the dashboard has to be able to name, and sniffing the
    first byte would be this tool deciding rather than the server saying.
    """
    request = urllib.request.Request(url, headers=_headers(url))
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read(), response.headers.get_content_type()
    except urllib.error.HTTPError as exc:
        # A 404 is a finding, not a crash: it is how we learned that ars and
        # ploverdb serve no OpenAPI at their registered URLs.
        return exc.code, exc.read(), exc.headers.get_content_type() if exc.headers else None


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _is_fresh(path: Path, max_age: int) -> bool:
    return (
        max_age > 0
        and path.exists()
        and (time.time() - path.stat().st_mtime) < max_age
    )


def fetch_to(
    url: str,
    destination: Path,
    fetcher: Fetcher,
    *,
    max_age: int = DEFAULT_MAX_AGE,
    root: Path | None = None,
) -> FetchResult:
    """Fetch one URL into one file, recording what happened either way."""
    relative = str(destination.relative_to(root)) if root else str(destination)
    if _is_fresh(destination, max_age):
        return FetchResult(
            url=url, path=relative, status=200, cached=True,
            bytes=destination.stat().st_size, fetched_at=_now(),
        )
    try:
        status, body, _ = _answer(fetcher, url)
    except Exception as exc:  # noqa: BLE001 - any failure is a recorded finding
        return FetchResult(
            url=url, path=relative,
            error=f"{type(exc).__name__}: {exc}", fetched_at=_now(),
        )
    if status == 200:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(body)
    return FetchResult(
        url=url, path=relative, status=status,
        bytes=len(body), fetched_at=_now(),
    )


def probe_to(
    url: str,
    destination: Path,
    fetcher: Fetcher,
    *,
    max_age: int = DEFAULT_MAX_AGE,
    root: Path | None = None,
) -> FetchResult:
    """Contact one URL and save how it answered, never what it said.

    A sibling of `fetch_to` rather than a flag on it, because the two save
    different things and the difference is the reason this exists. `fetch_to`
    writes the body: that is the point of an OpenAPI or a `/status` fetch.
    A root probe asks one question — did anything answer at this address — and
    the answer to it is three fields. Writing the body instead would put a
    file-browser's HTML, a login page and a single-page app's shell under
    `data/sync/`, where every other reader expects a document it can parse, and
    would cache a page per deployment to hold a number.

    So the destination holds `{"status", "content_type", "error"}` and the
    request still goes through a `FetchResult`, because the manifest promises
    every attempt this run made and a probe is one.

    A non-200 is written like any other outcome, which is the other half of the
    difference: `fetch_to` leaves the previous body in place on a 404 because a
    stale body is better than none for a document, whereas a stale *status*
    is exactly the lie the manifest gate exists to stop. A cached probe is
    therefore reported with the status it recorded, not with the 200 that
    "the file is fresh" would otherwise imply.
    """
    relative = str(destination.relative_to(root)) if root else str(destination)
    if _is_fresh(destination, max_age):
        recorded = read_json(destination)
        recorded = recorded if isinstance(recorded, dict) else {}
        return FetchResult(
            url=url, path=relative,
            status=recorded.get("status"), error=recorded.get("error"),
            cached=True, bytes=destination.stat().st_size, fetched_at=_now(),
        )
    error, status, content_type, size = None, None, None, 0
    try:
        status, body, content_type = _answer(fetcher, url)
        size = len(body)
    except Exception as exc:  # noqa: BLE001 - any failure is a recorded finding
        error = f"{type(exc).__name__}: {exc}"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(
            {"status": status, "content_type": content_type, "error": error},
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return FetchResult(
        url=url, path=relative, status=status, error=error,
        bytes=size, fetched_at=_now(),
    )
