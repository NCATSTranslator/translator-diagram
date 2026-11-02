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
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import click
import yaml

from .files import find_upward

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


FIELD_RECORDED_KEYS = {
    "type": "component_type",
    "chart_names": "helm_chart",
    "helm_charts": "helm_chart",
    "otel_presence": "otel_services",
    "repository": "repositories",
    "docs": "documentation",
}
"""Row fields the component file spells differently, by the file's own key.

A row field and a file key with the same name need no entry: `_recorded_slots`
finds those wherever the file keeps them. Each entry here is a row field whose
value is read from a key of another name, so withholding the field and leaving
the key would publish the same fact in the Recorded section.
`tests/test_privacy.py` builds a row from a file with every key filled, and
fails if a row field carrying one of those values leaves it behind.

The table also works the other way round: row fields that read one file key say
the same thing, so `_row_fields_saying` withholds them together. Withholding
`otel_services` and leaving `otel_presence` would still publish every name, and
the Component view would show them as the Telemetry fact.
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
    directory above it (`find_upward`, the same walk `load_owner_colors` does),
    so running from a subdirectory of the checkout behaves the same way.
    """
    found = path if path is not None else find_upward(CONFIG_POLICY_PATH)
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
    dead code that looks load-bearing. `unclaimed_charts` is not a row, so
    `build_payload` scrubs its descriptions itself; a chart a withheld
    component claims is never listed, since it is matched against every
    component.

    A finding is a sentence the build wrote, and several quote a value ("loads
    Biolink {loaded}", "telemetry name {service}"), so one that quotes anything
    withheld from its row goes too. Matching the text rather than naming the
    findings means a finding added later is covered, and a false match costs a
    finding rather than publishing a value.

    `recorded`, the component file as written, holds many of the same facts
    under the file's own keys, so everything withheld from the row is withheld
    there too. What held a value and no longer does is listed in the row's
    `recorded_withheld`, by its dotted path in the file. Without that list the
    Component view cannot tell a list the policy emptied from a list the file
    wrote as empty, and would say "checked: none" about an edge the file does
    record.
    """
    _check_known(rows, policy)
    withheld_ids = set(policy.component_ids)
    folded = {name.lower() for name in withheld_ids}
    patterns = patterns_for(policy)
    withheld_sources = {
        FIELD_VERSION_SOURCES[name]
        for name in policy.field_names
        if name in FIELD_VERSION_SOURCES
    }
    kept = [row for row in rows if row.get("id") not in withheld_ids]
    mentions = 0
    for row in kept:
        recorded = row.get("recorded")
        withheld_paths = _prune_ids(row, folded)
        quoted: set[str] = set()
        for name in policy.field_names:
            for field in _row_fields_saying(name):
                if field == name or field in row:
                    quoted |= _texts(row.get(field))
                    row[field] = _emptied(row.get(field))
            for mapping, key, path in _recorded_slots(recorded, name):
                withheld_paths.extend(_withhold(mapping, key, path))
        mentions += scrub(row, ROW_FREE_TEXT, patterns)
        for cell in row.get("environments", {}).values():
            for name in policy.environment_field_names:
                for key in _cell_keys_for(cell, name):
                    quoted |= _texts(cell.get(key))
                    cell[key] = _emptied(cell.get(key))
            _drop_withheld_versions(cell, withheld_sources)
        _drop_findings_quoting(row, quoted)
        for name in policy.environment_field_names:
            for mapping, key, path in _recorded_env_slots(recorded, name):
                withheld_paths.extend(_withhold(mapping, key, path))
        if isinstance(recorded, dict):
            row["recorded_withheld"] = sorted(set(withheld_paths))
    report = Report(
        components=tuple(
            row["id"] for row in rows if row.get("id") in withheld_ids
        ),
        fields=policy.field_names,
        environment_fields=policy.environment_field_names,
        mentions=mentions,
    )
    return kept, report


def _row_fields_saying(name: str) -> set[str]:
    """Every row field that reads the same file key as row field `name`."""
    key = FIELD_RECORDED_KEYS.get(name, name)
    siblings = {field for field, read in FIELD_RECORDED_KEYS.items() if read == key}
    return {name, key} | siblings


def _cell_keys_for(cell: dict[str, Any], name: str) -> list[str]:
    """Cell field `name` and what is spelled after it: `biolink` and its
    `biolink_source`, `biolink_url` and `biolink_declared`. Every such group in
    a cell is spelled this way, so the rule is the prefix rather than a list a
    new data axis would be missing from."""
    return [key for key in cell if key == name or key.startswith(f"{name}_")]


def _texts(value: Any) -> set[str]:
    """Every non-empty string in `value`, however deep."""
    if isinstance(value, str):
        return {value} if value else set()
    if isinstance(value, dict):
        value = list(value.values())
    if isinstance(value, list):
        return {text for child in value for text in _texts(child)}
    return set()


def _drop_findings_quoting(row: dict[str, Any], quoted: set[str]) -> None:
    """Remove a row's and its cells' findings that quote a withheld value.

    The key goes when the list is empty: a list with nothing in it is not a
    shape findings otherwise take, on a row or in a cell.
    """
    if not quoted:
        return
    for holder in (row, *row.get("environments", {}).values()):
        if "findings" not in holder:
            continue
        kept = [
            finding
            for finding in holder["findings"]
            if not any(text in str(finding.get("text", "")) for text in quoted)
        ]
        if kept:
            holder["findings"] = kept
        else:
            del holder["findings"]


def _recorded_slots(
    recorded: Any, name: str
) -> Iterator[tuple[dict[str, Any], str, str]]:
    """Where the component file holds what row field `name` holds.

    Yields (mapping, key, dotted path). A file key is at the top level or one
    block down (`identifiers.infores`, `connections.externals`), and it is
    looked for in both rather than each field being given its path, so a key
    added to a block later is withheld without anyone coming back to this.
    """
    if not isinstance(recorded, dict):
        return
    key = FIELD_RECORDED_KEYS.get(name, name)
    if key in recorded:
        yield recorded, key, key
    for block_name, block in recorded.items():
        if isinstance(block, dict) and key in block:
            yield block, key, f"{block_name}.{key}"


def _recorded_env_slots(
    recorded: Any, name: str
) -> Iterator[tuple[dict[str, Any], str, str]]:
    """Where the component file holds per-environment field `name`."""
    envs = recorded.get("environments") if isinstance(recorded, dict) else None
    if not isinstance(envs, dict):
        return
    for env, spec in envs.items():
        if isinstance(spec, dict) and name in spec:
            yield spec, name, f"environments.{env}.{name}"


def _holds_value(value: Any) -> bool:
    """Whether the file claims something here, as opposed to null or empty."""
    return value is not None and value != [] and value != {}


def _withhold(mapping: dict[str, Any], key: str, path: str) -> list[str]:
    """Empty one value of the file, and return the paths that held something.

    A block is emptied key by key rather than replaced with `{}`, and a value
    the file wrote as null or empty is not listed. Both keep the Recorded
    section truthful about the rest: an absent key stays "not recorded", a null
    one stays "checked: none", and only what the file did say reads "withheld".
    """
    value = mapping[key]
    if isinstance(value, dict):
        held = []
        for sub in value:
            held.extend(_withhold(value, sub, f"{path}.{sub}"))
        return held
    held_value = _holds_value(value)
    mapping[key] = _emptied(value)
    return [path] if held_value else []


def _leaves(value: Any) -> Iterator[Any]:
    """Every non-mapping value under `value`, for `verify`."""
    if isinstance(value, dict):
        for child in value.values():
            yield from _leaves(child)
    else:
        yield value


def _prune_ids(row: dict[str, Any], withheld: set[str]) -> list[str]:
    """Drop withheld components from a kept row's recorded connections.

    Returns the file's paths this left empty, for `recorded_withheld`.

    A row's `connections` come from `ComponentFile.connection_ids`, which has
    already stripped the planned-edge tilde and sorted each reference into
    its list, so a withheld id is matched as written. The tilde is stripped
    again here all the same: it costs nothing, and it keeps the rule true for
    a row built any other way. Matching is case-insensitive because that is
    how references resolve everywhere else here.

    Every list under `connections` is walked rather than the four keys being
    named, so a fifth edge kind added later is pruned without anyone
    remembering to come back to this function. The file's own `connections`
    block under `recorded` is walked the same way: it is the same claim in the
    file's vocabulary, tildes and all, and the Component view shows it.
    """
    recorded = row.get("recorded")
    file_block = recorded.get("connections") if isinstance(recorded, dict) else None
    emptied = []
    for connections in (row.get("connections"), file_block):
        if not isinstance(connections, dict):
            continue
        for key, refs in connections.items():
            if not isinstance(refs, list):
                continue
            kept = [
                ref
                for ref in refs
                if not (isinstance(ref, str) and ref.lstrip("~").lower() in withheld)
            ]
            connections[key] = kept
            if connections is file_block and refs and not kept:
                emptied.append(f"connections.{key}")
    return emptied


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


# Every free-text field a kept row carries, as (path to the mappings, keys).
# A list along a path is walked item by item, and `*` is every value of a
# mapping. URLs are deliberately absent: rewriting one breaks the link, and a
# URL naming a withheld component is a reference for `verify` to stop on.
ROW_FREE_TEXT: tuple[tuple[tuple[str, ...], tuple[str, ...]], ...] = (
    ((), ("notes", "summary", "description")),
    (("third_party",), ("software",)),
    (("smartapi_record",), ("title", "description_text", "tags")),
    (("smartapi_record", "servers"), ("description",)),
    (("smartapi_record", "contact"), ("name",)),
    (("smartapi_candidates",), ("title",)),
    (("releases",), ("name",)),
    (("releases_detail",), ("name", "body_excerpt")),
    (("repository_meta",), ("description", "topics")),
    (("helm_charts",), ("description",)),
    (("helm_charts", "last_changed"), ("subject",)),
    (("catalog",), ("name", "description")),
    (("environments", "*"), ("status_message", "openapi_title")),
    # Written by the build, but quoting what other people wrote: a repository
    # name, a reported version.
    (("findings",), ("text",)),
    (("environments", "*", "findings"), ("text",)),
    # The component file as written. Its prose is ours, but it is prose: a
    # note saying "calls jaeger on boot" is a mention, not a reference.
    (("recorded",), ("notes", "summary", "description")),
    (("recorded", "third_party"), ("software",)),
    (("recorded", "repositories"), ("note",)),
    (("recorded", "documentation"), ("note",)),
    (("recorded", "examples"), ("description",)),
)

# `unclaimed_charts` names no component, but its descriptions are still prose.
UNCLAIMED_CHART_FREE_TEXT = (((), ("description",)),)


def _mappings(node: Any, path: tuple[str, ...]) -> Iterator[dict[str, Any]]:
    """The mappings at the end of `path`, through any lists along the way."""
    if isinstance(node, list):
        for item in node:
            yield from _mappings(item, path)
    elif isinstance(node, dict):
        if not path:
            yield node
        elif path[0] == "*":
            for child in node.values():
                yield from _mappings(child, path[1:])
        else:
            yield from _mappings(node.get(path[0]), path[1:])


def scrub(
    node: Any,
    fields: tuple[tuple[tuple[str, ...], tuple[str, ...]], ...],
    patterns: tuple[re.Pattern[str], ...],
) -> int:
    """Replace withheld ids in the free text at `fields`, and count them.

    Every field named is prose from somewhere else: a note somebody wrote, a
    registry description, a release title, a repository topic. We cannot ask
    GitHub to reword a release, so the choice is between scrubbing the word and
    failing every publish on the day one of them says "jaeger". Structured
    fields are not named — those are pruned, not rewritten, because an id in a
    list of ids is a reference and half of one is worse than none.
    """
    if not patterns:
        return 0
    found = 0
    for path, keys in fields:
        for mapping in _mappings(node, path):
            for key in keys:
                value = mapping.get(key)
                if isinstance(value, list):
                    cleaned = []
                    for item in value:
                        item, hits = _scrubbed(item, patterns)
                        found += hits
                        cleaned.append(item)
                    mapping[key] = cleaned
                elif key in mapping:
                    mapping[key], hits = _scrubbed(value, patterns)
                    found += hits
    return found


def patterns_for(policy: Policy) -> tuple[re.Pattern[str], ...]:
    return tuple(_word(name) for name in policy.component_ids)


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
            for field in _row_fields_saying(name):
                if row.get(field):
                    raise click.ClickException(
                        f"Withheld field `{field}` is still set on row "
                        f"{row.get('id')!r}."
                    )
            for mapping, key, path in _recorded_slots(row.get("recorded"), name):
                if any(_holds_value(leaf) for leaf in _leaves(mapping[key])):
                    raise click.ClickException(
                        f"Withheld field `{name}` is still set in the component "
                        f"file carried on row {row.get('id')!r}, at `{path}`."
                    )
        for env, cell in row.get("environments", {}).items():
            for name in policy.environment_field_names:
                for key in _cell_keys_for(cell, name):
                    if cell.get(key):
                        raise click.ClickException(
                            f"Withheld environment field `{key}` is still set on "
                            f"{row.get('id')!r} / {env}."
                        )
        for name in policy.environment_field_names:
            for mapping, key, path in _recorded_env_slots(row.get("recorded"), name):
                if _holds_value(mapping[key]):
                    raise click.ClickException(
                        f"Withheld environment field `{name}` is still set in the "
                        f"component file carried on row {row.get('id')!r}, at "
                        f"`{path}`."
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

    Value and provenance go together in both directions, and every pair in a
    cell is spelled the same way — `version`/`version_source`,
    `trapi`/`trapi_source`, and one such pair per data axis in
    `cells.DATA_AXES` — so the rule is the suffix rather than a list of
    names: a list here would miss the next axis, and this module may not
    import `cells` to read theirs.
    """
    if not sources:
        return
    for source_key in [key for key in cell if key.endswith("_source")]:
        if cell.get(source_key) in sources:
            cell[source_key.removesuffix("_source")] = None
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
