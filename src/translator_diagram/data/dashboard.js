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
  layer: "",
  type: "",
  driftOnly: false,
  details: true,
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
  state.layer = (p.get("layer") ?? "").slice(0, 100);
  state.type = (p.get("type") ?? "").slice(0, 40);
  state.driftOnly = p.get("drift") === "1";
  state.details = p.get("details") !== "0";
}

function writeUrl() {
  // Watchers fire during setup too; without this guard the first render would
  // rewrite the URL and discard the state a shared link asked for.
  if (!urlReady) return;
  const p = new URLSearchParams();
  if (state.q.trim()) p.set("q", state.q.trim());
  if (state.owner) p.set("owner", state.owner);
  if (state.layer) p.set("layer", state.layer);
  if (state.type) p.set("type", state.type);
  if (state.driftOnly) p.set("drift", "1");
  if (!state.details) p.set("details", "0");
  const query = p.toString();
  history.replaceState(null, "", query ? `?${query}` : location.pathname);
}

/* --- Filtering ----------------------------------------------------------- */

function hasDrift(row) {
  return ENVS.some((env) => (row.environments[env]?.drift ?? []).length > 0);
}

function visibleRows() {
  const needle = state.q.trim().toLowerCase();
  return DATA.rows
    .filter((row) => !state.owner || row.owner === state.owner)
    .filter((row) => !state.layer || (row.layer ?? "") === state.layer)
    .filter((row) => !state.type || (row.type ?? "") === state.type)
    .filter((row) => !state.driftOnly || hasDrift(row))
    .filter((row) => {
      if (!needle) return true;
      const haystack = [
        row.id, row.name, row.owner, row.layer, row.type, row.infores,
        row.helm_chart, ...(row.otel_services ?? []),
        ...(row.releases ?? []).map((r) => r.tag),
        ...ENVS.map((env) => row.environments[env]?.version),
      ];
      return haystack.some((v) => String(v ?? "").toLowerCase().includes(needle));
    });
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

function rowHtml(row) {
  const externals = (row.externals ?? [])
    .map((e) => `<span class="chip">${e.direction === "in" ? "◀" : "▶"} ${esc(e.name)}</span>`)
    .join(" ");

  return `<tr class="${row.isolated ? "isolated" : ""}" id="c-${esc(row.id)}">
    <td>
      <span class="component">${esc(row.name)}</span>
      <span class="cid">${esc(row.id)}</span>
      ${externals}
    </td>
    <td><span class="owner" data-owner="${esc(row.owner)}">${esc(row.owner)}</span></td>
    <td class="meta drop-sm">${or(row.type, esc(row.type))}</td>
    <td class="meta drop-md">${or(row.layer, esc(row.layer))}</td>
    <td class="meta drop-md">${repoCell(row)}</td>
    ${ENVS.map((env) => envCell(row, env)).join("")}
  </tr>`;
}

function render() {
  const rows = visibleRows();
  document.getElementById("count").textContent =
    `${rows.length} of ${DATA.rows.length} components`;
  const body = document.getElementById("tbody");
  body.innerHTML = rows.length
    ? rows.map(rowHtml).join("")
    : `<tr><td class="empty" colspan="${5 + ENVS.length}">
         No components match these filters.
       </td></tr>`;
  for (const el of document.querySelectorAll("[data-bind]")) {
    const key = el.dataset.bind;
    if (el.type === "checkbox") el.checked = state[key];
    else el.value = state[key];
  }
  document.getElementById("drift-toggle").setAttribute("aria-pressed", state.driftOnly);
  document.getElementById("details-toggle").setAttribute("aria-pressed", state.details);
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

function shell() {
  const owners = unique(DATA.rows.map((r) => r.owner));
  const layers = unique(DATA.rows.map((r) => r.layer));
  const types = unique(DATA.rows.map((r) => r.type));
  const option = (value, selected) =>
    `<option value="${esc(value)}"${value === selected ? " selected" : ""}>${esc(value)}</option>`;
  const counts = DATA.sync_counts ?? {};

  document.getElementById("app").innerHTML = `
  <div class="wrap">
    <header>
      <div class="grow">
        <h1>Translator components overview</h1>
        <p class="subtitle">
          One row per recorded component, ordered the way data flows — sources at the top,
          the user at the bottom. Synced ${esc(DATA.synced_at || "never")}.
        </p>
      </div>
      <button id="theme">Theme</button>
      <button id="copy">Copy link</button>
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
      <select data-bind="layer" aria-label="Layer">
        <option value="">All layers</option>${layers.map((l) => option(l, state.layer)).join("")}
      </select>
      <select data-bind="type" aria-label="Type">
        <option value="">All types</option>${types.map((t) => option(t, state.type)).join("")}
      </select>
      <button id="drift-toggle" aria-pressed="false">Drift only</button>
      <button id="details-toggle" aria-pressed="true">Details</button>
      <button id="reset">Reset</button>
      <span class="spacer"></span>
      <span class="count" id="count"></span>
    </div>

    <div class="card">
      <table>
        <thead>
          <tr>
            <th>Component</th>
            <th>Owner</th>
            <th class="drop-sm">Type</th>
            <th class="drop-md">Layer</th>
            <th class="drop-md">Repository</th>
            ${ENVS.map((e) => `<th class="env">${esc(e)}</th>`).join("")}
          </tr>
        </thead>
        <tbody id="tbody"></tbody>
      </table>
    </div>

    <footer>
      A tinted cell is the odd one out for that component across environments.
      A badge on a version says where it was read from; a left bar marks a component
      with no recorded dependencies. In Repository, each tag links to that release's
      notes, and a filled tag is running in one of the environments on its row.
      Generated by <code>build-dashboard</code>.
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
  toggle("drift-toggle", "driftOnly");
  toggle("details-toggle", "details");

  document.getElementById("reset").addEventListener("click", () => {
    Object.assign(state, { q: "", owner: "", layer: "", type: "", driftOnly: false });
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
    const next = { light: "dark", dark: "auto", auto: "light" };
    const root = document.documentElement;
    const choice = next[root.dataset.themeChoice ?? "auto"];
    root.dataset.themeChoice = choice;
    try { localStorage.setItem("theme", choice); } catch { /* storage unavailable */ }
    const dark = choice === "dark" ||
      (choice === "auto" && matchMedia("(prefers-color-scheme: dark)").matches);
    root.dataset.theme = dark ? "dark" : "light";
  });
}

readUrl();
shell();
wire();
render();
// Only now: everything above can set state without the URL fighting it back.
urlReady = true;
