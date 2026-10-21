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
     version does not is exactly as interesting.

     The last three are the complements of the sync panel's shares: each
     share says how much of the platform has a property, and links here to
     list the rows that do not. The URL parameter is still `versions`, for
     the links already in the wild. */
  const SHOW_VIEWS = {
    all: { label: "All components", test: () => true },
    differ: { label: "Environments disagree", test: hasDrift },
    known: { label: "Any version known", test: (row) => knownVersions(row).size > 0 },
    none: { label: "No version known", test: (row) => knownVersions(row).size === 0 },
    unreachable: {
      label: "Not reachable",
      test: (row) => TD.ENVS.some((env) => TD.cell(row, env).reach === "down"),
    },
    unregistered: {
      label: "Absent from SmartAPI record",
      test: (row) => TD.ENVS.some((env) => TD.cell(row, env).flags.unregistered),
    },
    "no-smartapi": { label: "No SmartAPI record", test: (row) => !row.smartapi_record },
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
      .filter((SHOW_VIEWS[s.versions] || SHOW_VIEWS[DEFAULT_VIEW]).test)
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
      m.source ? `<span class="src" data-src="${esc(m.source)}" data-tip="src">${esc(m.sourceShort)}</span>` : "",
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
     to be a column of its own, and it belongs beside the thing it dates.

     The newest release itself, not `last_updated`: that is the newer of the
     release and the registration, and when it showed here only when the
     release won, a registration edited last week took the release date off
     Name Lookup's row. `releases_detail` is newest first. */
  function repoCell(row) {
    if (!row.repository) return `<td class="repo drop-md">${DASH()}</td>`;
    const newest = (row.releases_detail || [])[0];
    const released = newest && newest.published
      ? `<span class="l2" data-tip="rel" data-id="${esc(row.id)}" data-tag="${esc(newest.tag)}"><span class="age">${
          esc(TD.fmt.relativeAge(newest.published))}</span> · ${esc(newest.tag)}</span>`
      : "";
    // The release chips sit here too, shown only once the row is open: this is
    // the column they come from, so they need no label of their own.
    const chips = releaseChipsAll(row);
    return `<td class="repo drop-md">${link(row.repository, esc(TD.row.repoLabel(row.repository)))}${
      released}${chips ? `<span class="rels">${chips}</span>` : ""}</td>`;
  }

  /* One registration usually covers every environment, so it is a column of
     its own rather than four facts. It says what to do about the record, in
     TD.smartapi's words: the worst problem first, any others under it, then
     when the record last changed, and everything in the tooltip. The date has
     a line of its own: run on after the problems it wrapped, and left a "·"
     hanging at the end of the line above.

     The dot sits in a gutter of its own, kept empty on rows with no dot, so
     every first line starts at the same x and the lines under it start under
     the first rather than under the dot. */
  function smartapiCell(row) {
    const status = TD.smartapi.status(row);
    const dot = status.dot != null
      ? `<span class="dot ${status.dot}" aria-label="${esc(status.group)}"></span>`
      : "";
    const word = link(status.href, esc(status.word), status.href ? "" : "why");
    const others = status.problems.slice(1).map((problem) => esc(problem.word));
    const lines = [
      others.length ? others.join('<span class="sep"> · </span>') : "",
      status.changed ? `changed <span class="age">${esc(TD.fmt.relativeAge(status.changed))}</span>` : "",
    ].filter(Boolean).map((line) => `<span class="l2">${line}</span>`).join("");
    return `<td class="sapi drop-sm" data-tip="sapi" data-id="${esc(row.id)}"><span class="sapil">${
      dot}<span class="sapiw">${word}</span>${lines}</span></td>`;
  }

  /* The name on the first line and, under it, the summary; the id joins the
     second line only when the row is open, because it is the key a link or a
     search uses rather than a thing to read down a column.

     The name is text, not a link: a click on it opens the row like a click
     anywhere else on it, since the open row is where the connections are.
     The arrow at the cell's right edge opens the component's page, and the
     arrows line up down the table, so they read as a column without costing
     one. */
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
      TD.owner.coin(row.owner, "narrow")}<span class="cname">${esc(row.name)}</span>${externals}<button
        type="button" class="openpage" data-open="${esc(row.id)}" title="Open the ${esc(row.name)} page"
        aria-label="Open the ${esc(row.name)} page">${TD.ui.OPEN}</button></span>
      <span class="csub"><span class="cid">${esc(row.id)}</span>${summary}</span></td>`;
  }

  function ownerCell(row) {
    return `<td class="drop-xs quiet">${TD.row.ownerLabel(row.owner)}</td>`;
  }

  /* --- Columns -------------------------------------------------------------- */

  const registryDate = (row) => TD.smartapi.status(row).changed;

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
      // What needs a look first, in either direction: the state is a tier,
      // compared before the flip, and the date orders each band.
      rank: (row) => TD.smartapi.status(row).rank,
      band: (row) => TD.smartapi.status(row).group,
      value: registryDate,
      compare: TD.sort.byDate, prefer: "asc",
      words: ["problems first", "problems first, newest first"],
      hint: "Sort by what needs a look in the SmartAPI registration, problems first",
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

     The label sits immediately left of the first environment column, so the
     word and the values it names touch. Which cell that is depends on the
     width — SmartAPI, Owner and the rest drop out at the breakpoints — so
     the label is written into every non-environment cell, each carrying its
     column's drop class, and CSS shows the rightmost one still on screen
     (the ladder in table.css). A colspan cannot do this: a
     hidden cell generates no box, so a colspan row keeps claiming the
     columns that have gone and shifts every value one column right. It was
     once put in the first column instead, and read as detached from the
     numbers it named.

     Version is deliberately absent: it is the row directly above.

     `skipName` leaves out the Component column's cell, for the rows a
     connections cell spans (connectionsCell). */
  /* Where a narrow column wraps a label, its last word and the (?) wrap
     together (`.dkw`), so the (?) is never on a line alone. A word joiner
     before the button was tried first: Chrome still breaks before a button. */
  function labelHtml(label, help) {
    if (!help) return esc(label);
    const at = label.lastIndexOf(" ") + 1;
    return `${esc(label.slice(0, at))}<span class="dkw">${esc(label.slice(at))}${help}</span>`;
  }

  function labelCells(row, label, about, skipName) {
    const help = about
      ? `<button type="button" class="help" data-tip="fact" data-id="${esc(row.id)}"
           data-fact="${esc(label)}" aria-label="Where ${esc(label)} comes from">?</button>`
      : "";
    return COLUMNS
      .filter((column) => !column.env && !(skipName && column.key === "name"))
      .map((column) => `<td class="dk dk-${esc(column.key)} ${column.drop || ""}"><span class="dkl">${
        labelHtml(label, help)}</span></td>`)
      .join("");
  }

  function detailAttrs(row, group, flags) {
    const classes = ["detail"].concat(
      group == null ? [] : ["grp"],
      flags.first ? ["detail-first"] : [],
      flags.last ? ["detail-last"] : [],
      flags.spanned ? ["spanned"] : [],
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

  /* One connection: the component's coin and name, as a button that opens its
     page, exactly as the name in its own row does (the body's click handler
     answers both). */
  function connectionButton(item) {
    const other = rowById(item.id);
    const name = other ? other.name : item.id;
    const title = `Open ${name}${item.planned ? " (planned, not yet implemented)" : ""}`;
    return `<button type="button" class="conn${item.planned ? " planned" : ""}" data-open="${
      esc(item.id)}" title="${esc(title)}">${other ? TD.owner.coin(other.owner) : ""}${esc(name)}</button>`;
  }

  /* The connections, in the Component column of the detail rows, which is
     otherwise empty above the narrow breakpoint: the labels sit in the
     rightmost non-environment column, and that is never this one there. One
     cell spanning every detail row, in TD.row.connections' groups and order;
     the externals and the catalog's view stay on the Component page. */
  function connectionsCell(row, span) {
    const groups = TD.row.connections(row).filter((group) => group.items.length);
    const body = groups.length
      ? groups.map((group) => `<div class="cg"><span class="cgl">${esc(group.title)}</span>${
        group.items.map(connectionButton).join("")}</div>`).join("")
      : '<span class="why">No connections recorded</span>';
    // Words as well as the arrow on the row: someone who has opened the row
    // and read it is deciding whether to go further.
    const open = `<button type="button" class="openlink" data-open="${esc(row.id)}">Open the ${
      esc(row.name)} page ${TD.ui.OPEN}</button>`;
    return `<td class="dk-conn" rowspan="${span}">${open}${body}</td>`;
  }

  /* Only the facts some environment answered, each in its environment's
     column. The releases are not here: they are in the Repository cell of
     the row above, shown once it is open.

     `narrow` is whether the window is at or under NARROW. There the
     Component column is the label column, so the rows are drawn without the
     connections cell. It is an argument rather than a CSS rule because a
     rowspan cannot be undone in CSS: hiding the spanning cell would move
     every later row's cells one column left. */
  function detailRowsHtml(row, group, options) {
    const narrow = !!(options && options.narrow);
    const models = Object.fromEntries(TD.ENVS.map((env) => [env, TD.cell(row, env)]));
    const facts = [];
    for (const env of TD.ENVS) {
      for (const fact of models[env].facts) {
        if (!facts.some((f) => f.label === fact.label)) facts.push(fact);
      }
    }
    const lead = (flags) => (narrow || flags.index > 0 ? "" : connectionsCell(row, flags.count));
    const make = facts.map((fact) => (flags) =>
      `<tr ${detailAttrs(row, group, flags)}>${lead(flags)}${labelCells(row, fact.label, fact.about, !narrow)}${
        TD.ENVS.map((env) => factCell(models[env].facts.find((f) => f.label === fact.label))).join("")
      }</tr>`);
    if (!make.length) {
      make.push((flags) => `<tr ${detailAttrs(row, group, flags)}>${lead(flags)}${labelCells(row, "", "", !narrow)}<td
        class="dv note" colspan="${TD.ENVS.length}">Nothing else is recorded for this component.</td></tr>`);
    }
    return make
      .map((build, index) => build({
        index,
        count: make.length,
        first: index === 0,
        last: index === make.length - 1,
        spanned: !narrow && index > 0,
      }))
      .join("");
  }

  /* At and under this width the Component column holds the detail rows'
     labels: the last step of the label ladder in table.css, which must change
     with it. */
  const NARROW = "(max-width: 800px)";
  function isNarrow() {
    try {
      return typeof matchMedia === "function" && matchMedia(NARROW).matches;
    } catch {
      return false;
    }
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
  function rowHtml(row, group, options) {
    const open = (state().expand || []).indexOf(row.id) >= 0;
    const classes = ["row"];
    if (group != null) classes.push("grp");
    if (row.isolated) classes.push("isolated");
    if (state().sel === row.id) classes.push("sel");
    if (open) classes.push("open");
    const step = group == null ? "" : ` data-step="${esc(group)}"`;
    const body = `<tr class="${classes.join(" ")}" id="c-${esc(row.id)}" data-id="${esc(row.id)}"${
      step}>${COLUMNS.map((column) => column.cell(row)).join("")}</tr>`;
    return open ? body + detailRowsHtml(row, group, options) : body;
  }

  function bodyHtml(rows, options) {
    if (!rows.length) {
      return `<tr><td class="empty" colspan="${COLUMNS.length}"
        >No components match these filters.</td></tr>`;
    }
    const label = bandKey();
    if (!label) return rows.map((row) => rowHtml(row, null, options)).join("");
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
        bandHtml(group) + group.rows.map((row) => rowHtml(row, group.label, options)).join(""))
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
  };

  function tipHtml(target) {
    const kind = target.dataset.tip;
    if (kind === "src") {
      const key = target.dataset.src;
      return `<div><b>${esc(TD.fmt.sourceLabel(key))}</b></div><div class="note">${
        esc(SOURCE_NOTES[key] || "Where this value was read from.")}</div>`;
    }
    if (kind === "fact") {
      const row = rowById(target.dataset.id);
      const label = target.dataset.fact;
      const fact = row && TD.ENVS
        .map((env) => TD.cell(row, env).facts.find((f) => f.label === label)).find(Boolean);
      if (!fact) return "";
      return `<div><b>${esc(fact.label)}</b></div><div class="note">${esc(fact.about)}</div>`;
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
    if (kind === "sapi") {
      const row = rowById(target.dataset.id);
      if (!row) return "";
      const status = TD.smartapi.status(row);
      const pair = (term, value) => (value ? `<dt>${esc(term)}</dt><dd>${esc(value)}</dd>` : "");
      const day = (iso) => String(iso).slice(0, 10);
      // The registry writes one line per path; the failures are the ones to
      // read, and three is enough to say which.
      const failures = status.failures.slice(0, 3);
      return `<div class="title">SmartAPI · ${esc(status.group)}</div><dl>${
        pair("record", row.smartapi || "")}${
        pair("changed", status.changed ? day(status.changed) : "")}${
        pair("probed", status.probed ? day(status.probed) : "")}</dl>${
        status.problems.map((problem) => `<div class="note">${esc(problem.note)}</div>`).join("")}${
        failures.map((line) => `<div class="note">${esc(line)}</div>`).join("")}${
        status.failures.length > failures.length
          ? `<div class="note">and ${status.failures.length - failures.length} more</div>` : ""}`;
    }
    if (kind === "env") {
      const row = rowById(target.dataset.id);
      const env = target.dataset.env;
      if (!row) return "";
      const m = TD.cell(row, env);
      if (!m.deployed) return "";
      const pair = (term, value) => (value ? `<dt>${esc(term)}</dt><dd>${esc(value)}</dd>` : "");
      const notes = [
        m.flags.inferred
          ? "This environment was not declared in the registry; it was inferred from a server's description there, which is the weaker claim."
          : "",
        m.flags.unregistered
          ? "Deployed, but absent from this component's SmartAPI record, which lists other environments."
          : "",
      ].filter(Boolean);
      return `<div class="title">${esc(row.id)} · ${esc(env)}</div><dl>${
        pair("version", m.version)}${
        pair("read from", m.version ? m.sourceWord : "")}${
        pair("status", m.reason)}${
        m.facts.map((f) => pair(f.label, f.note ? `${f.value} (${f.note})` : f.value)).join("")}</dl>${
        m.drift.length
          ? `<div class="note">Disagrees with the rest of this row on ${esc(m.drift.join(", "))}.</div>` : ""}${
        notes.map((note) => `<div class="note">${esc(note)}</div>`).join("")}`;
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
    tr.insertAdjacentHTML("afterend", detailRowsHtml(row, group, { narrow: isNarrow() }));
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

    function toggleExpansion(tr) {
      const id = tr.dataset.id;
      const expand = (state().expand || []).slice();
      const at = expand.indexOf(id);
      if (at >= 0) { expand.splice(at, 1); closeExpansion(body, id); }
      else { expand.push(id); openExpansion(body, id); }
      tr.querySelector("button[data-expand]").setAttribute("aria-expanded", at < 0);
      TD.commit({ expand }, { silent: true });
    }

    /* A click anywhere on a row toggles it, so a reader looking at the
       environment columns need not travel back to the chevron. Links and
       buttons in the row keep their own job (the arrow opens the component's page), a
       drag that selected text to copy is not a click, and the detail rows
       never collapse their row: they hold the values people copy. The chevron
       stays the keyboard and screen-reader control; the <tr> is not made a
       button, because it contains links and buttons. */
    body.addEventListener("click", (event) => {
      const name = event.target.closest("button[data-open]");
      if (name) { TD.navigate({ view: "component", sel: name.dataset.open }); return; }
      const tr = event.target.closest("tr.row");
      if (!tr) return;
      if (event.target.closest("button[data-expand]")) { toggleExpansion(tr); return; }
      if (event.target.closest("a, button")) return;
      if (!(window.getSelection()?.isCollapsed ?? true)) return;
      toggleExpansion(tr);
    });

    TD.ui.tooltip.bind(body, "[data-tip]", tipHtml);

    // An open row's detail is drawn for one side of NARROW (detailRowsHtml),
    // so crossing it redraws the body. Only then: nothing else depends on it.
    if (typeof matchMedia === "function") {
      matchMedia(NARROW).addEventListener("change", () => {
        if (!(state().expand || []).length) return;
        body.innerHTML = bodyHtml(TD.sort.rows(visibleRows(), sortColumn(), state().dir), { narrow: isNarrow() });
      });
    }
  }

  table.render = function render(container) {
    table.ensureColumns();
    if (!wrap || !container.contains(wrap)) build(container);

    const rows = TD.sort.rows(visibleRows(), sortColumn(), state().dir);
    TD.ui.tooltip.hide();
    head.innerHTML = headHtml();
    body.innerHTML = bodyHtml(rows, { narrow: isNarrow() });
    return { shown: rows.length, total: (TD.DATA.rows || []).length };
  };

  table.ensureColumns = function ensureColumns() {
    if (!COLUMNS.some((column) => column.env)) buildColumns();
  };
  table.COLUMNS = COLUMNS;
  table.SHOW_VIEWS = SHOW_VIEWS;
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
  // The Component view's environment matrix shows the same tooltips.
  table.tipHtml = tipHtml;
  table.scrollTo = function scrollTo(id) {
    if (!body) return;
    const tr = findRow(body, id);
    if (tr) tr.scrollIntoView({ block: "center", behavior: TD.motion.enabled ? "smooth" : "auto" });
  };

  /* Scroll the table's own scrollport so the row sits just under the sticky
     header. Not scrollTo: scrollIntoView scrolls *every* ancestor scroller,
     the document included, which once slid the whole page down under a
     bottom sheet. */
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
