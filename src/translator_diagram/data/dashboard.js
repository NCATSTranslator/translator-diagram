/*
  The dashboard's entire script. No framework: 26 rows do not need one, and a
  page with no build step can be opened straight from disk.

  Two ideas are borrowed from babel-validation's dashboard because they are
  what make a table like this usable rather than merely correct:

    - every filter round-trips through the URL, so a view can be pasted into
      Slack and arrive as the sender saw it;
    - a value in the minority across environments is tinted, so drift is
      visible without reading every cell.
*/

const DATA = JSON.parse(document.getElementById("payload").textContent);
const ENVS = DATA.environments;

const state = {
  q: "",
  owner: "",
  versions: "all",
  details: true,
  sort: "",   // empty means the payload's own order, which is by stage
  dir: "asc",
};
let urlReady = false;

/* --- Utilities ----------------------------------------------------------- */

const esc = (value) =>
  String(value ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

const DASH = '<span class="dash">—</span>';
const or = (value, html) => (value ? html : DASH);

function unique(values) {
  return [...new Set(values.filter(Boolean))].sort((a, b) => a.localeCompare(b));
}

/* --- URL state ----------------------------------------------------------- */

function readUrl() {
  const p = new URLSearchParams(location.search);
  state.q = (p.get("q") ?? "").slice(0, 200);
  state.owner = (p.get("owner") ?? "").slice(0, 100);
  const view = p.get("versions") ?? "";
  state.versions = Object.hasOwn(VERSION_VIEWS, view) ? view : DEFAULT_VIEW;
  // A pasted URL can name anything; only a real sortable column counts.
  const sort = p.get("sort") ?? "";
  state.sort = COLUMNS.some((column) => column.key === sort) ? sort : "";
  state.dir = p.get("dir") === "desc" ? "desc" : "asc";
  state.details = p.get("details") !== "0";
}

function writeUrl() {
  // Watchers fire during setup too; without this guard the first render would
  // rewrite the URL and discard the state a shared link asked for.
  if (!urlReady) return;
  const p = new URLSearchParams();
  if (state.q.trim()) p.set("q", state.q.trim());
  if (state.owner) p.set("owner", state.owner);
  if (state.versions !== DEFAULT_VIEW) p.set("versions", state.versions);
  // Both, always: the first click's direction differs per column, so "asc" is
  // not a default a reader of the URL could infer.
  if (state.sort) { p.set("sort", state.sort); p.set("dir", state.dir); }
  if (!state.details) p.set("details", "0");
  const query = p.toString();
  history.replaceState(null, "", query ? `?${query}` : location.pathname);
}

/* --- Filtering ----------------------------------------------------------- */

function hasDrift(row) {
  return ENVS.some((env) => (row.environments[env]?.drift ?? []).length > 0);
}

function knownVersions(row) {
  return new Set(ENVS.map((env) => row.environments[env]?.version).filter(Boolean));
}

/* One control rather than a "drift only" toggle beside a version filter: the
   two would have said the same thing about the same rows, and a reader cannot
   tell overlapping filters apart.

   The page opens on all of them. It used to open on "Environments disagree",
   which showed seven rows of twenty-four and hid the platform to make a point
   about drift — a reader who came to look up one component found it missing
   from a page that had not said it was filtered. The drift is still the first
   thing said, in the finding above the table, and still one selection away
   here.

   "Environments disagree" is any of the three tinted axes, not versions
   alone: a component whose version matches everywhere while its TRAPI version
   does not is exactly as interesting, and hiding it would be a lie of
   omission. */
const VERSION_VIEWS = {
  all: { label: "All components", test: () => true },
  differ: { label: "Environments disagree", test: hasDrift },
  known: { label: "Any version known", test: (row) => knownVersions(row).size > 0 },
  none: { label: "No version known", test: (row) => knownVersions(row).size === 0 },
};
const DEFAULT_VIEW = "all";

function visibleRows() {
  const needle = state.q.trim().toLowerCase();
  return DATA.rows
    .filter((row) => !state.owner || row.owner === state.owner)
    .filter(VERSION_VIEWS[state.versions]?.test ?? VERSION_VIEWS[DEFAULT_VIEW].test)
    .filter((row) => {
      if (!needle) return true;
      const haystack = [
        row.id, row.name, row.owner, row.infores,
        row.helm_chart, row.last_updated?.date, ...(row.otel_services ?? []),
        ...(row.releases ?? []).map((r) => r.tag),
        ...ENVS.map((env) => row.environments[env]?.version),
      ];
      return haystack.some((v) => String(v ?? "").toLowerCase().includes(needle));
    });
}

/* --- Theme --------------------------------------------------------------- */

/* Inline SVG rather than ☀/☾: those render as colour emoji on one platform and
   as a tofu box on another, and a page that must work from file:// cannot
   fetch an icon font to settle it. `currentColor` keeps them correct in both
   themes for free. */
const THEME_ICONS = {
  light: `<svg viewBox="0 0 16 16" width="15" height="15" aria-hidden="true" fill="none"
    stroke="currentColor" stroke-width="1.4" stroke-linecap="round">
    <circle cx="8" cy="8" r="3.1"/>
    <path d="M8 1v1.7M8 13.3V15M1 8h1.7M13.3 8H15M3.05 3.05l1.2 1.2M11.75 11.75l1.2 1.2
             M12.95 3.05l-1.2 1.2M4.25 11.75l-1.2 1.2"/></svg>`,
  dark: `<svg viewBox="0 0 16 16" width="15" height="15" aria-hidden="true" fill="none"
    stroke="currentColor" stroke-width="1.4" stroke-linejoin="round">
    <path d="M13.2 9.6A5.8 5.8 0 0 1 6.4 2.8a5.8 5.8 0 1 0 6.8 6.8z"/></svg>`,
  auto: `<svg viewBox="0 0 16 16" width="15" height="15" aria-hidden="true"
    stroke="currentColor" stroke-width="1.4">
    <circle cx="8" cy="8" r="5.6" fill="none"/>
    <path d="M8 2.4a5.6 5.6 0 0 1 0 11.2z" fill="currentColor" stroke="none"/></svg>`,
};
const THEME_NAMES = { light: "light", dark: "dark", auto: "following the system" };

function systemPrefersDark() {
  return matchMedia("(prefers-color-scheme: dark)").matches;
}

function currentTheme() {
  const choice = document.documentElement.dataset.themeChoice;
  return choice in THEME_NAMES ? choice : "auto";
}

/* The cycle starts by moving *away* from what the system says, because the
   page opens following the system: ordering it auto → light → dark would spend
   the first click repainting a light machine light, which reads as a broken
   button rather than as a default worth keeping. */
function nextTheme(choice) {
  const differs = systemPrefersDark() ? "light" : "dark";
  if (choice === "auto") return differs;
  return choice === differs ? (systemPrefersDark() ? "dark" : "light") : "auto";
}

function applyTheme(choice) {
  const root = document.documentElement;
  root.dataset.themeChoice = choice;
  root.dataset.theme =
    choice === "dark" || (choice === "auto" && systemPrefersDark()) ? "dark" : "light";
  renderTheme();
}

function renderTheme() {
  const choice = currentTheme();
  const button = document.getElementById("theme");
  button.innerHTML = THEME_ICONS[choice];
  // The icon says which mode is on; the label has to say that *and* what the
  // click does, because an icon-only button otherwise announces nothing.
  const label = `Theme: ${THEME_NAMES[choice]} — switch to ${
    THEME_NAMES[nextTheme(choice)]}`;
  button.title = label;
  button.setAttribute("aria-label", label);
}

/* --- Rendering ----------------------------------------------------------- */

function envCell(row, env) {
  const cell = row.environments[env];
  if (!cell || !cell.deployed) {
    return `<td class="env absent">${DASH}</td>`;
  }
  const drift = (cell.drift ?? []).length ? " drift" : "";
  const source = cell.version_source;
  const badge = source
    ? `<span class="src" data-src="${esc(source)}" title="Version read from ${esc(
        DATA.source_labels[source] ?? source)}">${esc(DATA.source_labels[source] ?? source)}</span>`
    : "";
  const version = cell.version
    ? `<span class="version">${esc(cell.version)}</span>${badge}`
    : `<span class="version dash">—</span>`;

  const sub = [];
  if (cell.trapi) sub.push(`TRAPI ${esc(cell.trapi)}`);
  if (cell.biolink) sub.push(`Biolink ${esc(cell.biolink)}`);
  if (cell.data_release) sub.push(esc(cell.data_release));
  // The value this column sorts by. Without it the sort has invisible
  // criteria: the header says "age of the release running in ci" and the cell
  // showed nothing to check that against.
  if (cell.released) sub.push(`released ${esc(cell.released)}`);
  const detail = state.details && sub.length
    ? `<span class="sub">${sub.join(" · ")}</span>` : "";

  const href = cell.openapi_url || cell.url;
  // A bad URL here would throw inside the row loop and blank the entire
  // table, so the hostname is best-effort: the row is worth more than the tidy
  // label.
  let host = cell.url;
  try { host = new URL(cell.url).hostname; } catch { /* show it verbatim */ }
  const link = href
    ? `<a class="sub" href="${esc(href)}" title="${esc(cell.url)}">${esc(host)}</a>`
    : "";

  const title = cell.unregistered
    ? `${cell.url} — deployed, but missing from this component's SmartAPI record`
    : cell.url;
  return `<td class="env${drift}${cell.unregistered ? " unregistered" : ""}" title="${
    esc(title)}">${version}${detail}${state.details ? link : ""}</td>`;
}

/* The repository, then its latest releases — plus any older release an
   environment on this row is running, so the version in the table always has
   its notes one click away. A release running somewhere is marked rather than
   merely listed; that mark is the link between this column and the four to
   its right. */
function repoCell(row) {
  if (!row.repository) return DASH;
  const label = row.repository.replace("https://github.com/", "");
  const link = `<a href="${esc(row.repository)}">${esc(label)}</a>`;
  const releases = (row.releases ?? [])
    .filter((r) => r.url)
    .map((r) => {
      const title = [
        r.name,
        r.published ? `released ${r.published}` : null,
        r.prerelease ? "pre-release" : null,
        r.deployed ? "running in an environment on this row" : null,
      ].filter(Boolean).join(" — ");
      return `<a class="rel${r.deployed ? " deployed" : ""}${
        r.prerelease ? " pre" : ""}" href="${esc(r.url)}" title="${esc(title)}"
        >${esc(r.tag)}</a>`;
    })
    .join("");
  return releases ? `${link}<span class="releases">${releases}</span>` : link;
}

function componentCell(row) {
  const externals = (row.externals ?? [])
    .map((e) => `<span class="chip">${e.direction === "in" ? "◀" : "▶"} ${esc(e.name)}</span>`)
    .join(" ");
  return `<td>
      <span class="component">${esc(row.name)}</span>
      <span class="cid">${esc(row.id)}</span>
      ${externals}
    </td>`;
}

/* Ages are measured against the reader's clock, not against the sync: a page
   opened in December is telling the truth when it says a release is four
   months old. The exact date is one hover away, and the footer says so. */
const AGE = new Intl.RelativeTimeFormat(undefined, { numeric: "always" });

function relativeAge(iso) {
  const ms = Date.now() - Date.parse(iso);
  if (!Number.isFinite(ms)) return "";
  const days = ms / 86400000;
  // Clamped, so a clock that is slightly ahead of GitHub's says "today"
  // rather than "in 3 hours".
  if (days < 1) return "today";
  if (days < 14) return AGE.format(-Math.round(days), "day");
  if (days < 60) return AGE.format(-Math.round(days / 7), "week");
  if (days < 730) return AGE.format(-Math.round(days / 30.44), "month");
  return AGE.format(-Math.round(days / 365.25), "year");
}

function updatedCell(row) {
  const updated = row.last_updated;
  // Null for 13 of 26 components — no releases, and in no registry. A dash is
  // the honest reading, not a failure.
  if (!updated) return `<td class="meta drop-sm updated">${DASH}</td>`;
  const label = DATA.updated_labels?.[updated.source] ?? updated.source;
  // The three shepherds share one repository, so one release date lands on
  // three rows: without the tag that reads as three coincidental deploys.
  const title = updated.source === "release"
    ? `${updated.tag} released ${updated.date}`
    : `SmartAPI registration last changed ${updated.date}`;
  return `<td class="meta drop-sm updated" title="${esc(title)}"
    ><span class="age">${esc(relativeAge(updated.at))}</span
    ><span class="src" data-src="${esc(updated.source)}">${esc(label)}</span></td>`;
}

/* --- Columns ------------------------------------------------------------- */

/* One entry per column, because four things have to agree about each one: the
   header cell, the body cell, the class that hides both at narrow widths, and
   the count the empty row's colspan needs. Three of those used to be written
   out twice — the header said `drop-md` and the body said it again — which is
   how a header ends up hidden without its column, or the reverse. */
const byText = (a, b) =>
  String(a).localeCompare(String(b), undefined, { numeric: true, sensitivity: "base" });
// Explicit, not localeCompare: YYYY-MM-DD happens to collate correctly, but
// only by accident, and an accident is a poor thing to sort dates on.
const byDate = (a, b) => (a < b ? -1 : a > b ? 1 : 0);

/* How stale an environment is, in tiers: running a release we can date, then
   running something no release names, then not deployed. Tiers hold in both
   directions, so reversing the sort never lifts the blanks to the top. */
function envRank(row, env) {
  const cell = row.environments[env];
  if (!cell?.deployed) return 2;
  return cell.released ? 0 : 1;
}

const COLUMNS = [
  { key: "name", label: "Component", cell: componentCell, value: (row) => row.name },
  {
    key: "owner", label: "Owner", value: (row) => row.owner, band: (row) => row.owner,
    cell: (row) =>
      `<td><span class="owner" data-owner="${esc(row.owner)}">${esc(row.owner)}</span></td>`,
  },
  {
    key: "repo", label: "Repository", drop: "drop-md",
    value: (row) => (row.repository ?? "").replace("https://github.com/", ""),
    cell: (row) => `<td class="meta drop-md">${repoCell(row)}</td>`,
  },
  {
    key: "updated", label: "Last updated", drop: "drop-sm", cell: updatedCell,
    value: (row) => row.last_updated?.date ?? "",
    compare: byDate, prefer: "asc", words: ["oldest first", "newest first"],
    hint: "Sort by when this component last changed",
  },
  ...ENVS.map((env) => ({
    key: `env-${env}`, label: env, env, headerCls: "env",
    cell: (row) => envCell(row, env),
    value: (row) => row.environments[env]?.released ?? "",
    rank: (row) => envRank(row, env),
    compare: byDate, prefer: "asc", words: ["oldest first", "newest first"],
    hint: `Sort by the age of the release running in ${env}`,
  })),
];

function sortColumn() {
  return COLUMNS.find((column) => column.key === state.sort);
}

/* Sorts the array visibleRows() just built, never DATA.rows: the count, the
   drift sentence and the flow bands all read the payload in its own order.
   Array.prototype.sort is stable, so every tie falls back to stage order —
   which is why sorting by owner leaves each owner's components in pipeline
   order. */
function sortRows(rows) {
  const column = sortColumn();
  if (!column) return rows;
  const flip = state.dir === "desc" ? -1 : 1;
  return rows.sort((a, b) => {
    const ra = column.rank ? column.rank(a) : 0;
    const rb = column.rank ? column.rank(b) : 0;
    if (ra !== rb) return ra - rb;
    const av = column.value(a) || "";
    const bv = column.value(b) || "";
    // Before the flip, deliberately: reversing the sort must not promote the
    // thirteen components we have no date for to the top of the table.
    if (!av || !bv) return av ? -1 : bv ? 1 : 0;
    return flip * (column.compare ?? byText)(av, bv);
  });
}

function rowHtml(row) {
  return `<tr class="${row.isolated ? "isolated" : ""}" id="c-${esc(row.id)}">
    ${COLUMNS.map((column) => column.cell(row)).join("")}
  </tr>`;
}

// Inline SVG on currentColor, for the reason THEME_ICONS already argues: a
// glyph arrow renders as colour emoji on one platform and tofu on another.
const CARET = `<svg class="caret" viewBox="0 0 10 10" width="9" height="9"
  aria-hidden="true" fill="currentColor"><path d="M5 1.5 9 7H1z"/></svg>`;

function headHtml() {
  return `<tr>${COLUMNS.map((column) => {
    const active = state.sort === column.key;
    const cls = [column.headerCls, column.drop].filter(Boolean).join(" ");
    // aria-sort drives the styling too, so what is announced and what is shown
    // cannot drift apart.
    const sorted = active ? (state.dir === "asc" ? "ascending" : "descending") : "none";
    const hint = column.hint ?? `Sort by ${column.label}`;
    return `<th class="${cls}" aria-sort="${sorted}"><button type="button"
      class="sortcol" data-col="${esc(column.key)}" title="${esc(hint)}">${
      esc(column.label)}${CARET}</button></th>`;
  }).join("")}</tr>`;
}

/* What the rows are grouped under, or null for an order that has no groups.
   Data flow gets bands because the order is otherwise invisible; the
   low-cardinality text columns get them because they are what "sorted by
   owner" means. Dates and environments get none — every row is its own group. */
function bandKey() {
  const column = sortColumn();
  if (!column) return (row) => row.step_label;
  return column.band ?? null;
}

/* A band names its group and, in stage order, says what the group is for. The
   number alone was true and useless: "Step 6" tells a reader where the rows
   sit, not what they do. Both come from config/flow-steps.yaml, which is also
   where the order itself is decided. */
function bandHtml(group) {
  const first = group.rows[0];
  const flow = !sortColumn();
  // The unplaced band's label *is* its title, so it says its name once rather
  // than "Not yet placed · Not yet placed".
  const numbered = first.step_label && first.step_label !== first.step_title;
  const named = `<span class="band-title">${esc(first.step_title)}</span>`;
  const title = !flow || !first.step_title
    ? esc(group.label)
    : numbered ? `${esc(group.label)} · ${named}` : named;
  const description = flow && first.step_description
    ? `<span class="band-note drop-md">${esc(first.step_description)}</span>`
    : "";
  return `<tr class="band"><td colspan="${COLUMNS.length}">${title}${description}<span
     class="note">${group.rows.length} component${
       group.rows.length === 1 ? "" : "s"}</span></td></tr>`;
}

function bodyHtml(rows) {
  if (!rows.length) {
    return `<tr><td class="empty" colspan="${COLUMNS.length}">
         No components match these filters.
       </td></tr>`;
  }
  const label = bandKey();
  if (!label) return rows.map(rowHtml).join("");
  // Grouped as they come, so a step filtered down to nothing leaves no empty
  // band, and a visible gap — Step 1, Step 2, Step 8 — reports honestly what
  // the filter took out.
  const groups = [];
  for (const row of rows) {
    if (!groups.length || groups.at(-1).label !== label(row)) {
      groups.push({ label: label(row), rows: [] });
    }
    groups.at(-1).rows.push(row);
  }
  return groups.map((group) =>
    bandHtml(group) + group.rows.map(rowHtml).join("")).join("");
}

function orderHtml() {
  const column = sortColumn();
  if (!column) return "Ordered by stage";
  const words = column.words ?? ["A to Z", "Z to A"];
  // The button is the only way back when a narrow window has hidden the
  // column whose header would otherwise complete the cycle.
  return `Sorted by ${esc(column.label)}, ${words[state.dir === "asc" ? 0 : 1]}
    <button type="button" id="unsort" title="Back to stage order">✕</button>`;
}

/* The sticky header sits directly under the sticky filter bar, and the bar's
   height is not a constant: it wraps to two lines at the widths where the
   order label and the filters no longer fit on one. Measured rather than
   guessed, because a wrong offset hides the first row under the bar. */
function measureFilters() {
  const bar = document.querySelector(".filters");
  if (!bar) return;
  document.documentElement.style.setProperty(
    "--filters-height", `${Math.round(bar.getBoundingClientRect().height)}px`);
}

function render() {
  const rows = sortRows(visibleRows());
  document.getElementById("count").textContent =
    `${rows.length} of ${DATA.rows.length} components`;
  document.getElementById("order").innerHTML = orderHtml();
  document.getElementById("thead").innerHTML = headHtml();
  const body = document.getElementById("tbody");
  body.innerHTML = bodyHtml(rows);
  for (const el of document.querySelectorAll("[data-bind]")) {
    const key = el.dataset.bind;
    if (el.type === "checkbox") el.checked = state[key];
    else el.value = state[key];
  }
  document.getElementById("details-toggle").setAttribute("aria-pressed", state.details);
  measureFilters();
}

function findingSentence() {
  const tally = DATA.source_tally ?? {};
  const total = Object.values(tally).reduce((a, b) => a + b, 0);
  const named = ["openapi", "status", "smartapi", "helm"]
    .filter((key) => tally[key])
    .map((key) => `<strong>${tally[key]}</strong> from ${esc(DATA.source_labels[key] ?? key)}`);
  const none = tally.none
    ? `, and <strong>${tally.none}</strong> from nothing at all`
    : "";
  if (!total) return "No deployments were found — has <code>sync-components</code> run?";
  const gaps = DATA.unregistered_count
    ? ` <strong>${DATA.unregistered_count}</strong> of them are missing from their
       component's SmartAPI record, which does list other environments — found by
       trying the conventional ITRB hostname and confirmed by the infores they
       report.`
    : "";
  return `Of ${total} deployments, ${named.join(", ")}${none}.${gaps}`;
}

function driftSentence() {
  const drifting = DATA.rows.filter(hasDrift);
  if (!drifting.length) return "Every component reports the same version in every environment.";
  const names = drifting.map((r) => `<a href="#c-${esc(r.id)}">${esc(r.id)}</a>`);
  return `${drifting.length} disagree across environments: ${names.join(", ")}.`;
}

/* Says that something is missing, without listing it. A page that quietly
   drops rows is worse than one that shows fewer: a reader counting components
   against the repository should find the difference explained here rather than
   assume the table is everything. Absent on a full local build. */
function withheldNote() {
  const held = DATA.redacted;
  if (!held) return "";
  const parts = [];
  if (held.components) parts.push(`${held.components} components`);
  const fields = [...(held.fields ?? []), ...(held.environment_fields ?? [])];
  if (fields.length) parts.push(`the ${fields.map(esc).join(" and ")} fields`);
  if (!parts.length) return "";
  return ` This build withholds ${parts.join(" and ")}; see
    <code>config/privacy.yaml</code>.`;
}

function shell() {
  const owners = unique(DATA.rows.map((r) => r.owner));
  const option = (value, selected) =>
    `<option value="${esc(value)}"${value === selected ? " selected" : ""}>${esc(value)}</option>`;
  const counts = DATA.sync_counts ?? {};

  document.getElementById("app").innerHTML = `
  <div class="wrap">
    <header>
      <div class="grow">
        <h1>Translator components overview</h1>
        <p class="subtitle">
          One row per recorded component, in stages — data coming in at the top, the
          people who use it at the bottom. Synced ${esc(DATA.synced_at || "never")}.
        </p>
      </div>
      <button id="theme" class="icon"></button>
    </header>

    <div class="finding">
      <h2>Where the version numbers came from</h2>
      <p>${findingSentence()}</p>
      <p style="margin-top:6px">${driftSentence()}</p>
    </div>

    <div class="tiles">
      <div class="tile"><div class="label">Components</div>
        <div class="value">${DATA.rows.length}</div></div>
      <div class="tile"><div class="label">Deployments</div>
        <div class="value">${DATA.rows.reduce((n, r) =>
          n + ENVS.filter((e) => r.environments[e]?.deployed).length, 0)}</div></div>
      <div class="tile"><div class="label">Fetches</div>
        <div class="value">${counts.succeeded ?? 0}<span class="note"> / ${
          counts.attempted ?? 0}</span></div>
        <div class="note">${counts.failed ?? 0} failed</div></div>
      <div class="tile"><div class="label">OTel services</div>
        <div class="value">${DATA.otel_service_total ?? 0}</div>
        <div class="note">distinct across ${
          Object.entries(DATA.otel_service_counts ?? {})
            .map(([env, n]) => `${esc(env)} ${n}`).join(", ")}</div></div>
    </div>

    <div class="filters">
      <input type="search" data-bind="q" placeholder="Search components, versions, ids…"
             aria-label="Search">
      <select data-bind="owner" aria-label="Owner">
        <option value="">All owners</option>${owners.map((o) => option(o, state.owner)).join("")}
      </select>
      <select data-bind="versions" aria-label="Which components to show">
        ${Object.entries(VERSION_VIEWS)
          .map(([key, view]) => `<option value="${esc(key)}"${
            key === state.versions ? " selected" : ""}>${esc(view.label)}</option>`)
          .join("")}
      </select>
      <button id="details-toggle" aria-pressed="true">Details</button>
      <button id="reset" class="action">Reset</button>
      <button id="copy" class="action">Copy link</button>
      <span class="spacer"></span>
      <span class="status">
        <span class="order" id="order"></span>
        <span class="count" id="count"></span>
      </span>
    </div>

    <div class="card">
      <table>
        <thead id="thead"></thead>
        <tbody id="tbody"></tbody>
      </table>
    </div>

    <footer>
      A tinted cell disagrees with the rest of its row — the odd one out, or every
      one of them when there is no odd one out — and a badge on a value says where
      it was read from. A left bar marks a component whose
      dependencies nothing records. In Repository, each tag links to that release's
      notes, and a filled tag is running in one of the environments on its row. Ages
      are counted from your clock to the exact date in the tooltip, and they date a
      release or a registration — nothing here knows when an environment was last
      deployed. Click any header to sort; a third click returns to stage order.
      Generated by <code>build-dashboard</code>.${withheldNote()}
    </footer>
  </div>`;
}

/* --- Wiring -------------------------------------------------------------- */

function wire() {
  for (const el of document.querySelectorAll("[data-bind]")) {
    const key = el.dataset.bind;
    const event = el.tagName === "SELECT" ? "change" : "input";
    el.addEventListener(event, () => {
      state[key] = el.type === "checkbox" ? el.checked : el.value;
      writeUrl();
      render();
    });
  }
  const toggle = (id, key) =>
    document.getElementById(id).addEventListener("click", () => {
      state[key] = !state[key];
      writeUrl();
      render();
    });
  toggle("details-toggle", "details");

  document.getElementById("reset").addEventListener("click", () => {
    Object.assign(state, {
      q: "", owner: "", versions: DEFAULT_VIEW,
      sort: "", dir: "asc",
    });
    writeUrl();
    render();
  });

  // Delegated, because render() rewrites the header on every change and a
  // handler bound to a th would be thrown away with it.
  document.getElementById("thead").addEventListener("click", (event) => {
    const button = event.target.closest("button[data-col]");
    if (!button) return;
    const column = COLUMNS.find((c) => c.key === button.dataset.col);
    const preferred = column.prefer ?? "asc";
    if (state.sort !== column.key) {
      state.sort = column.key;
      state.dir = preferred;
    } else if (state.dir === preferred) {
      state.dir = preferred === "asc" ? "desc" : "asc";
    } else {
      // Third click goes home. Without it, stage order — the order the page
      // is built to argue for — would be unreachable once you left it.
      state.sort = "";
      state.dir = "asc";
    }
    writeUrl();
    render();
  });

  document.getElementById("order").addEventListener("click", (event) => {
    if (!event.target.closest("#unsort")) return;
    state.sort = "";
    state.dir = "asc";
    writeUrl();
    render();
  });

  document.getElementById("copy").addEventListener("click", async (event) => {
    const button = event.currentTarget;
    try {
      await navigator.clipboard.writeText(location.href);
      button.textContent = "Copied";
    } catch {
      button.textContent = "Press ⌘C";
    }
    setTimeout(() => { button.textContent = "Copy link"; }, 3000);
  });

  document.getElementById("theme").addEventListener("click", () => {
    const choice = nextTheme(currentTheme());
    try { localStorage.setItem("theme", choice); } catch { /* storage unavailable */ }
    applyTheme(choice);
  });

  // Following the system means following it while the page is open: someone
  // reading this at dusk has their machine switch under them.
  matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => {
    if (currentTheme() === "auto") applyTheme("auto");
  });
}

readUrl();
shell();
wire();
renderTheme();
render();
addEventListener("resize", measureFilters);
// Only now: everything above can set state without the URL fighting it back.
urlReady = true;
