"""The dashboard commands: sync, then build the page, or build the content tree.

Sync and build are split for the same reason the reference implementations
split them: fetching is slow and rate-limited, rendering is fast and iterated
on. Keeping them apart means you can rebuild the page a hundred times against
one sync. `build-content` is a second consumer of the same sync: the full
payload as Markdown and CSV for the repository, rather than one redacted page
for the web.

Nothing imports this module, in either direction — same rule as cli.py.
"""

import shutil
import subprocess
from pathlib import Path

import click

from .components import load_components
from .content import read_private, write_content
from .dashboard import SyncedData, build_payload, write_dashboard
from .flow import isolated
from .privacy import load_policy
from .privacy import verify as verify_policy
from .sync import DEFAULT_MAX_AGE, sync

DEFAULT_COMPONENTS = Path("components")
DEFAULT_SYNC_DIR = Path("data/sync")
DEFAULT_OUTPUT_DIR = Path("data/dashboard")
DEFAULT_CONTENT_DIR = Path("content")
# Where --diagram renders before copying the picture into the content tree:
# under data/, so the PNG, the legends and components.json it also writes stay
# out of the repository.
DIAGRAM_SCRATCH_DIR = Path("data/content-diagram")


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


def _synced(sync_dir: Path) -> SyncedData:
    if not (sync_dir / "manifest.json").exists():
        raise click.ClickException(
            f"No manifest at {sync_dir / 'manifest.json'}. Run sync-components first."
        )
    return SyncedData(sync_dir)


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
@click.option("--include-private", is_flag=True,
              help="Skip config/privacy.yaml and build the full page. For "
                   "local use: the result is not safe to publish.")
def build_main(components_dir, sync_dir, output_dir, include_private):
    """Compile the synced responses into a single self-contained page.

    Withholds what config/privacy.yaml names unless --include-private is
    passed. That way round on purpose: a forgotten flag costs information
    rather than publishing it, and the workflow that publishes passes no flag
    at all, so it cannot regress into a full build by being edited.
    """
    components = _load(components_dir)
    synced = _synced(sync_dir)
    policy = None if include_private else load_policy()
    payload = build_payload(components, synced, policy)
    if policy is not None:
        # Read back what is about to be written, rather than trusting that the
        # step which removed it covered every place it could appear.
        verify_policy(payload, policy)

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
    if policy is None:
        click.echo("Full build: nothing withheld. Do not publish this.")
    elif policy:
        click.echo(
            f"Withheld {len(policy.component_ids)} components "
            f"({', '.join(policy.component_ids)}) and "
            f"{len(policy.field_names)} fields "
            f"({', '.join(policy.field_names)}), per config/privacy.yaml."
        )
    click.echo(
        "Version sources: "
        + ", ".join(f"{source} {count}" for source, count in sorted(tally.items()))
    )
    stranded = isolated(components)
    if stranded:
        click.echo(f"No recorded dependencies for: {', '.join(stranded)}")
    click.echo(f"Wrote {json_path}")
    click.echo(f"Wrote {html_path}")


@click.command()
@click.option("--components", "components_dir", type=click.Path(path_type=Path),
              default=DEFAULT_COMPONENTS, show_default=True,
              help="Directory of component YAML files.")
@click.option("--sync-dir", type=click.Path(path_type=Path),
              default=DEFAULT_SYNC_DIR, show_default=True,
              help="Cache written by sync-components. Without one, only the "
                   "files a checkout alone determines are written.")
@click.option("--output-dir", type=click.Path(path_type=Path),
              default=DEFAULT_CONTENT_DIR, show_default=True,
              help="The content tree to write.")
@click.option("--diagram/--no-diagram", default=False, show_default=True,
              help="Also render diagram.svg from the generated components.csv. "
                   "Needs Graphviz; runs generate-diagram in a subprocess.")
def content_main(components_dir, sync_dir, output_dir, diagram):
    """Write the repository's Markdown and CSV view of the components.

    Nothing is withheld: this tree is read by people who already have the
    repository. The sheet-format components.csv and the static half of every
    page come from the component files alone; dashboard.md, deployments.csv
    and the live half of each page come from the last sync, and are skipped
    with a note when there is none.
    """
    components = _load(components_dir)
    private = read_private(components_dir)
    if (sync_dir / "manifest.json").exists():
        payload = build_payload(components, _synced(sync_dir), None)
    else:
        payload = None
        click.echo(
            f"No manifest at {sync_dir / 'manifest.json'}: writing components.csv "
            f"and the static half of each page only. Run sync-components for "
            f"the rest."
        )
    written = write_content(components, payload, private, output_dir)
    if diagram:
        written.extend(_render_diagram(output_dir))
    click.echo(
        f"{len(components)} components, {len(private)} with a private block, "
        f"{len(written)} files under {output_dir}."
    )
    for path in written:
        click.echo(f"Wrote {path}")


def _render_diagram(output_dir: Path) -> list[Path]:
    """diagram.svg and diagram.dot from the CSV just written.

    A subprocess rather than an import: cli.py is an entry point, and nothing
    may import one. The layer column is the sheet's, which `sheet_row` names
    `Tier` for exactly this call.
    """
    DIAGRAM_SCRATCH_DIR.mkdir(parents=True, exist_ok=True)
    command = [
        "generate-diagram",
        "--input", str(output_dir / "components.csv"),
        "--output-dir", str(DIAGRAM_SCRATCH_DIR),
        "--format", "svg",
        "--layer-column", "Tier",
    ]
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise click.ClickException(
            f"generate-diagram failed:\n{result.stderr.strip() or result.stdout.strip()}"
        )
    written = []
    for name in ("diagram.svg", "diagram.dot"):
        source = DIAGRAM_SCRATCH_DIR / name
        if not source.exists():
            raise click.ClickException(f"generate-diagram wrote no {name}.")
        shutil.copyfile(source, output_dir / name)
        written.append(output_dir / name)
    return written
