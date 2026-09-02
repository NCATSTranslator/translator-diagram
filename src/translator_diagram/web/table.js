/*
  The Overview view: one row per component, in stages.

  COLUMNS is the single source for every column. Four things have to agree
  about each one — the header cell, the body cell, the class that hides both
  at narrow widths, and how it sorts — and three of them used to be written
  out twice, which is how a header ends up hidden without its column.

  Two ideas are inherited from the page this replaces because they are what
  make a table like this usable rather than merely correct: every filter
  round-trips through the URL, so a view can be pasted into Slack and arrive
  as the sender saw it; and a value in the minority across environments is
  marked, so drift is visible without reading every cell. The mark is the
  tint; issue #28's point — that colour alone excludes readers who cannot see
  it — is answered by a visually-hidden sentence in the cell and by the
  tooltip, not by a glyph printed over the version.
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

  function visibleRows() {
    const s = state();
    const needle = (s.q || "").trim().toLowerCase();
    const owners = s.owner || [];
    return (TD.DATA.rows || [])
      .filter((row) => !owners.length || owners.indexOf(row.owner) >= 0)
      .filter((VERSION_VIEWS[s.versions] || VERSION_VIEWS[DEFAULT_VIEW]).test)
      .filter((row) => {
        if (!needle) return true;
        const haystack = [
          row.id, row.name, row.owner, row.infores,
          row.helm_chart, (row.last_updated || {}).date, ...(row.otel_services || []),
          ...(row.releases || []).map((release) => release.tag),
          ...TD.ENVS.map((env) => (cells(row)[env] || {}).version),
        ];
        return haystack.some((value) => String(value ?? "").toLowerCase().includes(needle));
      });
  }

  /* --- Cells --------------------------------------------------------------- */

  function sourceLabel(key) {
    return (TD.DATA.source_labels || {})[key] || key;
  }

  /* A cell with no version used to print a dash, which is the one thing this
     page exists not to do: a dash says "we have nothing" where the payload
     now says *why* we have nothing — no host recorded, no such host, up but
     no version endpoint, not in the registry for this environment. The reason
     goes where the version would have been, in the payload's own words, and
     the green dot stays in front of it when the host itself answered, because
     "up · no version endpoint" is a claim about a host that is up. */
  function envCell(row, env) {
    const cell = cells(row)[env];
    if (!cell) return `<td class="env absent">${DASH()}</td>`;

    const drift = (cell.drift || []).length ? " drift" : "";
    const unregistered = cell.unregistered ? " unregistered" : "";
    // The tint carries the signal on screen; aria-label carries it to a reader
    // who is not looking at one. A child span would extend the document: abs
    // positioning inside a table cell does not stay inside the scrollport.
    const driftLabel = drift ? ' aria-label="disagrees with the row"' : "";
    const dot = typeof cell.reachable === "boolean"
      ? `<span class="dot ${cell.reachable ? "up" : "down"}" aria-label="${
          cell.reachable ? "reachable" : "not reachable"}"></span>`
      : "";
    // Weaker than the rest of the row and it says so: this environment was
    // read off a server description in the registry, not recorded anywhere.
    const inferred = cell.inferred
      ? '<span class="inf" data-tip="inferred">inferred</span>'
      : "";
    const tip = `data-tip="env" data-id="${esc(row.id)}" data-env="${esc(env)}"`;

    if (!cell.version) {
      const why = cell.reason
        ? `<span class="why">${esc(cell.reason)}</span>`
        : `<span class="version dash">—</span>`;
      const up = cell.reachable === true
        ? '<span class="dot up" aria-label="reachable"></span>'
        : "";
      return `<td class="env absent${drift}"${driftLabel} ${tip}><span class="envline">${
        up}${why}</span>${inferred}</td>`;
    }

    const version = `<span class="version">${esc(cell.version)}</span>`;
    const source = cell.version_source
      ? `<span class="src" data-src="${esc(cell.version_source)}" data-tip="src"
           >${esc(sourceLabel(cell.version_source))}</span>`
      : "";

    return `<td class="env${drift}${unregistered}"${driftLabel} ${tip}><span class="envline">${
      version}${dot}</span>${source}${inferred}</td>`;
  }

  /* The repository, then its latest releases — plus any older release an
     environment on this row is running, so the version in the table always has
     its notes one click away. A release running somewhere is marked rather
     than merely listed; that mark is the link between this column and the four
     to its right. */
  function releaseChips(row) {
    return (row.releases || [])
      .filter((release) => release.url)
      .map((release) =>
        `<a class="rel${release.deployed ? " deployed" : ""}${release.prerelease ? " pre" : ""}"
          href="${esc(release.url)}" data-tip="rel" data-id="${esc(row.id)}"
          data-tag="${esc(release.tag)}">${esc(release.tag)}</a>`)
      .join("");
  }

  function repoCell(row) {
    if (!row.repository) return `<td class="repo meta drop-md">${DASH()}</td>`;
    const label = row.repository.replace("https://github.com/", "");
    const chips = releaseChips(row);
    return `<td class="repo meta drop-md"><a href="${esc(row.repository)}">${esc(label)}</a>${
      chips ? `<span class="releases">${chips}</span>` : ""}</td>`;
  }

  function updatedCell(row) {
    const updated = row.last_updated;
    // Null for half the components — no releases, and in no registry. A dash
    // is the honest reading, not a failure.
    if (!updated) return `<td class="updated meta drop-sm">${DASH()}</td>`;
    const label = (TD.DATA.updated_labels || {})[updated.source] || updated.source;
    return `<td class="updated meta drop-sm" data-tip="upd" data-id="${esc(row.id)}"
      ><span class="age">${esc(TD.fmt.relativeAge(updated.at))}</span>
      <span class="src" data-src="${esc(updated.source)}">${esc(label)}</span></td>`;
  }

  function componentCell(row) {
    const externals = (row.externals || [])
      .map((external) =>
        `<span class="chip">${external.direction === "in" ? "◀" : "▶"} ${esc(external.name)}</span>`)
      .join("");
    const open = (state().expand || []).indexOf(row.id) >= 0;
    return `<td><span class="cnamewrap"><button type="button" class="chev"
        aria-expanded="${open}" data-expand="${esc(row.id)}"
        aria-label="Environment detail for ${esc(row.name)}">${TD.ui.CHEVRON}</button>${
      TD.owner.coin(row.owner, "narrow")}<button type="button" class="cname"
        data-open="${esc(row.id)}">${esc(row.name)}</button>${externals}</span>
      <span class="cid">${esc(row.id)}</span></td>`;
  }

  function ownerCell(row) {
    return `<td class="drop-xs"><span class="ownercell">${TD.owner.coin(row.owner)}<span>${
      esc(row.owner)}</span></span></td>`;
  }

  /* --- Columns -------------------------------------------------------------- */

  const COLUMNS = [
    { key: "name", label: "Component", cell: componentCell, value: (row) => row.name },
    {
      key: "owner", label: "Owner", drop: "drop-xs", cell: ownerCell,
      value: (row) => row.owner, band: (row) => row.owner,
    },
    {
      key: "repo", label: "Repository", drop: "drop-md", cell: repoCell,
      value: (row) => (row.repository || "").replace("https://github.com/", ""),
    },
    {
      key: "updated", label: "Last updated", drop: "drop-sm", cell: updatedCell,
      value: (row) => (row.last_updated || {}).date || "",
      compare: TD.sort.byDate, prefer: "asc", words: ["oldest first", "newest first"],
      hint: "Sort by when this component last changed",
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
     rows sit, not what they do. Both come from config/flow-steps.yaml.

     It is a header, not a row, and everything in it is on the left: a count
     pushed to the right edge landed under the `prod` column and read as a
     value in it. The whole header is pinned to the left of the scrollport, so
     a table scrolled sideways keeps it. The group's rows carry the same
     `data-step`, which is what the spine in table.css is hung on. */
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
     table, one per field, and every value sits in the column of the
     environment it belongs to. That column alignment is the whole point — a
     free-standing grid made a reader match "ci" to "ci" by eye, four times,
     for every field.

     Version is deliberately absent: it is the row directly above. So is the
     operations list, which belongs in the drawer; the count is enough here. */
  const DETAIL_FIELDS = [
    { label: "TRAPI", read: (cell) => esc(cell.trapi || "") },
    { label: "Biolink", read: (cell) => esc(cell.biolink || "") },
    { label: "Data release", read: (cell) => esc(cell.data_release || "") },
    { label: "Released", read: (cell) => esc(cell.released || ""), num: true },
    {
      // A hostname has no spaces, so a narrow column either clips it or
      // breaks it mid-label as "…transltr.i / o". A <wbr> after each dot
      // gives the browser the only break points a reader would accept.
      label: "Host",
      mono: true,
      read: (cell) => {
        const href = cell.openapi_url || cell.url;
        const name = esc(TD.fmt.host(cell.url)).replace(/\./g, ".<wbr>");
        return href ? `<a href="${esc(href)}">${name}</a>` : name;
      },
    },
    {
      // The document's status when there is one, the root's when there is
      // not: a component with no OpenAPI document still answered something,
      // and "no status at all" and "404 on the document" are different facts.
      label: "HTTP", num: true,
      read: (cell) => {
        const status = cell.http_status == null ? cell.root_status : cell.http_status;
        return status == null ? "" : esc(status);
      },
    },
    {
      label: "Reachable",
      read: (cell) => (typeof cell.reachable === "boolean" ? (cell.reachable ? "yes" : "no") : ""),
    },
    {
      label: "Paths", num: true,
      read: (cell) => (cell.paths_count == null ? "" : esc(cell.paths_count)),
    },
    {
      label: "Operations", num: true,
      read: (cell) => {
        const count = (cell.trapi_operations || []).length;
        return count ? String(count) : "";
      },
    },
  ];

  /* The label sits immediately left of the first environment column, so the
     word and the numbers it names touch. Which cell that is depends on the
     width — Repository, Last updated and Owner drop out in that order — so
     the label is written into every non-environment cell and CSS shows the
     rightmost one still on screen. A colspan cannot do this: it is a fixed
     number, the columns it covers come and go, and the first mismatch shifts
     every value one column left. */
  /* Every cell of a detail row wraps its content twice: `.dg` is a one-row
     grid that goes 0fr → 1fr, `.dw` clips. That is the only way a <tr> can
     change height on a curve, and it is why opening a row no longer shoves
     everything under it down in a single step. */
  const fold = (html) => `<div class="dg"><div class="dw">${html}</div></div>`;

  function detailLabelCells(label) {
    return COLUMNS
      .filter((column) => !column.env)
      .map((column) => `<td class="dk dk-${esc(column.key)} ${column.drop || ""}">${fold(`<span class="dkl">${esc(label)}</span>`)}</td>`)
      .join("");
  }

  function detailAttrs(row, group, flags) {
    const classes = ["detail"].concat(
      group == null ? [] : ["grp"],
      flags.first ? ["detail-first"] : [],
      flags.last ? ["detail-last"] : [],
      // Rendered straight into the table — a shared link that already names
      // this component in `expand` — so it opens unfolded rather than
      // animating on first paint. The chevron path adds `on` a frame later.
      flags.on ? ["on"] : [],
    );
    return `class="${classes.join(" ")}" data-for="${esc(row.id)}"${
      group == null ? "" : ` data-step="${esc(group)}"`}`;
  }

  /* An environment with nothing to say gets an empty cell, not a dash: the
     version row directly above has already said "not deployed" once, and
     saying it nine more times underneath is what made the expansion read as a
     field of blanks. */
  function detailFieldRow(row, field, values, group, flags) {
    const kind = `dv${field.mono ? " mono" : ""}`;
    const cells_ = values.map((value) => `<td class="${kind}">${fold(value)}</td>`).join("");
    return `<tr ${detailAttrs(row, group, flags)}>${
      detailLabelCells(field.label)}${cells_}</tr>`;
  }

  function releaseChipsAll(row) {
    const detail = (row.releases_detail || []).length ? row.releases_detail : (row.releases || []);
    return detail
      .filter((release) => release.tag)
      .map((release) =>
        `<a class="rel${release.deployed ? " deployed" : ""}${release.prerelease ? " pre" : ""}"
          href="${esc(release.url || "#")}" data-tip="rel" data-id="${esc(row.id)}"
          data-tag="${esc(release.tag)}">${esc(release.tag)}</a>`)
      .join("");
  }

  function detailReleasesRow(row, chips, group, flags) {
    return `<tr ${detailAttrs(row, group, flags)}>${detailLabelCells("Releases")}<td
      class="dv rels" colspan="${TD.ENVS.length}">${fold(chips)}</td></tr>`;
  }

  /* Only the fields somebody answered. Nine rows of which six were empty is
     the shape the owner sent back; this builds the rows first and drops the
     ones no environment filled in. */
  function detailRowsHtml(row, group, unfolded) {
    const deployed = TD.ENVS.map((env) => {
      const cell = cells(row)[env];
      return cell && cell.deployed ? cell : null;
    });
    const make = [];
    for (const field of DETAIL_FIELDS) {
      const values = deployed.map((cell) => (cell ? field.read(cell) : ""));
      if (!values.some(Boolean)) continue;
      make.push((flags) => detailFieldRow(row, field, values, group, flags));
    }
    const chips = releaseChipsAll(row);
    if (chips) make.push((flags) => detailReleasesRow(row, chips, group, flags));
    if (!make.length) {
      make.push((flags) => `<tr ${detailAttrs(row, group, flags)}>${
        detailLabelCells("")}<td class="dv rels" colspan="${TD.ENVS.length}">${fold('<span class="dash">Nothing else is recorded for this component.</span>')
        }</td></tr>`);
    }
    return make
      .map((build, index) => build({
        first: index === 0,
        last: index === make.length - 1,
        on: unfolded !== false,
      }))
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
     bands (by date, by environment). It is what puts the spine on the row and
     the indent under it, so "no bands, no spine" needs no second rule. */
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
    return open ? body + detailRowsHtml(row, group, true) : body;
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

  const rowById = (id) => (TD.DATA.rows || []).find((row) => row.id === id);

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
      return `<div><b>${esc(sourceLabel(key))}</b></div><div class="note">${
        esc(SOURCE_NOTES[key] || "Where this value was read from.")}</div>`;
    }
    if (kind === "rel") {
      const row = rowById(target.dataset.id);
      if (!row) return "";
      const all = (row.releases_detail || []).concat(row.releases || []);
      const release = all.find((entry) => entry.tag === target.dataset.tag);
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
      const cell = row && cells(row)[env];
      if (!cell || !cell.deployed) return "";
      const pair = (term, value) => (value ? `<dt>${esc(term)}</dt><dd>${esc(value)}</dd>` : "");
      const note = cell.unregistered
        ? "Deployed, but absent from this component's SmartAPI record, which lists other environments."
        : "";
      return `<div class="title">${esc(row.id)} · ${esc(env)}</div><dl>${
        pair("version", cell.version)}${
        pair("source", cell.version_source ? sourceLabel(cell.version_source) : "")}${
        pair("trapi", cell.trapi)}${
        pair("biolink", cell.biolink)}${
        pair("data release", cell.data_release)}${
        pair("released", cell.released)}${
        pair("http", cell.http_status)}${
        pair("location", cell.location)}${
        pair("url", cell.url)}</dl>${
        (cell.drift || []).length
          ? `<div class="note">Disagrees with the rest of this row on ${
              esc((cell.drift || []).join(", "))}.</div>` : ""}${
        note ? `<div class="note">${esc(note)}</div>` : ""}`;
    }
    return "";
  }

  /* --- Motion ---------------------------------------------------------------- */

  /* FLIP: measure every row before the re-render, measure again after, apply
     the inverse transform and let it transition to none. Capped, because past
     sixty rows the glide is a screenful of movement nobody reads. */
  function positions(body) {
    const map = new Map();
    for (const row of body.querySelectorAll("tr.row")) {
      map.set(row.dataset.id, row.getBoundingClientRect().top);
    }
    return map;
  }

  function flip(body, before) {
    if (!TD.motion.enabled || !before) return;
    const rows = [...body.querySelectorAll("tr.row")];
    if (rows.length > 60) return;
    const moved = [];
    for (const row of rows) {
      const from = before.get(row.dataset.id);
      if (from == null) continue;
      const delta = from - row.getBoundingClientRect().top;
      if (!delta) continue;
      row.style.transform = `translateY(${delta}px)`;
      moved.push(row);
    }
    if (!moved.length) return;
    void body.offsetHeight;   // one forced reflow, so the inverse is painted
    for (const row of moved) {
      row.classList.add("flip");
      row.style.transform = "";
      row.addEventListener("transitionend", () => {
        row.classList.remove("flip");
      }, { once: true });
    }
  }

  function fadeIn(body) {
    if (!TD.motion.enabled) return;
    let index = 0;
    for (const row of body.querySelectorAll("tr.row")) {
      row.style.animationDelay = `calc(${Math.min(index, 20)} * var(--stagger))`;
      row.classList.add("fade");
      index += 1;
    }
  }

  /* --- Expansion, animated --------------------------------------------------- */

  function findRow(body, id) {
    return [...body.querySelectorAll("tr.row")].find((row) => row.dataset.id === id);
  }

  /* The gutter between rows, in pixels: the open item's measured height has to
     stop at the last detail row's surface rather than at the six transparent
     pixels under it, or the shadow sits six pixels low. */
  function rowGap() {
    const raw = getComputedStyle(document.documentElement).getPropertyValue("--row-gap");
    return parseFloat(raw) || 0;
  }

  /* The item's outer box, for the one shadow drawn round it. Width comes from
     the cells rather than from the row: `offsetWidth` on a <tr> is not worth
     trusting across engines, and the two cells share an offset parent. */
  function sizeOpen(tr, rows) {
    const first = tr.firstElementChild;
    const last = tr.lastElementChild;
    if (first && last) {
      tr.style.setProperty(
        "--open-w", `${Math.round(last.offsetLeft + last.offsetWidth - first.offsetLeft)}px`);
    }
    if (!rows.length) return tr.offsetHeight;
    const tail = rows[rows.length - 1];
    return Math.round(tail.offsetTop + tail.offsetHeight - tr.offsetTop - rowGap());
  }

  /* A row that arrived open — `?expand=` in a shared link, or a re-render
     while one was open — has no measurements yet, and the shadow is sized
     from them. Run after every render, not just after a click. */
  function settleOpen(container) {
    for (const tr of container.querySelectorAll("tr.row.open")) {
      const rows = detailRowsAfter(tr);
      tr.style.setProperty("--open-h", `${sizeOpen(tr, rows)}px`);
    }
  }

  /* Opening does not re-render the table. It inserts this component's detail
     rows and nothing else, then unfolds them: measure their natural height in
     one frame with transitions off, collapse, and let the grid rows go
     0fr → 1fr on the next. Two forced layouts on a click, and every row below
     moves on the same curve instead of jumping once when the rows appear. */
  function openExpansion(body, id) {
    const tr = findRow(body, id);
    const row = rowById(id);
    if (!tr || !row || tr.nextElementSibling?.classList.contains("detail")) return;
    // The band this row is under, read back off the row rather than passed in:
    // the click handler knows the id, not the grouping.
    const group = tr.classList.contains("grp") ? tr.dataset.step ?? "" : null;
    tr.insertAdjacentHTML("afterend", detailRowsHtml(row, group, false));
    const rows = detailRowsAfter(tr);
    const folds = rows.flatMap((detail) => [...detail.querySelectorAll(".dg")]);

    // `open` is what squares the row's bottom corners and draws the lift: the
    // detail rows are not a second item, they are this one, taller.
    tr.style.setProperty("--open-h", `${sizeOpen(tr, [])}px`);
    tr.classList.add("open");

    if (!TD.motion.enabled) {
      for (const detail of rows) detail.classList.add("on");
      tr.style.setProperty("--open-h", `${sizeOpen(tr, rows)}px`);
      return;
    }

    // Unfolded, measured, folded again — all before the browser paints, and
    // with transitions off so none of it is animated.
    for (const fold of folds) fold.classList.add("still");
    for (const detail of rows) detail.classList.add("on");
    const full = sizeOpen(tr, rows);
    for (const detail of rows) detail.classList.remove("on");
    void body.offsetHeight;
    for (const fold of folds) fold.classList.remove("still");
    requestAnimationFrame(() => {
      for (const detail of rows) detail.classList.add("on");
      tr.style.setProperty("--open-h", `${full}px`);
    });
  }

  /* Symmetrical: fold to nothing on the same curve, and only then take the
     rows out. Removing them first is what made the page jump. */
  function closeExpansion(body, id) {
    const tr = findRow(body, id);
    const rows = detailRowsAfter(tr);
    if (!rows.length) return;
    const finish = () => {
      for (const detail of rows) detail.remove();
      tr.classList.remove("open", "closing");
      tr.style.removeProperty("--open-h");
      tr.style.removeProperty("--open-w");
    };
    if (!TD.motion.enabled) { finish(); return; }
    tr.classList.add("closing");
    tr.style.setProperty("--open-h", `${sizeOpen(tr, [])}px`);
    for (const detail of rows) detail.classList.remove("on");
    let done = false;
    const once = () => { if (done) return; done = true; finish(); };
    // transitionend on the first fold, and a timer in case the row is scrolled
    // out of view and the transition never fires.
    const first = rows[0].querySelector(".dg");
    if (first) first.addEventListener("transitionend", once, { once: true });
    setTimeout(once, 600);
  }

  /* --- Render ----------------------------------------------------------------- */

  let wrap = null;
  let head = null;
  let body = null;
  let last = null;

  function build(container) {
    container.innerHTML = `<div class="tablewrap"><table class="grid">
      <thead></thead><tbody></tbody></table></div>`;
    wrap = container.querySelector(".tablewrap");
    head = container.querySelector("thead");
    body = container.querySelector("tbody");

    head.addEventListener("click", (event) => {
      const button = event.target.closest("button[data-col]");
      if (!button) return;
      const column = COLUMNS.find((entry) => entry.key === button.dataset.col);
      const preferred = column.prefer || "asc";
      const s = state();
      if (s.sort !== column.key) TD.commit({ sort: column.key, dir: preferred });
      else if (s.dir === preferred) {
        TD.commit({ dir: preferred === "asc" ? "desc" : "asc" });
      } else {
        // Third click goes home. Without it, stage order — the order the page
        // is built to argue for — would be unreachable once you left it.
        TD.commit({ sort: "", dir: "asc" });
      }
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
      if (name) {
        const id = name.dataset.open;
        TD.commit({ sel: id }, { silent: true });
        for (const row of body.querySelectorAll("tr.row")) {
          row.classList.toggle("sel", row.dataset.id === id);
        }
        // The drawer lands in a later step; until it does, selecting a
        // component records itself in the URL and does nothing else.
        if (TD.drawer && TD.drawer.open) TD.drawer.open(id);
      }
    });

    TD.ui.tooltip.bind(body, "[data-tip]", tipHtml);
  }

  table.render = function render(container) {
    table.ensureColumns();
    if (!wrap || !container.contains(wrap)) { last = null; build(container); }

    const s = state();
    const signature = {
      q: (s.q || "").trim(), owner: (s.owner || []).join(","), versions: s.versions,
      sort: s.sort, dir: s.dir,
    };
    const filtered = last && (last.q !== signature.q || last.owner !== signature.owner
      || last.versions !== signature.versions);
    const sorted = last && (last.sort !== signature.sort || last.dir !== signature.dir);

    const before = sorted ? positions(body) : null;
    const rows = TD.sort.rows(visibleRows(), sortColumn(), s.dir);

    TD.ui.tooltip.hide();
    head.innerHTML = headHtml();
    body.innerHTML = bodyHtml(rows);

    settleOpen(body);
    if (sorted) flip(body, before);
    else if (filtered) fadeIn(body);

    last = signature;
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
  table.scrollTo = function scrollTo(id) {
    if (!body) return;
    const tr = findRow(body, id);
    if (tr) tr.scrollIntoView({ block: "center", behavior: TD.motion.enabled ? "smooth" : "auto" });
  };
})();
