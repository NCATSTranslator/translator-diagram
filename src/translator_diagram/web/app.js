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

  function writeUrl() {
    if (!urlReady) return;
    const query = TD.url.serialize(TD.state);
    history.replaceState(null, "", query ? `?${query}${location.hash}` : location.pathname + location.hash);
  }

  TD.commit = function commit(patch, options) {
    Object.assign(TD.state, patch);
    writeUrl();
    if (!(options && options.silent)) renderView();
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

  /* --- Shell ------------------------------------------------------------------ */

  function shell() {
    const synced = DATA.synced_at
      ? `synced ${esc(TD.fmt.since(DATA.synced_at))}` : "never synced";
    document.getElementById("app").innerHTML = `
      <div class="topbar">
        <div class="brandmark">${BRAND_MARK}<span class="name">Translator Components</span><span
          class="tagline">what is running where, in which version, on which data</span></div>
        <div id="viewswitch"></div>
        <div class="topright"><span class="synced" title="${esc(DATA.synced_at || "")}"
          >${synced}</span><button type="button" class="btn icon" id="theme"></button></div>
      </div>
      <main class="page">
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

    // The order label's ✕ is the only way back to stage order when a narrow
    // window has hidden the column whose header would complete the cycle.
    document.getElementById("order").addEventListener("click", (event) => {
      if (event.target.closest("#unsort")) TD.commit({ sort: "", dir: "asc" });
    });
  }

  /* --- Measurement ------------------------------------------------------------ */

  /* The view switch's sliding indicator is placed from measured widths, so it
     is re-measured whenever the layout can have changed. */
  function measure() {
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
      const shown = TD.map.render(document.getElementById("view-map"));
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

  /* --- Boot --------------------------------------------------------------------- */

  TD.table.ensureColumns();
  shell();
  controls();
  renderTheme();
  showView(false);
  measure();

  addEventListener("resize", measure);

  /* Something other than the window changed how much room the views have —
     the drawer opening or closing. The same two measurements a window resize
     triggers, without dispatching a fake event to get them. */
  TD.layoutChanged = function layoutChanged() {
    measure();
    TD.map.resized();
  };

  // Back and forward: the URL is the state, so re-read it, set the controls
  // and the shown view from it, and let the drawer open or close to match.
  // renderView alone drew into whichever view was already showing.
  addEventListener("popstate", () => {
    Object.assign(TD.state, TD.url.parse(location.search));
    viewSwitch.set(TD.state.view);
    ownerBox.set(TD.state.owner);
    versionBox.set(TD.state.versions);
    search.value = TD.state.q;
    showView(false);
    TD.drawer.sync();
  });

  // A deep link arrives before the table exists, so the browser's own fragment
  // scroll finds nothing; this is the second attempt, once there are rows.
  const deep = /^#c-(.+)$/.exec(location.hash || "");
  if (deep) TD.table.scrollTo(decodeURIComponent(deep[1]));
  else if (TD.state.sel) TD.table.scrollTo(TD.state.sel);

  // Only now: everything above can set state without the URL fighting it back.
  urlReady = true;
})();
