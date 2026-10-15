/*
  The pure half of the page: URL state, sorting, formatting, motion
  preference, owner colour, and the payload handoff.

  Nothing in this file touches the DOM at definition time, and nothing here
  reads `document`, `location` or `window` at all. That is not tidiness for
  its own sake: it is what lets `tests/web/*.test.js` load this file into a
  bare Node context with `vm.runInThisContext` and drive the URL round-trip
  and the sort comparators over real values, with no browser and no stubs.

  Everything is hung off one global, `TD`, because the page ships every script
  concatenated into a single <script> (it must open from file://, where
  `import` needs a server) and one namespace is cheaper to reason about than
  a dozen top-level names in a shared scope.
*/

(() => {
  "use strict";

  const TD = (globalThis.TD = globalThis.TD || {});

  /* --- Payload ----------------------------------------------------------- */

  const DEFAULT_ENVS = ["dev", "ci", "test", "prod"];

  /* Called once by app.js. Every other file reads TD.DATA / TD.ENVS, so the
     payload is parsed in exactly one place and a build with an older sync
     cache — where half the keys below are simply absent — still boots. */
  TD.boot = function boot(payload) {
    TD.DATA = payload || {};
    rowIndex = null;
    TD.ENVS = Array.isArray(TD.DATA.environments) && TD.DATA.environments.length
      ? TD.DATA.environments
      : DEFAULT_ENVS;
    return TD.DATA;
  };

  /* --- Formatting -------------------------------------------------------- */

  const ENTITIES = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };

  const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (c) => ENTITIES[c]);

  /* Ages are measured against the reader's clock, not against the sync: a page
     opened in December is telling the truth when it says a release is four
     months old. The exact date is one hover away. */
  let ageFormat = null;
  const relative = () => {
    if (!ageFormat) ageFormat = new Intl.RelativeTimeFormat(undefined, { numeric: "always" });
    return ageFormat;
  };

  function relativeAge(iso, now = Date.now()) {
    const ms = now - Date.parse(iso);
    if (!Number.isFinite(ms)) return "";
    const days = ms / 86400000;
    // Clamped, so a clock slightly ahead of GitHub's says "today" rather than
    // "in 3 hours".
    if (days < 1) return "today";
    if (days < 14) return relative().format(-Math.round(days), "day");
    if (days < 60) return relative().format(-Math.round(days / 7), "week");
    if (days < 730) return relative().format(-Math.round(days / 30.44), "month");
    return relative().format(-Math.round(days / 365.25), "year");
  }

  /* The sync clock, which is usually hours old rather than months, so it needs
     a finer bottom end than a release date does. Kept separate rather than
     given to relativeAge: "the release running in prod is 3 hours old" is a
     claim this page cannot make, and blurring the two would let it. */
  function since(iso, now = Date.now()) {
    const ms = now - Date.parse(iso);
    if (!Number.isFinite(ms)) return "";
    const minutes = ms / 60000;
    if (minutes < 2) return "just now";
    if (minutes < 90) return relative().format(-Math.round(minutes), "minute");
    if (minutes < 1440) return relative().format(-Math.round(minutes / 60), "hour");
    return relativeAge(iso, now);
  }

  const plural = (n, one, many) => `${n} ${n === 1 ? one : many ?? `${one}s`}`;

  /* A bad URL would throw inside the row loop and blank the whole table, so
     the hostname is best-effort: the row is worth more than the tidy label. */
  function host(url) {
    try { return new URL(url).hostname; } catch { return String(url ?? ""); }
  }

  /* Only web links reach an href. These URLs come from GitHub and SmartAPI
     records other people edit, and escaping stops markup, not `javascript:`. */
  function href(url) {
    try {
      return /^https?:$/.test(new URL(url).protocol) ? String(url) : "";
    } catch { return ""; }
  }

  /* The payload's name for a version source, or the key itself. `data` is
     for the finding sentence, which is handed its payload so a test can. */
  const sourceLabel = (key, data = TD.DATA || {}) => (data.source_labels || {})[key] || key;

  /* A component's `description`: the small Markdown subset the schema allows.
     Blank lines separate blocks; a block whose first line starts with "- " is
     a list, and a line that does not continues the item above it. Inside a
     block, `code` and [text](url) are the only markup. Every other character
     is escaped, and a link whose URL is not http(s) is shown as its text.

     ponytail: no emphasis, headings, nested lists, tables or images, because
     nobody has written one into a component file. When a description needs
     them, inline a CommonMark library with a sanitiser rather than growing
     this; a hand-written parser stops being obviously safe soon after it stops
     being small. */
  const INLINE = /`([^`]+)`|\[([^\]]+)\]\(([^)\s]+)\)/g;

  function inline(text) {
    let html = "";
    let last = 0;
    for (const match of text.matchAll(INLINE)) {
      html += esc(text.slice(last, match.index));
      const [, code, label, url] = match;
      if (code !== undefined) {
        html += `<code>${esc(code)}</code>`;
      } else {
        const safe = href(url);
        html += safe
          ? `<a href="${esc(safe)}" target="_blank" rel="noopener">${esc(label)}</a>`
          : esc(label);
      }
      last = match.index + match[0].length;
    }
    return html + esc(text.slice(last));
  }

  function prose(text) {
    const blocks = String(text ?? "").replace(/\r\n?/g, "\n").split(/\n[ \t]*\n/);
    return blocks
      .map((block) => block.split("\n").map((line) => line.trim()).filter(Boolean))
      .filter((lines) => lines.length)
      .map((lines) => {
        if (!lines[0].startsWith("- ")) return `<p>${inline(lines.join(" "))}</p>`;
        const items = [];
        for (const line of lines) {
          if (line.startsWith("- ")) items.push(line.slice(2));
          else items[items.length - 1] += ` ${line}`;
        }
        return `<ul>${items.map((item) => `<li>${inline(item)}</li>`).join("")}</ul>`;
      })
      .join("");
  }

  TD.fmt = { esc, relativeAge, since, plural, host, href, prose, sourceLabel, DASH: '<span class="dash">—</span>' };

  /* --- Motion ------------------------------------------------------------ */

  /* Read lazily, and read every time: a reader can change the system setting
     while the page is open, and a value captured at load would go stale. */
  TD.motion = {
    get enabled() {
      if (typeof matchMedia !== "function") return false;
      try { return !matchMedia("(prefers-reduced-motion: reduce)").matches; } catch { return false; }
    },
  };

  /* --- Owner colour ------------------------------------------------------ */

  /* Base colour, readable text colour and the four metallic stops, all
     derived by colors.py from the one hex in catalog/owner-colors.csv. The
     payload is inlined into the same page as this script, so owner_styles is
     always there; an owner missing from it has no style. */
  function ownerStyle(name) {
    return ((TD.DATA || {}).owner_styles || {})[name] || null;
  }

  /* The brushed-metal gradient for one owner, at an angle: the coin, the
     drawer's rule and the map's rail all draw the same four stops. */
  function ownerMetal(name, angle) {
    const style = ownerStyle(name);
    return style ? `linear-gradient(${angle}, ${style.metal.join(", ")})` : "";
  }

  const HIGHLIGHT = "radial-gradient(circle at 32% 28%, rgba(255,255,255,.55), rgba(255,255,255,0) 62%)";

  function ownerCoin(name, extraClass) {
    const metal = ownerMetal(name, "135deg");
    const background = metal ? `${HIGHLIGHT}, ${metal}` : "";
    const cls = `coin${extraClass ? ` ${extraClass}` : ""}`;
    const style = background ? ` style="background:${background}"` : "";
    return `<span class="${cls}"${style} aria-hidden="true"></span>`;
  }

  TD.owner = { style: ownerStyle, metal: ownerMetal, coin: ownerCoin };

  /* --- Rows --------------------------------------------------------------- */

  /* What every view says about a row the same way. The table, the drawer and
     the map each used to carry their own copy of these, and a label that
     drifts between two views reads as two different facts. */

  let rowIndex = null;

  /* The row with this id, or null. Indexed once per payload rather than
     searched: the tooltips, the drawer and the map all look rows up by id,
     some of them on every hover. */
  function rowById(id) {
    if (!rowIndex) {
      rowIndex = new Map();
      for (const row of (TD.DATA || {}).rows || []) rowIndex.set(row.id, row);
    }
    return rowIndex.get(id) || null;
  }

  /* The owner's coin and name, as a chip. */
  const ownerLabel = (name) =>
    `<span class="ownercell">${ownerCoin(name)}<span>${esc(name)}</span></span>`;

  /* `owner/name` for a GitHub repository URL; anything else as it is. */
  const repoLabel = (url) => String(url ?? "").replace("https://github.com/", "");

  /* The payload's word for where a `last_updated` date came from. */
  const updatedLabel = (updated) =>
    ((TD.DATA || {}).updated_labels || {})[updated.source] || updated.source;

  /* An external's direction as the glyph every view draws it with. */
  const arrow = (direction) => (direction === "in" ? "◀" : "▶");

  /* "up", "down", or "" for a cell nothing probed: three states, because a
     host that was never contacted is not a host that failed. */
  const reach = (cell) =>
    (typeof (cell || {}).reachable === "boolean" ? (cell.reachable ? "up" : "down") : "");

  TD.row = { byId: rowById, ownerLabel, repoLabel, updatedLabel, arrow, reach };

  /* --- Theme ------------------------------------------------------------- */

  /* The cycle starts by moving *away* from what the system says, because the
     page opens following the system: ordering it auto → light → dark would
     spend the first click repainting a light machine light, which reads as a
     broken button rather than as a default worth keeping. */
  function nextTheme(choice, systemDark) {
    const differs = systemDark ? "light" : "dark";
    if (choice === "auto") return differs;
    return choice === differs ? (systemDark ? "dark" : "light") : "auto";
  }

  TD.theme = { next: nextTheme };

  /* --- The page's own summary of the payload ------------------------------ */

  /* Deployed cells, across every row and environment. The second stat tile;
     a count that once said 74 where there were 41, which is why it is here
     where a test can reach it rather than inline in the shell. */
  function deploymentCount(rows, envs) {
    return (rows || []).reduce(
      (n, row) => n + (envs || []).filter((env) => ((row.environments || {})[env] || {}).deployed).length,
      0,
    );
  }

  /* The first sentence on the page: how many deployments, and from which
     source each version was read. */
  function findingSentence(data) {
    const tally = data.source_tally || {};
    const total = Object.values(tally).reduce((a, b) => a + b, 0);
    const named = ["openapi", "status", "smartapi", "helm"]
      .filter((key) => tally[key])
      .map((key) => `<strong>${tally[key]}</strong> from ${esc(sourceLabel(key, data))}`);
    const none = tally.none
      ? `, and <strong>${tally.none}</strong> from nothing at all`
      : "";
    if (!total) return "No deployments were found — has <code>sync-components</code> run?";
    // The count is computed from the registry rather than from how the URL was
    // found, so it covers deployments recorded by hand and deployments
    // registered without an x-maturity as well as the ones a probe discovered.
    const gaps = data.unregistered_count
      ? ` <strong>${data.unregistered_count}</strong> of them are absent from their
         component's SmartAPI record, which does list other environments.`
      : "";
    return `Of ${total} deployments, ${named.join(", ")}${none}.${gaps}`;
  }

  TD.summary = { deployments: deploymentCount, finding: findingSentence };

  /* --- Sorting ----------------------------------------------------------- */

  const byText = (a, b) =>
    String(a).localeCompare(String(b), undefined, { numeric: true, sensitivity: "base" });

  // Explicit, not localeCompare: YYYY-MM-DD happens to collate correctly, but
  // only by accident, and an accident is a poor thing to sort dates on.
  const byDate = (a, b) => (a < b ? -1 : a > b ? 1 : 0);

  /* How stale an environment is, in tiers: running a release we can date,
     then running something no release names, then not deployed. Tiers are
     compared before the direction flip, so reversing the sort never lifts the
     blanks to the top. */
  function envRank(row, env) {
    const cell = (row.environments || {})[env];
    if (!cell || !cell.deployed) return 2;
    return cell.released ? 0 : 1;
  }

  function comparator(column, dir) {
    const flip = dir === "desc" ? -1 : 1;
    const compare = column.compare || byText;
    return (a, b) => {
      const ra = column.rank ? column.rank(a) : 0;
      const rb = column.rank ? column.rank(b) : 0;
      if (ra !== rb) return ra - rb;
      const av = column.value(a) || "";
      const bv = column.value(b) || "";
      // Before the flip, deliberately: reversing the sort must not promote the
      // thirteen components we have no date for to the top of the table.
      if (!av || !bv) return av ? -1 : bv ? 1 : 0;
      return flip * compare(av, bv);
    };
  }

  /* Sorts a copy, never the payload's own array: the count, the drift
     sentence and the stage bands all read DATA.rows in its own order.
     Array.prototype.sort is stable, so every tie falls back to that order —
     which is why sorting by owner leaves each owner's components in pipeline
     order. */
  function sortRows(rows, column, dir) {
    const copy = rows.slice();
    if (!column) return copy;
    return copy.sort(comparator(column, dir));
  }

  TD.sort = { byText, byDate, envRank, rows: sortRows };

  /* --- URL state --------------------------------------------------------- */

  const VIEWS = ["overview", "map"];
  const VERSIONS = ["all", "differ", "known", "none"];
  const BASE_SORTS = ["name", "owner", "repo", "updated"];
  const EDGE_KINDS = ["results", "calls", "planned", "externals", "crosscutting", "catalog"];

  const DEFAULTS = {
    view: "overview",
    q: "",
    owner: [],
    versions: "all",
    sort: "",          // empty means the payload's own order, which is by stage
    dir: "asc",
    expand: [],
    sel: "",
    tab: "",
    edges: [],
  };

  const defaults = () => ({ ...DEFAULTS, owner: [], expand: [], edges: [] });

  /* The environment columns are named by the payload, so the set of legal
     `sort` values is not a constant. Falls back to the four this platform has
     always had, which is what lets the unit tests call parse() with one
     argument and no payload. */
  function vocabulary() {
    const envs = Array.isArray(TD.ENVS) && TD.ENVS.length ? TD.ENVS : DEFAULT_ENVS;
    return {
      views: VIEWS,
      versions: VERSIONS,
      sorts: BASE_SORTS.concat(envs.map((env) => `env-${env}`)),
      edges: EDGE_KINDS,
    };
  }

  function commaList(value, limit) {
    return [...new Set(
      String(value ?? "").slice(0, limit).split(",").map((s) => s.trim()).filter(Boolean),
    )];
  }

  function parse(search, vocab) {
    const v = vocab || vocabulary();
    const state = defaults();
    const params = new URLSearchParams(String(search ?? "").replace(/^\?/, ""));
    const pick = (name, allowed, fallback) => {
      const value = params.get(name);
      return allowed.indexOf(value) >= 0 ? value : fallback;
    };

    state.view = pick("view", v.views, DEFAULTS.view);
    state.q = (params.get("q") ?? "").slice(0, 200);
    state.owner = commaList(params.get("owner"), 100);
    // A pasted URL can name anything; only a real view or a real sortable
    // column counts, and anything else quietly becomes the default rather
    // than an empty table nobody can explain.
    state.versions = pick("versions", v.versions, DEFAULTS.versions);
    state.sort = pick("sort", v.sorts, DEFAULTS.sort);
    state.dir = params.get("dir") === "desc" ? "desc" : "asc";
    // Without a column there is nothing to reverse, and a stray dir would
    // otherwise survive a round-trip that cannot write it back.
    if (!state.sort) state.dir = "asc";
    // `density` and its older spelling `details` are read and thrown away.
    // There is one row style now — the dense one, on a list-item surface — so
    // there is nothing for them to select, but a link someone pasted into
    // Slack last month still has to open on the same table rather than on an
    // error, which is why they are parsed at all and why serialize() never
    // writes them back.
    state.expand = commaList(params.get("expand"), 400);
    state.sel = (params.get("sel") ?? "").slice(0, 100);
    state.tab = (params.get("tab") ?? "").slice(0, 40);
    state.edges = commaList(params.get("edges"), 120)
      .filter((kind) => v.edges.indexOf(kind) >= 0);
    return state;
  }

  /* Only what differs from the default is written, so a shared link says what
     the sender changed and nothing else. `dir` is the exception: it is always
     written beside `sort`, because the first click's direction differs per
     column and "asc" is not a default a reader of the URL could infer. */
  function serialize(state, base) {
    const d = base || DEFAULTS;
    const params = new URLSearchParams();
    const q = (state.q ?? "").trim().slice(0, 200);
    const owner = (state.owner ?? []).join(",").slice(0, 100);
    const expand = (state.expand ?? []).join(",");
    const edges = (state.edges ?? []).join(",");

    if (state.view && state.view !== d.view) params.set("view", state.view);
    if (q && q !== (d.q ?? "").trim()) params.set("q", q);
    if (owner && owner !== (d.owner ?? []).join(",")) params.set("owner", owner);
    if (state.versions && state.versions !== d.versions) params.set("versions", state.versions);
    if (state.sort) {
      params.set("sort", state.sort);
      params.set("dir", state.dir === "desc" ? "desc" : "asc");
    }
    if (expand) params.set("expand", expand);
    if (state.sel) params.set("sel", state.sel);
    if (state.tab) params.set("tab", state.tab);
    if (edges) params.set("edges", edges);
    // Commas are legal in a query string and this page's are all list
    // separators; leaving them encoded makes a shared link unreadable.
    return params.toString().replace(/%2C/g, ",");
  }

  TD.url = { DEFAULTS, defaults, vocabulary, parse, serialize };
})();
