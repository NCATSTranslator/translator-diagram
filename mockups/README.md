# Mockups

Three directions for the Overview table, each a full render of the real
`data/dashboard/overview.json` over one shared cell model (`common.js`). They
exist to be compared and then deleted: the chosen one is ported into
`src/translator_diagram/web/`, and `common.js` is the part that ports verbatim.

```bash
uv run build-dashboard                      # writes data/dashboard/overview.json
( printf 'window.PAYLOAD='; cat data/dashboard/overview.json; echo ';' ) > mockups/payload.js
open mockups/ledger.html                    # or matrix.html, github.html
```

`payload.js` is gitignored: it is the build's `overview.json` as a script, so
the pages open straight from the file system (a browser will not `fetch` one
local file from another). Served over HTTP from the repo root they fetch the
JSON themselves and the file is not needed.

`?theme=dark` forces the dark theme, `?expand=<id>` opens a different row
(default `arax`). The controls are drawn, not wired.

- `ledger.html`: the current tokens on a plain ruled table, 14px, no pill rows.
- `matrix.html`: the same, with environment cells tinted by state (same as
  the row, differs, up without a version, down, not deployed) and a legend.
- `github.html`: GitHub's palette, radii and Labels; no purple.
