# components/

One YAML file per Translator component. The repo-wide working agreements are in
[../AGENTS.md](../AGENTS.md); the case for the format is in
[../docs/component-metadata.md](../docs/component-metadata.md).

`components/<id>.yaml` holds one file per component, validated against
`schema/component.schema.json` by `tests/test_component_files.py` and parsed
by `components.py` (whose own tests are `tests/test_components.py`).

**The dashboard reads them; the diagram does not.** `sync`, `flow` and
`dashboard` are built on them, while `loading.py` still parses the sheet CSV.
The two stacks meet only at `colors`, and merging them is issue #19. The
rationale for the format is in `docs/component-metadata.md`, the upstream
survey in `docs/metadata-sources.md`.

Rules the tests enforce, so a change that breaks one fails CI rather than
sitting there wrong: the filename stem equals `id`; ids are unique
case-insensitively; every id in `connections.gets_results_from`/`calls` has a
file (which is why `docmetadata-api` has one — `ui` calls it); every `owner`
appears in `config/owner-colors.csv`; `endpoints` values are relative paths,
never URLs; and no file writes a `diagram:` flag at its default, which is what
keeps that block absent rather than 26 copies of `ubiquitous: false`.

`unknown.yaml` collects identifiers observed in the platform that no
component file claims — today, the OpenTelemetry service names that could not
be attributed. Do not delete an entry to make a test pass: an entry is removed
only when its identifier moves into a component file. The tests enforce that
no identifier is claimed twice, and that a `not-recorded` entry whose
component now has a file fails until it is promoted.

Quote ISO dates in that file. YAML parses a bare `2026-08-31` into a
`datetime.date`, which is not a JSON Schema string, and the failure message
points at the schema rather than the quoting.

`pyyaml` is a **runtime** dependency because the dashboard reads
`components/*.yaml` at run time. `jsonschema` stays **dev-only**: nothing but
the tests validates those files, and a schema library in the runtime
dependency set would suggest otherwise.
