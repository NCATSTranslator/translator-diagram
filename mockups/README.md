# Mockups

Three directions for the Overview table, each a full render of the real
`data/dashboard/overview.json` over one shared cell model (`common.js`). They
exist to be compared and then deleted: the chosen one is ported into
`src/translator_diagram/web/`, and `common.js` is the part that ports verbatim.

```bash
uv run build-dashboard                      # writes data/dashboard/overview.json
python3 -m http.server 8765                 # from the repo root
open http://localhost:8765/mockups/ledger.html
```

`?theme=dark` forces the dark theme, `?expand=<id>` opens a different row
(default `arax`). The controls are drawn, not wired.

- `ledger.html`: the current tokens on a plain ruled table, 14px, no pill rows.
- `matrix.html`: the same, with environment cells tinted by state (same as
  the row, differs, up without a version, down, not deployed) and a legend.
- `github.html`: GitHub's palette, radii and Labels; no purple.
