# content/

The components as files, with nothing withheld. This directory is the private
half of the answer to
[issue #7](https://github.com/NCATSTranslator/translator-diagram/issues/7):
the published dashboard is one redacted page anyone can open, and this is
the same inventory, plus everything the page has no column for, readable by
anyone who can read the repository. The design, the alternatives it was
chosen over, and the runbook for making the repository private are in
[`docs/public-private-split.md`](../docs/public-private-split.md).

**This is a demonstration.** The repository is still public, so every value
that would be private is the literal string `PRIVATE`, on three components.
Everything else here comes from a public service or a file already in this
repository.

## The public page and these files, side by side

| | Published page | This directory |
|---|---|---|
| Who can open it | Anyone with the link | Anyone with access to this repository |
| What it withholds | Whatever [`config/privacy.yaml`](../config/privacy.yaml) names | Nothing |
| The `private:` block in a component file | Never reaches it | On that component's page |
| Interactive | Sort, filter, search | No — GitHub renders the Markdown and the CSV |
| Refreshed | Daily, by the Pages workflow | By the refresh workflow, through a pull request |
| Where the date is | On the page | `git log -1 -- content/` |

The interactive view of *this* data is a local build:

```bash
uv run sync-components
uv run build-dashboard --include-private
open data/dashboard/index.html
```

## What is here

| File | What it is | Comes from |
|---|---|---|
| [`dashboard.md`](dashboard.md) | The dashboard's table, by stage, as one file | The last sync |
| [`deployments.csv`](deployments.csv) | One row per component and environment, every field of every cell | The last sync |
| [`components.csv`](components.csv) | The components in the Google Sheet's column layout; `generate-diagram --input content/components.csv` draws it | `components/*.yaml` |
| [`diagram.svg`](diagram.svg), [`diagram.dot`](diagram.dot) | The diagram drawn from that CSV | `components.csv`, through Graphviz |
| [`components/`](components/) | One page per component: what its file records, then what is running | `components/*.yaml` and the last sync |

Each component page is two halves around a `<!-- live -->` marker. Above it
is what a checkout alone determines, and a test fails when that half is out
of date with the component files. Below it is what the last sync found, which
only a run with a sync can refresh.

`components.csv` holds the 26 components that have a file. The Google Sheet
holds about 96 rows; converting the rest is
[issue #20](https://github.com/NCATSTranslator/translator-diagram/issues/20),
and until it is done this CSV shows the format rather than replacing the
sheet.

## Regenerating it

```bash
uv run sync-components              # fetch, into data/sync/
uv run build-content --diagram      # write this directory
```

Without a sync, `build-content` writes `components.csv` and the static half
of each page and says so. `--diagram` needs Graphviz on the path.

Nothing here carries a timestamp, on purpose: a rebuild that changes nothing
writes nothing, so a scheduled refresh on a quiet day opens no pull request.
When a file was last rebuilt is `git log -1 -- content/`, and it says who
merged it, which the file could not.

## Editing it

Do not. Every file here is written by `build-content`, and the next run
overwrites it. Change the component files, the stage order, or the code, and
rebuild. This README is the one hand-written file.
