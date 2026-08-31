"""Following the pointers in components/*.yaml out to their sources.

Writes raw responses under data/sync/ and a manifest recording every fetch it
attempted, including the ones that failed. The dashboard reads that directory;
nothing here renders anything, and nothing here decides what a version *is* —
that judgement lives in dashboard.py, so it can be tested without a network.

A service being down is data, not an error. The manifest records what
happened and the run still succeeds, because "was this endpoint reachable at
14:05" is exactly the question the dashboard exists to answer.
"""

import json
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .components import (
    ComponentFile,
    deployments_from_smartapi,
    endpoint_url_in,
    merge_deployments,
)

SMARTAPI_QUERY = (
    "https://smart-api.info/api/query"
    "?q=tags.name:translator&size=200&meta=1"
    "&fields=info.title,info.version,info.x-translator,info.x-trapi,servers,_status"
)
"""Every Translator-tagged SmartAPI record.

`meta=1` is not optional: without it the response carries no `_id` at all, so
records cannot be matched to the smartapi identifiers in the component files.
"""

OTEL_COLLECTORS = {
    "ci": "https://translator-otel.ci.transltr.io/api/services",
    "test": "https://translator-otel.test.transltr.io/api/services",
    "prod": "https://translator-otel.transltr.io/api/services",
}

DEVOPS_RAW = (
    "https://raw.githubusercontent.com/helxplatform/translator-devops"
    "/develop/helm/{chart}/{file}"
)
HELM_FILES = ("Chart.yaml", "values.yaml", "ncats-images-meta.yaml")

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


@dataclass
class SyncReport:
    started_at: str = ""
    finished_at: str = ""
    fetches: list[FetchResult] = field(default_factory=list)

    @property
    def succeeded(self) -> int:
        return sum(1 for f in self.fetches if f.ok)

    def to_dict(self) -> dict[str, Any]:
        return {
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "counts": {
                "attempted": len(self.fetches),
                "succeeded": self.succeeded,
                "cached": sum(1 for f in self.fetches if f.cached),
                "failed": len(self.fetches) - self.succeeded,
            },
            "fetches": [asdict(f) for f in self.fetches],
        }


Fetcher = Callable[[str], tuple[int, bytes]]
"""Given a URL, return (http status, body). Injected so tests never fetch."""


def http_fetch(url: str, timeout: int = DEFAULT_TIMEOUT) -> tuple[int, bytes]:
    """The real fetcher. urllib rather than requests: `loading.py` already
    reaches the network with the stdlib, and one HTTP client is enough."""
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        # A 404 is a finding, not a crash: it is how we learned that ars and
        # ploverdb serve no OpenAPI at their registered URLs.
        return exc.code, exc.read()


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
        status, body = fetcher(url)
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


def _plan_endpoint_fetches(
    components: Iterable[ComponentFile],
    by_smartapi: dict[str, dict[str, Any]],
    root: Path,
) -> list[tuple[str, Path]]:
    """Every (url, destination) for the OpenAPI and status endpoints."""
    jobs: list[tuple[str, Path]] = []
    for component in components:
        record = by_smartapi.get(component.smartapi_id or "", {})
        deployments = merge_deployments(
            component, deployments_from_smartapi(record)
        )
        for env, deployment in deployments.items():
            for kind in ("openapi", "status"):
                url = endpoint_url_in(component, deployment, kind)
                if url:
                    jobs.append((url, root / kind / component.id / f"{env}.json"))
    return jobs


def sync(
    components: list[ComponentFile],
    root: Path,
    *,
    fetcher: Fetcher = http_fetch,
    max_age: int = DEFAULT_MAX_AGE,
    workers: int = 12,
    echo: Callable[[str], None] = lambda _: None,
) -> SyncReport:
    """Fetch everything the component files point at, into `root`.

    Runs in two waves because the second depends on the first: SmartAPI is
    what tells us which environments most components have, so the per-endpoint
    fetches cannot be planned until it has landed.
    """
    report = SyncReport(started_at=_now())
    root.mkdir(parents=True, exist_ok=True)

    def run(jobs: list[tuple[str, Path]]) -> list[FetchResult]:
        if not jobs:
            return []
        with ThreadPoolExecutor(max_workers=workers) as pool:
            results = list(
                pool.map(
                    lambda job: fetch_to(
                        job[0], job[1], fetcher, max_age=max_age, root=root
                    ),
                    jobs,
                )
            )
        report.fetches.extend(results)
        return results

    # Wave one: the registries.
    echo("Fetching the SmartAPI registry and the OpenTelemetry collectors ...")
    registry_jobs = [(SMARTAPI_QUERY, root / "smartapi.json")]
    registry_jobs += [
        (url, root / "otel" / f"{env}.json") for env, url in OTEL_COLLECTORS.items()
    ]
    for component in components:
        if component.helm_chart:
            for name in HELM_FILES:
                registry_jobs.append(
                    (
                        DEVOPS_RAW.format(chart=component.helm_chart, file=name),
                        root / "helm" / component.helm_chart / name,
                    )
                )
    run(registry_jobs)

    by_smartapi = {}
    smartapi_path = root / "smartapi.json"
    if smartapi_path.exists():
        payload = json.loads(smartapi_path.read_text(encoding="utf-8"))
        by_smartapi = {
            hit["_id"]: hit for hit in payload.get("hits", []) if hit.get("_id")
        }
        echo(f"  {len(by_smartapi)} SmartAPI records")

    # Wave two: the endpoints those registries point at.
    endpoint_jobs = _plan_endpoint_fetches(components, by_smartapi, root)
    echo(f"Fetching {len(endpoint_jobs)} component endpoints ...")
    run(endpoint_jobs)

    report.finished_at = _now()
    (root / "manifest.json").write_text(
        json.dumps(report.to_dict(), indent=2) + "\n", encoding="utf-8"
    )
    return report
