# Security

This document covers the security questions this repository raises, with a
focus on the published dashboard. Two risks matter most:

1. **Load.** Information that helps someone put load on Translator where it
   hurts most: which service is thinnest, which endpoint is slowest, and what
   query to send it.
2. **Access.** Information that helps someone get into a component: internal
   tools, software inventories, credentials, and a map of what talks to what.

A third section covers the page and its build as attack surfaces in their own
right.

This is a living document. Each section separates what we have addressed from
what we must not reintroduce and what is still open. If you spot something
missing, add it under [Areas not yet examined](#areas-not-yet-examined), even
as a single line.

**Do not report a live vulnerability in a Translator component as a public
issue here.** This repository is public. Report it privately from the
repository's Security tab, as [`SECURITY.md`](../SECURITY.md) describes.

## The ground rule: reach, not secrecy

Everything the dashboard shows is read from public sources. Those are the
SmartAPI registry, GitHub, the infores catalog, `helxplatform/translator-devops`,
and the deployments' own public endpoints. This repository is also public, and
[`config/privacy.yaml`](../config/privacy.yaml) names what it withholds and
why.

So the privacy policy hides nothing from someone who goes looking. What it does
is keep a few facts off a page that arrives without being asked for. That
shapes how problems get fixed:

- **A fact too sensitive to publish must be fixed where it is served.** For
  example, an unauthenticated API should get authentication, and a registry
  record with a private hostname should be edited. Redacting it here only makes
  the exposure harder to notice.
- **This repository's job is to avoid concentrating scattered public facts
  into one convenient target list**, and to avoid becoming a leak itself.

Background: [`src/translator_diagram/privacy.py`](../src/translator_diagram/privacy.py)
(module docstring) and the README section *What a published build leaves out*.
The wider public/private question is
[#7](https://github.com/NCATSTranslator/translator-diagram/issues/7); who the
private build is for is
[#34](https://github.com/NCATSTranslator/translator-diagram/issues/34).

## What is published, and where

- **The dashboard.** `index.html` and `overview.json` on GitHub Pages, rebuilt
  daily and on every push to `main` by `.github/workflows/pages.yml`. The HTML
  carries `<meta name="robots" content="noindex, nofollow">`: anyone with the
  link can reach it, but search engines should not list it.
- **Branch builds.** A manual run of the same workflow on any other branch
  uploads the same page as a downloadable workflow artifact, with the privacy
  policy applied. Pull requests do not build it.
- **This repository.** Component files, `unknown.yaml`, the privacy policy,
  and the sync code, including the URLs it contacts.
- **The diagram** (`generate-diagram`). Not published automatically today.
  [#10](https://github.com/NCATSTranslator/translator-diagram/issues/10) would
  publish it and is blocked on #7.

## 1. Information that helps someone load Translator

### Published today, deliberately

Each item is already public at its source. Together they answer "where would
an attack hurt most", so each one should stay a considered choice.

- **Deployment hosts per environment.** These are what make a version claim
  checkable, and every one is recorded in this repository or listed in the
  SmartAPI registry.
- **Endpoint shape.** The OpenAPI and `/status` URLs, TRAPI operations,
  `asyncquery` support, and path counts, all read from each service's own
  public document.
- **`batch_size_limit` and `rate_limit`** from SmartAPI records. These tell a
  caller exactly how large a request can be before it is refused.
- **`test_data_location`** from SmartAPI records. These are ready-made queries
  that are known to exercise each service.
- **`recent_queries`.** A count plus p50 and p95 latency from `/status` bodies
  that report them. This is the only usage-shaped signal on the page.
  `config/privacy.yaml` names it as the first environment field to withhold if
  any needs withholding.
- **Helm capacity.** Replicas, CPU and memory requests and limits, and storage
  sizes. Together these rank services by how little it takes to exhaust them.
- **Reachability and uptime.** Rebuilt at most daily, which limits how useful
  the page is as feedback while someone is attacking a service.

### Do not introduce

- **Anything live or near-live.** A faster rebuild, or a client-side fetch of
  current status, turns the page into a monitor for anyone degrading a service.
- **Per-query or per-caller detail** beyond the three `recent_queries` numbers.
- **Sampled traces or latency breakdowns.** `FUTURE.md` sketches trace samples
  and rendered Helm manifests. Both would need a fresh review against this
  section before being built.
- **Error bodies copied verbatim.** Stack traces and framework error pages
  reveal internals. The page shows short reasons such as `HTTP 502`, not
  response bodies. Keep it that way.

### The sync must not become the load

`sync-components` runs daily, on every push to `main`, and on each manual run
of the workflow, from any branch. Each run fetches every recorded endpoint and
root, with 12 workers and a 30 second timeout. It also *derives* likely
hostnames for environments nobody recorded and probes them
(`derive_deployments` in `deployments.py`, `_confirm_derived` in `sync.py`).

Each fetch identifies itself with a `User-Agent` naming this repository, and
results are cached under `data/sync/`. Any change that adds fetches, workers,
triggers or retries should state what it adds per run.

## 2. Information that helps someone gain access

### Addressed

- **Internal tools are withheld as whole rows.** `jaeger` (the OpenTelemetry
  tracing console) and `test-harness` (the internal test rig) are dropped from
  the table and from `overview.json`. Any recorded connection to them is pruned
  from the rows that remain.
- **Mentions are scrubbed, then the whole payload is checked.** A withheld id
  that appears as a word in third-party free text is replaced with `…`. That
  covers notes, registry and repository descriptions, topics, release notes,
  chart descriptions and commit subjects, catalog text, and status messages.
  `privacy.verify` then serializes the finished payload and refuses to write
  the build if a withheld id appears anywhere, including in a URL.
- **Container image tags are withheld.** Next to the version grid they would
  form a ready-made inventory to match against a CVE feed.
  `tests/test_payload_details.py` scans every cached chart's real output to
  confirm the public Helm block never carries an image, and checks that the
  scan can fail.
- **Placeholder ingress hosts are dropped** (`fillthisin`, `ingress_HOST`)
  rather than published as if they were hostnames.
- **Redaction is the default.** `build-dashboard` withholds unless given
  `--include-private`, and the Pages workflow passes no flag. A policy entry
  that matches nothing stops the build, so a renamed component cannot quietly
  stop being withheld.
- **A full build has its own directory.** `build-dashboard --include-private`
  writes to `data/dashboard-private/`, so it cannot overwrite the publishable
  build in `data/dashboard/` and be served or shared from there by mistake. An
  explicit `--output-dir` still overrides this. Either way, `build-dashboard`
  names on stderr any file in its output directory that it did not write, since
  a preview serves it beside the page. Who the full build is for is still
  [#34](https://github.com/NCATSTranslator/translator-diagram/issues/34).
- **The agent notes stay off the page.** `src/translator_diagram/web/` holds
  `AGENTS.md`, with screenshot recipes and internal decisions, beside the files
  the page inlines. Tests in `tests/test_dashboard.py` and
  `tests/test_dashboard_cli.py` fail if it is inlined, raw, escaped or rendered,
  or written beside the page.
- **Credentials stay where they belong.**
  - `GITHUB_TOKEN` is sent to `api.github.com` and nowhere else (`_headers` in
    `fetch.py`). Locally it comes from the environment or a gitignored `.env`;
    in Actions it is the default workflow token, which the Pages workflow's
    `contents: read` limits to reading.
  - `GOOGLE_SHEET_ID` is read from a `.env` in the working directory or a
    parent (`loading.py`), and `.env` is gitignored.
  - All cached and generated output lives under the gitignored `data/`.

### Published today, deliberately

- **Software versions per environment**, including chart `appVersion`. This is
  the dashboard's purpose. It is Translator's own software, with public release
  notes, rather than third-party images.
- **The connection graph**, recording which component calls which. It is built
  from the public component files, but it is also a map for moving between
  services. Withheld components are absent from it.
- **OpenTelemetry service names** (`otel_services`). Internal naming, already
  public in the component files.
- **SmartAPI contact names and emails.** Already public in each registry
  record, but gathered in one place they make a phishing list.
- **Chart-default ingress hosts**, labelled as defaults rather than as what
  ITRB deploys.
- **`derived_rejected`.** Hostnames the naming convention predicted, where
  nothing answered or something other than this component did. A live host
  under a conventional name that does not belong to the component is worth a
  person's attention, and is also worth an attacker's.
- **`overview.json` without a `noindex`.** GitHub Pages cannot send an
  `X-Robots-Tag` header, and crawlers read `robots.txt` only from the root of
  the Pages domain, not from this project's path. The file stays published
  anyway, for three reasons. It is a contract other tools may read. The page
  does not link to it, so a crawler finds it only through someone else's link.
  And it adds nothing: the same payload is inlined in `index.html`, which does
  carry `noindex`. If the file ever holds something the page does not, look at
  this again.

### Do not introduce

- **Any credential in a fetched URL or header** beyond `GITHUB_TOKEN` to GitHub.
  If a source ever needs authentication, the token goes only to that host, and
  nothing derived from an authenticated response is published without review.
- **Image repositories or tags by another route.** For example, rendered
  manifests, SBOMs, or a `/status` body that reports base images.
- **New internal hosts.** Anything under `translator-otel.*`, admin consoles,
  databases, or cluster-internal names. Add the component to
  `config/privacy.yaml`, not just the field.
- **Free text that is not scrubbed.** A new prose field must be added to
  `ROW_FREE_TEXT` in `privacy.py`. If it is missed, `verify` still catches a
  withheld id, but only by failing the nightly build.

### Open

- **Is the Jaeger query API reachable without authentication?** `sync.py`
  reads `https://translator-otel.{ci,test,}.transltr.io/api/services` with no
  credential. If that works from the public internet, the trace search API on
  the same host probably does too. Traces can carry query contents, internal
  hostnames and headers. This needs confirming with ITRB, and fixing there if
  so. Withholding the `jaeger` row does not help: the URLs are in this public
  repository. Tracked in
  [#44](https://github.com/NCATSTranslator/translator-diagram/issues/44).
- **Handing out the full build.** Its own directory stops accidents, not
  decisions: sharing it on purpose is
  [#38](https://github.com/NCATSTranslator/translator-diagram/issues/38).
- **The diagram is not covered by the privacy policy.** Its SVG tooltips embed
  owner, status and notes from the Google Sheet, and `components.json` carries
  every column of every row that is not hidden. Both must be reviewed before
  #10 publishes them.

## 3. The page and its build as attack surfaces

Much of the data on the page is written by people outside this repository: the
SmartAPI registry is open to registration, and GitHub release notes and
repository topics belong to other teams. Treat every field as hostile markup.

### Addressed

- **Escaping.** Every value is escaped (`TD.fmt.esc`) before it is put into
  HTML. The one exception is a component's `description`, which
  `TD.fmt.prose` renders from a small Markdown subset, `code` and links only:
  every other character is escaped, and its links pass the check below.
  `tests/web/prose.test.js` covers it.
- **Links.** Only `http` and `https` URLs become links (`TD.fmt.href` on the
  dashboard, `_valid_url` in the diagram). Anything else, such as a
  `javascript:` server URL in a registry record, renders as text.
  `tests/web/urlstate.test.js` covers the check.
- **The inlined payload** has `</` escaped, so a string cannot close the
  `<script>` tag early.
- **URL state.** Query parameters are parsed against a fixed vocabulary
  (`TD.url.parse` in `core.js`), so a crafted link can only select views,
  sorts and filters that already exist.
- **No third-party resources.** No external scripts, fonts, CDNs or analytics.
  The page is one self-contained file, so a compromised third party cannot
  change it and no viewer's visit is reported to anyone. `localStorage` holds
  only the theme choice.
- **Actions are pinned to commit SHAs**, with the version in a comment, so a
  moved tag cannot run new code with Pages deploy permission.
  `.github/dependabot.yml` proposes updated pins weekly. A pin covers only the
  action it names: a composite action that runs another by tag is still
  exposed through it. `upload-pages-artifact` is the one composite here, and is
  at v4.0.0 or later because v3 ran `actions/upload-artifact@v4` by tag; the
  others are plain Node actions that run nothing else.
- **Python dependencies move only by review.** CI and the Pages build install
  `uv.lock` with `--locked`, and `.github/dependabot.yml` proposes updates to
  it weekly, as pull requests, alongside the action pins.
- **Deploys are narrow.** The Pages workflow runs with `contents: read`. Only
  the deploy job gets more: `pages: write`, and `id-token: write`, which lets
  it mint an OIDC token. `deploy-pages` needs it to prove to Pages which
  repository and workflow is deploying. Nothing in this repository accepts
  that token elsewhere, but a cloud role set up to trust this repository's
  OIDC identity would let the job assume that role too, so grant one only with
  this job in mind. The job runs only on `main`, which the
  `github-pages` environment enforces from its side too: it accepts
  deployments from `main` alone. A manual run on any other branch only uploads
  an artifact, and pull requests, including from forks, build nothing.
- **Every change to `main` goes through a pull request.** The *Protect
  default branch* ruleset requires one, approved by a code owner, and
  [`.github/CODEOWNERS`](../.github/CODEOWNERS) names the owner of every path,
  workflows included. Its one bypass, for the repository's owner, applies to
  pull requests only, so even that cannot push to `main` directly.

### Do not introduce

- **A new `innerHTML` interpolation that skips `esc`**, or an `href` or `src`
  that skips `TD.fmt.href`. Around twenty `innerHTML` assignments depend on
  this discipline. `tests/web/` covers the pure helpers, but the code that
  builds the drawer, table and map has no test harness
  ([#22](https://github.com/NCATSTranslator/translator-diagram/issues/22)).
- **External scripts, stylesheets, fonts or images** loaded at view time.
- **A deploy from anywhere but `main`.** The deploy job's `if:` names `main`
  alone, whichever event started the run, and the `github-pages` environment
  refuses other branches. Keep both.

### Open

- **No Content Security Policy.** The page is one file with inline script and
  style. A `<meta http-equiv="Content-Security-Policy">` with hashes, or
  `script-src 'self'` once assets are split out, would limit the damage of an
  escaping mistake.
- **Dependabot security updates and secret scanning are off.** Vulnerability
  alerts are on, so a known-vulnerable package in `uv.lock` is flagged, but
  nothing opens the fix as a pull request ahead of the weekly update, and
  nothing scans pushes for committed credentials.
- **`main` accepts force pushes, and CI is not a required check.** The ruleset
  blocks deleting `main` and requires an approved pull request, but has no
  *Block force pushes* rule and no required status checks, so a reviewed pull
  request can merge with failing tests.

## Checklist for a change

Run through this when a pull request adds a field, a source, a fetch or a
rendering path:

- [ ] **A new payload field.** Does it help someone load Translator
  (section 1) or reach a component (section 2), and is it written by someone
  outside this repository, which makes it hostile markup (section 3)? Is it
  public at its source? If it stays published, record why in the *Considered
  and deliberately not withheld* list at the bottom of `config/privacy.yaml`.
  If it is prose, add it to `ROW_FREE_TEXT`.
- [ ] **A new source.** Does it need a credential? The credential goes only to
  that host, and it must not appear in `data/sync/manifest.json`, the cache, or
  an error message.
- [ ] **A new fetch.** How many requests per run, on which triggers, against
  whose service?
- [ ] **A new rendering path.** Is every value escaped and every link checked?
  Does it load nothing external?
- [ ] **A workflow change.** A new action is pinned to a commit SHA with its
  version in a comment, and, if it is a composite (`using: composite` in its
  `action.yml`), the actions it runs are pinned too. The deploy job still
  deploys from `main` alone.
- [ ] **A new internal tool or host.** Add it to `config/privacy.yaml` in the
  same pull request.
- [ ] **This document.** Move anything you addressed out of *Open*, and add
  anything you noticed.

## Areas not yet examined

These have not been looked at closely. Add to this list freely.

- What upstream `/status` bodies and OpenAPI documents actually contain beyond
  the fields we read. We copy titles, messages and descriptions, and a team
  could put an internal hostname or a note about a known weakness in any of
  them.
- Release note excerpts. The scrub only removes withheld component ids, so a
  release that mentions a hostname, a password reset or an unpatched issue is
  published as written.
- [`catalog/unknown.yaml`](../catalog/unknown.yaml) and the component files in
  [`catalog/components/`](../catalog/components/), for internal URLs committed
  by hand.
- Whether the connection graph plus Helm capacity identifies a single point of
  failure that the platform would rather not advertise.
