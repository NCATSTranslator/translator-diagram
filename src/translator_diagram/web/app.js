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

  TD.boot(JSON.parse(document.getElementById("payload").textContent));
  const DATA = TD.DATA;

  /* --- State and URL -------------------------------------------------------- */

  TD.state = TD.url.parse(location.search);
  // Watchers fire during setup too; without this guard the first render would
  // rewrite the URL and discard the state a shared link asked for.
  let urlReady = false;

  function writeUrl(push) {
    if (!urlReady) return;
    const query = TD.url.serialize(TD.state);
    // A change of view or of component is a place, so it gets a history entry
    // and Back returns to it; a keystroke in the search box is not, and
    // replaces the entry rather than burying the last place under fifty.
    const url = query ? `?${query}${location.hash}` : location.pathname + location.hash;
    if (push) history.pushState(null, "", url);
    else history.replaceState(null, "", url);
  }

  TD.commit = function commit(patch, options) {
    Object.assign(TD.state, patch);
    writeUrl(false);
    if (!(options && options.silent)) renderView();
  };

  /* Go somewhere: another view, or another component. Unlike commit, this
     pushes a history entry and redraws the whole shown view. */
  TD.navigate = function navigate(patch) {
    // Leaving a view for a component: the entry being left records which one
    // was picked there, so Back returns to its row highlighted and in view,
    // or to its node ringed, rather than to the place as it was before.
    if (patch.sel && patch.view && patch.view !== TD.state.view) {
      TD.state.sel = patch.sel;
      writeUrl(false);
    }
    Object.assign(TD.state, patch);
    writeUrl(true);
    syncControls();
    showView(true);
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

  const nextTheme = (choice) => TD.theme.next(choice, systemPrefersDark());

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

  /* A "Tr" tile in the Translator UI's purple, and deliberately not that UI's
     own logo (NCATSTranslator/ui-fe, src/assets/images/Logo.svg), whose plate
     spells NIH: this page is not an official NIH page, and a mark that reads
     as one would be taken as a claim that it is. tools/make_favicon.py draws
     the favicon from the same design. Fills are left to base.css so the tile
     follows the theme, and the whole thing is `aria-hidden` because the name
     is right there in text. */
  const BRAND_MARK = `<svg class="mark" viewBox="0 0 32 32" aria-hidden="true"
    xmlns="http://www.w3.org/2000/svg"><rect class="tile" width="32" height="32"
    rx="6"/><text class="glyph" x="16" y="22.6" text-anchor="middle">Tr</text></svg>`;

  /* --- The sync panel ------------------------------------------------------- */

  /* What the page knows about its own data, behind the note that says when
     it was checked: shares rather than counts, because "27 components" has
     nothing to be compared to and "40 of 49 reachable" does, and each share
     links to the Show view that lists the rest. A native <details>: it is
     prose and links, not a listbox, and <details> gives the toggle, the
     keyboard and aria-expanded for nothing. */
  function syncPanelHtml() {
    const f = TD.summary.figures(DATA);
    const when = f.syncedAt ? `checked ${esc(TD.fmt.since(f.syncedAt))}` : "never checked";
    const stamp = f.syncedAt ? f.syncedAt.slice(0, 16).replace("T", " ") + " UTC" : "";
    const pct = (s) => Math.round((100 * s.n) / s.of);
    const shares = f.shares.map((s) => {
      const query = TD.url.serialize({ ...TD.url.defaults(), versions: s.view });
      return `<tr><td class="n">${s.n} of ${s.of}</td><td class="pct">${pct(s)}%</td><td>${esc(s.label)}
        <span class="bar"><i style="width:${pct(s)}%"></i></span>
        <a href="?${esc(query)}" data-show="${esc(s.view)}">show which are not</a></td></tr>`;
    }).join("");
    const otel = f.otel.perEnv.map(([env, n]) => `${esc(env)} ${n}`).join(" · ");
    return `<details class="sync" id="sync"><summary class="btn" title="${esc(stamp)}">${when}</summary>
      <div class="sync-pop">
        <p>Every deployment was checked <b>${esc(TD.fmt.since(f.syncedAt))}</b>${
          stamp ? ` <span class="muted">(${esc(stamp)})</span>` : ""}: ${
          f.checks.succeeded} of ${f.checks.attempted} checks succeeded, ${f.checks.failed} failed.</p>
        ${shares ? `<h3>How much of the platform</h3><table>${shares}</table>` : ""}
        ${f.sources.length ? `<h3>Where versions came from</h3><p>${f.sources.map(esc).join(", ")}.</p>` : ""}
        ${f.otel.total ? `<h3>OpenTelemetry</h3><p>${f.otel.total} services reporting: ${otel}.</p>` : ""}
      </div></details>`;
  }

  /* --- The data releases strip ---------------------------------------------- */

  /* One line per data axis: each release seen, and the environments it is
     in with how many components are on it there (hover for which). A
     release moving dev → ci → test → prod is read off this line; the table
     below is where to find the cell. Each version is a search: the search
     box already matches data releases, so one click lists the rows on it.
     Drawn once, from the whole payload: it describes the platform, not
     the filter. */
  function axesStripHtml() {
    const strip = TD.summary.axes(DATA);
    if (!strip.length) return "";
    const env = (e) => `<span class="axenv" title="${esc(e.ids.join(", "))}">${esc(e.env)}${
      e.ids.length > 1 ? `<i>${e.ids.length}</i>` : ""}</span>`;
    const version = (v) => `<span class="axver"><a class="v data" href="?q=${
      encodeURIComponent(v.version)}" data-q="${esc(v.version)}">${esc(v.version)}</a><span
      class="axenvs">${v.envs.map(env).join("")}</span></span>`;
    return `<div class="axes" aria-label="Data releases, and where each is running">${
      strip.map((a) => `<div class="axis"><span class="axname">${esc(a.label)}</span>${
        a.versions.map(version).join("")}</div>`).join("")}</div>`;
  }

  /* --- Shell ------------------------------------------------------------------ */

  function shell() {
    document.getElementById("app").innerHTML = `
      <div class="topbar">
        <div class="brandmark">${BRAND_MARK}<span class="name">Translator Components</span><span
          class="tagline">what is running where, in which version, on which data</span></div>
        <div id="viewswitch"></div>
        <div class="topright">${syncPanelHtml()}<button type="button" class="btn icon" id="theme"></button></div>
      </div>
      <main class="page">
        <div class="filters">
          <input type="search" id="q" placeholder="Search components, versions, ids…"
                 aria-label="Search components">
          <span id="f-owner"></span><span id="f-view"></span>
          <button type="button" class="btn" id="reset">Reset</button>
          <button type="button" class="btn" id="copy">Copy link</button>
          <span class="legend" aria-label="What the environment cells' colours mean">
            <span><i class="sw same"></i>same as the rest of the row</span>
            <span><i class="sw diff"></i>differs</span>
            <span><i class="sw nov"></i>up, no version</span>
            <span><i class="sw down"></i>down</span>
            <span><i class="sw off"></i>no address on file</span>
            <span><i class="sw copied"></i>copied from a registry or chart</span>
            <span><span class="dot up"></span>host answers</span>
            <span><span class="dot warn"></span>answers, with a finding</span>
            <span><span class="dot down"></span>down, or a severe finding</span>
          </span>
          <span class="spacer"></span>
          <span class="status">
            <span class="order" id="order"></span>
            <span class="count" id="count" aria-live="polite"></span>
          </span>
        </div>
        ${axesStripHtml()}
        <div class="view on" id="view-overview"></div>
        <div class="view" id="view-map"></div>
        <div class="view" id="view-component"></div>
      </main>`;
  }

  /* --- Controls --------------------------------------------------------------- */

  let viewSwitch = null;
  let ownerBox = null;
  let versionBox = null;
  let search = null;

  function uniqueOwners() {
    return [...new Set((DATA.rows || []).map((row) => row.owner).filter(Boolean))]
      .sort((a, b) => a.localeCompare(b));
  }

  function controls() {
    viewSwitch = TD.ui.segmented({
      label: "View",
      items: [
        { value: "overview", label: "Overview" },
        { value: "map", label: "Map" },
        { value: "component", label: "Component" },
      ],
      value: TD.state.view,
      onChange: (value) => TD.navigate({ view: value }),
    });
    document.getElementById("viewswitch").append(viewSwitch.el);

    ownerBox = TD.ui.listbox({
      label: "Owner", multi: true, placeholder: "All",
      value: TD.state.owner,
      options: [{ value: "", label: "All owners" }, { separator: true }].concat(
        uniqueOwners().map((owner) => ({
          value: owner, label: owner,
          render: () => TD.row.ownerLabel(owner),
        }))),
      onChange: (value) => TD.commit({ owner: value }),
    });
    document.getElementById("f-owner").append(ownerBox.el);

    versionBox = TD.ui.listbox({
      label: "Show",
      value: TD.state.versions,
      options: Object.entries(TD.table.SHOW_VIEWS)
        .map(([key, view]) => ({ value: key, label: view.label })),
      onChange: (value) => TD.commit({ versions: value }),
    });
    document.getElementById("f-view").append(versionBox.el);

    search = document.getElementById("q");
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

    // A share's link lists the rows it leaves out: switch to the Overview on
    // that view, set the control to match, and close the panel. The href is
    // real too, so a middle-click opens the same view in a new tab.
    const sync = document.getElementById("sync");
    sync.addEventListener("click", (event) => {
      const link = event.target.closest("a[data-show]");
      if (!link) return;
      event.preventDefault();
      TD.commit({ view: "overview", versions: link.dataset.show }, { silent: true });
      viewSwitch.set("overview");
      versionBox.set(link.dataset.show);
      showView(false);
      sync.open = false;
    });
    // Anywhere else closes it, the way the listboxes close.
    document.addEventListener("click", (event) => {
      if (sync.open && !sync.contains(event.target)) sync.open = false;
    });

    // A release in the strip is a search for it. The href is real too, so a
    // middle-click opens the same list in a new tab.
    const axes = document.querySelector(".axes");
    if (axes) {
      axes.addEventListener("click", (event) => {
        const link = event.target.closest("a[data-q]");
        if (!link) return;
        event.preventDefault();
        search.value = link.dataset.q;
        TD.commit({ q: link.dataset.q });
      });
    }

    // The order label's ✕ is the only way back to stage order when a narrow
    // window has hidden the column whose header would complete the cycle.
    document.getElementById("order").addEventListener("click", (event) => {
      if (event.target.closest("#unsort")) TD.commit({ sort: "", dir: "asc" });
    });
  }

  /* Set every control from TD.state, after something other than the control
     itself changed it: Back, Forward, or a navigation. */
  function syncControls() {
    viewSwitch.set(TD.state.view);
    ownerBox.set(TD.state.owner);
    versionBox.set(TD.state.versions);
    search.value = TD.state.q;
  }

  /* --- Measurement ------------------------------------------------------------ */

  /* The view switch's sliding indicator is placed from measured widths, so it
     is re-measured whenever the layout can have changed. */
  function measure() {
    if (viewSwitch) viewSwitch.measure();
  }

  /* --- Views ------------------------------------------------------------------- */

  function showView(animate) {
    const name = TD.state.view;
    // base.css hides the filter bar on the Component view, where it filters
    // nothing; this attribute is what it keys on.
    document.documentElement.dataset.view = name;
    let shown = null;
    for (const view of TD.url.vocabulary().views) {
      const el = document.getElementById(`view-${view}`);
      el.classList.toggle("on", view === name);
      if (view === name) shown = el;
    }
    if (animate && TD.motion.enabled) {
      shown.classList.remove("enter");
      void shown.offsetWidth;
      shown.classList.add("enter");
    }
    renderView();
    // Back from a component lands on the table freshly drawn and scrolled to
    // the top, so bring its row back into sight.
    if (name === "overview" && TD.state.sel) TD.table.revealRow(TD.state.sel);
  }

  function renderView() {
    if (TD.state.view === "map") {
      const shown = TD.map.render(document.getElementById("view-map"));
      setStatus(shown, (DATA.rows || []).length);
      return;
    }
    if (TD.state.view === "component") {
      TD.component.render(document.getElementById("view-component"));
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

  /* --- Boot --------------------------------------------------------------------- */

  TD.table.ensureColumns();
  shell();
  controls();
  renderTheme();
  showView(false);
  measure();

  addEventListener("resize", measure);

  // Back and forward: the URL is the state, so re-read it, set the controls
  // and the shown view from it. renderView alone drew into whichever view
  // was already showing.
  addEventListener("popstate", () => {
    Object.assign(TD.state, TD.url.parse(location.search));
    syncControls();
    showView(false);
  });

  // A deep link arrives before the table exists, so the browser's own fragment
  // scroll finds nothing; this is the second attempt, once there are rows.
  const deep = /^#c-(.+)$/.exec(location.hash || "");
  if (deep) TD.table.scrollTo(decodeURIComponent(deep[1]));
  else if (TD.state.sel) TD.table.scrollTo(TD.state.sel);

  // Only now: everything above can set state without the URL fighting it back.
  urlReady = true;
})();
