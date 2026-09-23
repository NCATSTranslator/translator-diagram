"""Following the pointers in components/*.yaml out to their sources.

Writes raw responses under data/sync/ and a manifest recording every fetch it
attempted, including the ones that failed. The dashboard reads that directory;
nothing here renders anything, and nothing here decides what a version *is* —
that judgement lives in cells.py, so it can be tested without a network.

A service being down is data, not an error. The manifest records what
happened and the run still succeeds, because "was this endpoint reachable at
14:05" is exactly the question the dashboard exists to answer.
"""

import json
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from .charts import CHART_META_FILES, chart_dirs, unclaimed_charts
from .components import (
    ComponentFile,
    Deployment,
    endpoint_url_in,
    github_repo,
    read_json,
    read_yaml,
)
from .deployments import (
    deployments_from_smartapi,
    derive_deployments,
    merge_deployments,
    record_infores,
    smartapi_record_for,
)
from .fetch import (
    DEFAULT_MAX_AGE,
    GITHUB_API_PREFIX,
    Fetcher,
    FetchResult,
    fetch_to,
    http_fetch,
    now,
    probe_to,
)

SMARTAPI_QUERY = (
    "https://smart-api.info/api/query"
    "?q=tags.name:translator&size=200&meta=1"
    "&fields=info.title,info.version,info.x-translator,info.x-trapi,servers"
    ",_status,_meta,info.description,info.contact,tags"
)
"""Every Translator-tagged SmartAPI record.

`meta=1` is not optional: without it the response carries no `_id` at all, so
records cannot be matched to the smartapi identifiers in the component files.
It is a different parameter from the `_meta` field, which has to be asked for
by name like any other: `_meta.last_updated` is when the registered document
last changed, and it is the only date SmartAPI offers that moves when something
about a component does. `_status.refresh_ts` is not that date — it is when
SmartAPI last polled the API, and it reads as this morning on all 127 records.
"""

OTEL_COLLECTORS = {
    "ci": "https://translator-otel.ci.transltr.io/api/services",
    "test": "https://translator-otel.test.transltr.io/api/services",
    "prod": "https://translator-otel.transltr.io/api/services",
}

GITHUB_RELEASES = "https://api.github.com/repos/{repo}/releases?per_page=100"
"""Every release of one repository, newest first.

The whole list rather than the newest few, because prod routinely runs an
older release than dev does — answer-appraiser's prod is two minor versions
behind its ci — and a release-notes link is worth most for exactly the version
someone is looking at.

ponytail: one page. A repository with more than 100 releases would lose its
oldest, which nothing here has; paginating means following the Link header.
"""

DEVOPS_RAW = (
    "https://raw.githubusercontent.com/helxplatform/translator-devops"
    "/develop/helm/{chart}/{file}"
)
HELM_FILES = ("Chart.yaml", "values.yaml", "ncats-images-meta.yaml")

DEVOPS_HELM_INDEX = (
    "https://api.github.com/repos/helxplatform/translator-devops"
    "/contents/helm?ref=develop"
)
"""Every chart directory under `helm/`, in one call.

`develop` is both this repository's default branch and the branch ITRB deploys
from. It is named explicitly rather than left to the default so this and
`DEVOPS_RAW` cannot come to mean two different trees.
"""

DEVOPS_CHART_COMMIT = (
    "https://api.github.com/repos/helxplatform/translator-devops"
    "/commits?path=helm/{chart}&per_page=1"
)
"""The last commit touching one chart directory.

It dates the *intent* to deploy, not a deployment: a chart change that was
never rolled out, and a rollout of an unchanged chart, both make it wrong.
Whatever renders it has to say which of the two it is — see FUTURE.md.
"""

GITHUB_REPO_META = "https://api.github.com/repos/{repo}"
"""One repository's own metadata — description, default branch, `pushed_at`,
archived, licence, topics. A second call per repository, keyed the same way the
release lists are so the three shepherds still cost one between them."""

INFORES_CATALOG = (
    "https://raw.githubusercontent.com/biolink/information-resource-registry"
    "/main/infores_catalog.yaml"
)
"""The Biolink information-resource registry, as the one YAML file it ships as.

Verified with `curl -sI` on 2026-09-02: 200 on the `main` branch at that path.
`raw.githubusercontent.com`, so it spends nothing from the API budget below.
"""


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


def _plan_root_probes(
    components: Iterable[ComponentFile],
    by_smartapi: dict[str, dict[str, Any]],
    derived: dict[str, dict[str, Deployment]],
    root: Path,
) -> list[tuple[str, Path]]:
    """Every (url, destination) for the deployment URLs themselves.

    One per deployment, whichever way we came to know about it — recorded in
    the component file, declared in a registry record, or confirmed by an
    earlier run's probe of a conventional hostname. Deliberately not per
    endpoint: this asks whether a *host* is answering, which is a different
    question from whether it serves an API document, and the two were being
    answered with one number.

    The gap it closes: the four UI deployments record `openapi: null`, so
    nothing was ever fetched for them and the page reported them as not
    reachable with no HTTP status beside it — a claim about four hosts that
    were up the whole time, made on the strength of never having asked.

    `probe_to`, not `fetch_to`: what these hosts answer with is HTML, and the
    manifest wants the attempt while `data/sync/` does not want the page.
    """
    jobs: list[tuple[str, Path]] = []
    for component in components:
        record = by_smartapi.get(component.smartapi_id or "", {})
        deployments = merge_deployments(
            component,
            deployments_from_smartapi(record),
            derived.get(component.id, {}),
        )
        for env, deployment in deployments.items():
            jobs.append(
                (deployment.url, root / "root" / component.id / f"{env}.json")
            )
    return jobs


def _confirmed_deployments(
    previous: dict[str, Any],
) -> dict[str, dict[str, Deployment]]:
    """The previous run's confirmed derived hosts, as Deployments.

    Read at the top of the run rather than in wave three, because the root
    probes go out in wave two and a host confirmed last run is a host worth
    contacting this run. This run's own confirmations land in `derived.json` at
    the end and are probed by the next sync — a wave-two job cannot wait on a
    wave-three answer, and probing the same host twice in one run to close that
    one-run gap would cost every deployment a second request.
    """
    return {
        cid: {
            env: Deployment(
                env=env, url=spec["url"], location=spec.get("location")
            )
            for env, spec in (envs or {}).items()
            if isinstance(spec, dict) and spec.get("url")
        }
        for cid, envs in (previous.get("confirmed") or {}).items()
    }


# What one sync spends from GitHub's API budget, and why it is close to the
# floor: 1 chart index + ~19 repository descriptions + ~6 chart commits + ~20
# release lists ≈ 46 calls. That fits under the 60-an-hour unauthenticated
# ceiling once, and is nothing against the 5000 a GITHUB_TOKEN raises it to
# (see `fetch._headers`). Every planner below is keyed by the thing being
# fetched rather than by the component asking for it, which is what keeps the
# count at the number of distinct answers -- the three shepherds share a
# repository and a chart, and pay for one of each between them. Everything else
# this module fetches is raw.githubusercontent.com or a public API, and costs
# nothing here.
#
# A run that runs out of budget loses facts, not the run: a 403 is recorded
# like any other status, named in the wave-one summary, and picked up by the
# next sync.


def _source_repos(components: Iterable[ComponentFile]) -> list[str]:
    """Every distinct source repository, as `owner/name`, sorted.

    Planners are keyed by the repository rather than by the component, because
    three shepherd components share one repository and fetching it three times
    would spend three of GitHub's sixty hourly calls on the same answer. The
    `github_repo` rule also rejects a `helm-chart` URL, which names a path
    *inside* translator-devops: that repository is the devops team's, not this
    component's.
    """
    return sorted(
        {repo for c in components if (repo := github_repo(c.repository("source")))}
    )


def _plan_release_fetches(
    components: Iterable[ComponentFile], root: Path
) -> list[tuple[str, Path]]:
    """Every (url, destination) for a source repository's GitHub releases."""
    return [
        (GITHUB_RELEASES.format(repo=repo), root / "releases" / f"{repo}.json")
        for repo in _source_repos(components)
    ]


def _plan_chart_fetches(
    components: Iterable[ComponentFile], root: Path
) -> list[tuple[str, Path]]:
    """Every (url, destination) for a component's Helm chart files.

    Keyed by the chart rather than by the component, the same way
    `_plan_release_fetches` is keyed by the repository. Three shepherd
    components share one chart, and the loop this replaced scheduled all three
    -- eighteen requests for fifteen files, with three threads in the same pool
    writing one destination at once. GitHub's raw host is not rate-limited the
    way the API is, so the cost was the race, not the budget.
    """
    return [
        (DEVOPS_RAW.format(chart=chart, file=name), root / "helm" / chart / name)
        for chart in _claimed_charts(components)
        for name in HELM_FILES
    ]


def _claimed_charts(components: Iterable[ComponentFile]) -> list[str]:
    """Every chart a component file claims, sorted and deduped.

    Read through `helm_charts` rather than `helm_chart`, which is the first of
    them: a component deployed by a web server chart and a loader chart records
    both, and planning only the first would cache half of it.
    """
    return sorted({chart for c in components for chart in c.helm_charts})


def _plan_repo_meta(
    components: Iterable[ComponentFile], root: Path
) -> list[tuple[str, Path]]:
    """Every (url, destination) for a source repository's own metadata."""
    return [
        (GITHUB_REPO_META.format(repo=repo), root / "repos" / f"{repo}.json")
        for repo in _source_repos(components)
    ]


def _chart_names(root: Path) -> list[str]:
    """Chart directory names from the cached index, tolerating its absence."""
    return chart_dirs(read_json(root / "helm" / "index.json"))


def _plan_index_chart_fetches(
    root: Path, planned: Iterable[Path] = ()
) -> list[tuple[str, Path]]:
    """A `Chart.yaml` for every chart the index named, minus the ones planned.

    Chart.yaml is the cheap half of a chart — a name, a version, an appVersion,
    a description — and it is raw, not API-budgeted, so it is worth having for
    all fifty charts including the forty-odd no component claims: that list is
    the answer to "what else is deployed from translator-devops". `values.yaml`
    and `ncats-images-meta.yaml` stay in `_plan_chart_fetches`, claimed charts
    only, so the cache stays proportional to what the page can show.

    Deduped on the destination rather than the chart name, because that is what
    the collision would be: two jobs in one pool writing one file, which is the
    race `_plan_chart_fetches` was keyed by chart to end.
    """
    already = set(planned)
    jobs = []
    for chart in _chart_names(root):
        destination = root / "helm" / chart / "Chart.yaml"
        if destination not in already:
            jobs.append(
                (DEVOPS_RAW.format(chart=chart, file="Chart.yaml"), destination)
            )
    return jobs


def _plan_chart_commits(
    components: Iterable[ComponentFile], root: Path
) -> list[tuple[str, Path]]:
    """The last commit touching each claimed chart's directory.

    Claimed charts only: this one is an API call each, unlike the raw
    `Chart.yaml` fetches, and only a component that records a chart has a row
    the date can be shown on. Keyed by chart, so the three shepherds cost one
    call between them.
    """
    return [
        (
            DEVOPS_CHART_COMMIT.format(chart=chart),
            root / "helm" / chart / "commit.json",
        )
        for chart in _claimed_charts(components)
    ]


def _chart_totals(
    components: Iterable[ComponentFile], root: Path
) -> tuple[int, int]:
    """(charts in translator-devops, distinct charts the component files claim).

    The second is not "how many components record a chart": three shepherds
    share one. Which of the remaining charts belong to which component is a
    different question, needing evidence out of the chart files themselves, and
    it is deliberately not answered here — this pair says only how much of the
    chart repository is currently accounted for.
    """
    return (
        len(_chart_names(root)),
        len(_claimed_charts(components)),
    )


def _cached_chart_meta(root: Path, charts: Iterable[str]) -> dict[str, dict[str, Any]]:
    """Every cached chart, in the shape `charts.chart_matches` reads.

    The same three files `HELM_FILES` fetches, keyed by what the matcher calls
    them rather than by filename — `CHART_META_FILES` owns that vocabulary, so
    this and the dashboard's own reader cannot come to disagree about it.

    Most charts have only a `Chart.yaml`: `values.yaml` and
    `ncats-images-meta.yaml` are fetched for claimed charts only. A missing or
    malformed file is None, which is a rule that cannot fire rather than an
    error — this runs at the end of a sync to print two lines, and it must not
    be able to fail a run that has already fetched everything.
    """
    return {
        chart: {
            key: read_yaml(root / "helm" / chart / name)
            for key, name in CHART_META_FILES.items()
        }
        for chart in charts
    }


def _previous_urls(root: Path) -> dict[str, str]:
    """What each cached file was last fetched from, per the previous manifest.

    `fetch_to` judges freshness by the destination's mtime, which is blind to
    the URL having changed underneath it. Adding a field to SMARTAPI_QUERY
    would otherwise leave a perfectly fresh smartapi.json that was fetched to
    answer a different question, and the new field would appear to be missing
    upstream until someone thought to run --force.
    """
    manifest = read_json(root / "manifest.json")
    if not isinstance(manifest, dict):
        return {}
    return {
        fetch["path"]: fetch["url"]
        for fetch in manifest.get("fetches", [])
        if isinstance(fetch, dict) and fetch.get("path") and fetch.get("url")
    }


def _read_derived(root: Path) -> dict[str, Any]:
    """The previous run's derived.json, tolerating absence or an older shape."""
    loaded = read_json(root / "derived.json")
    return loaded if isinstance(loaded, dict) else {}


def _still_fresh(record: dict[str, Any] | None, max_age: int) -> bool:
    """True if a recorded check is recent enough to reuse."""
    if not record or max_age <= 0:
        return False
    try:
        checked = datetime.fromisoformat(record["checked_at"])
    except (KeyError, TypeError, ValueError):
        return False
    return datetime.now(UTC) - checked < timedelta(seconds=max_age)


def _confirm_derived(
    component: ComponentFile,
    candidate: Deployment,
    fetcher: Fetcher,
    root: Path,
    max_age: int,
) -> tuple[FetchResult | None, bool]:
    """Contact a derived host, and keep it only if it is really this component.

    Returns what the request was, and whether it confirmed the candidate. The
    two are separate because they answer different questions: the manifest
    records every request this run made, and a probe that reached a host and
    was turned away is still a request. Returning only the accepted ones is how
    the manifest came to under-report its own attempts.

    A 200 alone is not enough. Hostnames in one namespace can and do resolve to
    something adjacent, so where the component records an infores the document
    has to report the same one. That check is the difference between
    discovering a deployment and guessing at one, and it is why these URLs can
    be believed without a human confirming each.

    Where there is no recorded infores there is nothing to check against, and
    the candidate is dropped: an unverifiable guess is worth less than a gap.
    The address is still contacted, with a root probe rather than a document
    fetch, and the outcome recorded on the rejection — because "there is no
    such host" and "we never looked" are different gaps and only the first is
    a finding. Six of the ten candidates this repository derives fall in here,
    and they were the six the page could say nothing about.
    """
    url = endpoint_url_in(component, candidate, "openapi") if component.infores else None
    if not url:
        # Nothing to check an answer against — no infores, or no OpenAPI
        # document to ask for one. Probe the root so the rejection carries a
        # verdict, and reject it whatever comes back: an unverifiable 200 is
        # exactly the guess this function exists not to make.
        return (
            probe_to(
                candidate.url,
                root / "root" / component.id / f"{candidate.env}.json",
                fetcher,
                max_age=max_age,
                root=root,
            ),
            False,
        )
    destination = root / "openapi" / component.id / f"{candidate.env}.json"
    result = fetch_to(url, destination, fetcher, max_age=max_age, root=root)
    if not result.ok:
        return result, False
    # A guessed hostname answers with whatever it likes — a JSON array, or
    # `{"info": null}` — and `record_infores` checks every level, so one
    # unlucky candidate cannot end the whole sync.
    if record_infores(read_json(destination)) != component.infores:
        # Answered, but it is not this component. Drop the body so a later run
        # does not read it as though it were.
        destination.unlink(missing_ok=True)
        return result, False
    return result, True


def _probe_derived_hosts(
    components: list[ComponentFile],
    by_smartapi: dict[str, dict[str, Any]],
    previous: dict[str, Any],
    *,
    fetcher: Fetcher,
    root: Path,
    max_age: int,
    workers: int,
    echo: Callable[[str], None],
) -> list[FetchResult]:
    """Wave three: the environments nobody registered.

    ITRB's hostnames follow a convention, so knowing one tells us where to look
    for the others — answer-appraiser registers only production but is deployed
    to ci and test as well. Each candidate is confirmed against the infores it
    reports before it is believed.

    Writes `derived.json` and returns every request it made, for the manifest.
    """
    confirmed_before = previous.get("confirmed", {})
    rejected_before = previous.get("rejected", {})

    results: list[FetchResult] = []
    derived: dict[str, dict[str, Any]] = {}
    rejected: dict[str, dict[str, Any]] = {}
    pending, skipped = [], 0
    for component in components:
        known = merge_deployments(
            component, deployments_from_smartapi(
                by_smartapi.get(component.smartapi_id or "", {})
            )
        )
        for env, candidate in derive_deployments(known).items():
            stale = rejected_before.get(component.id, {}).get(env)
            if _still_fresh(stale, max_age) and stale.get("url") == candidate.url:
                # Most candidates are hostnames that do not resolve, and there
                # are nine of those for every one that does. Re-probing them
                # every run buys nothing: carry the answer forward until it is
                # as stale as anything else we cache.
                rejected.setdefault(component.id, {})[env] = stale
                skipped += 1
                continue
            pending.append((component, env, candidate))
    if skipped:
        echo(f"  {skipped} hostnames already known not to resolve")
    if pending:
        echo(f"Probing {len(pending)} conventional hostnames ...")
        with ThreadPoolExecutor(max_workers=workers) as pool:
            confirmed = list(pool.map(
                lambda job: (job[0], job[1], job[2],
                             _confirm_derived(job[0], job[2], fetcher, root, max_age)),
                pending,
            ))
        for component, env, candidate, (result, accepted) in confirmed:
            url = endpoint_url_in(component, candidate, "openapi") if component.infores else None
            # Every request, not every success: nine of these hostnames do not
            # resolve, and a manifest that leaves them out is one that cannot
            # be used to ask what this run actually did.
            if result is not None:
                results.append(result)
            if not accepted:
                # How it was turned away, not just that it was. A hostname that
                # does not resolve and a host that answers as something else
                # are both "not confirmed" and they are not the same finding —
                # the first says there is nothing there, the second says there
                # is, and it belongs to somebody else. Recorded here rather
                # than left to be read out of the manifest, because a rejection
                # is carried forward for as long as it is fresh and the
                # manifest entry that explained it is not.
                rejected.setdefault(component.id, {})[env] = {
                    "url": candidate.url,
                    "checked_at": now(),
                    "status": result.status if result else None,
                    "error": result.error if result else None,
                    # Which question was asked, because a 200 means two
                    # different things depending on it. To a document check, a
                    # 200 reporting somebody else's infores is evidence the
                    # host belongs to another service. To a root probe -- all
                    # this component had, having no infores to check against --
                    # a 200 is only "something answers here", and calling that
                    # another service would be inventing the finding the check
                    # exists to make.
                    "checked": "document" if url else "root",
                }
                continue
            derived.setdefault(component.id, {})[env] = {
                "url": candidate.url, "location": candidate.location,
            }
        found = sum(len(envs) for envs in derived.values())
        echo(f"  {found} confirmed by the infores they report")
    # Carry forward anything confirmed earlier whose candidate was not re-derived
    # this run — a URL recorded in a component file stops being derived, and
    # dropping it here would look like the deployment had disappeared.
    #
    # Not the ones this run probed and rejected, though: those were asked and
    # answered, and reinstating them would publish a derived deployment forever
    # on the strength of one confirmation, however long ago it stopped being
    # true. A rejection is the newer fact.
    for cid, envs in confirmed_before.items():
        for env, spec in envs.items():
            if env in rejected.get(cid, {}):
                continue
            derived.setdefault(cid, {}).setdefault(env, spec)
    (root / "derived.json").write_text(
        json.dumps({"confirmed": derived, "rejected": rejected}, indent=2) + "\n",
        encoding="utf-8",
    )
    return results


def _echo_matching_summary(
    components: list[ComponentFile],
    root: Path,
    by_smartapi: dict[str, dict[str, Any]],
    echo: Callable[[str], None],
) -> None:
    """The two lines that say what this sync could not attribute.

    Printed even at zero, unlike the throttling warning: "no chart is
    unaccounted for" is a finding, and a line that appears only on bad news
    reads as a missing check on the good day.
    """
    names = _chart_names(root)
    unclaimed = unclaimed_charts(names, _cached_chart_meta(root, names), components)
    echo(
        f"Charts matching no component: {len(unclaimed)}"
        + (f" ({', '.join(unclaimed)})" if unclaimed else "")
    )

    hits = list(by_smartapi.values())
    suggestions = []
    for component in components:
        # Only where the file records no id: a component that records one has
        # already been matched by it, and a fallback firing because the
        # recorded id is missing from the registry is a different finding —
        # that one belongs in the record, not in a list of pointers to add.
        if component.smartapi_id:
            continue
        record, matched_by, _ = smartapi_record_for(component, hits)
        if matched_by == "infores" and record:
            title = (record.get("info") or {}).get("title") or record.get("_id")
            suggestions.append(f"{component.id} ← {title}")
    echo(
        "SmartAPI records matching a component by infores that records no id: "
        f"{len(suggestions)}"
        + (f" ({', '.join(suggestions)})" if suggestions else "")
    )


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

    Runs in waves because each depends on the one before it: SmartAPI is what
    tells us which environments most components have and the chart index is
    what tells us which charts exist, so neither the per-endpoint fetches nor
    the per-chart ones can be planned until wave one has landed.

    1. Wave one waits on nothing: the SmartAPI registry, the OpenTelemetry
       collectors, the infores catalog, the chart index, the claimed charts'
       files and last commits, and each source repository's releases and
       description.
    2. Wave two waits on wave one: the OpenAPI and `/status` endpoints the
       registry and the component files point at, a `Chart.yaml` for every
       chart the index names, and a root probe of every known deployment.
    3. Wave three, last: the conventional `transltr.io` hosts nobody
       registered, derived from the deployments wave one revealed, each
       believed only if it reports the component's own infores. What it
       confirms is probed by the next run's wave two (`_confirmed_deployments`).

    Then the run writes `derived.json`, prints the chart and matching summaries,
    and writes the manifest.
    """
    report = SyncReport(started_at=now())
    root.mkdir(parents=True, exist_ok=True)

    previous_urls = _previous_urls(root)

    def age_for(url: str, destination: Path) -> int:
        recorded = previous_urls.get(str(destination.relative_to(root)))
        # Cached, but fetched from somewhere else: not an answer to this run's
        # question, however recent it is.
        return 0 if recorded is not None and recorded != url else max_age

    def run_all(
        *groups: tuple[list[tuple[str, Path]], Callable[..., FetchResult]],
    ) -> list[FetchResult]:
        """Several groups of jobs in one pool, each with its own writer.

        The writer is `fetch_to` or `probe_to` — the same pool, the same
        freshness rule and the same manifest, differing only in what lands on
        disk. Grouped rather than run one list after another so a wave stays
        one wave: the root probes and the endpoint fetches wait on the same
        registry answer and on nothing else, and two sequential pools would
        pay the slowest host's latency twice for no reason.
        """
        planned = [(url, dest, do) for jobs, do in groups for url, dest in jobs]
        if not planned:
            return []
        with ThreadPoolExecutor(max_workers=workers) as pool:
            results = list(
                pool.map(
                    lambda job: job[2](
                        job[0], job[1], fetcher,
                        max_age=age_for(job[0], job[1]), root=root,
                    ),
                    planned,
                )
            )
        report.fetches.extend(results)
        return results

    def run(jobs: list[tuple[str, Path]]) -> list[FetchResult]:
        return run_all((jobs, fetch_to))

    # Wave one: the registries, the catalogue, the charts, the chart index, the
    # release lists and the repository descriptions. None of these depends on
    # any of the others, so they go out together.
    release_jobs = _plan_release_fetches(components, root)
    repo_jobs = _plan_repo_meta(components, root)
    chart_jobs = _plan_chart_fetches(components, root)
    commit_jobs = _plan_chart_commits(components, root)
    echo(
        "Fetching the SmartAPI registry, the OpenTelemetry collectors, the "
        f"infores catalog, the chart index, {len(release_jobs)} GitHub release "
        f"lists and {len(repo_jobs)} repository descriptions ..."
    )
    registry_jobs = [(SMARTAPI_QUERY, root / "smartapi.json")]
    registry_jobs += [
        (url, root / "otel" / f"{env}.json") for env, url in OTEL_COLLECTORS.items()
    ]
    registry_results = run(
        registry_jobs
        + [
            (INFORES_CATALOG, root / "infores_catalog.yaml"),
            (DEVOPS_HELM_INDEX, root / "helm" / "index.json"),
        ]
        + chart_jobs
        + commit_jobs
        + repo_jobs
        + release_jobs
    )
    throttled = sum(
        1
        for result in registry_results
        if result.url.startswith(GITHUB_API_PREFIX) and result.status in (403, 429)
    )
    if throttled:
        # Silence here would look like "these repositories have no releases",
        # "this chart has never been committed to" and "there is no such
        # repository" — three findings, none of them true.
        echo(
            f"  {throttled} GitHub API calls were rate-limited — set "
            f"GITHUB_TOKEN to raise the hourly limit. This run shows fewer "
            f"facts; the next one picks them up"
        )

    by_smartapi = {}
    smartapi_path = root / "smartapi.json"
    if smartapi_path.exists():
        # Several Translator hosts answer 200 with an HTML error page, and this
        # file is whatever came back. Parsing it in the open would end the run
        # after the registries, the charts and the release lists had all
        # succeeded — the opposite of "a service being down is data".
        try:
            payload = json.loads(smartapi_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            payload = None
        if not isinstance(payload, dict):
            echo("  smartapi.json is not a registry response — continuing without it")
            payload = {}
        hits = payload.get("hits")
        by_smartapi = {
            hit["_id"]: hit
            for hit in (hits if isinstance(hits, list) else [])
            if isinstance(hit, dict) and hit.get("_id")
        }
        echo(f"  {len(by_smartapi)} SmartAPI records")

    # Wave two: the endpoints those registries point at, and a Chart.yaml for
    # every chart the index just named. Neither could be planned before wave
    # one landed — one waits on SmartAPI, the other on the index — and neither
    # waits on the other, so they go out in one pool.
    endpoint_jobs = _plan_endpoint_fetches(components, by_smartapi, root)
    index_chart_jobs = _plan_index_chart_fetches(
        root, [destination for _, destination in chart_jobs]
    )
    previous = _read_derived(root)
    root_jobs = _plan_root_probes(
        components, by_smartapi, _confirmed_deployments(previous), root
    )
    echo(
        f"Fetching {len(endpoint_jobs)} component endpoints and "
        f"{len(index_chart_jobs)} unclaimed charts, and probing "
        f"{len(root_jobs)} deployment roots ..."
    )
    run_all((endpoint_jobs + index_chart_jobs, fetch_to), (root_jobs, probe_to))

    # Wave three: the environments nobody registered, each confirmed against
    # the infores it reports before it is believed.
    report.fetches.extend(_probe_derived_hosts(
        components, by_smartapi, previous,
        fetcher=fetcher, root=root, max_age=max_age, workers=workers, echo=echo,
    ))

    # How much of the chart repository the component files account for. Two
    # numbers rather than a list of names: naming the unclaimed charts is a
    # matching problem, and a guess at it printed here would be read as a
    # finding.
    charted, claimed = _chart_totals(components, root)
    echo(
        f"Helm charts in translator-devops: {charted}; "
        f"claimed by component files: {claimed}"
    )
    # And now the matching problem itself, answered with evidence rather than
    # guessed at. Both lines are the sync's half of the data PR they ask for:
    # a chart nothing accounts for wants an entry in unknown.yaml, and a
    # registry record found by infores wants its id recorded in the component
    # file. Neither is written anywhere by this command — components/*.yaml and
    # unknown.yaml are hand-edited and test-enforced, and a fetcher that edited
    # them would be deciding what the maintainers decide.
    _echo_matching_summary(components, root, by_smartapi, echo)

    report.finished_at = now()
    (root / "manifest.json").write_text(
        json.dumps(report.to_dict(), indent=2) + "\n", encoding="utf-8"
    )
    return report
