/*
  Shared by every mockup: it loads the real payload and holds the one cell
  model all three render from, so the pages differ in presentation and in
  nothing else. `cell`, `figures` and the small vocabularies are what port
  into web/core.js when a direction is chosen; `load` and `bands` are
  mockup scaffolding (the real page inlines the payload and already groups
  rows by stage in table.js).

  Copied helpers (`esc`, `host`, `href`, `since`, `relativeAge`, `reach`) are
  verbatim from web/core.js so the port is a move, not a rewrite.
*/
window.MOCK = (() => {
  "use strict";

  const ENTITIES = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };
  const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (c) => ENTITIES[c]);

  let ageFormat = null;
  const relative = () => {
    if (!ageFormat) ageFormat = new Intl.RelativeTimeFormat(undefined, { numeric: "always" });
    return ageFormat;
  };
  function relativeAge(iso, now = Date.now()) {
    const ms = now - Date.parse(iso);
    if (!Number.isFinite(ms)) return "";
    const days = ms / 86400000;
    if (days < 1) return "today";
    if (days < 14) return relative().format(-Math.round(days), "day");
    if (days < 60) return relative().format(-Math.round(days / 7), "week");
    if (days < 730) return relative().format(-Math.round(days / 30.44), "month");
    return relative().format(-Math.round(days / 365.25), "year");
  }
  function since(iso, now = Date.now()) {
    const ms = now - Date.parse(iso);
    if (!Number.isFinite(ms)) return "";
    const minutes = ms / 60000;
    if (minutes < 2) return "just now";
    if (minutes < 90) return relative().format(-Math.round(minutes), "minute");
    if (minutes < 1440) return relative().format(-Math.round(minutes / 60), "hour");
    return relativeAge(iso, now);
  }
  function host(url) {
    try { return new URL(url).hostname; } catch { return String(url ?? ""); }
  }
  function href(url) {
    try { return /^https?:$/.test(new URL(url).protocol) ? String(url) : ""; } catch { return ""; }
  }
  const reach = (cell) =>
    (typeof (cell || {}).reachable === "boolean" ? (cell.reachable ? "up" : "down") : "");

  /* --- Vocabulary: the page's words for the payload's keys ------------------ */

  /* Where a version was read from, as a reader would say it, and the short
     form that fits beside the number. The payload's own `source_labels`
     (OpenAPI, status, SmartAPI, Helm) stay the contract; these are the page's. */
  const SOURCE_WORDS = {
    openapi: "its API document",
    status: "its /status page",
    smartapi: "the SmartAPI registry",
    helm: "the Helm chart",
  };
  const SOURCE_SHORT = { openapi: "API", status: "status", smartapi: "registry", helm: "chart" };

  /* Which document the version was read from, so the cell can link to it. */
  const VERSION_DOC = {
    openapi: (row, cell) => cell.openapi_url,
    status: (row, cell) => cell.status_url,
    smartapi: (row) => (row.smartapi_record || {}).registry_url,
    helm: (row) => ((row.helm_charts || [])[0] || {}).source_url,
  };

  const DOCUMENT_WORDS = {
    version: "carries a version",
    "no-version": "document has no version",
    "not-json": "serves HTML, not JSON",
  };

  function recentQueries(value) {
    if (!value || typeof value.count !== "number") return "";
    const parts = [`${value.count.toLocaleString()} queries`];
    if (value.p50_ms != null) parts.push(`p50 ${value.p50_ms} ms`);
    if (value.p95_ms != null) parts.push(`p95 ${value.p95_ms} ms`);
    return parts.join(" · ");
  }

  /* --- The cell model --------------------------------------------------- */

  /* Everything a renderer needs to know about one environment of one
     component, in one shape, so the table cell, its tooltip and the expanded
     row cannot disagree. Always an object: a missing environment is simply
     not deployed, with no facts. `facts` is the ordered, null-pruned list the
     expansion and the tooltip iterate, so a new per-environment payload key
     reaches both by being added here. */
  function cellModel(row, env) {
    const cell = (row.environments || {})[env] || {};
    const source = cell.version_source || "";
    const otel = (row.otel_presence || [])
      .filter((p) => (p.seen_in || []).includes(env)).map((p) => p.service);
    const facts = [
      { label: "TRAPI", value: cell.trapi, src: cell.trapi_source },
      { label: "Biolink", value: cell.biolink },
      { label: "Data release", value: cell.data_release, href: href(cell.status_url) },
      { label: "Released", value: cell.released, href: href(cell.release_url),
        note: cell.release_tag },
      { label: "Host", value: cell.url ? host(cell.url) : "", href: href(cell.url), mono: true },
      { label: "Location", value: cell.location },
      { label: "API document", value: DOCUMENT_WORDS[cell.document] || "",
        href: href(cell.openapi_url), note: cell.http_status != null ? `HTTP ${cell.http_status}` : "" },
      { label: "Root answers", value: cell.root_status != null ? `HTTP ${cell.root_status}` : "" },
      { label: "Title", value: cell.openapi_title },
      { label: "Paths", value: cell.paths_count },
      { label: "Operations", value: (cell.trapi_operations || []).length || "" },
      { label: "Async query", value: typeof cell.asyncquery === "boolean" ? (cell.asyncquery ? "yes" : "no") : "" },
      { label: "Recent queries", value: recentQueries(cell.recent_queries) },
      { label: "Status message", value: cell.status_message },
      { label: "Telemetry", value: otel.join(", ") },
    ]
      .filter((f) => f.value != null && f.value !== "")
      .map((f) => ({ ...f, value: String(f.value) }));
    return {
      deployed: !!cell.deployed,
      version: cell.version || "",
      source,
      sourceWord: SOURCE_WORDS[source] || source,
      sourceShort: SOURCE_SHORT[source] || source,
      live: source === "openapi" || source === "status",
      href: href(VERSION_DOC[source] ? VERSION_DOC[source](row, cell) : ""),
      reach: reach(cell),
      drift: cell.drift || [],
      reason: cell.reason || "",
      dataRelease: cell.data_release || "",
      flags: { inferred: !!cell.inferred, unregistered: !!cell.unregistered },
      facts,
    };
  }

  /* --- The figures behind the sync note --------------------------------- */

  /* Shares, not counts: each one says what fraction of the platform has a
     property, and names the Show view that lists the rest. */
  function figures(data) {
    const rows = data.rows || [];
    const envs = data.environments || ["dev", "ci", "test", "prod"];
    const cells = [];
    for (const row of rows) for (const env of envs) cells.push({ row, m: cellModel(row, env) });
    const deployed = cells.filter((c) => c.m.deployed);
    const probed = deployed.filter((c) => c.m.reach);
    const onRecord = deployed.filter((c) => c.row.smartapi);
    const share = (label, n, of, view) => ({ label, n, of, view });
    const counts = data.sync_counts || {};
    const tally = data.source_tally || {};
    return {
      syncedAt: data.synced_at || "",
      checks: { attempted: counts.attempted ?? 0, succeeded: counts.succeeded ?? 0, failed: counts.failed ?? 0 },
      shares: [
        share("deployments reachable", probed.filter((c) => c.m.reach === "up").length, probed.length, "unreachable"),
        share("deployments with a version read", deployed.filter((c) => c.m.version).length, deployed.length, "none"),
        share("deployments listed in their SmartAPI record", onRecord.filter((c) => !c.m.flags.unregistered).length, onRecord.length, "unregistered"),
        share("components with a SmartAPI record", rows.filter((r) => r.smartapi_record).length, rows.length, "no-smartapi"),
        share("components running the same version everywhere",
          rows.filter((r) => !envs.some((env) => cellModel(r, env).drift.length)).length, rows.length, "differ"),
      ].filter((s) => s.of > 0),
      otel: { total: data.otel_service_total ?? 0, perEnv: Object.entries(data.otel_service_counts || {}) },
      sources: ["openapi", "status", "smartapi", "helm"].filter((k) => tally[k])
        .map((k) => `${tally[k]} from ${SOURCE_WORDS[k]}`)
        .concat(tally.none ? [`${tally.none} from nowhere`] : []),
    };
  }

  /* --- Mockup scaffolding ------------------------------------------------- */

  function bands(rows) {
    const out = [];
    for (const row of rows) {
      const last = out[out.length - 1];
      if (last && last.key === row.step_label) { last.rows.push(row); continue; }
      out.push({ key: row.step_label, label: row.step_label, title: row.step_title,
        description: row.step_description, rows: [row] });
    }
    return out;
  }

  /* payload.js (gitignored; the README says how to write it) inlines the
     build's overview.json so the pages open from file://, where a browser
     refuses to fetch one local file from another. Served over HTTP, the fetch
     works without it. */
  async function load() {
    if (window.PAYLOAD) return window.PAYLOAD;
    let res;
    try { res = await fetch("../data/dashboard/overview.json"); } catch (e) { res = null; }
    if (!res || !res.ok) {
      document.body.insertAdjacentHTML("afterbegin",
        "<p style='margin:16px;padding:12px;border:1px solid #c00;font:14px system-ui'>No payload. " +
        "Run <code>uv run build-dashboard</code>, then write <code>mockups/payload.js</code> as mockups/README.md says.</p>");
      throw new Error("no payload");
    }
    return res.json();
  }

  /* ?theme=dark|light, else the system. The real page's inline bootstrap does
     the same from localStorage. */
  function applyTheme() {
    const asked = new URLSearchParams(location.search).get("theme");
    const dark = asked ? asked === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
    document.documentElement.dataset.theme = dark ? "dark" : "light";
  }

  const SHOW_VIEWS = {
    all: "All components", differ: "Environments disagree", known: "Any version known",
    none: "No version known", unreachable: "Not reachable",
    unregistered: "Absent from SmartAPI record", "no-smartapi": "No SmartAPI record",
  };

  return { esc, host, href, since, relativeAge, reach, cell: cellModel, figures, bands, load,
    applyTheme, SOURCE_WORDS, SOURCE_SHORT, SHOW_VIEWS };
})();
