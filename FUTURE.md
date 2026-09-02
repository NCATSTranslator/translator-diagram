# Future work

Things worth doing that are not done, with enough of the reasoning that the
next person does not have to rediscover why. Open issues live on GitHub; this
file is for the ideas that came out of building something and would otherwise
be lost in a pull request description.

## Date a deployment, not just a release

The dashboard's `Last updated` column answers "when did this component last
change" from a GitHub release or a SmartAPI registration. Neither answers the
question people actually ask, which is **when was this environment last
deployed**. Nothing we currently fetch knows: the OpenAPI documents carry no
date, the Helm chart files carry no date, and SmartAPI's `_status.refresh_ts`
is its own uptime probe.

**The Helm chart's last commit is the closest available proxy.** ITRB deploys
from [`helxplatform/translator-devops`](https://github.com/helxplatform/translator-devops),
so the last commit touching `helm/<chart>/` dates the intent to deploy:

```bash
curl -s 'https://api.github.com/repos/helxplatform/translator-devops/commits?path=helm/name-lookup&per_page=1'
```

One call per chart, and we record five charts (`answer-appraiser`, `jaeger`,
`name-lookup`, `shepherd`, `test-harness`), so five calls a sync. Two things
to be careful about if this is built:

- It dates the *intent*, not the deployment. A chart change that was never
  rolled out, or a rollout of an unchanged chart, both make it wrong. It
  belongs in its own column or its own badge — `deployed`, say — and never
  silently merged into `Last updated`.
- It would give `jaeger` a date it currently lacks, but only two of the five
  charted components are among the thirteen with no date at all, so it is
  worth doing for what it *means* rather than for the coverage.

## Fill in the components with no date at all

Thirteen of twenty-six components show no `Last updated`: they publish no
GitHub releases and appear in no SmartAPI record. `GET /repos/{owner}/{name}`
returns `pushed_at`, which would date every one of them that has a repository,
at the cost of a second GitHub call per repository — about 19 more per sync.

Deliberately not done for now: a push to any branch moves `pushed_at`, so it
answers "has anyone touched this repository" rather than "has this component
changed", and it would outrank the release date on nearly every row and make
the `release` badge vanish. If it is added, it should rank *below* a release
rather than by recency.

## Watch the GitHub budget

Both ideas above spend from the same allowance: **60 requests an hour** for an
unauthenticated address, 5000 with a `GITHUB_TOKEN` in the environment (see
`_headers` in `sync.py`). One full sync currently spends 19. Release lists are
already keyed by repository rather than by component, so the three shepherds
cost one call between them; anything added here should be keyed the same way.

## An authenticated web view of the full dashboard

`content/` is the non-interactive private view, and the interactive one is a
local build. The thing not built is the full dashboard, with its sorting and
filtering, behind a sign-in — so someone without a checkout could open it.
Considered in [`docs/public-private-split.md`](docs/public-private-split.md)
and set aside, not rejected.

The cheapest shape is a static site behind an identity proxy: the published
workflow builds the full page as well as the redacted one, pushes the full
one to a private host, and something like Cloudflare Access or an nginx
`auth_request` in front of it checks a GitHub login against the same team
that can read this repository. No application code; the page is already
self-contained. The costs are what any hosted thing costs — a host, a
certificate, a person who knows it exists when it breaks — plus a second
access list that must be kept in step with the repository's collaborators,
which is the part most likely to drift.

If it is built, build it from `data/dashboard-full/`, the output of
`build-dashboard --include-private`, and change nothing else: the full build
is already the input this needs.
