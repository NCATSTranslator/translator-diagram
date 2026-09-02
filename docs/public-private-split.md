# The public/private split: a private repository with a public page

The design behind `content/`, the `private:` block and the refresh workflow,
written to be read before deciding whether to make this repository private.
It answers [issue #7](https://github.com/NCATSTranslator/translator-diagram/issues/7).

## The problem

Some of what this repository knows is for anyone: which components exist,
how they fit together, which API each one serves and where. Some of it is
not: internal hosts, who to call when a service is down, deployment details
that would be better kept to the people who deploy. Today the split is
enforced field by field. The repository is public, `data/` is gitignored,
`config/privacy.yaml` withholds a few rows and fields from the published
dashboard, and `docs/component-metadata.md` forbids copying anything
non-public into a component file at all.

That works only while nothing private ever enters the repository, and that
is exactly what stops this repository replacing the Google Sheet as the
source of truth. The sheet holds things the files may not, so the sheet
stays, and two sources of truth drift.

## The proposal

**Make the repository private, keep the page public, and move the border to
the one place that leaves the repository: the published build.** Inside the
repository, anything goes. The same tools then write two views:

- `build-dashboard` writes the page, redacted by `config/privacy.yaml`,
  verified by `privacy.verify`, and pushed to a public site. Anyone can open
  it.
- `build-content` writes `content/`: the same inventory with nothing
  withheld, plus everything a component file records that the page has no
  column for, as Markdown and CSV that GitHub renders. Anyone with access to
  the repository can open it, and the page links to it, so a reader who
  wants more finds the border drawn on the page rather than inferring it.

The private view is non-interactive, and that is a real cost. The
interactive private view is still a local build,
`build-dashboard --include-private`, which already exists and costs nothing.

## Two facts that shape it

**The NCATSTranslator organisation is on GitHub's Free plan.** GitHub Pages
on a private repository needs a Team plan or above, so the moment this
repository goes private, `ncatstranslator.github.io/translator-diagram/`
stops deploying. The page therefore has to be pushed *out* of the private
repository into a separate public repository whose only content is the built
site. That is a feature rather than a workaround: the border becomes "what
one workflow step pushes", and that step runs `privacy.verify` on its input.
The consequence to decide is that the public URL changes to
`ncatstranslator.github.io/<site-repository>/`, so the name of the site
repository is the name people bookmark.

**Actions minutes are metered on private repositories:** 2,000 a month on
Free. A sync and a build take about three minutes, so a daily refresh plus
the pull-request builds fit comfortably, but they are no longer unlimited.

## The alternatives

| Option | What it is | Verdict |
|---|---|---|
| Private sheet, public tools | Today, for the diagram: the source of truth is a sheet nobody can see without its URL, and the tools are public | The sheet is already outgrowing itself, it gives no public site, it is a second truth beside `components/`, and no tool with a checkout can read it. Retire it. |
| Public repository, per-field review | Today, for the dashboard: `privacy.yaml` plus the "public information only" rule | Sound as far as it goes, and "reach, not secrecy" stays true of the page. But it forbids ever recording anything private, so it cannot absorb the sheet. Keep the mechanism; drop it as the whole answer. |
| **Private repository, public site, generated `content/`** | This document | One truth, one border, GitHub enforces access, nothing to host. Costs: the URL changes, minutes are metered, a deploy key to manage, and the code goes private with the data. |
| A web application with authentication | The full interactive dashboard behind GitHub sign-in: Cloudflare Access in front of a static site, or a small server at RENCI | The interactive private view without cloning, but something to host, patch and gate, and a second access list to keep in step with the GitHub team. Not now. The private repository does not preclude it: the full build is its input, and `FUTURE.md` records the cost. |
| Clone and run locally | `uv run build-dashboard --include-private` | Already exists. Keep it as *the* interactive private view; `content/` is the one you can link to. |

## How the border is enforced

Three checks, each in code rather than in a review:

1. **`privacy.apply`** drops the rows and empties the fields
   `config/privacy.yaml` names, by default, so a forgotten flag costs
   information rather than publishing it. An entry that matches nothing is
   an error, so a renamed component cannot slip through.
2. **`privacy.verify`** re-reads the finished payload and searches it for
   anything the policy withheld, so a field added later that carries a
   withheld id somewhere `apply` never looks still stops the build.
3. **The `private:` block cannot reach the page at all.** `components.py`
   does not parse the key, so `ComponentFile` has no such field and nothing
   in the dashboard stack can copy it into the payload. `content.py` reads
   the YAML directly and is the only reader. `tests/test_content.py` builds a
   full payload from the real files and asserts that no key is `private` and
   no string from any block appears in it, which keeps holding when real
   values replace the `PRIVATE` placeholders.

The first two exist today and are about reach: everything the page shows
comes from a public service. The third is new and is about secrecy, which is
what changes when the repository is private. The rule to keep is that
**anything that must never be public goes under `private:`**, and nothing
else in a component file is treated as secret. A one-off review of the other
fields is not a mechanism.

## Refreshing `content/` without a robot rewriting the repository

Two kinds of file live in `content/`. The sheet CSV and the static half of
every component page are determined by the checkout alone; a test rebuilds
them and fails a pull request that changed `components/` without
regenerating. `dashboard.md`, `deployments.csv` and the live half of each
page come from a sync, and they change when the platform does, not when
anyone pushes. Three ways to refresh that second kind were weighed:

| Mechanism | `main` is written by | Freshness | Verdict |
|---|---|---|---|
| A workflow opens a pull request from a fixed branch; a person merges | People only | Daily, when someone merges | **Chosen.** Nothing lands on `main` unread; branch protection makes that structural; a quiet day opens nothing |
| A workflow commits to a `generated` branch, never `main` | Nobody | Daily, automatically | Simplest, but two places to look, and the page would link to a branch nobody reviews |
| People only, with the freshness test | People only | When someone remembers | Right for the static files; the live files would rot |

`.github/workflows/content.yml` is the first, with the freshness test
covering the static files. The job's token can write contents and pull
requests, it pushes only to `refresh-content`, and `main` requires a pull
request. That is the answer to "a workflow rewriting the repository": it
cannot, by permission and by branch protection rather than by convention.
Nothing generated carries a timestamp, so a sync that changes nothing
produces no diff and no pull request; when a file was last rebuilt is
`git log -1 -- content/`.

One gotcha, found the hard way: GitHub will only dispatch a
`workflow_dispatch` workflow that exists on the default branch. Until this
pull request merges, `gh workflow run content.yml` answers 404, so the first
manual run happens after the merge, not before it.

When to run it by hand: after editing a component file, run
`uv run build-content` and commit the result with the edit, or the freshness
test will say so. After a deployment you want reflected today, dispatch the
workflow rather than waiting for the schedule.

## Publishing the page from a private repository

Not built yet, because the site repository and its key do not exist. The
`deploy` job in `pages.yml` becomes a push into that repository:

```yaml
  publish:
    needs: build
    if: github.event_name == 'workflow_dispatch' || github.ref == 'refs/heads/main'
    runs-on: ubuntu-latest
    steps:
      - uses: actions/download-artifact@v4
        with:
          name: dashboard
          path: site
      - uses: peaceiris/actions-gh-pages@v4
        with:
          deploy_key: ${{ secrets.SITE_DEPLOY_KEY }}
          external_repository: NCATSTranslator/<site-repository>
          publish_branch: gh-pages
          publish_dir: site
          # One commit, replaced each time: the site repository holds the
          # current build and nothing else.
          force_orphan: true
```

The site repository is public and carries only the built page, so its
history is nothing but redacted builds. `force_orphan` keeps it to one
commit. `GITHUB_TOKEN` cannot reach another repository; a deploy key can,
and it is the only secret this design needs.

## The runbook for going private

In this order, because the page goes dark the moment the visibility changes:

1. Create the public site repository. Its name is the public URL; choose it
   for that.
2. Generate an SSH key pair. Public half as a deploy key with write access on
   the site repository; private half as `SITE_DEPLOY_KEY` on this one.
3. Replace the `deploy` job in `pages.yml` with the `publish` job above, and
   run it once by hand. Confirm the site repository's Pages settings serve
   `gh-pages`, and the page appears at the new URL.
4. Protect `main`: require a pull request, and do not exempt the Actions
   token.
5. Make this repository private. Confirm the old URL is gone, and that the
   new one still builds on the schedule.
6. Uncomment the schedule in `content.yml`.
7. Replace the `PRIVATE` placeholders with real values, and start moving
   what the Google Sheet holds that the files do not.
8. Retire `--google-sheet` (issue #19), once `components.csv` holds every row
   the sheet did (issue #20).

## Open questions for the group

- **The site repository's name**, which is the public URL from then on.
- **The refresh cadence.** Daily pull requests are a chore if nobody merges
  them; weekly might be enough, with a manual run for the day something
  changes.
- **What goes under `private:` first.** The block has three fields today;
  the sheet will say which others it needs.
- **Whether the code should stay public.** This design puts the code and
  the data in one private repository. Splitting them is possible later, at
  the cost of two repositories to keep in step.
