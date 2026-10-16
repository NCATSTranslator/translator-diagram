/*
  The Component view: one component on a page of its own, every section at
  once, chosen from a picker so a reader can move between components without
  going back to the table. It replaced a 440px side drawer whose six tabs did
  not fit and which was too narrow to read an environment side by side with
  another. It renders from the row object rather than from anything the table
  computed, so a field the table drops at 800px is still here.

  Two rules run through the whole file.

  Every value is optional. A build made from an older sync cache, or a public
  build with a policy applied, is missing whole blocks (`catalog_edges`,
  `repository_meta`, `smartapi_record`, half of `helm_charts[].last_changed`),
  and a section that throws on one absent key must not take the page with it.
  So nothing here indexes without a guard and nothing assumes a list is a list.

  And a fact is never shown without its provenance. A Helm chart says what
  *should* run; `derived_rejected` says a conventional hostname did not answer,
  not that a service is down; `uptime` belongs to a SmartAPI record, not to an
  environment. Each of those carries its label in the markup beside it, and
  every document a fact was read from is linked, so a reader who doubts a
  value can open where it came from.
*/

(() => {
  "use strict";

  const TD = (globalThis.TD = globalThis.TD || {});
  const view = (TD.component = TD.component || {});

  const WIKI_BASE = "https://github.com/NCATSTranslator/Translator-All/wiki/";
  // ponytail: the catalog lives in this repository on `main`; a fork that
  // publishes its own page would need this to come from the payload instead.
  const CATALOG_BASE = "https://github.com/NCATSTranslator/translator-diagram";
  const LIST_LIMIT = 8;

  /* --- Small helpers ------------------------------------------------------- */

  const esc = (value) => TD.fmt.esc(value);
  const DASH = TD.fmt.DASH;

  const data = () => TD.DATA || {};
  const envs = () => (Array.isArray(TD.ENVS) && TD.ENVS.length ? TD.ENVS : []);
  const rows = () => data().rows || [];
  const rowById = (id) => TD.row.byId(id);

  const list = (value) => (Array.isArray(value) ? value.filter((v) => v != null) : []);
  const filled = (value) => value !== null && value !== undefined && value !== "";

  const mono = (value) => `<span class="dw-mono">${esc(value)}</span>`;
  const note = (text) => `<span class="dw-note">${esc(text)}</span>`;

  /* A value as text, or nothing: what most rows of a definition list are. */
  const val = (value) => (filled(value) ? esc(value) : "");

  /* The parts that are there, with a middle dot between them: text, which
     note() escapes. joinHtml is the same thing escaped, for a template that
     does not escape; handing note() the HTML one shows an `&` in a tag as
     `&amp;` (#87), so the name says which is which. */
  const dotJoin = (parts) => parts.filter(filled).join(" · ");
  const joinHtml = (parts) => esc(dotJoin(parts));

  /* A list of small-caps tags, or nothing. */
  const tags = (items) =>
    items.map((item) => `<span class="dw-tag">${esc(item)}</span>`).join("");

  /* Every link out of this page opens in its own tab: the page holds the
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

  /* A definition-list row. Absent by default, because a page that prints a
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

  /* "5 › show": the count beside a disclosure of the items themselves, for a
     list that is usually read as a number and occasionally as a list. */
  function counted(items, summary) {
    if (!items.length) return "";
    return `${items.length} ${disclosure(summary, stack(items))}`;
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
    // What this page knows about the component that nobody upstream told it:
    // the catalog file, and where to correct it.
    const file = catalogUrls(row.id);
    links.push(ext(file.view, "Catalog file"), ext(file.edit, "Edit catalog file"));
    return links.length ? `<div class="dw-links">${links.join("")}</div>` : "";
  }

  /* The component's own file in catalog/components/, on GitHub, to read and to
     edit. A component's id is its file's name (tests/test_component_files.py
     holds that), so the id alone is enough. */
  function catalogUrls(id) {
    const path = `catalog/components/${encodeURIComponent(id)}.yaml`;
    return { view: `${CATALOG_BASE}/blob/main/${path}`, edit: `${CATALOG_BASE}/edit/main/${path}` };
  }

  /* The catalog's `summary`, else GitHub's one-liner for the repository: the
     shortest true sentence about what this thing is. The catalog's wins
     because a repository's blurb can describe the repository rather than the
     service (docmetadata-api's reads as a fork request). */
  function blurbFor(row) {
    const summary = (row || {}).summary;
    if (filled(summary)) return summary;
    const description = ((row || {}).repository_meta || {}).description;
    return filled(description) ? description : "";
  }

  /* The upstream software this component is a deployment of -- "Jaeger",
     "MongoDB" -- when the catalog says the code is not ours, else "". */
  function thirdPartyText(row) {
    const block = (row || {}).third_party;
    return block && filled(block.software) ? String(block.software) : "";
  }

  function headerHtml(row) {
    const blurb = blurbFor(row);
    const meta = joinHtml([row.refactor_status, row.hosted_at, row.component_type || row.type,
      row.layer, thirdPartyText(row) ? "third-party" : ""]);
    return `<div class="dw-headtop">
        <div class="dw-name">${TD.owner.coin(row.owner)}<h2>${esc(row.name || row.id)}</h2></div>
      </div>
      <div class="dw-id">${esc(row.id)}</div>
      ${blurb ? `<div class="dw-blurb clamp-2">${esc(blurb)}</div>` : ""}
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
      const label = TD.row.repoLabel(repo.url);
      const bits = dotJoin([repo.role, repo.visibility && repo.visibility !== "public" ? repo.visibility : ""]);
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
    const label = TD.row.updatedLabel(updated);
    const bits = dotJoin([label, updated.tag]);
    return `${esc(TD.fmt.relativeAge(updated.at) || updated.date || "")} ${
      bits ? note(bits) : ""}`;
  }

  function repoMetaHtml(row) {
    const meta = row.repository_meta;
    if (!meta) return "";
    const topics = list(meta.topics);
    // Description is deliberately absent: it is the header's subtitle now, and
    // printing it twice on one page is the kind of padding this page avoids.
    return dl([
      drow("Default branch", meta.default_branch ? mono(meta.default_branch) : ""),
      drow("Last push", meta.pushed_at ? ago(meta.pushed_at) : ""),
      drow("Archived", meta.archived ? "yes" : ""),
      drow("Licence", val(meta.license)),
      drow("Open issues", val(meta.open_issues)),
      drow("Stars", val(meta.stars)),
      drow("Homepage", ext(meta.homepage)),
      drow("Topics", tags(topics)),
    ]);
  }

  function panelOverview(row) {
    const itrb = row.itrb || {};
    const record = row.smartapi_record;

    const typeValue = row.component_type || row.type;
    const typeExtra = row.type && row.component_type && row.type !== row.component_type
      ? ` ${note(`registry reads ${row.type}`)}` : "";

    const stage = joinHtml([row.step_label, row.step_title]);

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

    // Software we deploy but did not write. Saying whose it is beside the
    // name is what stops the Releases and Repositories below reading as
    // claims about code of ours.
    const software = thirdPartyText(row);
    const softwareUrl = software ? (row.third_party || {}).url : "";
    const softwareHtml = software
      ? `${softwareUrl ? ext(softwareUrl, software) : esc(software)} ${
        note("third-party; only the deployment is ours")}`
      : "";

    const identity = dl([
      drow("Type", typeValue ? esc(typeValue) + typeExtra : "", true),
      drow("Software", softwareHtml),
      drow("Layer", val(row.layer), true),
      drow("Stage", stage ? `${stage}${row.step_description
        ? `<span class="dw-sub">${esc(row.step_description)}</span>` : ""}` : "", true),
      drow("Owner", row.owner ? TD.row.ownerLabel(row.owner) : "", true),
      drow("Part of", val(row.part_of)),
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
      // here is what stops that reading as a missing node. The wording is
      // #51's (7fb4520); this said "drawn beside each caller", which is the
      // Graphviz picture, not the web map.
      drow("On the map", (row.diagram || {}).ubiquitous
        ? `on the rail at the right, edges hidden by default ${note("ubiquitous")}` : ""),
    ]);

    const meta = repoMetaHtml(row);

    // What the component is, then what is odd about our record of it: the
    // catalog's `description` and `notes` answer those two questions, which
    // is why the notes carry a heading and the description does not.
    return sections([
      row.description ? `<div class="dw-prose dw-desc">${TD.fmt.prose(row.description)}</div>` : "",
      row.notes
        ? `<div class="dw-notes">${heading("Notes")}<p class="dw-prose">${esc(row.notes)}</p></div>`
        : "",
      identity,
      meta ? heading("Repository") + meta : "",
    ]);
  }

  /* --- Environments ----------------------------------------------------- */

  /* One column per environment and one row per fact, so a reader compares
     dev with prod along a line rather than matching four lists by eye. It is
     the table's expanded row at full width, built on the same model
     (TD.cell), so the two cannot disagree; the first row is the table's own
     cell. What the table has no room for comes after: the full address of
     every document a fact was read from, and the TRAPI operations by name. */
  function factHtml(fact) {
    if (!fact) return DASH;
    const text = fact.mono ? esc(fact.value).replace(/\./g, ".<wbr>") : esc(fact.value);
    const value = fact.href
      ? `<a class="dw-link" href="${esc(fact.href)}" target="_blank" rel="noopener">${text}</a>`
      : text;
    const src = fact.src ? ` <span class="src" data-src="${esc(fact.src)}">${esc(sourceLabel(fact.src))}</span>` : "";
    return `${value}${src}${fact.note ? ` ${note(fact.note)}` : ""}`;
  }

  const helpButton = (row, label) =>
    `<button type="button" class="help" data-tip="fact" data-id="${esc(row.id)}"
      data-fact="${esc(label)}" aria-label="Where ${esc(label)} comes from">?</button>`;

  function urlCell(url) {
    if (!filled(url)) return DASH;
    return ext(url, url, "dw-link dw-mono dw-url");
  }

  function envMatrix(row) {
    const names = envs();
    if (!names.length) return muted("This build names no environments.");
    const cells = row.environments || {};
    const models = Object.fromEntries(names.map((env) => [env, TD.cell(row, env)]));
    const labels = [];
    for (const env of names) {
      for (const fact of models[env].facts) {
        if (labels.indexOf(fact.label) < 0) labels.push(fact.label);
      }
    }
    const line = (label, cellsHtml, help) =>
      `<tr><th scope="row">${esc(label)}${help ? helpButton(row, label) : ""}</th>${cellsHtml}</tr>`;
    const across = (fn) => names.map((env) => `<td>${fn(env)}</td>`).join("");
    const any = (key) => names.some((env) => filled((cells[env] || {})[key]));

    const body = [
      line("Version", names.map((env) => TD.table.envCell(row, env)).join("")),
      ...labels.map((label) => line(label,
        across((env) => factHtml(models[env].facts.find((f) => f.label === label))), true)),
      any("url") ? line("Address", across((env) => urlCell((cells[env] || {}).url))) : "",
      any("openapi_url") ? line("API document URL", across((env) => urlCell((cells[env] || {}).openapi_url))) : "",
      any("status_url") ? line("Status page URL", across((env) => urlCell((cells[env] || {}).status_url))) : "",
      names.some((env) => list((cells[env] || {}).trapi_operations).length)
        ? line("TRAPI operations", across((env) =>
          counted(list((cells[env] || {}).trapi_operations).map(mono), "show") || DASH))
        : "",
    ].join("");

    return `<div class="dw-tscroll"><table class="cv-envs">
        <thead><tr><th></th>${names.map((env) => `<th scope="col">${esc(env)}</th>`).join("")}</tr></thead>
        <tbody>${body}</tbody></table></div>${rejectedHtml(row)}`;
  }

  function rejectedHtml(row) {
    const rejected = list(row.derived_rejected);
    if (!rejected.length) return "";
    return heading("Probed, not confirmed")
      + caption("a conventional hostname that did not confirm; not a claim that anything is down")
      + stack(rejected.map((entry) =>
        `<span class="dw-key">${esc(entry.env)}</span> ${ext(entry.url, entry.url, "dw-link dw-mono")}`));
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
      val(service.replicas),
      service.requests ? esc([service.requests.cpu, service.requests.memory].filter(filled).join(" / ")) : "",
      service.limits ? esc([service.limits.cpu, service.limits.memory].filter(filled).join(" / ")) : "",
    ]);
    const deps = list(chart.dependencies).map((dep) => [
      dep.name ? mono(dep.name) : "",
      val(dep.version),
      dep.repository ? clip(dep.repository) : "",
    ]);
    const storage = list(chart.storage).map((entry) => [
      entry.name ? mono(entry.name) : "",
      val(entry.size),
    ]);
    const hosts = list(chart.ingress_hosts);
    const changed = chart.last_changed;

    return heading(chart.chart || "chart") + dl([
      drow("Chart", chart.chart ? mono(chart.chart) : "", true),
      drow("Chart version", chart.chart_version ? mono(chart.chart_version) : "", true),
      drow("app version, from the chart", chart.app_version ? mono(chart.app_version) : "", true),
      drow("Description", val(chart.description)),
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
          val(c.title)}`));
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
      drow("Title", val(record.title), true),
      drow("Version", record.version ? mono(record.version) : ""),
      drow("Team", teams.length ? esc(teams.join(", ")) : ""),
      drow("Component", val(record.component)),
      drow("infores", record.infores ? mono(record.infores) : ""),
      drow("Biolink version", record.biolink_version ? mono(record.biolink_version) : ""),
    ]);

    const trapiBlock = heading("TRAPI") + dl([
      drow("Version", trapi.version ? mono(trapi.version) : "", true),
      drow("Async query", yesNo(trapi.asyncquery)),
      drow("Batch size limit", val(trapi.batch_size_limit)),
      drow("Rate limit", val(trapi.rate_limit)),
      drow("Test data", testData.length
        ? stack(testData.map(([maturity, url]) => `${esc(maturity)} ${ext(url, TD.fmt.host(url))}`)) : ""),
      drow("Operations", counted(operations.map(mono), `show all ${operations.length}`)),
    ]);

    const servers = list(record.servers).map((server) => {
      const under = joinHtml([server.location, server.description]);
      return [
        val(server.maturity),
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

    const recordTags = list(record.tags);
    const registration = heading("Registration") + dl([
      drow("Registered", meta.date_created ? ago(meta.date_created) : ""),
      drow("Last updated", meta.last_updated ? ago(meta.last_updated) : ""),
      drow("By", val(meta.username)),
      drow("Source", meta.source_url ? ext(meta.source_url, "the registration document") : ""),
      drow("Meta knowledge graph", yesNo(meta.has_metakg)),
      drow("Tags", tags(recordTags)),
      drow("Contact", [contact.name, contact.email, contact.url].filter(filled).length
        ? [
          val(contact.name),
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

  /* The chips of a connections group, or nothing. */
  const conns = (items) => (items.length ? `<div class="dw-conns">${items.join("")}</div>` : "");

  function connGroup(title, ids, plannedIds) {
    const items = list(ids).map((id) => connButton(id, false))
      .concat(list(plannedIds).map((id) => connButton(id, true)));
    return heading(title) + (conns(items) || muted("None recorded."));
  }

  /* Catalog edges follow the data (`build_catalog_edges`): what this
     component consumes is an edge *into* it, and its consumers are edges out.
     Getting the direction backwards once showed each list the other's
     components. */
  function catalogNeighbours(edges, id) {
    const consumes = [];
    const consumedBy = [];
    for (const edge of edges) {
      if (!edge) continue;
      if (edge.to === id) consumes.push(edge.from);
      if (edge.from === id) consumedBy.push(edge.to);
    }
    return { consumes, consumedBy };
  }

  function panelConnections(row) {
    const connections = row.connections || {};
    const all = rows();

    const reverse = (key) => all
      .filter((other) => other.id !== row.id
        && list((other.connections || {})[key]).indexOf(row.id) >= 0)
      .map((other) => other.id);

    const externalsHtml = conns(list(row.externals).map((entry) =>
      `<span class="dw-conn static">${TD.row.arrow(entry.direction)}
          <span class="dw-connname">${esc(entry.name)}</span></span>`)) || muted("None recorded.");

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
      const { consumes, consumedBy } = catalogNeighbours(catalogEdges, row.id);
      const facts = catalog ? dl([
        drow("Status", val(catalog.status)),
        drow("Knowledge level", val(catalog.knowledge_level)),
        drow("Agent type", val(catalog.agent_type)),
        drow("Description", val(catalog.description)),
        drow("Cross-references", list(catalog.xref).length
          ? stack(list(catalog.xref).map((x) => mono(x))) : ""),
      ]) : "";
      parts.push(heading("Catalog says")
        + caption("the infores catalog's view, beside what this repository records")
        + facts
        + (consumes.length
          ? `<div class="dw-sublabel">consumes</div>${
            conns(consumes.map((id) => connButton(id, false)))}` : "")
        + (consumedBy.length
          ? `<div class="dw-sublabel">consumed by</div>${
            conns(consumedBy.map((id) => connButton(id, false)))}` : "")
        + (!consumes.length && !consumedBy.length && !facts
          ? muted("Nothing recorded in the catalog for this component.") : ""));
    }

    if (row.isolated) {
      parts.unshift(caption("Nothing in this repository records a connection for this component."));
    }
    return sections(parts);
  }

  /* The sections under the environments, in reading order: what it is, how
     it is registered, what it has released, what should be deployed, and
     what it talks to. */
  const PANELS = [
    { id: "overview", label: "Overview", render: panelOverview },
    { id: "smartapi", label: "SmartAPI", render: panelSmartapi },
    { id: "releases", label: "Releases", render: panelReleases },
    { id: "helm", label: "Helm", render: panelHelm },
    { id: "connections", label: "Connections", render: panelConnections },
  ];

  /* One malformed field must cost its section, not the page: this is a
     reading surface over data fetched from six upstreams. */
  function panelHtml(row, panel, wide) {
    let html;
    try {
      html = panel.render(row);
    } catch (error) {
      html = muted(`This section could not be rendered for ${row.id}.`);
      if (typeof console !== "undefined") console.error(`component ${panel.id}:`, error);
    }
    return `<section class="cv-panel${wide ? " wide" : ""}" id="cv-${panel.id}"
      aria-labelledby="cv-${panel.id}-h"><h2 class="cv-ph" id="cv-${panel.id}-h">${
      esc(panel.label)}</h2>${html}</section>`;
  }

  /* --- The picker --------------------------------------------------------- */

  /* The components grouped by stage, in the payload's order, which is the
     table's order before anyone sorts it: so a stage reads the same in the
     picker as it does in the bands. */
  function pickerGroups(all) {
    const groups = [];
    for (const row of all) {
      const numbered = row.step_label && row.step_title && row.step_label !== row.step_title;
      const label = numbered ? `${row.step_label}: ${row.step_title}` : row.step_title || row.step_label || "";
      if (!groups.length || groups[groups.length - 1].label !== label) groups.push({ label, rows: [] });
      groups[groups.length - 1].rows.push(row);
    }
    return groups;
  }

  /* A native <select>: type-to-find, the keyboard and a phone's own picker,
     none of which a listbox here would have without writing them. */
  function pickerHtml(current) {
    const known = !!rowById(current);
    const option = (row) =>
      `<option value="${esc(row.id)}"${row.id === current ? " selected" : ""}>${esc(row.name || row.id)}</option>`;
    const groups = pickerGroups(rows()).map((group) => group.label
      ? `<optgroup label="${esc(group.label)}">${group.rows.map(option).join("")}</optgroup>`
      : group.rows.map(option).join(""));
    return `<label class="cv-pick"><span class="cv-picklabel">Component</span><select id="cv-select">${
      known ? "" : '<option value="" selected disabled>Choose a component…</option>'}${groups.join("")}</select></label>`;
  }

  /* --- The page ----------------------------------------------------------- */

  function pageHtml(id) {
    const row = rowById(id);
    const bar = `<div class="cv-bar">${pickerHtml(id)}
      ${row ? `<span class="spacer"></span>
        <button type="button" class="btn" id="cv-copy">Copy link</button>
        <button type="button" class="btn" id="cv-map">Show on map</button>` : ""}</div>`;
    if (!row) {
      return bar + muted(id
        ? `No component has the id ${id}. Choose one above.`
        : "Choose a component above, or click a component's name in the Overview or a node on the Map.");
    }
    return `${bar}<header class="cv-head">${headerHtml(row)}</header>
      <section class="cv-panel wide" id="cv-environments" aria-labelledby="cv-environments-h">
        <h2 class="cv-ph" id="cv-environments-h">Environments</h2>${envMatrix(row)}</section>
      <div class="cv-cols">${PANELS.map((panel) => panelHtml(row, panel)).join("")}</div>`;
  }

  let host = null;
  let shown = null;

  function bind(container) {
    host = container;
    container.addEventListener("click", (event) => {
      const disc = event.target.closest("[data-disc]");
      if (disc) {
        const expanded = disc.getAttribute("aria-expanded") === "true";
        disc.setAttribute("aria-expanded", expanded ? "false" : "true");
        return;
      }
      const go = event.target.closest("[data-go]");
      if (go) {
        event.preventDefault();
        if (rowById(go.dataset.go)) TD.navigate({ sel: go.dataset.go });
        return;
      }
      if (event.target.closest("#cv-map")) { TD.navigate({ view: "map" }); return; }
      const copy = event.target.closest("#cv-copy");
      if (copy) copyLink(copy);
    });
    container.addEventListener("change", (event) => {
      if (event.target.id === "cv-select" && event.target.value) {
        TD.navigate({ sel: event.target.value });
      }
    });
    TD.ui.tooltip.bind(container, "[data-tip]", (target) => {
      const kind = target.dataset.tip;
      // The table's kinds (an environment cell, a fact's (?), a source label)
      // read the same here as there; "say" and "1" are this page's own.
      if (kind !== "say" && kind !== "1") return TD.table.tipHtml(target);
      const full = target.dataset.full || target.textContent || "";
      // data-tip="say" carries a sentence the element does not show; "1" is a
      // truncation tooltip, and declines to repeat text already legible.
      if (kind === "say") return esc(full);
      if (target.scrollWidth <= target.clientWidth + 1) return "";
      return esc(full);
    });
  }

  async function copyLink(button) {
    try {
      await navigator.clipboard.writeText(location.href);
      button.textContent = "Copied";
    } catch {
      button.textContent = "Press ⌘C";
    }
    setTimeout(() => { button.textContent = "Copy link"; }, 3000);
  }

  /* Redrawn only when the component changes: app.js renders the shown view on
     every commit, and a page that rebuilt itself would close every disclosure
     the reader had opened and lose their scroll. */
  view.render = function render(container) {
    if (host !== container) bind(container);
    const id = (TD.state && TD.state.sel) || "";
    if (id === shown && container.firstChild) return;
    shown = id;
    container.innerHTML = pageHtml(id);
    container.scrollTop = 0;
  };

  // For tests/web/component.test.js; nothing on the page calls these from outside.
  view.blurbFor = blurbFor;
  view.thirdPartyText = thirdPartyText;
  view.catalogNeighbours = catalogNeighbours;
  view.catalogUrls = catalogUrls;
  view.deployedIn = deployedIn;
  view.docLabel = docLabel;
  view.pickerGroups = pickerGroups;
  view.pageHtml = pageHtml;
  view.updatedHtml = updatedHtml;
})();
