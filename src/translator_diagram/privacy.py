"""What a published build of the dashboard withholds.

The page reports live facts about running infrastructure, and a few of those
are things we would rather not hand to a search engine: the tracing console,
the internal test rig, the container image tags that turn the version grid into
a CVE-matching exercise. This module drops them.

**This is reach, not secrecy, and the difference matters.** Everything here is
read from public services, this repository is public, and `config/privacy.yaml`
names what it withholds and why — so nothing in this file hides anything from
someone who looks. What it does is keep those facts off an indexed page that
arrives without being asked for. If something genuinely secret ever reaches the
page, the fix is upstream, at the API that served it; redacting it here would
only make the leak harder to notice.

Two consequences follow, and both are deliberate:

- **Redaction is the default.** `build-dashboard` withholds unless asked not
  to, so a forgotten flag costs information rather than leaking it, and the
  published workflow passes no flag at all and cannot regress.
- **A policy that no longer matches the data is an error, not a no-op.** A
  component id that names nothing, or a field that no row has, means someone
  renamed the thing being withheld — and silently withholding nothing is the
  one failure this module must not have.
"""

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import click
import yaml

CONFIG_POLICY_PATH = Path("config/privacy.yaml")
"""Where the policy lives, relative to the working directory or a parent.

Deliberately no packaged fallback, unlike `owner-colors.csv`. That copy exists
so an install with no checkout still renders; here, a missing file must stop a
publishing build rather than quietly produce a full-fidelity one.
"""


SECTIONS = {"components", "fields", "environment_fields"}
"""Every top-level key the policy file may have. Anything else is a typo."""


FIELD_VERSION_SOURCES = {"helm_version": "helm"}
"""Row fields that are also the origin of a value shown in the table.

Emptying `helm_version` on the row is not enough on its own: a cell whose
version was *read from* the chart still carries that number, with a badge
saying where it came from, so withholding the field alone would leave the thing
it was withholding on display one column over. Any cell whose `version_source`
names a withheld origin therefore loses its version too.

Both together, never one: a version with no provenance is precisely what this
dashboard exists not to show.

`helm_images` used to be here as well, and that was wrong. No cell ever reads
its version from the image list — the chart's `appVersion` is what the `helm`
tier supplies, and that is `helm_version` — so this entry meant withholding the
images would blank a version they had nothing to do with. It cost nothing on
today's data only because the three helm-sourced cells all sit on jaeger's row,
which is withheld whole; the first time a published component takes its version
from a chart, it would have blanked that cell for no reason anyone could find
in the policy. Only a field a cell actually read its value from belongs here.
"""


SCRUBBED = "…"
"""What a withheld id becomes where it is mentioned in somebody else's prose."""


@dataclass(frozen=True)
class Redaction:
    """One thing withheld, and why. The reason is documentation, not logic."""

    name: str
    reason: str = ""


@dataclass(frozen=True)
class Policy:
    """The parsed `config/privacy.yaml`."""

    components: tuple[Redaction, ...] = ()
    fields: tuple[Redaction, ...] = ()
    environment_fields: tuple[Redaction, ...] = ()

    @property
    def component_ids(self) -> tuple[str, ...]:
        return tuple(item.name for item in self.components)

    @property
    def field_names(self) -> tuple[str, ...]:
        return tuple(item.name for item in self.fields)

    @property
    def environment_field_names(self) -> tuple[str, ...]:
        return tuple(item.name for item in self.environment_fields)

    def __bool__(self) -> bool:
        return bool(self.components or self.fields or self.environment_fields)


@dataclass(frozen=True)
class Report:
    """What `apply` actually removed."""

    components: tuple[str, ...] = ()
    fields: tuple[str, ...] = ()
    environment_fields: tuple[str, ...] = ()
    mentions: int = 0
    """How many times a withheld id was found in free text and replaced."""

    def __bool__(self) -> bool:
        return bool(
            self.components
            or self.fields
            or self.environment_fields
            or self.mentions
        )

    def summary(self) -> str:
        """One line for the build log."""
        parts = []
        if self.components:
            parts.append(
                f"{len(self.components)} components "
                f"({', '.join(self.components)})"
            )
        if self.fields:
            parts.append(f"{len(self.fields)} fields ({', '.join(self.fields)})")
        if self.environment_fields:
            parts.append(
                f"{len(self.environment_fields)} environment fields "
                f"({', '.join(self.environment_fields)})"
            )
        if self.mentions:
            parts.append(
                f"{self.mentions} mention{'' if self.mentions == 1 else 's'} "
                f"in free text"
            )
        return "Withheld " + ", and ".join(parts) + "."

    def for_payload(self) -> dict[str, Any]:
        """The block the page reads, so it can say something was withheld.

        Counts for components, names for fields: a missing column is visible
        anyway, so naming it is honest, while listing the withheld components
        on the page would put back what was taken out. Not that either is
        secret — see the module docstring — but the page should not advertise
        what it declined to show.
        """
        return {
            "components": len(self.components),
            "fields": list(self.fields),
            "environment_fields": list(self.environment_fields),
            # A count, for the same reason as components: the page can say "3
            # mentions withheld" without the sentence naming what it withheld.
            "mentions": self.mentions,
        }


def load_policy(path: Path | None = None) -> Policy:
    """Read the policy, or fail saying which file was missing.

    With no path, `config/privacy.yaml` in the working directory or any
    directory above it — the same walk `load_owner_colors` does, so running
    from a subdirectory of the checkout behaves the same way.
    """
    found = path if path is not None else _find_policy()
    if found is None:
        raise click.ClickException(
            f"No privacy policy at {CONFIG_POLICY_PATH}. A published build "
            f"must know what to withhold; pass --include-private to build the "
            f"full page for local use."
        )
    if not found.exists():
        raise click.ClickException(f"Privacy policy not found: {found}")
    try:
        loaded = yaml.safe_load(found.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise click.ClickException(f"{found} is not valid YAML: {exc}") from exc
    if loaded is None:
        loaded = {}
    if not isinstance(loaded, dict):
        raise click.ClickException(f"{found} must contain a mapping.")
    # A mistyped section is the one way a policy can withhold nothing without
    # anything downstream noticing: `component:` for `components:` parses, and
    # every later check passes because there is nothing left to check. The
    # per-entry checks in `apply` cannot see it — there are no entries.
    unknown = sorted(set(loaded) - SECTIONS)
    if unknown:
        raise click.ClickException(
            f"{found}: unknown section{'s' if len(unknown) > 1 else ''} "
            f"{', '.join(repr(name) for name in unknown)}. Expected "
            f"{', '.join(sorted(SECTIONS))}. A mistyped section withholds "
            f"nothing at all."
        )
    return Policy(
        components=_redactions(loaded, "components", found, key="id"),
        fields=_redactions(loaded, "fields", found),
        environment_fields=_redactions(loaded, "environment_fields", found),
    )


def _find_policy() -> Path | None:
    cwd = Path.cwd()
    for directory in (cwd, *cwd.parents):
        candidate = directory / CONFIG_POLICY_PATH
        if candidate.exists():
            return candidate
    return None


def _redactions(
    loaded: dict[str, Any], section: str, path: Path, key: str = "name"
) -> tuple[Redaction, ...]:
    """Parse one list of entries, each `{<key>: ..., reason: ...}`."""
    entries = loaded.get(section) or []
    if not isinstance(entries, list):
        raise click.ClickException(f"{path}: `{section}` must be a list.")
    out = []
    for entry in entries:
        if not isinstance(entry, dict) or not entry.get(key):
            raise click.ClickException(
                f"{path}: every `{section}` entry needs a `{key}`."
            )
        out.append(Redaction(str(entry[key]), str(entry.get("reason") or "")))
    return tuple(out)


def apply(
    rows: list[dict[str, Any]], policy: Policy
) -> tuple[list[dict[str, Any]], Report]:
    """Withhold what the policy names, and say what was withheld.

    Rows are dropped; fields are emptied in place rather than deleted, because
    `overview.json` is a contract a consumer may already read — a key that
    disappears breaks it, where a null one reads as "not available", which is
    exactly what it is.

    A kept row can still *point at* a withheld one. Nine component files record
    `calls: [jaeger]`, so `connections` is pruned here as well: an id the policy
    withholds is removed from every list under it, planned references included.

    And a kept row can still *mention* one. Notes, a registry description, a
    release title — third-party prose we did not write and cannot edit at the
    source. A withheld id appearing there as a word is not a leak worth
    stopping a nightly publish over, so it is replaced with an ellipsis and
    counted, and the count reaches the page. `verify` stays exactly as strict:
    it reads the finished payload back and refuses anything that got past this.

    What this does *not* touch is `edges`, `stages`, `externals`,
    `catalog_edges` and `smartapi_suggestions`. They are built in
    `build_payload` after this runs, out of the rows it returns, so they cannot
    carry an id that is not in a kept row. A second pass over them here would be
    dead code that looks load-bearing. `unclaimed_charts` needs no pass either,
    for the opposite reason: it is matched against every component, so a chart a
    withheld component claims is never listed, and an entry names a chart and a
    description rather than a component.
    """
    _check_known(rows, policy)
    withheld_ids = set(policy.component_ids)
    folded = {name.lower() for name in withheld_ids}
    patterns = tuple(_word(name) for name in withheld_ids)
    withheld_sources = {
        FIELD_VERSION_SOURCES[name]
        for name in policy.field_names
        if name in FIELD_VERSION_SOURCES
    }
    kept = [row for row in rows if row.get("id") not in withheld_ids]
    mentions = 0
    for row in kept:
        for name in policy.field_names:
            row[name] = _emptied(row.get(name))
        _prune_ids(row, folded)
        mentions += _scrub_row(row, patterns)
        for cell in row.get("environments", {}).values():
            for name in policy.environment_field_names:
                if name in cell:
                    cell[name] = _emptied(cell.get(name))
            _drop_withheld_versions(cell, withheld_sources)
    report = Report(
        components=tuple(
            row["id"] for row in rows if row.get("id") in withheld_ids
        ),
        fields=policy.field_names,
        environment_fields=policy.environment_field_names,
        mentions=mentions,
    )
    return kept, report


def _prune_ids(row: dict[str, Any], withheld: set[str]) -> None:
    """Drop withheld components from a kept row's recorded connections.

    The tilde is a marker on the reference and not part of the id, so
    `~jaeger` is the same component as `jaeger` and goes for the same reason —
    a planned edge to a withheld component names it just as plainly as an
    implemented one does. Matching is case-insensitive because that is how
    references resolve everywhere else here.

    Every list under `connections` is walked rather than the four keys being
    named, so a fifth edge kind added later is pruned without anyone
    remembering to come back to this function.
    """
    connections = row.get("connections")
    if not isinstance(connections, dict):
        return
    for key, refs in connections.items():
        if not isinstance(refs, list):
            continue
        connections[key] = [
            ref
            for ref in refs
            if not (isinstance(ref, str) and ref.lstrip("~").lower() in withheld)
        ]


def _word(name: str) -> re.Pattern[str]:
    """One withheld id as a whole-word pattern, bounded by non-alphanumerics.

    The same boundary `verify` uses, and for the same reason: as a substring
    this would eat the `ars` inside `parsers`. The two must agree, or `apply`
    scrubs what `verify` does not look for, or misses what it does.
    """
    return re.compile(
        rf"(?<![0-9A-Za-z]){re.escape(name)}(?![0-9A-Za-z])", re.IGNORECASE
    )


def _scrubbed(value: Any, patterns: tuple[re.Pattern[str], ...]) -> tuple[Any, int]:
    """One string with every withheld id replaced, and how many were found."""
    if not isinstance(value, str) or not value:
        return value, 0
    found = 0
    for pattern in patterns:
        value, hits = pattern.subn(SCRUBBED, value)
        found += hits
    return value, found


def _scrub_row(row: dict[str, Any], patterns: tuple[re.Pattern[str], ...]) -> int:
    """Replace withheld ids in the free text a kept row carries.

    Every field here is prose from somewhere else: a note somebody wrote about
    this component, the description and tags in its registry entry, the titles
    and excerpts of its releases. We cannot ask GitHub to reword a release, so
    the choice is between scrubbing the word and failing every publish on the
    day one of them says "jaeger". Structured fields are not in this list —
    those are pruned, not rewritten, because an id in a list of ids is a
    reference and half of one is worse than none.
    """
    if not patterns:
        return 0
    found = 0
    for key in ("notes",):
        if key in row:
            row[key], hits = _scrubbed(row.get(key), patterns)
            found += hits
    record = row.get("smartapi_record")
    if isinstance(record, dict):
        for key in ("description_text", "title"):
            if key in record:
                record[key], hits = _scrubbed(record.get(key), patterns)
                found += hits
        tags = record.get("tags")
        if isinstance(tags, list):
            cleaned = []
            for tag in tags:
                tag, hits = _scrubbed(tag, patterns)
                found += hits
                cleaned.append(tag)
            record["tags"] = cleaned
    for entry in row.get("releases_detail") or []:
        if not isinstance(entry, dict):
            continue
        for key in ("name", "body_excerpt"):
            if key in entry:
                entry[key], hits = _scrubbed(entry.get(key), patterns)
                found += hits
    return found


def verify(payload: dict[str, Any], policy: Policy) -> None:
    """Read the finished payload back and confirm the policy actually held.

    `apply` withholds; this checks. They are separate on purpose: the thing
    being guarded against is a future change that adds a field carrying a
    withheld component's id — a "referenced by" list, a per-stage roster, a
    debug block — somewhere `apply` never looks. Serialising the whole payload
    and searching it is the only check that does not have to be kept in step
    with the payload's shape.

    Called on every published build rather than only in CI, so the guarantee
    travels with the command instead of with the workflow that happens to run
    it.

    The search is for the id as a whole word, not as a substring. A plain
    substring test passes today only because `jaeger` and `test-harness`
    happen to occur nowhere else; withholding a short id — `ars`, `ui` — would
    abort every published build over a `ui` inside some unrelated word, and
    the message would tell the operator to go and find a leak that is not
    there. A false alarm that cannot be cleared is worse than no alarm,
    because the way to clear it is to stop running the check.
    """
    blob = json.dumps(payload)
    leaked = sorted(name for name in policy.component_ids if _mentions(blob, name))
    if leaked:
        raise click.ClickException(
            f"Withheld components still appear in the payload: "
            f"{', '.join(leaked)}. Something references them by id — a note, "
            f"a URL, or a field added since. Find it and remove the reference; "
            f"do not relax the policy."
        )
    for row in payload.get("rows", []):
        for name in policy.field_names:
            if row.get(name):
                raise click.ClickException(
                    f"Withheld field `{name}` is still set on row "
                    f"{row.get('id')!r}."
                )
        for env, cell in row.get("environments", {}).items():
            for name in policy.environment_field_names:
                if cell.get(name):
                    raise click.ClickException(
                        f"Withheld environment field `{name}` is still set on "
                        f"{row.get('id')!r} / {env}."
                    )


def _mentions(blob: str, name: str) -> bool:
    """Whether the serialised payload names one component.

    A word here is bounded by anything that is not a letter or a digit, so an
    id is found in a URL, a path segment, a tag or a sentence — every shape a
    stray reference actually takes — but not inside a longer word. The id may
    contain hyphens of its own, which is why the boundary is written out
    rather than left to `\b`.

    One definition, shared with the scrubber in `apply`: if the two spelled the
    boundary differently, one of them would be looking for something the other
    does not remove.
    """
    return _word(name).search(blob) is not None


def _drop_withheld_versions(cell: dict[str, Any], sources: set[str]) -> None:
    """Empty a cell's version when it was read from a withheld origin.

    Value and provenance go together in both directions: the pairs are
    (`version`, `version_source`) and (`trapi`, `trapi_source`), and each pair
    is cleared whole.
    """
    if not sources:
        return
    for value_key, source_key in (("version", "version_source"), ("trapi", "trapi_source")):
        if cell.get(source_key) in sources:
            cell[value_key] = None
            cell[source_key] = None


def _emptied(value: Any) -> Any:
    """The empty value of the same shape, so consumers keep their types."""
    if isinstance(value, list):
        return []
    if isinstance(value, dict):
        return {}
    return None


def _check_known(rows: list[dict[str, Any]], policy: Policy) -> None:
    """Fail on a policy entry that matches nothing.

    The whole point: if `jaeger` is renamed and the policy is not, the build
    should stop rather than publish the row the policy meant to withhold.
    """
    known_ids = {row.get("id") for row in rows}
    unknown = [name for name in policy.component_ids if name not in known_ids]
    if unknown:
        raise click.ClickException(
            f"{CONFIG_POLICY_PATH} withholds components that do not exist: "
            f"{', '.join(sorted(unknown))}. Was one renamed? Withholding "
            f"nothing is the failure this check exists to prevent."
        )
    row_keys = set().union(*(row.keys() for row in rows)) if rows else set()
    unknown = [name for name in policy.field_names if name not in row_keys]
    if unknown:
        raise click.ClickException(
            f"{CONFIG_POLICY_PATH} withholds fields no row has: "
            f"{', '.join(sorted(unknown))}."
        )
    cell_keys: set[str] = set()
    for row in rows:
        for cell in row.get("environments", {}).values():
            cell_keys |= set(cell.keys())
    unknown = [
        name for name in policy.environment_field_names if name not in cell_keys
    ]
    if unknown:
        raise click.ClickException(
            f"{CONFIG_POLICY_PATH} withholds environment fields no cell has: "
            f"{', '.join(sorted(unknown))}."
        )
