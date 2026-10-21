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
     Component view's rule and the map's rail all draw the same four stops. */
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

  /* What every view says about a row the same way. The table, the Component
     view and the map each used to carry their own copy of these, and a label
     that drifts between two views reads as two different facts. */

  let rowIndex = null;

  /* The row with this id, or null. Indexed once per payload rather than
     searched: the tooltips, the Component view and the map all look rows up
     by id, some of them on every hover. */
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

  /* A component's recorded connections, in four groups in data-flow order:
     what it gets results from, what it provides them to, what it calls and
     what calls it. The second and fourth are read off the other rows, since
     a component file records only its own outgoing edges. In each group the
     planned ones follow the implemented ones. The Component view and the
     table's expanded row both draw these. */
  const CONNECTION_GROUPS = [
    { key: "gets_results_from", title: "Gets results from", own: "gets_results_from" },
    { key: "provides_results_to", title: "Provides results to", reverse: "gets_results_from" },
    { key: "calls", title: "Calls", own: "calls" },
    { key: "called_by", title: "Called by", reverse: "calls" },
  ];

  function connections(row) {
    const id = (row || {}).id;
    const own = (row || {}).connections || {};
    const all = (TD.DATA || {}).rows || [];
    const ids = (field) => (Array.isArray(own[field]) ? own[field] : []);
    const pointingHere = (field) => all
      .filter((other) => other.id !== id
        && ((other.connections || {})[field] || []).indexOf(id) >= 0)
      .map((other) => other.id);
    return CONNECTION_GROUPS.map((group) => {
      const pick = group.own ? ids : pointingHere;
      const field = group.own || group.reverse;
      return {
        key: group.key,
        title: group.title,
        items: pick(field).map((other) => ({ id: other, planned: false }))
          .concat(pick(`planned_${field}`).map((other) => ({ id: other, planned: true }))),
      };
    });
  }

  TD.row = { byId: rowById, ownerLabel, repoLabel, updatedLabel, arrow, reach, connections };

  /* --- The cell model ---------------------------------------------------- */

  /* Everything a renderer needs to know about one environment of one
     component, in one shape, so the table cell, its tooltip and the expanded
     row cannot disagree (issue #78: four renderers once did). Always an
     object: a missing environment is simply not deployed, with no facts.

     `facts` is the ordered, null-pruned list the expansion and the tooltip
     iterate, so a new per-environment payload key reaches both by being
     added here. Version, source, reachability, the reason and the two flags
     are named fields instead, because the row shows them and the tooltip
     prints them first. */

  /* Where a version was read from, as a reader would say it, and the short
     form that fits beside the number. The payload's own `source_labels`
     (OpenAPI, status, SmartAPI, Helm) stay the contract; these are the
     page's words for the same keys. */
  const SOURCE_WORDS = {
    openapi: "its API document",
    status: "its /status page",
    smartapi: "the SmartAPI registry",
    helm: "the Helm chart",
  };
  const SOURCE_SHORT = { openapi: "API", status: "status", smartapi: "registry", helm: "chart" };

  /* The document the version was read from, so the cell can link to it. */
  const VERSION_DOC = {
    openapi: (row, cell) => cell.openapi_url,
    status: (row, cell) => cell.status_url,
    smartapi: (row) => (row.smartapi_record || {}).registry_url,
    helm: (row) => ((row.helm_charts || [])[0] || {}).source_url,
  };

  const DOCUMENT_WORDS = {
    version: "has a version",
    "no-version": "document has no version",
    "not-json": "serves HTML, not JSON",
  };

  /* An absence the page is sure of, as against one that is a gap in its own
     data: a hostname that does not resolve, a registry that lists other
     environments and not this one, a component that runs on no server. */
  const KNOWN_ABSENT = ["no-such-host", "not-registered", "not-hosted"];

  function recentQueries(value) {
    if (!value || typeof value.count !== "number") return "";
    const parts = [`${value.count.toLocaleString()} queries`];
    if (value.p50_ms != null) parts.push(`p50 ${value.p50_ms} ms`);
    if (value.p95_ms != null) parts.push(`p95 ${value.p95_ms} ms`);
    return parts.join(" · ");
  }

  function cellModel(row, env) {
    const cell = ((row || {}).environments || {})[env] || {};
    const source = cell.version_source || "";
    const otel = ((row || {}).otel_presence || [])
      .filter((p) => (p.seen_in || []).includes(env)).map((p) => p.service);
    // Each fact says where it comes from (`about`): the (?) beside its label
    // in the expanded row shows that sentence, so a new fact explains itself.
    const facts = [
      { label: "TRAPI", value: cell.trapi, src: cell.trapi_source,
        about: "The TRAPI version the deployment's own API document declares (x-trapi.version), or failing that the SmartAPI registration's copy." },
      { label: "Biolink", value: cell.biolink,
        about: "The Biolink Model version the API document declares (x-translator.biolink-version), or failing that the registration's." },
      { label: "Data release", value: cell.data_release, href: href(cell.status_url),
        about: "From the deployment's /status page: the Babel release it has loaded, and the Biolink model tag where the page reports one." },
      { label: "Released", value: cell.released, href: href(cell.release_url), note: cell.release_tag,
        about: "The GitHub release whose tag matches the version running here, and the day it was published." },
      { label: "Host", value: cell.url ? host(cell.url) : "", href: href(cell.url), mono: true,
        about: "The deployment's address, from its catalog file or from the SmartAPI registration." },
      { label: "Location", value: cell.location,
        about: "Who hosts it: the catalog file's word, or the registration's x-location." },
      { label: "API document", value: DOCUMENT_WORDS[cell.document] || "",
        href: href(cell.openapi_url), note: cell.http_status != null ? `HTTP ${cell.http_status}` : "",
        about: "What fetching the OpenAPI document returned this sync: a version, a document with none, or a web page instead of JSON, with the HTTP status." },
      { label: "Root URL", value: cell.root_status != null ? `HTTP ${cell.root_status}` : "",
        about: "The HTTP status the deployment's own URL answered with this sync; what says it is up when there is no document to read." },
      { label: "Title", value: cell.openapi_title, about: "The title the API document gives itself." },
      { label: "Paths", value: cell.paths_count, about: "How many paths the API document lists." },
      { label: "Operations", value: (cell.trapi_operations || []).length || "",
        about: "How many TRAPI operations the API document declares (x-trapi.operations)." },
      { label: "Async query",
        value: typeof cell.asyncquery === "boolean" ? (cell.asyncquery ? "yes" : "no") : "",
        about: "Whether the API document declares support for asynchronous queries (x-trapi.asyncquery)." },
      { label: "Recent queries", value: recentQueries(cell.recent_queries),
        about: "From the /status page: how many queries the service has answered lately, and its median and 95th-percentile latency." },
      { label: "Status message", value: cell.status_message,
        about: "The sentence the /status page reports about the service." },
      { label: "Telemetry", value: otel.join(", "),
        about: "The service names this component reports under that were seen at this environment's OpenTelemetry collector." },
    ]
      .filter((f) => f.value != null && f.value !== "")
      .map((f) => ({ ...f, value: String(f.value) }));
    return {
      deployed: !!cell.deployed,
      version: cell.version || "",
      source,
      sourceLabel: source ? sourceLabel(source) : "",
      sourceWord: SOURCE_WORDS[source] || source,
      sourceShort: SOURCE_SHORT[source] || source,
      live: source === "openapi" || source === "status",
      href: href(VERSION_DOC[source] ? VERSION_DOC[source](row || {}, cell) : ""),
      reach: reach(cell),
      drift: cell.drift || [],
      reason: cell.reason || "",
      reasonKey: cell.reason_key || "",
      knownAbsent: KNOWN_ABSENT.includes(cell.reason_key),
      dataRelease: cell.data_release || "",
      flags: { inferred: !!cell.inferred, unregistered: !!cell.unregistered },
      facts,
    };
  }

  TD.cell = cellModel;

  /* --- SmartAPI registration --------------------------------------------- */

  /* What a reader should do about a component's SmartAPI registration, in one
     answer the table's cell, its sort and its tooltip all read. The column
     used to say "registered" for every record whatever state it was in, and
     drew the registry's "unknown" as red: a record whose paths the registry
     skipped looked exactly like one whose probe failed.

     The states are listed worst first, and `rank` is that order, so sorting
     the column is the triage list. A record can have several problems (a
     shepherd is both missing an environment and unprobed): `problems` holds
     them all, worst first, and the state is the first. `dot` is the class of
     the dot in front, or null for none: green is kept for a probe that
     passed, and "unknown" is grey because nothing failed. */
  const SMARTAPI_STATES = {
    missing: { group: "SmartAPI record not found", dot: "warn" },
    failing: { group: "Registry probe failing", dot: "down" },
    unlisted: { group: "Deployments missing from the record", dot: "warn" },
    unprobed: { group: "Not probed by the registry", dot: "" },
    candidates: { group: "Possible records, none recorded", dot: null },
    none: { group: "Not registered", dot: null },
    ok: { group: "Registered", dot: null },
    "n/a": { group: "Not an API", dot: null },
  };
  const SMARTAPI_ORDER = Object.keys(SMARTAPI_STATES);

  /* The probe's own lines, with its traffic-light emoji: 🔴 failed, 🟠
     skipped, 🟢 passed. */
  const probeLines = (record, light) =>
    ((record.status || {}).uptime_msg || []).filter((line) => String(line).startsWith(light));

  function smartapiProblems(row, record) {
    const status = record.status || {};
    const problems = [];
    if (status.uptime_status === "fail") {
      problems.push({ key: "failing", word: "probe failing",
        note: "The registry's last probe of this API failed on at least one path." });
    }
    const unlisted = (TD.ENVS || []).filter((env) => cellModel(row, env).flags.unregistered);
    if (unlisted.length) {
      problems.push({ key: "unlisted", word: `${unlisted.join(", ")} not listed`,
        note: `Deployed in ${unlisted.join(", ")}, but the record lists no server there.` });
    }
    if (status.uptime_status === "unknown") {
      const lines = status.uptime_msg || [];
      const skipped = lines.length && lines.every((line) => String(line).includes("(skipped)"));
      problems.push({ key: "unprobed", word: "not probed",
        note: skipped
          ? "The registry skipped every path: the registration gives it no example requests to send."
          : "The registry's probe could not tell whether this API is up." });
    }
    return problems;
  }

  function smartapiStatus(given) {
    const row = given || {};
    const record = row.smartapi_record;
    const identifiers = (row.recorded || {}).identifiers || {};
    let key;
    let word;
    let problems = [];
    let url = "";
    if (record) {
      problems = smartapiProblems(row, record);
      key = problems.length ? problems[0].key : "ok";
      word = problems.length ? problems[0].word : "registered";
      url = record.registry_url;
    } else if (row.smartapi) {
      key = "missing";
      word = "record not found";
      problems = [{ key, word,
        note: "The catalog records this SmartAPI id, but no Translator-tagged record has it: it may have been deleted, or lost its translator tag." }];
      url = `https://smart-api.info/ui/${row.smartapi}`;
    } else if ((row.smartapi_candidates || []).length) {
      key = "candidates";
      word = `${row.smartapi_candidates.length} possible records`;
    } else if ("smartapi" in identifiers && identifiers.smartapi === null) {
      // `smartapi: null` in a component file: checked, and there is none to have.
      key = "n/a";
      word = "not an API";
    } else {
      key = "none";
      word = "not registered";
    }
    const state = SMARTAPI_STATES[key];
    const ok = key === "ok" && ((record || {}).status || {}).uptime_status === "pass";
    return {
      key,
      word,
      rank: SMARTAPI_ORDER.indexOf(key),
      group: state.group,
      dot: ok ? "up" : state.dot,
      problems,
      href: href(url),
      changed: ((record || {}).meta || {}).last_updated || "",
      probed: ((record || {}).status || {}).uptime_ts || "",
      failures: record ? probeLines(record, "🔴") : [],
    };
  }

  TD.smartapi = { status: smartapiStatus, STATES: SMARTAPI_STATES };

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

  /* The figures behind the sync note. Shares, not counts: a count of
     deployments has nothing to be compared to, but "40 of 49 reachable"
     says how much of the platform has a property, and each share names the
     Show view that lists the rest. Data, not HTML, so a test can read it.

     Denominators: reachable is up over up + down, so a cell nothing probed
     counts in neither; with-a-version is over deployed cells; listed-in-
     record is over deployed cells on rows with a recorded SmartAPI id, the
     same gate rows.py uses for `unregistered`; the two component shares are
     over rows. One mismatch to know: `none` is a row view (no version in any
     environment) while its share counts cells. */
  function figures(data) {
    const rows = data.rows || [];
    const envs = Array.isArray(data.environments) && data.environments.length
      ? data.environments : DEFAULT_ENVS;
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
      checks: {
        attempted: counts.attempted ?? 0, succeeded: counts.succeeded ?? 0, failed: counts.failed ?? 0,
      },
      shares: [
        share("deployments reachable",
          probed.filter((c) => c.m.reach === "up").length, probed.length, "unreachable"),
        share("deployments with a version read",
          deployed.filter((c) => c.m.version).length, deployed.length, "none"),
        share("deployments listed in their SmartAPI record",
          onRecord.filter((c) => !c.m.flags.unregistered).length, onRecord.length, "unregistered"),
        share("components with a SmartAPI record",
          rows.filter((r) => r.smartapi_record).length, rows.length, "no-smartapi"),
        share("components running the same version everywhere",
          rows.filter((r) => !envs.some((env) => cellModel(r, env).drift.length)).length,
          rows.length, "differ"),
      ].filter((s) => s.of > 0),
      otel: {
        total: data.otel_service_total ?? 0,
        perEnv: Object.entries(data.otel_service_counts || {}),
      },
      sources: ["openapi", "status", "smartapi", "helm"].filter((k) => tally[k])
        .map((k) => `${tally[k]} from ${SOURCE_WORDS[k]}`)
        .concat(tally.none ? [`${tally.none} from nowhere`] : []),
    };
  }

  TD.summary = { figures };

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

  const VIEWS = ["overview", "map", "component"];
  const VERSIONS = ["all", "differ", "known", "none", "unreachable", "unregistered", "no-smartapi"];
  const BASE_SORTS = ["name", "owner", "repo", "smartapi"];
  const EDGE_KINDS = ["results", "calls", "planned", "externals", "crosscutting", "catalog"];

  const DEFAULTS = {
    view: "overview",
    q: "",
    owner: [],
    versions: "all",
    sort: "",          // empty means the payload's own order, which is by stage
    dir: "asc",
    expand: [],
    sel: "",           // the component looked at: its page, its table row, its map node
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
    // `tab` named the drawer's tab; the drawer is gone and the Component
    // view shows every section at once, so an old link's tab is ignored.
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
    if (edges) params.set("edges", edges);
    // Commas are legal in a query string and this page's are all list
    // separators; leaving them encoded makes a shared link unreadable.
    return params.toString().replace(/%2C/g, ",");
  }

  TD.url = { DEFAULTS, defaults, vocabulary, parse, serialize };
})();
