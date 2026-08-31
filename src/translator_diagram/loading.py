"""Getting the components CSV, and turning its cells into Components."""

import csv
import os
import urllib.error
import urllib.request
from pathlib import Path

import click
from dotenv import find_dotenv, load_dotenv

from .model import Component


# Node URLs come from the sheet and become live <a xlink:href> in the SVG. Only
# ordinary web links are allowed through — see _valid_url.
URL_SCHEMES = ("http://", "https://")


def _parse_bool(value: str) -> bool:
    """Parse a CSV boolean cell — accepts TRUE/yes/y/1 (case-insensitive)."""
    return value.strip().lower() in ("true", "yes", "y", "1")


def parse_id_list(field_value: str) -> tuple[list[str], list[str]]:
    """Split a comma-separated field into (implemented_ids, planned_ids).

    IDs prefixed with '~' are planned-but-not-yet-implemented.
    """
    implemented, planned = [], []
    for part in field_value.split(","):
        part = part.strip()
        if not part:
            continue
        if part.startswith("~"):
            planned.append(part[1:].strip())
        else:
            implemented.append(part)
    return implemented, planned


def parse_externals(field_value: str, where: str = "") -> list[tuple[str, str]]:
    """Parse the Externals column into a list of (direction, name) pairs.

    Values are standard CSV (commas as separators, double-quotes for names
    that contain commas). Each token must start with '<' (external source
    that sends data *into* this component) or '>' (external sink that
    receives data *from* this component). A token with neither prefix has no
    direction to draw, so it is dropped with a warning rather than silently —
    otherwise a typo in the sheet just makes a node disappear.

    Examples
    --------
    ``<External data sources, >User``
    ``"<Upstream, service", >Researcher``
    """
    if not field_value.strip():
        return []
    result = []
    reader = csv.reader([field_value])
    for row in reader:
        for token in row:
            token = token.strip()
            if not token:
                continue
            if token.startswith("<"):
                result.append(("in", token[1:].strip()))
            elif token.startswith(">"):
                result.append(("out", token[1:].strip()))
            else:
                click.echo(
                    f"WARNING: external '{token}' in {where or 'Externals'} has "
                    f"no '<' or '>' prefix; ignoring it",
                    err=True,
                )
    return result


def _valid_url(url: str, comp_id: str) -> str:
    """Return url if it is a plain web link, else "" with a warning.

    Node URLs become live <a xlink:href> wrappers in the SVG, and the planned
    Pages view inlines that SVG — so a 'javascript:' URL pasted into the sheet
    would otherwise become executable on a public page.
    """
    # Schemes are case-insensitive per RFC 3986, and the sheet contains what
    # people pasted, so compare lowercased.
    if not url or url.lower().startswith(URL_SCHEMES):
        return url
    click.echo(
        f"WARNING: '{comp_id}' has URL '{url}', which is not http(s); ignoring it",
        err=True,
    )
    return ""


def load_components(csv_path: Path, layer_column: str = "") -> list[Component]:
    """Parse the CSV into a sorted list of Components.

    A file with no "id" column at all is an error, not an empty result: that
    is what a wrong --sheet-gid looks like.

    Rows with a blank id are skipped: they are spacer or trailing rows from the
    sheet, and keeping them yields an unnamed graphviz node, or a baffling
    "duplicate id: '' and ''" error once there are two of them. A skipped row
    that carries other data warns, since that one is a typo rather than a
    spacer.

    Sorted by lowercase id for deterministic .dot / .json output across CSV
    row reorderings.
    """
    # utf-8-sig strips a UTF-8 BOM if present (Excel-resaved or Windows-edited
    # files), otherwise the first header would read as "﻿id" and KeyError.
    with csv_path.open(newline="", encoding="utf-8-sig") as f:
        # restval="" because DictReader defaults missing trailing fields to
        # None, and every .strip() below would then raise AttributeError. The
        # Sheets export pads its rows, but a hand-edited CSV need not.
        reader = csv.DictReader(f, restval="")
        # Without an "id" column every row is skipped as id-less and the run
        # ends with an empty diagram and exit 0 — which is what a wrong
        # --sheet-gid looks like, and a scheduled job would then publish that
        # blank diagram over the good one.
        if not reader.fieldnames or "id" not in reader.fieldnames:
            found = ", ".join(reader.fieldnames or []) or "no columns at all"
            raise click.ClickException(
                f"{csv_path} has no 'id' column (found: {found}). "
                "If this came from --google-sheet, check --sheet-gid."
            )
        rows: list[Component] = []
        for row in reader:
            comp_id = row.get("id", "").strip()
            if not comp_id:
                # An entirely blank row is a spacer or a trailing row and is
                # skipped quietly. A row carrying data but no id is a
                # data-entry mistake, and would otherwise vanish without trace.
                if any(isinstance(v, str) and v.strip() for v in row.values()):
                    click.echo(
                        f"WARNING: skipping a row with no id "
                        f"(Name: '{row.get('Name', '').strip()}')",
                        err=True,
                    )
                continue
            depends_on, depends_on_planned = parse_id_list(
                row.get("Gets results from", "")
            )
            uses, uses_planned = parse_id_list(row.get("Calls", ""))
            rows.append(Component(
                id=comp_id,
                name=row.get("Name", "").strip(),
                owner=(row.get("Owner") or "None").strip() or "None",
                itrb=row.get("Component in ITRB", "").strip(),
                refactor_status=row.get("Refactor status", "").strip(),
                notes=row.get("Notes", "").strip(),
                url=_valid_url(row.get("URL", "").strip(), comp_id),
                ubiquitous=_parse_bool(row.get("Ubiquitous", "")),
                hide=_parse_bool(row.get("Hide", "")),
                part_of=row.get("Part of", "").strip(),
                hosted_at=row.get("Hosted at", "").strip(),
                layer=row.get(layer_column, "").strip() if layer_column else "",
                externals=parse_externals(row.get("Externals", ""), comp_id),
                depends_on=depends_on,
                depends_on_planned=depends_on_planned,
                uses=uses,
                uses_planned=uses_planned,
            ))
    rows.sort(key=lambda c: c.id.lower())
    return rows


def download_sheet_csv(sheet_gid: int, output_dir: Path) -> Path:
    """Download the components CSV from the configured Google Sheet.

    Returns the path it was written to, inside output_dir.
    """
    # usecwd=True is load-bearing: a bare load_dotenv() resolves via
    # find_dotenv(), which searches from *this module's* file rather than the
    # working directory — so it would quietly read whatever .env happens to sit
    # beside the installed package. This searches the working directory and its
    # parents, which reaches the .env at the root of a checkout.
    cwd_env = find_dotenv(usecwd=True)
    if cwd_env:
        load_dotenv(cwd_env)
    sheet_id = os.environ.get("GOOGLE_SHEET_ID", "").strip()
    if not sheet_id:
        raise click.ClickException(
            "GOOGLE_SHEET_ID is not set. Put it in a .env file in the current "
            "directory or one above it, or set it in the environment; "
            "env.default at the repo root is the template."
        )
    url = (
        f"https://docs.google.com/spreadsheets/d/{sheet_id}"
        f"/export?format=csv&gid={sheet_gid}"
    )
    download_path = output_dir / "components.csv"
    click.echo(f"Downloading CSV from Google Sheet to {download_path} ...")
    # Use urlopen + content-type check rather than urlretrieve: a private
    # or missing sheet redirects to a 200 HTML login page, which would
    # otherwise be silently saved as components.csv.
    try:
        # timeout so a stalled request fails the run rather than hanging a
        # scheduled CI job forever.
        with urllib.request.urlopen(url, timeout=30) as response:
            content_type = response.headers.get("Content-Type", "")
            body = response.read()
    # A stall during read() raises a bare TimeoutError, which is not a
    # URLError; without it here a scheduled job dies with a traceback.
    except (urllib.error.URLError, TimeoutError) as exc:
        raise click.ClickException(
            f"Failed to download Google Sheet (gid {sheet_gid}): {exc}"
        ) from exc
    if "text/csv" not in content_type.lower():
        # The sheet ID is a shareable secret and these messages end up in
        # CI logs, so it stays out of both of them.
        raise click.ClickException(
            f"Google Sheet response was not CSV (Content-Type: "
            f"{content_type or 'unset'}). The sheet may be private, "
            f"GOOGLE_SHEET_ID may be wrong, or gid {sheet_gid} may not exist."
        )
    download_path.write_bytes(body)
    input_path = download_path
