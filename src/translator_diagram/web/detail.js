/*
  The detail renderers: one component in, HTML out. The drawer shows these
  six panels in tabs and the component page shows them as sections, from the
  same functions, so a fact read in one place and the same fact read in the
  other are one claim rather than two renderings that could drift.

  Two rules run through the whole file.

  Every value is optional. A build made from an older sync cache, or a public
  build with a policy applied, is missing whole blocks (`catalog_edges`,
  `repository_meta`, `smartapi_record`, half of `helm_charts[].last_changed`),
  and a renderer that throws on one absent key takes the page with it. So
  nothing here indexes without a guard and nothing assumes a list is a list.

  And a fact is never shown without its provenance. A Helm chart says what
  *should* run; `derived_rejected` says a conventional hostname did not answer,
  not that a service is down; `uptime` belongs to a SmartAPI record, not to an
  environment. Each of those carries its label in the markup beside it, because
  a reader who screenshots one row of this takes the label with them.

  Nothing here touches the document at definition time, so tests/web/ can load
  it under node the way it loads layout.js and map.js. The `dw-` class prefix
  is the shared detail vocabulary (detail.css); it predates the page and was
  kept rather than renamed across five hundred lines of stylesheet.
*/

(() => {
  "use strict";

  const TD = (globalThis.TD = globalThis.TD || {});
  const detail = (TD.detail = TD.detail || {});

  const WIKI_BASE = "https://github.com/NCATSTranslator/Translator-All/wiki/";
  const TABS = [
    { id: "overview", label: "Overview" },
    { id: "environments", label: "Environments" },
    { id: "releases", label: "Releases" },
    { id: "helm", label: "Helm" },
    { id: "smartapi", label: "SmartAPI" },
    { id: "connections", label: "Connections" },
  ];
  const TAB_IDS = TABS.map((tab) => tab.id);
  const DEFAULT_TAB = "overview";
  const LIST_LIMIT = 8;

  /* --- Small helpers ------------------------------------------------------- */

  const esc = (value) => TD.fmt.esc(value);
  const DASH = TD.fmt.DASH;

  const data = () => TD.DATA || {};
  const envs = () => (Array.isArray(TD.ENVS) && TD.ENVS.length ? TD.ENVS : []);
  const rows = () => data().rows || [];
  const rowById = (id) => rows().find((row) => row.id === id) || null;

  const list = (value) => (Array.isArray(value) ? value.filter((v) => v != null) : []);
  const filled = (value) => value !== null && value !== undefined && value !== "";

  const mono = (value) => `<span class="dw-mono">${esc(value)}</span>`;
  const note = (text) => `<span class="dw-note">${esc(text)}</span>`;

  /* Every link out of this page opens in its own tab: the drawer holds the
     reader's place in a filtered, sorted, scrolled table, and navigating away
     from it in place loses all of that. */
  function ext(url, text, cls) {
    if (!filled(url)) return "";
    const href = TD.fmt.href(url);
    if (!href) return esc(filled(text) ? text : url);
    return `<a class="${cls || "dw-link"}" href="${esc(href)}" target="_blank"
      rel="noopener">${esc(filled(text) ? text : url)}</a>`;
  }

  /* Truncation is done by CSS (one line, ellipsis), so the full string has to
     travel with the node for the tooltip to have anything to show. */
  function clip(text) {
    return `<span class="dw-clip" data-tip="1" data-full="${esc(text)}">${esc(text)}</span>`;
  }

  const yesNo = (value) =>
    value === true ? "yes" : value === false ? "no" : "";

  /* A definition-list row. Absent by default, because a drawer that prints a
     dash for each of forty keys is a form, not a reading surface; `always` is
     for the handful where "we do not know" is itself the answer. */
  function drow(label, html, always) {
    if (!html) {
      if (!always) return "";
      html = DASH;
    }
    return `<div class="dw-r"><dt>${esc(label)}</dt><dd>${html}</dd></div>`;
  }

  const dl = (parts) => {
    const body = parts.filter(Boolean).join("");
    return body ? `<dl class="dw-dl">${body}</dl>` : "";
  };

  const stack = (items) =>
    items.length ? `<ul class="dw-stack">${items.map((i) => `<li>${i}</li>`).join("")}</ul>` : "";

  let discId = 0;

  /* A disclosure, not <details>: the native element cannot animate its own
     height, and this page's contract is that anything which changes height
     eases. The grid-template-rows 0fr→1fr trick is what does the easing; it
     collapses to nothing under prefers-reduced-motion because --dur-layout
     does. */
  function disclosure(summary, html) {
    if (!html) return "";
    const id = `dw-disc-${++discId}`;
    return `<button type="button" class="dw-disc" data-disc="${id}"
        aria-expanded="false" aria-controls="${id}"
        >${TD.ui.CHEVRON}<span>${esc(summary)}</span></button>
      <div class="dw-disc-body" id="${id}"><div>${html}</div></div>`;
  }

  /* Eight is where a list stops being scannable and starts being a wall. The
     count in the summary is the whole list's, not the hidden remainder's, so
     "show all 21" answers "how many are there" without expanding. */
  function longList(items, word) {
    if (!items.length) return "";
    if (items.length <= LIST_LIMIT) return stack(items);
    const head = stack(items.slice(0, LIST_LIMIT));
    const rest = stack(items.slice(LIST_LIMIT));
    return head + disclosure(`show all ${items.length} ${word}`, rest);
  }

  function sections(parts, cls) {
    return parts
      .filter(Boolean)
      .map((html, index) =>
        `<section class="dw-sec${cls ? ` ${cls}` : ""}" style="--i:${index}">${html}</section>`)
      .join("");
  }

  const heading = (text) => `<h3 class="dw-h">${esc(text)}</h3>`;
  const caption = (text) => `<p class="dw-cap">${esc(text)}</p>`;
  const muted = (text) => `<p class="dw-muted">${esc(text)}</p>`;

  function table(headers, bodyRows) {
    if (!bodyRows.length) return "";
    const head = headers.map((h) => `<th>${esc(h)}</th>`).join("");
    const body = bodyRows
      .map((cells) => `<tr>${cells.map((c) => `<td>${c || DASH}</td>`).join("")}</tr>`)
      .join("");
    return `<div class="dw-tscroll"><table class="dw-t"><thead><tr>${head}</tr></thead>
      <tbody>${body}</tbody></table></div>`;
  }

  const sourceLabel = TD.fmt.sourceLabel;

  /* Colour is never the only carrier here either: the dot has a word beside
     it in every place it is used. */
  function dot(state) {
    const cls = state === true || state === "pass" ? "up" : state === false || state === "fail" ? "down" : "";
    return `<span class="dot ${cls}" aria-hidden="true"></span>`;
  }

  function ago(iso) {
    if (!filled(iso)) return "";
    const age = TD.fmt.relativeAge(iso);
    return age ? `${age} <span class="dw-note" title="${esc(iso)}">${esc(String(iso).slice(0, 10))}</span>` : esc(String(iso).slice(0, 10));
  }

  /* --- Header -------------------------------------------------------------- */

  /* Derived from the same four stops colors.py hands the map, so the rule
     under the name and the rail on the map node are the same metal. A
     component with no owner style gets a hairline rather than a gap. */
  function metalRule(owner) {
    return `background: ${TD.owner.metal(owner, "90deg") || "var(--hairline-strong)"}`;
  }

  function headerLinks(row) {
    const links = [];
    if (row.repository) links.push(ext(row.repository, "Repository"));
    const doc = list(row.docs)[0];
    if (doc && doc.url) links.push(ext(doc.url, "Docs"));
    if (row.translator_all_wiki) {
      links.push(ext(WIKI_BASE + row.translator_all_wiki, "Wiki"));
    }
    const record = row.smartapi_record;
    if (record && record.registry_url) links.push(ext(record.registry_url, "SmartAPI registry"));
    const chart = list(row.helm_charts)[0];
    if (chart && chart.source_url) links.push(ext(chart.source_url, "Helm chart"));
    return links.length ? `<div class="dw-links">${links.join("")}</div>` : "";
  }

  const CLOSE_BUTTON = `<button type="button" class="dw-close" aria-label="Close details">
          <svg viewBox="0 0 14 14" width="12" height="12" aria-hidden="true" fill="none"
            stroke="currentColor" stroke-width="1.6" stroke-linecap="round"
            ><path d="M3 3l8 8M11 3l-8 8"/></svg>
        </button>`;

  /* The name, id, blurb, owner rule, meta line and links: the top of the
     drawer and the top of the component page, from one function so the two
     cannot come to describe a component differently. `close` adds the
     drawer's ✕; a page has nothing to close. */
  function headerHtml(row, options) {
    const opts = options || {};
    // GitHub's own one-liner for the repository. It is the shortest true
    // sentence about what this thing is, and it costs one line.
    const blurb = (row.repository_meta || {}).description || "";
    const meta = [row.refactor_status, row.hosted_at, row.component_type || row.type, row.layer]
      .filter(filled)
      .map(esc)
      .join(" · ");
    return `<div class="dw-headtop">
        <div class="dw-name">${TD.owner.coin(row.owner)}<h2>${esc(row.name || row.id)}</h2></div>
        ${opts.close ? CLOSE_BUTTON : ""}
      </div>
      <div class="dw-id">${esc(row.id)}</div>
      ${blurb ? `<div class="dw-blurb">${esc(blurb)}</div>` : ""}
      <div class="dw-rule" style="${metalRule(row.owner)}" aria-hidden="true"></div>
      ${meta ? `<div class="dw-metaline">${meta}</div>` : ""}
      ${headerLinks(row)}`;
  }

  /* --- Overview tab -------------------------------------------------------- */

  function otelHtml(row) {
    const names = list(row.otel_services);
    if (!names.length) return "";
    const presence = list(row.otel_presence);
    const items = names.map((name) => {
      const hit = presence.find((entry) => entry && entry.service === name);
      const seen = hit ? list(hit.seen_in) : [];
      // The join is case-sensitive on the Python side: a recorded name that
      // differs from the reported one by a capital letter is genuinely a name
      // nothing reports, and saying so is the point of this row.
      const where = seen.length
        ? `<span class="dw-note">${esc(seen.join(" · "))}</span>`
        : `<span class="dw-note dw-off">not reporting</span>`;
      return `${mono(name)} ${where}`;
    });
    return longList(items, "services");
  }

  function repositoriesHtml(row) {
    const repos = list(row.repositories);
    if (!repos.length) return row.repository ? stack([ext(row.repository)]) : "";
    return stack(repos.map((repo) => {
      const label = String(repo.url || "").replace("https://github.com/", "");
      const bits = [repo.role, repo.visibility && repo.visibility !== "public" ? repo.visibility : ""]
        .filter(filled).join(" · ");
      return `${ext(repo.url, label)} ${bits ? note(bits) : ""}`;
    }));
  }

  /* "github.com" is what a bare hostname says about five of these links, so
     the last path segment comes with it — that is the part that names the
     page, and it is what the wiki row shows too. */
  function docLabel(url) {
    let path = "";
    try { path = new URL(url).pathname; } catch { path = ""; }
    const last = path.split("/").filter(Boolean).pop();
    const host = TD.fmt.host(url);
    return last ? `${host} / ${decodeURIComponent(last)}` : host || url;
  }

  function docsHtml(row) {
    const docs = list(row.docs);
    if (!docs.length) return "";
    return stack(docs.map((doc) =>
      `${ext(doc.url, docLabel(doc.url))} ${doc.kind ? note(doc.kind) : ""}`));
  }

  function endpointsHtml(row) {
    const endpoints = row.endpoints && typeof row.endpoints === "object" ? row.endpoints : {};
    const keys = Object.keys(endpoints);
    if (!keys.length) return "";
    // The key in small caps, the path in mono: "openapi openapi.json" in one
    // typeface reads as one string rather than as a name and its value.
    return stack(keys.map((key) =>
      `<span class="dw-key">${esc(key)}</span> ${
        filled(endpoints[key]) ? mono(endpoints[key]) : DASH}`));
  }

  function updatedHtml(row) {
    const updated = row.last_updated;
    if (!updated) return "";
    const label = (data().updated_labels || {})[updated.source] || updated.source;
    const bits = [label, updated.tag].filter(filled).map(esc).join(" · ");
    return `${esc(TD.fmt.relativeAge(updated.at) || updated.date || "")} ${
      bits ? note(bits) : ""}`;
  }

  function repoMetaHtml(row) {
    const meta = row.repository_meta;
    if (!meta) return "";
    const topics = list(meta.topics);
    // Description is deliberately absent: it is the header's subtitle now, and
    // printing it twice in one drawer is the kind of padding this page avoids.
    return dl([
      drow("Default branch", meta.default_branch ? mono(meta.default_branch) : ""),
      drow("Last push", meta.pushed_at ? ago(meta.pushed_at) : ""),
      drow("Archived", meta.archived ? "yes" : ""),
      drow("Licence", meta.license ? esc(meta.license) : ""),
      drow("Open issues", filled(meta.open_issues) ? esc(meta.open_issues) : ""),
      drow("Stars", filled(meta.stars) ? esc(meta.stars) : ""),
      drow("Homepage", ext(meta.homepage)),
      drow("Topics", topics.length
        ? topics.map((t) => `<span class="dw-tag">${esc(t)}</span>`).join("") : ""),
    ]);
  }

  function panelOverview(row) {
    const itrb = row.itrb || {};
    const record = row.smartapi_record;

    const typeValue = row.component_type || row.type;
    const typeExtra = row.type && row.component_type && row.type !== row.component_type
      ? ` ${note(`registry reads ${row.type}`)}` : "";

    const stage = [row.step_label, row.step_title].filter(filled).map(esc).join(" · ");

    const smartapiId = row.smartapi;
    const smartapiCell = smartapiId
      ? (record && record.registry_url
        ? ext(record.registry_url, smartapiId, "dw-link dw-mono")
        : mono(smartapiId))
      : "";

    const charts = list(row.chart_names);
    const chartDetails = list(row.helm_charts);
    const chartCell = charts.length
      ? charts.map((name) => {
        const detail = chartDetails.find((c) => c && c.chart === name);
        return detail && detail.source_url
          ? ext(detail.source_url, name, "dw-link dw-mono")
          : mono(name);
      }).join(" ")
      : "";

    // Uptime is one value per SmartAPI *record*, not per environment: the
    // registry probes the servers it knows about and reports one verdict.
    // Saying so beside it is what stops it being read as "prod is up".
    const uptime = filled(row.uptime)
      ? `${dot(row.uptime)}${esc(row.uptime)} ${note("from SmartAPI, whole record")}`
      : "";

    const identity = dl([
      drow("Type", typeValue ? esc(typeValue) + typeExtra : "", true),
      drow("Layer", row.layer ? esc(row.layer) : "", true),
      drow("Stage", stage ? `${stage}${row.step_description
        ? `<span class="dw-sub">${esc(row.step_description)}</span>` : ""}` : "", true),
      drow("Owner", row.owner
        ? `<span class="ownercell">${TD.owner.coin(row.owner)}<span>${esc(row.owner)}</span></span>` : "", true),
      drow("Part of", row.part_of ? esc(row.part_of) : ""),
      drow("ITRB app / group", [itrb.app, itrb.group].filter(filled).length
        ? `${itrb.app ? mono(itrb.app) : DASH}${itrb.group ? ` ${note(`group ${itrb.group}`)}` : ""}` : ""),
      drow("infores", row.infores ? mono(row.infores) : "", true),
      drow("SmartAPI id", smartapiCell, true),
      drow("Helm chart", chartCell),
      drow("Wiki", row.translator_all_wiki
        ? ext(WIKI_BASE + row.translator_all_wiki, row.translator_all_wiki) : ""),
      drow("OTel services", otelHtml(row)),
      drow("Repositories", repositoriesHtml(row)),
      drow("Documentation", docsHtml(row)),
      drow("Endpoints", endpointsHtml(row)),
      drow("Last updated", updatedHtml(row), true),
      drow("Uptime", uptime),
      drow("Isolated?", row.isolated ? "no recorded connections" : ""),
      // The map puts a ubiquitous component on a rail at the right, outside
      // the stage rows, with its edges off by default (layout.js); saying so
      // here is what stops that reading as a missing node.
      drow("On the map", (row.diagram || {}).ubiquitous
        ? `on the rail at the right, edges hidden by default ${note("ubiquitous")}` : ""),
    ]);

    const meta = repoMetaHtml(row);

    return sections([
      row.notes ? `<p class="dw-prose">${esc(row.notes)}</p>` : "",
      identity,
      meta ? heading("Repository") + meta : "",
    ]);
  }

  /* --- Environments tab ---------------------------------------------------- */

  /* What the document at the far end turned out to be. "version" is the
     ordinary case and the Version row above already says it, so only the two
     that explain an absence are drawn. */
  const DOCUMENT_WORDS = {
    "no-version": "document has no version",
    "not-json": "serves HTML, not JSON",
    version: "carries a version",
  };

  /* One environment's facts as a list of rows, in the order they are read.
     The drawer draws them as a definition list under the environment's
     name and the component page draws the four environments side by side
     as a matrix; both come from here, so the two cannot disagree about what
     an environment has to say. An empty cell — not deployed — gives an
     empty list, and `reason` (below) is the sentence for that. */
  function envFields(row, env) {
    const cell = (row.environments || {})[env];
    if (!cell || !cell.deployed) return [];

    const drift = list(cell.drift);
    // No glyph: the tint carries it, the sentence is one hover away, and
    // aria-label is what a screen reader gets — the same three parts the
    // table's cells use, so the two surfaces make one claim.
    const driftSays = drift.length
      ? `disagrees with the rest of this row: ${drift.join(", ")}` : "";
    const version = cell.version
      ? `<span class="dw-ver${drift.length ? " dw-drift" : ""}"${drift.length
        ? ` data-tip="say" data-full="${esc(driftSays)}" aria-label="${esc(driftSays)}"` : ""}>${
        esc(cell.version)}</span>`
      : DASH;
    const source = cell.version_source
      ? ` <span class="src" data-src="${esc(cell.version_source)}">${
        esc(sourceLabel(cell.version_source))}</span>` : "";
    const unregistered = cell.unregistered
      ? ` ${note("absent from the SmartAPI record")}` : "";

    const href = cell.openapi_url || cell.url;
    const host = href
      ? `${ext(href, TD.fmt.host(cell.url || href))}<span class="dw-sub">${esc(cell.url || href)}</span>`
      : "";

    const dotHtml = typeof cell.reachable === "boolean" ? dot(cell.reachable) : "";
    const reach = typeof cell.reachable === "boolean"
      ? note(cell.reachable ? "reachable" : "not reachable") : "";
    // When the OpenAPI document did not answer there is no http_status, and
    // the root probe is the only thing that did. Shown under its own label so
    // a 200 from "/" is never read as a 200 from the document.
    const noHttp = !filled(cell.http_status);
    const httpRow = noHttp ? "" : `${dotHtml}${esc(cell.http_status)} ${reach}`;
    // The dot travels to whichever row is the actual evidence, so a service
    // whose document never answered still says whether anything answered.
    const rootRow = noHttp && filled(cell.root_status)
      ? `${dotHtml}${esc(cell.root_status)} ${note("the service's root path, not its document")}`
      : "";
    const reachRow = noHttp && !filled(cell.root_status) && dotHtml
      ? `${dotHtml}${reach}` : "";

    const queries = cell.recent_queries
      ? [
        filled(cell.recent_queries.count) ? `${esc(cell.recent_queries.count)} queries` : "",
        filled(cell.recent_queries.p50_ms) ? `p50 ${esc(cell.recent_queries.p50_ms)} ms` : "",
        filled(cell.recent_queries.p95_ms) ? `p95 ${esc(cell.recent_queries.p95_ms)} ms` : "",
      ].filter(Boolean).join(" · ")
      : "";

    const operations = list(cell.trapi_operations);
    const opsHtml = operations.length
      ? `${operations.length} ${disclosure("show", stack(operations.map((op) => mono(op))))}`
      : "";

    const document = cell.document && cell.document !== "version"
      ? (DOCUMENT_WORDS[cell.document] || cell.document) : "";

    const field = (label, html, always) => ({ label, html: html || "", always: !!always });
    return [
      field("Version", `${version}${source}${unregistered}`, true),
      field("TRAPI", cell.trapi
        ? `${esc(cell.trapi)}${cell.trapi_source ? ` <span class="src" data-src="${
          esc(cell.trapi_source)}">${esc(sourceLabel(cell.trapi_source))}</span>` : ""}` : ""),
      field("Biolink", cell.biolink ? esc(cell.biolink) : ""),
      field("Data release", cell.data_release ? esc(cell.data_release) : ""),
      field("Released", cell.released
        ? `${esc(cell.released)}${cell.release_tag
          ? ` ${cell.release_url ? ext(cell.release_url, cell.release_tag, "dw-link dw-mono")
            : mono(cell.release_tag)}` : ""}` : ""),
      field("Host", host),
      field("HTTP status", httpRow),
      field("Root", rootRow),
      field("Reachable", reachRow),
      field("Document", document ? esc(document) : ""),
      field("Status endpoint", cell.status_url
        ? ext(cell.status_url, TD.fmt.host(cell.status_url)) : ""),
      field("Location", cell.location ? esc(cell.location) : ""),
      field("OpenAPI title", cell.openapi_title ? esc(cell.openapi_title) : ""),
      field("Paths", filled(cell.paths_count) ? esc(cell.paths_count) : ""),
      field("Async query", yesNo(cell.asyncquery)),
      field("Status message", cell.status_message ? esc(cell.status_message) : ""),
      field("Recent queries", queries),
      field("TRAPI operations", opsHtml),
    ];
  }

  /* The sentence over an environment's facts, or in place of them. `reason`
     is the payload's own line for why there is no version — "no such host",
     "up · no version endpoint", "not in registry for ci" — and is a better
     first line than "Not deployed", which says less and is sometimes wrong:
     a service can be up and still report no version. An inferred deployment
     is one nothing probed directly: the registry named this maturity in a
     server description, which qualifies every row beneath it. */
  function envCaption(row, env) {
    const cell = (row.environments || {})[env];
    if (!cell || !cell.deployed) {
      return cell && cell.reason ? muted(cell.reason) : muted("Not deployed.");
    }
    const inferred = cell.inferred
      ? caption("inferred from the registry server's description") : "";
    return inferred + (cell.version || !cell.reason ? "" : muted(cell.reason));
  }

  function envBlock(row, env) {
    const fields = envFields(row, env);
    if (!fields.length) return heading(env) + envCaption(row, env);
    return heading(env) + envCaption(row, env)
      + dl(fields.map((f) => drow(f.label, f.html, f.always)));
  }

  /* The four environments side by side: one row per fact, one column per
     environment, a dash wherever an environment has nothing to say. The
     drawer's per-environment list hides an absent fact by design; this is
     the layout for a page whose job is to show the gaps, so every fact any
     environment reports gets a row and every environment gets a cell in it.
     The caption row under the header carries what `envBlock` says above its
     list: the reason there is no version, or that a deployment was inferred. */
  function envMatrix(row) {
    const names = envs();
    if (!names.length) return muted("This build names no environments.");
    const perEnv = names.map((env) => envFields(row, env));
    const labels = [];
    for (const fields of perEnv) {
      for (const f of fields) if (labels.indexOf(f.label) < 0) labels.push(f.label);
    }
    if (!labels.length) {
      return `<div class="dw-tscroll"><table class="dw-t dw-matrix"><thead><tr><th></th>${
        names.map((env) => `<th>${esc(env)}</th>`).join("")}</tr></thead><tbody><tr><th scope="row"></th>${
        names.map((env) => `<td>${envCaption(row, env)}</td>`).join("")}</tr></tbody></table></div>`;
    }
    const head = `<tr><th></th>${names.map((env) => `<th>${esc(env)}</th>`).join("")}</tr>`;
    const captions = `<tr class="dw-matrix-cap"><th scope="row"></th>${
      names.map((env) => `<td>${envCaption(row, env)}</td>`).join("")}</tr>`;
    const body = labels.map((label) => {
      const cells = perEnv.map((fields) => {
        const hit = fields.find((f) => f.label === label);
        return `<td>${hit && hit.html ? hit.html : DASH}</td>`;
      });
      return `<tr><th scope="row">${esc(label)}</th>${cells.join("")}</tr>`;
    }).join("");
    return `<div class="dw-tscroll"><table class="dw-t dw-matrix"><thead>${head}</thead><tbody>${
      captions}${body}</tbody></table></div>` + rejectedHtml(row);
  }

  function rejectedHtml(row) {
    const rejected = list(row.derived_rejected);
    if (!rejected.length) return "";
    return heading("Probed, not confirmed")
      + caption("a conventional hostname that did not confirm; not a claim that anything is down")
      + stack(rejected.map((entry) =>
        `<span class="dw-key">${esc(entry.env)}</span> ${ext(entry.url, entry.url, "dw-link dw-mono")}`));
  }

  function panelEnvironments(row) {
    const blocks = envs().map((env) => envBlock(row, env));
    if (!blocks.length) blocks.push(muted("This build names no environments."));
    // The one class on the page that puts a rule back: four environments read
    // as four claims, and spacing alone was not enough to keep prod's rows
    // from looking like more of test's.
    return sections(blocks.concat([rejectedHtml(row)]), "dw-envsec");
  }

  /* --- Releases tab -------------------------------------------------------- */

  /* Which environments run this release. Two sources, deliberately: the
     release carries a `deployed` flag computed on the Python side, and the
     environment cells carry the tag they are actually running. The second is
     what names the environments, which is the part a reader asks about. */
  function deployedIn(row, release) {
    const where = envs().filter((env) => {
      const cell = (row.environments || {})[env];
      return cell && cell.deployed && cell.release_tag === release.tag;
    });
    if (where.length) return where;
    return release.deployed ? [] : null;
  }

  function releaseItem(row, release) {
    const where = deployedIn(row, release);
    const isDeployed = where !== null;
    const marks = [];
    if (isDeployed) {
      marks.push(note(where.length ? `deployed in ${where.join(", ")}` : "deployed"));
    }
    if (release.prerelease) marks.push(note("prerelease"));
    if (release.author) marks.push(note(`by ${release.author}`));
    if (release.published) marks.push(note(release.published));

    const tag = release.url
      ? ext(release.url, release.tag, `dw-link dw-mono${isDeployed ? " dw-on" : ""}`)
      : `<span class="dw-mono${isDeployed ? " dw-on" : ""}">${esc(release.tag)}</span>`;
    const name = release.name && release.name !== release.tag
      ? `<span class="dw-relname">${esc(release.name)}</span>` : "";

    return `<div class="dw-rel">
      <div class="dw-relhead">${tag}${name}</div>
      <div class="dw-relmeta">${marks.join(" ")}</div>
      ${release.body_excerpt ? `<p class="dw-excerpt">${esc(release.body_excerpt)}</p>` : ""}
    </div>`;
  }

  function panelReleases(row) {
    const usable = list(row.releases_detail);
    if (!usable.length) return sections([muted("No releases recorded.")]);
    const items = usable.map((release) => releaseItem(row, release));
    const head = items.slice(0, LIST_LIMIT).join("");
    const rest = items.slice(LIST_LIMIT).join("");
    return sections([
      head + (rest ? disclosure(`show all ${items.length} releases`, rest) : ""),
    ]);
  }

  /* --- Helm tab ------------------------------------------------------------ */

  function chartBlock(chart) {
    const services = list(chart.services).map((service) => [
      service.name ? mono(service.name) : "",
      filled(service.replicas) ? esc(service.replicas) : "",
      service.requests ? esc([service.requests.cpu, service.requests.memory].filter(filled).join(" / ")) : "",
      service.limits ? esc([service.limits.cpu, service.limits.memory].filter(filled).join(" / ")) : "",
    ]);
    const deps = list(chart.dependencies).map((dep) => [
      dep.name ? mono(dep.name) : "",
      dep.version ? esc(dep.version) : "",
      dep.repository ? clip(dep.repository) : "",
    ]);
    const storage = list(chart.storage).map((entry) => [
      entry.name ? mono(entry.name) : "",
      entry.size ? esc(entry.size) : "",
    ]);
    const hosts = list(chart.ingress_hosts);
    const changed = chart.last_changed;

    return heading(chart.chart || "chart") + dl([
      drow("Chart", chart.chart ? mono(chart.chart) : "", true),
      drow("Chart version", chart.chart_version ? mono(chart.chart_version) : "", true),
      drow("app version, from the chart", chart.app_version ? mono(chart.app_version) : "", true),
      drow("Description", chart.description ? esc(chart.description) : ""),
      // Labelled every time it is drawn. A commit that touched a chart says
      // someone meant to change what runs; it does not say a cluster took it.
      drow("Chart last changed", changed
        ? `${changed.url ? ext(changed.url, changed.date || changed.sha || "commit") : esc(changed.date || "")}
           ${changed.subject ? `<span class="dw-sub">${esc(changed.subject)}</span>` : ""}
           ${note("intent to deploy, not a deployment")}`
        : ""),
      drow("Chart source", ext(chart.source_url, "open in translator-devops")),
    ])
      + (deps.length ? heading("Dependencies") + table(["Name", "Version", "Repository"], deps) : "")
      + (services.length
        ? heading("Services")
          + table(["Service", "Replicas", "Requests cpu / mem", "Limits cpu / mem"], services)
        : "")
      + (storage.length ? heading("Storage") + table(["Volume", "Size"], storage) : "")
      + (hosts.length
        ? heading("Ingress hosts") + caption("chart defaults")
          + stack(hosts.map((host) => mono(host)))
        : "");
  }

  function panelHelm(row) {
    const charts = list(row.helm_charts);
    const status = row.helm_status;
    const parts = [caption(
      "From the chart in translator-devops: what should be deployed, not what is running.")];

    if (status === "none-in-devops") {
      parts.push(muted("No chart for this component in helxplatform/translator-devops."));
    } else if (status === "not-devops-hosted") {
      parts.push(muted(`Deployed from ${row.hosted_at || "elsewhere"}, not from translator-devops.`));
    } else if (charts.length) {
      for (const chart of charts) parts.push(chartBlock(chart));
    } else {
      parts.push(muted("No chart recorded for this component."));
    }

    // The public build withholds image tags; the page has to say so, or the
    // absence reads as "this chart pins nothing".
    const withheld = list((data().redacted || {}).fields);
    if (withheld.indexOf("helm_images") >= 0) {
      parts.push(caption("Container image tags are withheld from the published page."));
    }
    return sections(parts);
  }

  /* --- SmartAPI tab -------------------------------------------------------- */

  function candidatesHtml(row) {
    const candidates = list(row.smartapi_candidates);
    if (!candidates.length) return "";
    const titles = candidates.map((c) => c.title || c.smartapi_id).filter(filled);
    return caption(`${candidates.length} registry ${
      candidates.length === 1 ? "entry shares" : "entries share"
    } this infores; none is recorded on the component: ${titles.join(", ")}`)
      + stack(candidates.map((c) =>
        `${ext(`https://smart-api.info/ui/${c.smartapi_id}`, c.smartapi_id, "dw-link dw-mono")} ${
          c.title ? esc(c.title) : ""}`));
  }

  function panelSmartapi(row) {
    const record = row.smartapi_record;
    if (!record) {
      return sections([
        muted("Not registered in SmartAPI."),
        candidatesHtml(row),
      ]);
    }

    const trapi = record.trapi || {};
    const status = record.status || {};
    const meta = record.meta || {};
    const contact = record.contact || {};
    const teams = list(record.team);
    const operations = list(trapi.operations);
    const testData = trapi.test_data_location && typeof trapi.test_data_location === "object"
      ? Object.entries(trapi.test_data_location)
      : [];

    const identity = dl([
      drow("Title", record.title ? esc(record.title) : "", true),
      drow("Version", record.version ? mono(record.version) : ""),
      drow("Team", teams.length ? esc(teams.join(", ")) : ""),
      drow("Component", record.component ? esc(record.component) : ""),
      drow("infores", record.infores ? mono(record.infores) : ""),
      drow("Biolink version", record.biolink_version ? mono(record.biolink_version) : ""),
    ]);

    const trapiBlock = heading("TRAPI") + dl([
      drow("Version", trapi.version ? mono(trapi.version) : "", true),
      drow("Async query", yesNo(trapi.asyncquery)),
      drow("Batch size limit", filled(trapi.batch_size_limit) ? esc(trapi.batch_size_limit) : ""),
      drow("Rate limit", filled(trapi.rate_limit) ? esc(trapi.rate_limit) : ""),
      drow("Test data", testData.length
        ? stack(testData.map(([maturity, url]) => `${esc(maturity)} ${ext(url, TD.fmt.host(url))}`)) : ""),
      drow("Operations", operations.length
        ? `${operations.length} ${disclosure(
          `show all ${operations.length}`, stack(operations.map((op) => mono(op))))}` : ""),
    ]);

    const servers = list(record.servers).map((server) => {
      const under = [server.location, server.description].filter(filled).map(esc).join(" · ");
      return [
        server.maturity ? esc(server.maturity) : "",
        `${server.url ? ext(server.url, server.url, "dw-link dw-mono") : ""}${
          under ? `<span class="dw-sub">${under}</span>` : ""}`,
      ];
    });

    const checks = list(status.uptime_msg);
    const statusBlock = heading("Status") + dl([
      drow("Uptime", filled(status.uptime_status)
        ? `${dot(status.uptime_status)}${esc(status.uptime_status)}` : "", true),
      drow("Last probe", status.uptime_ts ? ago(status.uptime_ts) : ""),
      drow("Refresh", filled(status.refresh_status)
        ? `${esc(status.refresh_status)}${status.refresh_ts ? ` ${note(TD.fmt.relativeAge(status.refresh_ts))}` : ""}` : ""),
      drow("Per-path checks", checks.length
        ? disclosure(`show all ${checks.length}`, stack(checks.map((line) => esc(line)))) : ""),
    ]);

    const tags = list(record.tags);
    const registration = heading("Registration") + dl([
      drow("Registered", meta.date_created ? ago(meta.date_created) : ""),
      drow("Last updated", meta.last_updated ? ago(meta.last_updated) : ""),
      drow("By", meta.username ? esc(meta.username) : ""),
      drow("Source", meta.source_url ? ext(meta.source_url, "the registration document") : ""),
      drow("Meta knowledge graph", yesNo(meta.has_metakg)),
      drow("Tags", tags.length
        ? tags.map((tag) => `<span class="dw-tag">${esc(tag)}</span>`).join("") : ""),
      drow("Contact", [contact.name, contact.email, contact.url].filter(filled).length
        ? [
          contact.name ? esc(contact.name) : "",
          contact.email ? `<a class="dw-link" href="mailto:${esc(contact.email)}">${esc(contact.email)}</a>` : "",
          contact.url ? ext(contact.url) : "",
        ].filter(Boolean).join(" · ")
        : ""),
      drow("Matched by", record.matched_by ? note(`matched by ${record.matched_by}`) : ""),
    ]);

    return sections([
      identity,
      trapiBlock,
      servers.length ? heading("Servers") + table(["Maturity", "Server"], servers) : "",
      statusBlock,
      registration,
      record.description_text ? heading("Description")
        + `<p class="dw-prose">${esc(record.description_text)}</p>` : "",
    ]);
  }

  /* --- Connections tab ----------------------------------------------------- */

  function connButton(id, planned) {
    const other = rowById(id);
    const label = other ? other.name : id;
    return `<button type="button" class="dw-conn${planned ? " planned" : ""}" data-go="${esc(id)}">
      ${other ? TD.owner.coin(other.owner) : ""}<span class="dw-connname">${esc(label)}</span>
      <span class="dw-mono dw-connid" data-tip="1" data-full="${esc(id)}">${esc(id)}</span>${
      planned ? `<span class="dw-note">planned</span>` : ""}</button>`;
  }

  function connGroup(title, ids, plannedIds) {
    const items = list(ids).map((id) => connButton(id, false))
      .concat(list(plannedIds).map((id) => connButton(id, true)));
    return heading(title) + (items.length ? `<div class="dw-conns">${items.join("")}</div>`
      : muted("None recorded."));
  }

  function panelConnections(row) {
    const connections = row.connections || {};
    const all = rows();

    const reverse = (key) => all
      .filter((other) => other.id !== row.id
        && list((other.connections || {})[key]).indexOf(row.id) >= 0)
      .map((other) => other.id);

    const externals = list(row.externals);
    const externalsHtml = externals.length
      ? `<div class="dw-conns">${externals.map((entry) =>
        `<span class="dw-conn static">${entry.direction === "in" ? "◀" : "▶"}
          <span class="dw-connname">${esc(entry.name)}</span></span>`).join("")}</div>`
      : muted("None recorded.");

    const parts = [
      connGroup("Gets results from",
        connections.gets_results_from, connections.planned_gets_results_from),
      connGroup("Provides results to",
        reverse("gets_results_from"), reverse("planned_gets_results_from")),
      connGroup("Calls", connections.calls, connections.planned_calls),
      connGroup("Called by", reverse("calls"), reverse("planned_calls")),
      heading("Externals") + externalsHtml,
    ];

    // A second opinion, kept separate from the hand-recorded graph rather than
    // merged into it: the catalog is a different claim by a different group.
    const catalogEdges = list(data().catalog_edges);
    const catalog = row.catalog;
    if (catalogEdges.length || catalog) {
      // Catalog edges follow the data (`build_catalog_edges`): what this row
      // consumes is an edge *into* it, and its consumers are edges out.
      const consumes = catalogEdges
        .filter((edge) => edge && edge.to === row.id).map((edge) => edge.from);
      const consumedBy = catalogEdges
        .filter((edge) => edge && edge.from === row.id).map((edge) => edge.to);
      const facts = catalog ? dl([
        drow("Status", catalog.status ? esc(catalog.status) : ""),
        drow("Knowledge level", catalog.knowledge_level ? esc(catalog.knowledge_level) : ""),
        drow("Agent type", catalog.agent_type ? esc(catalog.agent_type) : ""),
        drow("Description", catalog.description ? esc(catalog.description) : ""),
        drow("Cross-references", list(catalog.xref).length
          ? stack(list(catalog.xref).map((x) => mono(x))) : ""),
      ]) : "";
      parts.push(heading("Catalog says")
        + caption("the infores catalog's view, beside what this repository records")
        + facts
        + (consumes.length
          ? `<div class="dw-sublabel">consumes</div><div class="dw-conns">${
            consumes.map((id) => connButton(id, false)).join("")}</div>` : "")
        + (consumedBy.length
          ? `<div class="dw-sublabel">consumed by</div><div class="dw-conns">${
            consumedBy.map((id) => connButton(id, false)).join("")}</div>` : "")
        + (!consumes.length && !consumedBy.length && !facts
          ? muted("Nothing recorded in the catalog for this component.") : ""));
    }

    if (row.isolated) {
      parts.unshift(caption("Nothing in this repository records a connection for this component."));
    }
    return sections(parts);
  }

  const PANELS = {
    overview: panelOverview,
    environments: panelEnvironments,
    releases: panelReleases,
    helm: panelHelm,
    smartapi: panelSmartapi,
    connections: panelConnections,
  };

  /* --- Public API ---------------------------------------------------------- */

  detail.WIKI_BASE = WIKI_BASE;
  detail.TABS = TABS;
  detail.TAB_IDS = TAB_IDS;
  detail.DEFAULT_TAB = DEFAULT_TAB;
  detail.header = headerHtml;
  detail.links = headerLinks;
  detail.panels = PANELS;
  detail.envFields = envFields;
  detail.envMatrix = envMatrix;
  detail.rowById = rowById;
  // The building blocks, for a surface that lays the same facts out another
  // way (the component page's environment matrix) without restyling them.
  detail.helpers = {
    esc, DASH, list, filled, mono, note, ext, clip, drow, dl, stack, disclosure, longList,
    sections, heading, caption, muted, table, dot, ago, yesNo, metalRule,
  };
})();
