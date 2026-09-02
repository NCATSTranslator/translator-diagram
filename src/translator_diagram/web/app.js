/*
  The boot file: it runs last, and it is the only one that touches the page's
  own elements. It reads the payload, builds the shell, owns the shared state
  and the URL, and hands the views a container each.

  Everything a reader changes goes through `TD.commit`, which is the one place
  that writes the URL — so a view can be pasted into Slack and arrive as the
  sender saw it, and no control can quietly diverge from the address bar.
*/

(() => {
  "use strict";

  const TD = (globalThis.TD = globalThis.TD || {});
  const esc = (value) => TD.fmt.esc(value);
  const $ = (selector) => document.querySelector(selector);

  TD.boot(JSON.parse(document.getElementById("payload").textContent));
  const DATA = TD.DATA;
  const ENVS = TD.ENVS;

  /* --- State and URL -------------------------------------------------------- */

  TD.state = TD.url.parse(location.search);
  // Watchers fire during setup too; without this guard the first render would
  // rewrite the URL and discard the state a shared link asked for.
  let urlReady = false;

  function writeUrl() {
    if (!urlReady) return;
    const query = TD.url.serialize(TD.state);
    history.replaceState(null, "", query ? `?${query}${location.hash}` : location.pathname + location.hash);
  }

  TD.commit = function commit(patch, options) {
    Object.assign(TD.state, patch);
    writeUrl();
    if (!(options && options.silent)) refresh();
  };

  /* --- Theme ----------------------------------------------------------------- */

  /* Inline SVG rather than ☀/☾: those render as colour emoji on one platform
     and as a tofu box on another, and a page that must work from file:// cannot
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

  const systemPrefersDark = () => matchMedia("(prefers-color-scheme: dark)").matches;

  function currentTheme() {
    const choice = document.documentElement.dataset.themeChoice;
    return choice in THEME_NAMES ? choice : "auto";
  }

  /* The cycle starts by moving *away* from what the system says, because the
     page opens following the system: ordering it auto → light → dark would
     spend the first click repainting a light machine light, which reads as a
     broken button rather than as a default worth keeping. */
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
    if (!button) return;
    button.innerHTML = THEME_ICONS[choice];
    // The icon says which mode is on; the label has to say that *and* what the
    // click does, because an icon-only button otherwise announces nothing.
    const label = `Theme: ${THEME_NAMES[choice]} — switch to ${THEME_NAMES[nextTheme(choice)]}`;
    button.title = label;
    button.setAttribute("aria-label", label);
  }

  /* --- Brand mark ------------------------------------------------------------- */

  /* The two glyph paths of the Translator UI's own logo
     (NCATSTranslator/ui-fe, src/assets/images/Logo.svg): the plate and the
     wedge. The wordmark that follows them in the original is dropped — the
     title beside it already says the words. Fills are left to base.css so the
     mark follows the theme, and the whole thing is `aria-hidden` because the
     name is right there in text. */
  const BRAND_MARK = `<svg class="mark" viewBox="0 0 64.1 40" aria-hidden="true"
    xmlns="http://www.w3.org/2000/svg"><path class="wedge" d="M63.791 19.2182L54.0164
    2.04559C53.2974 0.78236 51.9407 0 50.4691 0H47.1602L58.0991 19.2182C58.3755 19.7039 58.3755
    20.2961 58.0991 20.7818L47.1602 40H50.4691C51.9407 40 53.2974 39.2176 54.0164
    37.9544L63.791 20.7818C64.0675 20.2961 64.0675 19.7039 63.791 19.2182Z"/><path class="plate"
    fill-rule="evenodd" clip-rule="evenodd" d="M4.06567 0H44.7224L55.6613 19.2182C55.9378 19.7039
    55.9378 20.2961 55.6613 20.7818L44.7224 40H4.06567C1.82026 40 0 38.2091 0 36V4C0 1.79086
    1.82026 0 4.06567 0ZM18.2574 29.6H22.0055V11.325H19.223V20.9375C19.2315 21.4875 19.2442
    22.0583 19.2611 22.65C19.2865 23.2333 19.312 23.8 19.3374 24.35C19.3628 24.9 19.3839 25.3875
    19.4009 25.8125H19.312L10.2277 11.325H6.50508V29.6H9.27482V20.05C9.25788 19.45 9.2367 18.8583
    9.21129 18.275C9.19435 17.6917 9.16894 17.125 9.13506 16.575C9.10965 16.025 9.08 15.5042
    9.04612 15.0125H9.16047L18.2574 29.6ZM24.5424 11.325V29.6H27.5917V11.325H24.5424ZM41.7667
    29.6H44.8032V11.325H41.7667V18.8H33.2033V11.325H30.1541V29.6H33.2033V21.35H41.7667V29.6Z"/>
    </svg>`;

  /* --- Prose ----------------------------------------------------------------- */

  function findingSentence() {
    const tally = DATA.source_tally || {};
    const total = Object.values(tally).reduce((a, b) => a + b, 0);
    const named = ["openapi", "status", "smartapi", "helm"]
      .filter((key) => tally[key])
      .map((key) => `<strong>${tally[key]}</strong> from ${
        esc((DATA.source_labels || {})[key] || key)}`);
    const none = tally.none
      ? `, and <strong>${tally.none}</strong> from nothing at all`
      : "";
    if (!total) return "No deployments were found — has <code>sync-components</code> run?";
    // The count is computed from the registry rather than from how the URL was
    // found, so it covers deployments recorded by hand and deployments
    // registered without an x-maturity as well as the ones a probe discovered.
    const gaps = DATA.unregistered_count
      ? ` <strong>${DATA.unregistered_count}</strong> of them are absent from their
         component's SmartAPI record, which does list other environments.`
      : "";
    return `Of ${total} deployments, ${named.join(", ")}${none}.${gaps}`;
  }

  function driftSentence() {
    const drifting = (DATA.rows || []).filter(TD.table.hasDrift);
    if (!drifting.length) return "Every component reports the same version in every environment.";
    const names = drifting.map((row) => `<a href="#c-${esc(row.id)}">${esc(row.id)}</a>`);
    return `${drifting.length} disagree across environments: ${names.join(", ")}.`;
  }

  /* Says that something is missing, without listing it. A page that quietly
     drops rows is worse than one that shows fewer: a reader counting
     components against the repository should find the difference explained
     here rather than assume the table is everything.

     It is the whole footer now. The reference paragraph that used to sit
     beside it described marks the table makes plain, and cost every reader a
     screenful to say so; this one line cannot be dropped, because a policy
     that hides rows without saying it did is not a policy. */
  function footerHtml() {
    const held = DATA.redacted;
    if (!held) return "";
    const parts = [];
    if (held.components) parts.push(TD.fmt.plural(held.components, "component"));
    const fields = [...(held.fields || []), ...(held.environment_fields || [])];
    if (fields.length) {
      parts.push(`the ${fields.map(esc).join(" and ")} ${
        fields.length === 1 ? "field" : "fields"}`);
    }
    if (!parts.length) return "";
    return `<footer>This build withholds ${parts.join(" and ")} ·
      <code>config/privacy.yaml</code></footer>`;
  }

  function statsHtml() {
    const counts = DATA.sync_counts || {};
    const deployments = (DATA.rows || []).reduce(
      (n, row) => n + ENVS.filter((env) => (row.environments || {})[env]?.deployed).length, 0);
    const perEnv = Object.entries(DATA.otel_service_counts || {})
      .map(([env, n]) => `${esc(env)} ${n}`).join(", ");
    const stat = (n, key) =>
      `<div class="stat"><span class="n" data-n="${n}">${n}</span><span class="k">${key}</span></div>`;
    return [
      stat(DATA.rows.length, "components"),
      stat(deployments, "deployments"),
      stat(counts.succeeded ?? 0,
        `of ${counts.attempted ?? 0} fetches<span class="qual"> · ${counts.failed ?? 0} failed</span>`),
      stat(DATA.otel_service_total ?? 0,
        `otel services${perEnv ? `<span class="qual"> · ${perEnv}</span>` : ""}`),
    ].join("");
  }

  /* --- Shell ------------------------------------------------------------------ */

  function shell() {
    const synced = DATA.synced_at
      ? `synced ${esc(TD.fmt.since(DATA.synced_at))}` : "never synced";
    document.getElementById("app").innerHTML = `
      <div class="topbar">
        <div class="brandmark">${BRAND_MARK}<span class="name">Translator components</span></div>
        <div id="viewswitch"></div>
        <div class="topright"><span class="synced" title="${esc(DATA.synced_at || "")}"
          >${synced}</span><button type="button" class="btn icon" id="theme"></button></div>
      </div>
      <main class="page">
        <div class="finding">
          <p>${findingSentence()}</p>
          <p>${driftSentence()}</p>
        </div>
        <div class="stats">${statsHtml()}</div>
        <div class="filters">
          <input type="search" id="q" placeholder="Search components, versions, ids…"
                 aria-label="Search components">
          <span id="f-owner"></span><span id="f-view"></span>
          <button type="button" class="btn" id="reset">Reset</button>
          <button type="button" class="btn" id="copy">Copy link</button>
          <span class="spacer"></span>
          <span class="status">
            <span class="order" id="order"></span>
            <span class="count" id="count" aria-live="polite"></span>
          </span>
        </div>
        <div class="view on" id="view-overview"></div>
        <div class="view" id="view-map"></div>
        ${footerHtml()}
      </main>`;
  }

  /* --- Controls --------------------------------------------------------------- */

  let viewSwitch = null;
  let ownerBox = null;
  let versionBox = null;

  function uniqueOwners() {
    return [...new Set((DATA.rows || []).map((row) => row.owner).filter(Boolean))]
      .sort((a, b) => a.localeCompare(b));
  }

  function controls() {
    viewSwitch = TD.ui.segmented({
      label: "View",
      items: [{ value: "overview", label: "Overview" }, { value: "map", label: "Map" }],
      value: TD.state.view,
      onChange: (value) => { TD.commit({ view: value }); showView(true); },
    });
    document.getElementById("viewswitch").append(viewSwitch.el);

    ownerBox = TD.ui.listbox({
      label: "Owner", multi: true, placeholder: "All",
      value: TD.state.owner,
      options: [{ value: "", label: "All owners" }, { separator: true }].concat(
        uniqueOwners().map((owner) => ({
          value: owner, label: owner,
          render: () => `<span class="ownercell">${TD.owner.coin(owner)}<span>${
            esc(owner)}</span></span>`,
        }))),
      onChange: (value) => TD.commit({ owner: value }),
    });
    document.getElementById("f-owner").append(ownerBox.el);

    versionBox = TD.ui.listbox({
      label: "Show",
      value: TD.state.versions,
      options: Object.entries(TD.table.VERSION_VIEWS)
        .map(([key, view]) => ({ value: key, label: view.label })),
      onChange: (value) => TD.commit({ versions: value }),
    });
    document.getElementById("f-view").append(versionBox.el);

    const search = document.getElementById("q");
    search.value = TD.state.q;
    search.addEventListener("input", () => TD.commit({ q: search.value }));

    document.getElementById("reset").addEventListener("click", () => {
      TD.commit({ q: "", owner: [], versions: TD.table.DEFAULT_VIEW, sort: "", dir: "asc", expand: [] });
      search.value = "";
      ownerBox.set([]);
      versionBox.set(TD.table.DEFAULT_VIEW);
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

    // The order label's ✕ is the only way back to stage order when a narrow
    // window has hidden the column whose header would complete the cycle.
    document.getElementById("order").addEventListener("click", (event) => {
      if (event.target.closest("#unsort")) TD.commit({ sort: "", dir: "asc" });
    });

    // A component named in the drift sentence scrolls the table to its row,
    // which now has its own scrollport and so is not reachable by the
    // browser's own fragment handling.
    document.addEventListener("click", (event) => {
      const link = event.target.closest('a[href^="#c-"]');
      if (!link) return;
      event.preventDefault();
      const id = link.getAttribute("href").slice(3);
      history.replaceState(null, "", `${location.pathname}${location.search}#c-${id}`);
      TD.table.scrollTo(id);
    });
  }

  /* --- Measurement ------------------------------------------------------------ */

  /* The filter strip is not a constant height: it wraps at the widths where the
     controls and the order label no longer fit on one line. Measured rather
     than guessed, because a wrong offset hides the first row under the bar. */
  function measure() {
    const root = document.documentElement;
    const bar = $(".filters");
    if (bar) {
      root.style.setProperty("--filters-height",
        `${Math.round(bar.getBoundingClientRect().height)}px`);
    }
    // The table is the page's scrollport (see table.css), so its height is the
    // window minus whatever sits above it and the one line that sits below.
    // Measured, not reserved by guess: the footer is a single line when the
    // policy withheld something and no element at all when it did not, and a
    // constant here is a blank band under the table in the second case.
    // Floored, so a short window leaves a usable table rather than a two-row
    // slot.
    const wrap = $(".tablewrap");
    if (wrap) {
      const top = wrap.getBoundingClientRect().top + scrollY;
      const note = $("footer");
      const below = note ? Math.ceil(note.getBoundingClientRect().height) : 0;
      root.style.setProperty(
        "--table-h", `${Math.max(240, Math.round(innerHeight - top - below))}px`);
    }
    if (viewSwitch) viewSwitch.measure();
  }

  /* --- Views ------------------------------------------------------------------- */

  function showView(animate) {
    const overview = document.getElementById("view-overview");
    const map = document.getElementById("view-map");
    const onMap = TD.state.view === "map";
    overview.classList.toggle("on", !onMap);
    map.classList.toggle("on", onMap);
    const shown = onMap ? map : overview;
    if (animate && TD.motion.enabled) {
      shown.classList.remove("enter");
      void shown.offsetWidth;
      shown.classList.add("enter");
    }
    renderView();
  }

  function renderView() {
    if (TD.state.view === "map") {
      const container = document.getElementById("view-map");
      // The map lands in a later step. Until then the switch is honest about
      // it rather than showing an empty frame that looks like a failure.
      if (TD.map && TD.map.render) TD.map.render(container);
      else if (!container.querySelector(".empty-view")) {
        container.innerHTML =
          '<p class="empty-view">Map view is not built into this page yet.</p>';
      }
      const shown = TD.table.visibleRows().length;
      setStatus(shown, (DATA.rows || []).length);
      return;
    }
    const result = TD.table.render(document.getElementById("view-overview"));
    setStatus(result.shown, result.total);
    measure();
  }

  function setStatus(shown, total) {
    document.getElementById("order").innerHTML = TD.table.orderHtml();
    document.getElementById("count").textContent =
      `${shown} of ${total} component${total === 1 ? "" : "s"}`;
  }

  function refresh() {
    renderView();
  }

  /* --- Stat count-up ------------------------------------------------------------ */

  /* Once, on first paint, and never again: a number that re-counts every time a
     filter changes is a distraction, and these four do not depend on the
     filters anyway. */
  function countUp() {
    const nodes = [...document.querySelectorAll(".stat .n[data-n]")];
    const targets = nodes.map((node) => Math.max(0, Number(node.dataset.n) || 0));
    const write = (values) => {
      nodes.forEach((node, index) => { node.textContent = String(values[index]); });
    };
    // A hidden document does not animate: rAF is throttled in a background
    // tab, and a screenshot or a print of a tab that was never shown would
    // otherwise catch the counters part-way to their own values.
    if (!TD.motion.enabled || document.hidden) { write(targets); return; }
    const duration = 600;
    const start = performance.now();
    const step = (now) => {
      const t = Math.min(1, (now - start) / duration);
      const eased = 1 - Math.pow(1 - t, 3);
      // Clamped at zero and, on the last frame, written exactly: an eased
      // value is never allowed to render as a number the payload does not
      // contain.
      if (t < 1) {
        write(targets.map((value) => Math.max(0, Math.round(value * eased))));
        requestAnimationFrame(step);
      } else {
        write(targets);
      }
    };
    write(targets.map(() => 0));
    requestAnimationFrame(step);
  }

  /* --- Boot --------------------------------------------------------------------- */

  TD.table.ensureColumns();
  shell();
  controls();
  renderTheme();
  showView(false);
  measure();
  countUp();

  addEventListener("resize", measure);

  // A deep link arrives before the table exists, so the browser's own fragment
  // scroll finds nothing; this is the second attempt, once there are rows.
  const deep = /^#c-(.+)$/.exec(location.hash || "");
  if (deep) TD.table.scrollTo(decodeURIComponent(deep[1]));
  else if (TD.state.sel) TD.table.scrollTo(TD.state.sel);

  // Only now: everything above can set state without the URL fighting it back.
  urlReady = true;
})();
