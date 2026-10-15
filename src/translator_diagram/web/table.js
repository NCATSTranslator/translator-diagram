/*
  The Overview view: one row per component, in stages.

  COLUMNS is the single source for every column. Four things have to agree
  about each one — the header cell, the body cell, the class that hides both
  at narrow widths, and how it sorts — and three of them used to be written
  out twice, which is how a header ends up hidden without its column.

  Every fact about an environment cell comes from TD.cell (core.js): the cell,
  its tooltip and the expanded row read one model, so they cannot disagree
  about a version or a reason. What this file decides is presentation — which
  state a cell is in, and so which tint it gets — and the two ideas inherited
  from the page this replaces: every filter round-trips through the URL, so a
  view can be pasted into Slack and arrive as the sender saw it; and a value
  in the minority across environments is marked, with a ≠ and an aria-label
  as well as a tint, so drift is visible to a reader who cannot see colour
  (issue #28).
*/

(() => {
  "use strict";

  const TD = (globalThis.TD = globalThis.TD || {});
  const table = (TD.table = TD.table || {});
  const esc = (value) => TD.fmt.esc(value);
  const DASH = () => TD.fmt.DASH;
  const state = () => TD.state;

  /* --- Which rows ---------------------------------------------------------- */

  const cells = (row) => row.environments || {};

  function hasDrift(row) {
    return TD.ENVS.some((env) => ((cells(row)[env] || {}).drift || []).length > 0);
  }

  function knownVersions(row) {
    return new Set(TD.ENVS.map((env) => (cells(row)[env] || {}).version).filter(Boolean));
  }

  /* One control rather than a "drift only" toggle beside a version filter: the
     two would have said the same thing about the same rows, and a reader
     cannot tell overlapping filters apart.

     The page opens on all of them. It used to open on "Environments
     disagree", which showed seven rows of twenty-four and hid the platform to
     make a point about drift — a reader who came to look up one component
     found it missing from a page that had not said it was filtered.

     "Environments disagree" is any of the three tinted axes, not versions
     alone: a component whose version matches everywhere while its TRAPI
     version does not is exactly as interesting. */
  const VERSION_VIEWS = {
    all: { label: "All components", test: () => true },
    differ: { label: "Environments disagree", test: hasDrift },
    known: { label: "Any version known", test: (row) => knownVersions(row).size > 0 },
    none: { label: "No version known", test: (row) => knownVersions(row).size === 0 },
  };
  const DEFAULT_VIEW = "all";

  /* Everything the search box can match on a row, lowercased and joined once.
     Keyed by the row object, so a keystroke does not rebuild twenty-seven
     arrays, and dropped whenever TD.ENVS changes: the versions in it are read
     per environment, and a payload can reuse its rows with a different list. */
  let haystacks = new WeakMap();
  let haystackEnvs = null;

  function haystack(row) {
    if (haystackEnvs !== TD.ENVS) {
      haystacks = new WeakMap();
      haystackEnvs = TD.ENVS;
    }
    let text = haystacks.get(row);
    if (text === undefined) {
      text = [
        row.id, row.name, row.owner, row.infores, row.summary,
        row.helm_chart, (row.last_updated || {}).date, ...(row.otel_services || []),
        ...(row.releases || []).map((release) => release.tag),
        ...TD.ENVS.map((env) => (cells(row)[env] || {}).version),
        ...TD.ENVS.map((env) => (cells(row)[env] || {}).data_release),
      ].map((value) => String(value ?? "").toLowerCase()).join("\n");
      haystacks.set(row, text);
    }
    return text;
  }

  function visibleRows() {
    const s = state();
    const needle = (s.q || "").trim().toLowerCase();
    const owners = s.owner || [];
    return (TD.DATA.rows || [])
      .filter((row) => !owners.length || owners.indexOf(row.owner) >= 0)
      .filter((VERSION_VIEWS[s.versions] || VERSION_VIEWS[DEFAULT_VIEW]).test)
      .filter((row) => !needle || haystack(row).includes(needle));
  }

  /* --- Cells --------------------------------------------------------------- */

  const link = (url, html, cls) => {
    const safe = TD.fmt.href(url);
    return safe
      ? `<a${cls ? ` class="${cls}"` : ""} href="${esc(safe)}" target="_blank" rel="noopener">${html}</a>`
      : cls ? `<span class="${cls}">${html}</span>` : html;
  };

  /* The dot, with its word for a reader who is not looking at it. */
  function reachDot(reach) {
    if (!reach) return "";
    return `<span class="dot ${reach}" aria-label="${
      reach === "up" ? "reachable" : "not reachable"}"></span>`;
  }

  /* Which of the board's states a cell is in. The tint carries this on
     screen; the words in the cell carry it everywhere else.

     "same" needs company: a component deployed in one environment agrees
     with nobody, and tinting it green read as a claim the row never made.
     "off" is the page's own gap (no address on file); an absence the page is
     sure of — no such host, no server listed, not a hosted service — is
     left white, because there is nothing to look at there. */
  function cellState(m, peers) {
    if (!m.deployed) return m.knownAbsent ? "none" : "off";
    if (m.reach === "down") return "down";
    if (!m.version) return "nov";
    if (m.drift.length) return "diff";
    return peers > 1 ? "same" : "one";
  }

  /* A cell with no version used to print a dash, which is the one thing this
     page exists not to do: a dash says "we have nothing" where the payload
     says *why* we have nothing — no address on file, no such host, no version
     endpoint to read, no server listed for this environment. The reason goes
     where the version would have been, in the payload's own words, and the
     green dot stays in front of it when the host itself answered. */
  function envCell(row, env) {
    if (!cells(row)[env]) return `<td class="env absent">${DASH()}</td>`;
    const m = TD.cell(row, env);
    const peers = TD.ENVS.filter((e) => TD.cell(row, e).version).length;
    const drift = m.drift.length ? " drift" : "";
    const classes = `env${drift} ${cellState(m, peers)}${m.flags.unregistered ? " unregistered" : ""}`;
    // The tint carries the signal on screen; aria-label carries it to a reader
    // who is not looking at one. A child span would extend the document: abs
    // positioning inside a table cell does not stay inside the scrollport.
    const driftLabel = drift ? ' aria-label="disagrees with the row"' : "";
    const tip = `data-tip="env" data-id="${esc(row.id)}" data-env="${esc(env)}"`;
    const dot = reachDot(m.reach);

    if (!m.version) {
      const why = m.reason ? `<span class="why">${esc(m.reason)}</span>` : DASH();
      return `<td class="${classes}"${driftLabel} ${tip}>${dot}${why}</td>`;
    }

    // The version links to the document it was read from, so a reader who
    // doubts it can open that document in a new tab. A copied value — from
    // the registry or the chart, not the running service — is drawn as a
    // dashed pill, so four identical registry values no longer read as four
    // services agreeing (issue #30).
    const pill = link(m.href, esc(m.version), `v${m.live ? "" : " copied"}`);
    const neq = drift
      ? `<span class="neq" aria-hidden="true" title="differs from the rest of this row on ${
          esc(m.drift.join(", "))}">≠</span>`
      : "";
    const second = [
      `<span class="src" data-src="${esc(m.source)}" data-tip="src">${esc(m.sourceShort)}</span>`,
      m.dataRelease ? `<span class="data">${esc(m.dataRelease)}</span>` : "",
      m.flags.inferred ? '<span class="inf">inferred</span>' : "",
      m.flags.unregistered ? '<span class="inf">not in SmartAPI</span>' : "",
    ].filter(Boolean).join('<span class="sep"> · </span>');
    return `<td class="${classes}"${driftLabel} ${tip}><span class="envline">${
      dot}${pill}${neq}</span><span class="l2">${second}</span></td>`;
  }

  /* A release as a chip, for the expanded row's strip and the tooltips. A
     release running somewhere is marked rather than merely listed; that mark
     is the link between the strip and the four environment columns. */
  function releaseChip(row, release) {
    return `<a class="rel${release.deployed ? " deployed" : ""}${release.prerelease ? " pre" : ""}"
      href="${esc(TD.fmt.href(release.url) || "#")}" target="_blank" rel="noopener"
      data-tip="rel" data-id="${esc(row.id)}" data-tag="${esc(release.tag)}">${esc(release.tag)}</a>`;
  }

  /* The repository, and under it the newest release and when: that date used
     to be a column of its own, and it belongs beside the thing it dates. */
  function repoCell(row) {
    if (!row.repository) return `<td class="repo drop-md">${DASH()}</td>`;
    const updated = row.last_updated;
    const released = updated && updated.source === "release"
      ? `<span class="l2" data-tip="upd" data-id="${esc(row.id)}"><span class="age">${
          esc(TD.fmt.relativeAge(updated.at))}</span> · ${esc(updated.tag || "release")}</span>`
      : "";
    return `<td class="repo drop-md">${link(row.repository, esc(TD.row.repoLabel(row.repository)))}${
      released}</td>`;
  }

  /* One registration usually covers every environment, so it is a column of
     its own rather than four facts: whether the component is registered at
     all, how the registry's own probe finds it, and when the record last
     changed. */
  function smartapiCell(row) {
    const record = row.smartapi_record;
    if (!record) {
      const candidates = (row.smartapi_candidates || []).length;
      return `<td class="sapi drop-sm"><span class="why">${
        candidates ? `${candidates} possible records` : "not registered"}</span></td>`;
    }
    const uptime = record.status && record.status.uptime_status;
    const dot = uptime
      ? `<span class="dot ${uptime === "pass" ? "up" : "down"}" aria-label="registry probe: ${esc(uptime)}"></span>`
      : "";
    const changed = row.last_updated && row.last_updated.source === "registry"
      ? `<span class="l2" data-tip="upd" data-id="${esc(row.id)}">changed <span class="age">${
          esc(TD.fmt.relativeAge(row.last_updated.at))}</span></span>`
      : "";
    return `<td class="sapi drop-sm">${dot}${link(record.registry_url, "registered")}${changed}</td>`;
  }

  /* The name on the first line and, under it, the summary; the id joins the
     second line only when the row is open, because it is the key a link or a
     search uses rather than a thing to read down a column. */
  function componentCell(row) {
    const externals = (row.externals || [])
      .map((external) =>
        `<span class="chip">${TD.row.arrow(external.direction)} ${esc(external.name)}</span>`)
      .join("");
    const open = (state().expand || []).indexOf(row.id) >= 0;
    const summary = row.summary ? `<span class="csum">${esc(row.summary)}</span>` : "";
    return `<td><span class="cnamewrap"><button type="button" class="chev"
        aria-expanded="${open}" data-expand="${esc(row.id)}"
        aria-label="Environment detail for ${esc(row.name)}">${TD.ui.CHEVRON}</button>${
      TD.owner.coin(row.owner, "narrow")}<button type="button" class="cname"
        data-open="${esc(row.id)}">${esc(row.name)}</button>${externals}</span>
      <span class="csub"><span class="cid">${esc(row.id)}</span>${summary}</span></td>`;
  }

  function ownerCell(row) {
    return `<td class="drop-xs quiet">${TD.row.ownerLabel(row.owner)}</td>`;
  }

  /* --- Columns -------------------------------------------------------------- */

  const registryDate = (row) =>
    (row.last_updated && row.last_updated.source === "registry" ? row.last_updated.date : "")
    || ((row.smartapi_record || {}).meta || {}).last_updated || "";

  const COLUMNS = [
    { key: "name", label: "Component", cell: componentCell, value: (row) => row.name },
    {
      key: "owner", label: "Owner", drop: "drop-xs", cell: ownerCell,
      value: (row) => row.owner, band: (row) => row.owner,
    },
    {
      key: "repo", label: "Repository", drop: "drop-md", cell: repoCell,
      value: (row) => TD.row.repoLabel(row.repository),
    },
    {
      key: "smartapi", label: "SmartAPI", drop: "drop-sm", cell: smartapiCell,
      value: registryDate,
      compare: TD.sort.byDate, prefer: "asc", words: ["oldest first", "newest first"],
      hint: "Sort by when the SmartAPI registration last changed",
    },
  ];

  function buildColumns() {
    COLUMNS.length = 4;
    for (const env of TD.ENVS) {
      COLUMNS.push({
        key: `env-${env}`, label: env, env, headerCls: "env",
        cell: (row) => envCell(row, env),
        value: (row) => (cells(row)[env] || {}).released || "",
        rank: (row) => TD.sort.envRank(row, env),
        compare: TD.sort.byDate, prefer: "asc", words: ["oldest first", "newest first"],
        hint: `Sort by the age of the release running in ${env}`,
      });
    }
  }

  const sortColumn = () => COLUMNS.find((column) => column.key === state().sort);

  /* What a click on a column header does to the sort: the column's preferred
     direction first, then the other, then home. The third click goes home
     because without it stage order — the order the page is built to argue
     for — would be unreachable once you left it. */
  function nextSort(s, column) {
    const preferred = column.prefer || "asc";
    if (s.sort !== column.key) return { sort: column.key, dir: preferred };
    if (s.dir === preferred) return { dir: preferred === "asc" ? "desc" : "asc" };
    return { sort: "", dir: "asc" };
  }

  /* --- Bands ---------------------------------------------------------------- */

  /* What the rows are grouped under, or null for an order that has no groups.
     Data flow gets bands because the order is otherwise invisible; owner gets
     them because that is what "sorted by owner" means. Dates and environments
     get none — every row is its own group. */
  function bandKey() {
    const column = sortColumn();
    if (!column) return (row) => row.step_label;
    return column.band || null;
  }

  /* A band names its group and, in stage order, says what the group is for.
     The number alone was true and useless: "Step 6" tells a reader where the
     rows sit, not what they do. Both come from catalog/flow-steps.yaml.

     It is a section row, not a data row, and everything in it is on the
     left: a count pushed to the right edge landed under the `prod` column and
     read as a value in it. The group's rows carry the same `data-step`. */
  function bandHtml(group) {
    const first = group.rows[0];
    const flow = !sortColumn();
    // The unplaced band's label *is* its title, so it says its name once
    // rather than "Not yet placed · Not yet placed".
    const numbered = first.step_label && first.step_label !== first.step_title;
    const step = flow && numbered ? `<span class="band-step">${esc(first.step_label)}</span>` : "";
    const title = flow && first.step_title ? first.step_title : group.label;
    const description = flow && first.step_description
      ? `<span class="band-note drop-md">${esc(first.step_description)}</span>`
      : "";
    const count = TD.fmt.plural(group.rows.length, "component");
    return `<tr class="band" data-step="${esc(group.label)}"><td colspan="${COLUMNS.length}"
      ><span class="band-inner">${step}<span class="band-title">${esc(title)}</span><span
      class="band-count">${esc(count)}</span>${description}</span></td></tr>`;
  }

  /* --- Row expansion --------------------------------------------------------- */

  /* The expansion is not a panel under the row: it is more rows of the same
     table, one per fact, and every value sits in the column of the
     environment it belongs to. That column alignment is the whole point — a
     free-standing grid made a reader match "ci" to "ci" by eye, four times,
     for every field.

     The label sits in the first column, which is sticky, and the other
     non-environment columns are empty cells carrying that column's drop
     class, so they leave the table with their column. A colspan cannot do
     this: a hidden cell generates no box, so a colspan row keeps claiming the
     columns that have gone and shifts every value one column right.

     Version is deliberately absent: it is the row directly above. */
  const fillers = () => COLUMNS
    .filter((column) => !column.env && column.key !== "name")
    .map((column) => `<td class="${column.drop || ""}"></td>`)
    .join("");

  function detailAttrs(row, group, flags) {
    const classes = ["detail"].concat(
      group == null ? [] : ["grp"],
      flags.first ? ["detail-first"] : [],
      flags.last ? ["detail-last"] : [],
      flags.cls ? [flags.cls] : [],
    );
    return `class="${classes.join(" ")}" data-for="${esc(row.id)}"${
      group == null ? "" : ` data-step="${esc(group)}"`}`;
  }

  function factCell(fact) {
    if (!fact) return `<td class="dv"></td>`;
    const text = fact.mono ? esc(fact.value).replace(/\./g, ".<wbr>") : esc(fact.value);
    const note = fact.note ? `<span class="n">${esc(fact.note)}</span>` : "";
    return `<td class="dv${fact.mono ? " mono" : ""}">${link(fact.href, text)}${note}</td>`;
  }

  /* `releases` is a slice of `releases_detail` (see `_release_chips`), so the
     expanded strip and the tooltips read the full list and nothing else. */
  function releaseChipsAll(row) {
    return (row.releases_detail || []).map((release) => releaseChip(row, release)).join("");
  }

  /* Only the facts some environment answered, each in its environment's
     column. The releases go under Repository, where the repository is, so
     that row leaves the table with the column. */
  function detailRowsHtml(row, group) {
    const models = Object.fromEntries(TD.ENVS.map((env) => [env, TD.cell(row, env)]));
    const labels = [...new Set(TD.ENVS.flatMap((env) => models[env].facts.map((f) => f.label)))];
    const make = labels.map((label) => (flags) =>
      `<tr ${detailAttrs(row, group, flags)}><td class="dk">${esc(label)}</td>${fillers()}${
        TD.ENVS.map((env) => factCell(models[env].facts.find((f) => f.label === label))).join("")
      }</tr>`);
    const chips = releaseChipsAll(row);
    if (chips) {
      make.push((flags) => `<tr ${detailAttrs(row, group, { ...flags, cls: "drop-md" })}><td class="dk">Releases</td>${
        COLUMNS.filter((column) => !column.env && column.key !== "name")
          .map((column) => `<td class="${column.drop || ""}${column.key === "repo" ? " rels" : ""}">${
            column.key === "repo" ? chips : ""}</td>`).join("")
      }${TD.ENVS.map(() => `<td class="dv"></td>`).join("")}</tr>`);
    }
    if (!make.length) {
      make.push((flags) => `<tr ${detailAttrs(row, group, flags)}><td class="dk"></td>${fillers()}<td
        class="dv note" colspan="${TD.ENVS.length}">Nothing else is recorded for this component.</td></tr>`);
    }
    return make
      .map((build, index) => build({ first: index === 0, last: index === make.length - 1 }))
      .join("");
  }

  /* Everything the chevron opened, in document order. Walked rather than
     queried, because an id is not a safe CSS selector and the rows are always
     the ones straight after their own. */
  function detailRowsAfter(tr) {
    const found = [];
    let next = tr && tr.nextElementSibling;
    while (next && next.classList.contains("detail")) {
      found.push(next);
      next = next.nextElementSibling;
    }
    return found;
  }

  /* --- Table body ------------------------------------------------------------ */

  /* `group` is the band this row sits under, or null in an order that has no
     bands (by date, by environment). */
  function rowHtml(row, group) {
    const open = (state().expand || []).indexOf(row.id) >= 0;
    const classes = ["row"];
    if (group != null) classes.push("grp");
    if (row.isolated) classes.push("isolated");
    if (state().sel === row.id) classes.push("sel");
    if (open) classes.push("open");
    const step = group == null ? "" : ` data-step="${esc(group)}"`;
    const body = `<tr class="${classes.join(" ")}" id="c-${esc(row.id)}" data-id="${esc(row.id)}"${
      step}>${COLUMNS.map((column) => column.cell(row)).join("")}</tr>`;
    return open ? body + detailRowsHtml(row, group) : body;
  }

  function bodyHtml(rows) {
    if (!rows.length) {
      return `<tr><td class="empty" colspan="${COLUMNS.length}"
        >No components match these filters.</td></tr>`;
    }
    const label = bandKey();
    if (!label) return rows.map((row) => rowHtml(row, null)).join("");
    // Grouped as they come, so a step filtered down to nothing leaves no empty
    // band, and a visible gap — Step 1, Step 2, Step 8 — reports honestly what
    // the filter took out.
    const groups = [];
    for (const row of rows) {
      if (!groups.length || groups[groups.length - 1].label !== label(row)) {
        groups.push({ label: label(row), rows: [] });
      }
      groups[groups.length - 1].rows.push(row);
    }
    return groups
      .map((group) =>
        bandHtml(group) + group.rows.map((row) => rowHtml(row, group.label)).join(""))
      .join("");
  }

  function headHtml() {
    return `<tr>${COLUMNS.map((column) => {
      const active = state().sort === column.key;
      const cls = [column.headerCls, column.drop].filter(Boolean).join(" ");
      // aria-sort drives the styling too, so what is announced and what is
      // shown cannot drift apart.
      const sorted = active ? (state().dir === "asc" ? "ascending" : "descending") : "none";
      const hint = column.hint || `Sort by ${column.label}`;
      return `<th class="${cls}" aria-sort="${sorted}"><button type="button" class="sortcol"
        data-col="${esc(column.key)}" title="${esc(hint)}">${esc(column.label)}${
        TD.ui.CARET_UP}</button></th>`;
    }).join("")}</tr>`;
  }

  function orderHtml() {
    const column = sortColumn();
    if (!column) return "Ordered by stage";
    const words = column.words || ["A to Z", "Z to A"];
    // The button is the only way back when a narrow window has hidden the
    // column whose header would otherwise complete the cycle.
    return `Sorted by ${esc(column.label)}, ${words[state().dir === "asc" ? 0 : 1]}
      <button type="button" id="unsort" title="Back to stage order"
        aria-label="Back to stage order">✕</button>`;
  }

  /* --- Tooltips -------------------------------------------------------------- */

  const rowById = (id) => TD.row.byId(id);

  const SOURCE_NOTES = {
    openapi: "Read live from the deployment's own OpenAPI document.",
    status: "Read live from the deployment's /status endpoint.",
    smartapi: "Copied from the SmartAPI registry, not from the running service.",
    helm: "From the Helm chart — what should be deployed, not what is.",
    release: "The newest GitHub release on this component's repository.",
    registry: "When this component's SmartAPI registration last changed.",
  };

  function tipHtml(target) {
    const kind = target.dataset.tip;
    if (kind === "src") {
      const key = target.dataset.src;
      return `<div><b>${esc(TD.fmt.sourceLabel(key))}</b></div><div class="note">${
        esc(SOURCE_NOTES[key] || "Where this value was read from.")}</div>`;
    }
    if (kind === "rel") {
      const row = rowById(target.dataset.id);
      if (!row) return "";
      const release = (row.releases_detail || []).find((entry) => entry.tag === target.dataset.tag);
      if (!release) return "";
      const where = release.deployed ? "Running in an environment on this row" : "";
      return `<div class="title">${esc(release.tag)}</div><dl>${
        release.name && release.name !== release.tag ? `<dt>name</dt><dd>${esc(release.name)}</dd>` : ""}${
        release.published ? `<dt>released</dt><dd>${esc(release.published)}</dd>` : ""}${
        release.prerelease ? "<dt>kind</dt><dd>pre-release</dd>" : ""}${
        release.author ? `<dt>author</dt><dd>${esc(release.author)}</dd>` : ""}</dl>${
        where ? `<div class="note">${esc(where)}</div>` : ""}${
        release.body_excerpt ? `<div class="note">${esc(release.body_excerpt)}</div>` : ""}`;
    }
    if (kind === "upd") {
      const row = rowById(target.dataset.id);
      const updated = row && row.last_updated;
      if (!updated) return "";
      // The three shepherds share one repository, so one release date lands on
      // three rows: without the tag that reads as three coincidental deploys.
      const what = updated.source === "release"
        ? `${updated.tag} released ${updated.date}`
        : `SmartAPI registration last changed ${updated.date}`;
      return `<div><b>${esc(what)}</b></div><div class="note">${
        esc(SOURCE_NOTES[updated.source] || "")}</div>`;
    }
    if (kind === "env") {
      const row = rowById(target.dataset.id);
      const env = target.dataset.env;
      if (!row) return "";
      const m = TD.cell(row, env);
      if (!m.deployed) return "";
      const pair = (term, value) => (value ? `<dt>${esc(term)}</dt><dd>${esc(value)}</dd>` : "");
      const note = m.flags.unregistered
        ? "Deployed, but absent from this component's SmartAPI record, which lists other environments."
        : "";
      return `<div class="title">${esc(row.id)} · ${esc(env)}</div><dl>${
        pair("version", m.version)}${
        pair("read from", m.version ? m.sourceWord : "")}${
        pair("status", m.reason)}${
        m.facts.map((f) => pair(f.label, f.note ? `${f.value} (${f.note})` : f.value)).join("")}</dl>${
        m.drift.length
          ? `<div class="note">Disagrees with the rest of this row on ${esc(m.drift.join(", "))}.</div>` : ""}${
        note ? `<div class="note">${esc(note)}</div>` : ""}`;
    }
    return "";
  }

  /* --- Expansion ------------------------------------------------------------- */

  function findRow(body, id) {
    return [...body.querySelectorAll("tr.row")].find((row) => row.dataset.id === id);
  }

  /* Opening does not re-render the table: it inserts this component's detail
     rows after its own and nothing else, so the chevron keeps focus. */
  function openExpansion(body, id) {
    const tr = findRow(body, id);
    const row = rowById(id);
    if (!tr || !row || tr.nextElementSibling?.classList.contains("detail")) return;
    // The band this row is under, read back off the row rather than passed in:
    // the click handler knows the id, not the grouping.
    const group = tr.classList.contains("grp") ? tr.dataset.step ?? "" : null;
    tr.insertAdjacentHTML("afterend", detailRowsHtml(row, group));
    tr.classList.add("open");
  }

  function closeExpansion(body, id) {
    const tr = findRow(body, id);
    for (const detail of detailRowsAfter(tr)) detail.remove();
    if (tr) tr.classList.remove("open");
  }

  /* --- Render ----------------------------------------------------------------- */

  let wrap = null;
  let head = null;
  let body = null;

  function build(container) {
    container.innerHTML = `<div class="tablewrap"><table class="grid">
      <thead></thead><tbody></tbody></table></div>`;
    wrap = container.querySelector(".tablewrap");
    head = container.querySelector("thead");
    body = container.querySelector("tbody");

    head.addEventListener("click", (event) => {
      const button = event.target.closest("button[data-col]");
      if (!button) return;
      TD.commit(nextSort(state(), COLUMNS.find((entry) => entry.key === button.dataset.col)));
    });

    body.addEventListener("click", (event) => {
      const chevron = event.target.closest("button[data-expand]");
      if (chevron) {
        const id = chevron.dataset.expand;
        const expand = (state().expand || []).slice();
        const at = expand.indexOf(id);
        if (at >= 0) { expand.splice(at, 1); closeExpansion(body, id); }
        else { expand.push(id); openExpansion(body, id); }
        chevron.setAttribute("aria-expanded", at < 0);
        TD.commit({ expand }, { silent: true });
        return;
      }
      const name = event.target.closest("button[data-open]");
      if (name) TD.drawer.open(name.dataset.open);
    });

    TD.ui.tooltip.bind(body, "[data-tip]", tipHtml);
  }

  table.render = function render(container) {
    table.ensureColumns();
    if (!wrap || !container.contains(wrap)) build(container);

    const rows = TD.sort.rows(visibleRows(), sortColumn(), state().dir);
    TD.ui.tooltip.hide();
    head.innerHTML = headHtml();
    body.innerHTML = bodyHtml(rows);
    return { shown: rows.length, total: (TD.DATA.rows || []).length };
  };

  table.ensureColumns = function ensureColumns() {
    if (!COLUMNS.some((column) => column.env)) buildColumns();
  };
  table.COLUMNS = COLUMNS;
  table.VERSION_VIEWS = VERSION_VIEWS;
  table.DEFAULT_VIEW = DEFAULT_VIEW;
  table.orderHtml = orderHtml;
  table.visibleRows = visibleRows;
  table.hasDrift = hasDrift;
  // Pure given TD.state and TD.DATA, for tests/web/table.test.js.
  table.nextSort = nextSort;
  table.cellState = cellState;
  table.envCell = envCell;
  table.bodyHtml = bodyHtml;
  table.detailRowsHtml = detailRowsHtml;
  table.scrollTo = function scrollTo(id) {
    if (!body) return;
    const tr = findRow(body, id);
    if (tr) tr.scrollIntoView({ block: "center", behavior: TD.motion.enabled ? "smooth" : "auto" });
  };

  /* The selected row's highlight, moved by hand: the drawer's commits are
     silent (a full re-render for a tab change is a lot of work for nothing),
     and the table paints `.sel` from TD.state only at render time. */
  table.markSelected = function markSelected(id) {
    if (!body) return;
    for (const row of body.querySelectorAll("tr.row")) {
      row.classList.toggle("sel", row.dataset.id === id);
    }
  };

  /* Scroll the table's own scrollport so the row sits just under the sticky
     header. Not scrollTo: scrollIntoView scrolls *every* ancestor scroller,
     the document included, and with the drawer open as a sheet that slid the
     whole page down and put the table behind the sheet. */
  table.revealRow = function revealRow(id) {
    if (!body || !wrap) return;
    const tr = findRow(body, id);
    if (!tr) return;
    const thead = wrap.querySelector("thead");
    const cover = thead ? thead.getBoundingClientRect().height : 0;
    const delta = tr.getBoundingClientRect().top - wrap.getBoundingClientRect().top;
    wrap.scrollTop += delta - cover - 8;
  };
})();
