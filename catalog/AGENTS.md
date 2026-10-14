# catalog/

Everything a curator edits: the component files, `unknown.yaml`, the stage
order, the owner colours and their schemas. The repo-wide working agreements
are in [../AGENTS.md](../AGENTS.md). **[README.md](README.md) is the guide to
this directory**: what each file holds, how to add a component, the rules the
tests enforce, the conventions, and what each `unknown.yaml` status means.
Read it rather than expecting the rules here. The case for the format is in
[../docs/component-metadata.md](../docs/component-metadata.md).

This directory is written for people who know the platform, not the code, so
keep it that way. Curator-facing prose belongs in `README.md`, not in a module
docstring, and paths written inside `catalog/` are relative to it
(`components/<id>.yaml`, `owner-colors.csv`).

`components/` holds nothing but component files, so `load_components` and
`tests/test_component_files.py` can glob `*.yaml` without exceptions. Do not
put anything else in it.

**The dashboard reads the component files; the diagram does not.** `sync`,
`flow` and `dashboard` are built on them, while `loading.py` still parses the
sheet CSV. The two stacks meet only at `colors`, and merging them is
issue #19. The files are validated by `tests/test_component_files.py`, parsed
by `components.py` (tested by `tests/test_components.py`), and
`flow-steps.yaml` is checked by `tests/test_flow_steps.py`.

Do not delete an `unknown.yaml` entry to make a test pass: an entry is removed
only when its identifier moves into a component file.

`pyyaml` is a **runtime** dependency because the dashboard reads
`components/*.yaml` at run time. `jsonschema` stays **dev-only**: nothing but
the tests validates these files, and a schema library in the runtime
dependency set would suggest otherwise.
