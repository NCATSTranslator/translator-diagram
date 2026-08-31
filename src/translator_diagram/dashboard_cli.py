"""The two dashboard commands: sync, then build.

Split for the same reason the reference implementations split them: fetching
is slow and rate-limited, rendering is fast and iterated on. Keeping them apart
means you can rebuild the page a hundred times against one sync.

Nothing imports this module, in either direction — same rule as cli.py.
"""

from pathlib import Path

import click

from .components import load_components
from .dashboard import SyncedData, build_payload, write_dashboard
from .flow import isolated
from .sync import DEFAULT_MAX_AGE, sync

DEFAULT_COMPONENTS = Path("components")
DEFAULT_SYNC_DIR = Path("data/sync")
DEFAULT_OUTPUT_DIR = Path("data/dashboard")


def _load(components_dir: Path):
    if not components_dir.is_dir():
        raise click.ClickException(
            f"No components directory at {components_dir}. Run from the "
            f"repository root, or pass --components."
        )
    components = load_components(components_dir)
    if not components:
        raise click.ClickException(f"No *.yaml files in {components_dir}.")
    return components


@click.command()
@click.option("--components", "components_dir", type=click.Path(path_type=Path),
              default=DEFAULT_COMPONENTS, show_default=True,
              help="Directory of component YAML files.")
@click.option("--output-dir", type=click.Path(path_type=Path),
              default=DEFAULT_SYNC_DIR, show_default=True,
              help="Where to cache the fetched responses.")
@click.option("--max-age", type=int, default=DEFAULT_MAX_AGE, show_default=True,
              help="Skip re-fetching anything cached and newer than this many "
                   "seconds. 0 fetches everything.")
@click.option("--force", is_flag=True,
              help="Re-fetch everything, ignoring --max-age.")
@click.option("--workers", type=int, default=12, show_default=True,
              help="Parallel fetches.")
def sync_main(components_dir, output_dir, max_age, force, workers):
    """Fetch what the component files point at, into a local cache.

    A service being down is recorded, not fatal: the manifest keeps the status
    of every fetch, and the dashboard shows it. The command fails only if it
    could not fetch anything at all, so a non-zero exit stays meaningful.
    """
    components = _load(components_dir)
    click.echo(f"Following the pointers in {len(components)} component files ...")
    report = sync(
        components,
        output_dir,
        max_age=0 if force else max_age,
        workers=workers,
        echo=click.echo,
    )
    counts = report.to_dict()["counts"]
    click.echo(
        f"{counts['succeeded']}/{counts['attempted']} fetches succeeded "
        f"({counts['cached']} from cache, {counts['failed']} failed)."
    )
    click.echo(f"Wrote {output_dir / 'manifest.json'}")
    if counts["succeeded"] == 0:
        raise click.ClickException(
            "Every fetch failed — check the network rather than the data."
        )


@click.command()
@click.option("--components", "components_dir", type=click.Path(path_type=Path),
              default=DEFAULT_COMPONENTS, show_default=True,
              help="Directory of component YAML files.")
@click.option("--sync-dir", type=click.Path(path_type=Path),
              default=DEFAULT_SYNC_DIR, show_default=True,
              help="Cache written by sync-components.")
@click.option("--output-dir", type=click.Path(path_type=Path),
              default=DEFAULT_OUTPUT_DIR, show_default=True,
              help="Where to write index.html and overview.json.")
def build_main(components_dir, sync_dir, output_dir):
    """Compile the synced responses into a single self-contained page."""
    components = _load(components_dir)
    if not (sync_dir / "manifest.json").exists():
        raise click.ClickException(
            f"No manifest at {sync_dir / 'manifest.json'}. Run sync-components first."
        )
    synced = SyncedData(sync_dir)
    payload = build_payload(components, synced)

    deployments = sum(
        1
        for row in payload["rows"]
        for cell in row["environments"].values()
        if cell.get("deployed")
    )
    if deployments == 0:
        # Refusing beats publishing a page that looks fine and says nothing.
        raise click.ClickException(
            "No deployments resolved for any component — refusing to write an "
            "empty dashboard. Is data/sync/smartapi.json present and non-empty?"
        )

    html_path, json_path = write_dashboard(payload, output_dir)
    tally = payload["source_tally"]
    click.echo(f"{len(payload['rows'])} components, {deployments} deployments.")
    click.echo(
        "Version sources: "
        + ", ".join(f"{source} {count}" for source, count in sorted(tally.items()))
    )
    stranded = isolated(components)
    if stranded:
        click.echo(f"No recorded dependencies for: {', '.join(stranded)}")
    click.echo(f"Wrote {json_path}")
    click.echo(f"Wrote {html_path}")
