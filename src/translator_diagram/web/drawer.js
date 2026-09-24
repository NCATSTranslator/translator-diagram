/*
  The detail drawer: the chrome around the renderers in detail.js. A 440px
  side panel beside the table or the map, a bottom sheet under 900px, six
  tabs, and the focus and keyboard handling that go with them. What each tab
  says is detail.js's business; this file decides where it appears, when it
  opens and what happens to focus when it closes.

  This file loads before app.js (JS_FILES order), so TD.state, TD.commit and
  TD.DATA do not exist yet at definition time. Boot is deferred to a
  microtask, which runs after the whole concatenated <script> — app.js
  included — has finished.
*/

(() => {
  "use strict";

  const TD = (globalThis.TD = globalThis.TD || {});
  const drawer = (TD.drawer = TD.drawer || {});

  const { TABS, TAB_IDS, DEFAULT_TAB, rowById } = TD.detail;
  const PANELS = TD.detail.panels;
  const headerHtml = (row) => TD.detail.header(row, { close: true });
  const esc = (value) => TD.fmt.esc(value);

  /* --- The element --------------------------------------------------------- */

  let root = null;
  let head = null;
  let bodyEl = null;
  let panelEl = null;
  let tabsWrap = null;
  let tabs = null;
  let currentId = "";
  let currentTab = DEFAULT_TAB;
  let opener = null;
  let openerId = "";
  let pending = null;

  /* table.js opens the drawer without handing over the button that was
     clicked, and rewrites its <tbody> on the next render, so by the time Esc
     is pressed that button is a detached node. Capturing the click here — one
     listener, before the table's own — is how Esc gets the focus back to the
     row the reader started from without table.js having to know the drawer
     exists. */
  document.addEventListener("click", (event) => {
    const trigger = event.target.closest && event.target.closest("[data-open]");
    if (trigger && !(root && root.contains(trigger))) pending = trigger;
  }, true);

  const normaliseTab = (tab) => (TAB_IDS.indexOf(tab) >= 0 ? tab : DEFAULT_TAB);

  /* One row of tabs at 440px does not fit six labels, and a scrollbar is
     hidden by design. A fade at the right edge is the only remaining sign
     that there is more, and it must not be painted when everything fits —
     which is a measurement, so it happens here rather than in the sheet. */
  function measureTabs() {
    if (!tabsWrap) return;
    // The wrapper is the scroller; the strip inside it is width:max-content and
    // so is never wider than itself. Measuring the strip always said "fits".
    const more = tabsWrap.scrollWidth > tabsWrap.clientWidth + 1;
    tabsWrap.dataset.more = more ? "1" : "0";
  }

  /* Keeps the selected tab in view when the strip is scrolled: arrow keys can
     move to a tab that is off the right edge, and a focused control the
     reader cannot see is worse than no scrolling at all. */
  function revealTab() {
    if (!tabsWrap) return;
    const on = tabsWrap.querySelector('[aria-selected="true"]');
    if (on && on.scrollIntoView) on.scrollIntoView({ block: "nearest", inline: "nearest" });
  }

  function build() {
    if (root) return root;
    root = document.createElement("aside");
    root.className = "drawer";
    root.setAttribute("role", "complementary");
    root.setAttribute("aria-label", "Component details");
    root.hidden = true;
    root.innerHTML = `<button type="button" class="dw-sheetclose"
        >${TD.ui.CARET_DOWN}<span>Close</span></button>
      <div class="dw-head"></div>
      <div class="dw-tabs"></div>
      <div class="dw-body"><div class="dw-panel" id="dw-panel" role="tabpanel"
        tabindex="0"></div></div>`;
    head = root.querySelector(".dw-head");
    tabsWrap = root.querySelector(".dw-tabs");
    bodyEl = root.querySelector(".dw-body");
    panelEl = root.querySelector(".dw-panel");

    tabs = TD.ui.tabs({
      label: "Component details",
      tabs: TABS.map((tab) => ({ id: tab.id, label: tab.label, panel: "dw-panel" })),
      value: currentTab,
      onChange: (value) => setTab(value, false),
    });
    // The tabs control does not hand its buttons ids, and a tabpanel has to
    // name the tab that labels it; assigning them here keeps controls.js
    // untouched.
    for (const button of tabs.el.querySelectorAll("button[data-id]")) {
      button.id = `dw-tab-${button.dataset.id}`;
    }
    tabsWrap.append(tabs.el);

    root.addEventListener("click", onClick);
    document.body.append(root);
    TD.ui.tooltip.bind(root, "[data-tip]", (target) => {
      const full = target.dataset.full || target.textContent || "";
      // data-tip="say" carries a sentence the element does not show — the
      // drift explanation, now that the ≠ glyph is gone. Everything else is a
      // truncation tooltip, and declines to repeat text already legible.
      if (target.dataset.tip === "say") return esc(full);
      if (target.scrollWidth <= target.clientWidth + 1) return "";
      return esc(full);
    });
    return root;
  }

  function onClick(event) {
    const closeButton = event.target.closest(".dw-close, .dw-sheetclose");
    if (closeButton) {
      close();
      return;
    }
    const disc = event.target.closest("[data-disc]");
    if (disc) {
      const expanded = disc.getAttribute("aria-expanded") === "true";
      disc.setAttribute("aria-expanded", expanded ? "false" : "true");
      return;
    }
    const go = event.target.closest("[data-go]");
    if (go) {
      event.preventDefault();
      const id = go.dataset.go;
      if (!rowById(id)) return;
      open(id, currentTab, { opener: go });
      if (TD.map && TD.map.focus) {
        try { TD.map.focus(id); } catch { /* the map is optional */ }
      }
    }
  }

  /* The table paints its selected row from TD.state at render time, and the
     commits below are silent (a full table re-render for a drawer tab change
     is a lot of work for nothing). So the highlight is moved by hand — the
     same two lines table.js runs on its own click. */
  function syncSelection(id) {
    for (const tr of document.querySelectorAll("table.grid tr.row")) {
      tr.classList.toggle("sel", tr.dataset.id === id);
    }
    // The commits here are silent, so the map never repaints on its own and
    // would keep ringing a node the drawer has let go of.
    if (TD.map && TD.map.ring) TD.map.ring(id);
  }

  function renderPanel() {
    const row = rowById(currentId);
    if (!row) {
      panelEl.innerHTML = `<p class="dw-muted">No component with the id ${esc(currentId)}.</p>`;
      return;
    }
    const make = PANELS[currentTab] || PANELS[DEFAULT_TAB];
    let html;
    try {
      html = make(row);
    } catch (error) {
      // One malformed field must cost that tab, not the page: the drawer is a
      // reading surface over data fetched from six upstreams.
      html = `<p class="dw-muted">This tab could not be rendered for ${esc(row.id)}.</p>`;
      if (typeof console !== "undefined") console.error("drawer:", error);
    }
    panelEl.innerHTML = html;
    panelEl.setAttribute("aria-labelledby", `dw-tab-${currentTab}`);
    panelEl.scrollTop = 0;
    bodyEl.scrollTop = 0;
  }

  function setTab(tab, silentControl) {
    const next = normaliseTab(tab);
    if (next === currentTab && panelEl && panelEl.innerHTML) return;
    currentTab = next;
    if (tabs && silentControl !== false) tabs.set(next);
    renderPanel();
    revealTab();
    // Only when it differs from the default: a link that says ?tab=overview
    // is telling the reader nothing they would not have got anyway.
    if (TD.state) TD.commit({ tab: next === DEFAULT_TAB ? "" : next }, { silent: true });
  }

  /* --- Open, close --------------------------------------------------------- */

  let reflowTimer = 0;

  /* Not TD.table.scrollTo: that calls scrollIntoView, which scrolls *every*
     ancestor scroller including the document — and with the sheet's
     padding-bottom the document is now scrollable, so it slid the whole page
     down and put the table behind the sheet, which is the bug this was meant
     to fix. Moving the table's own scrollport is the smallest thing that
     works. */
  function revealRow(id) {
    if (!id) return;
    const wrap = document.querySelector(".tablewrap");
    if (!wrap) return;
    let tr = null;
    try { tr = wrap.querySelector(`tr.row[data-id="${CSS.escape(id)}"]`); } catch { tr = null; }
    if (!tr) return;
    // The table's own <thead> is sticky inside this scrollport, so scrolling
    // the row to the top puts it under the header rather than beside it.
    const thead = wrap.querySelector("thead");
    const cover = thead ? thead.getBoundingClientRect().height : 0;
    const delta = tr.getBoundingClientRect().top - wrap.getBoundingClientRect().top;
    wrap.scrollTop += delta - cover - 8;
  }

  /* app.js measures the table's scrollport against the window, and its sticky
     header measures itself; the drawer has just taken 440px of the row and
     only a resize tells either of them. Sent twice: once now, so the reflow
     happens with the slide rather than after it, and once when the entrance
     has finished, because the first measurement is taken mid-animation. */
  function reflow() {
    const fire = () => {
      try { dispatchEvent(new Event("resize")); } catch { /* older browsers */ }
      measureTabs();
      // Sheet mode only. The 30vh cap on the table lands the moment
      // data-drawer is set, which is after app.js has already scrolled to the
      // selected row against the full-height scrollport — so without this the
      // row the reader just tapped sits behind the sheet.
      if (innerWidth <= 900) revealRow(currentId);
    };
    fire();
    clearTimeout(reflowTimer);
    reflowTimer = setTimeout(fire, 340);
  }

  function open(id, tab, options) {
    const row = rowById(id);
    if (!row) return;
    if (TD.state && TD.state.view === "component") return;
    build();

    const opts = options || {};
    const wasOpen = drawer.isOpen();
    // Only when the drawer is opening, or opening on a different component:
    // clicking through Connections should return focus to the row that
    // started the journey, not to the last link on the way.
    const from = opts.opener || pending;
    pending = null;
    if (from && (!wasOpen || openerId !== id)) {
      opener = from;
      openerId = id;
    }
    if (!wasOpen && !from) { opener = null; openerId = id; }

    const sameId = currentId === id;
    currentId = id;
    currentTab = normaliseTab(tab || (sameId ? currentTab : TD.state && TD.state.tab) || DEFAULT_TAB);

    head.innerHTML = headerHtml(row);
    if (tabs) tabs.set(currentTab);
    renderPanel();

    root.hidden = false;
    measureTabs();
    revealTab();
    document.documentElement.dataset.drawer = "open";
    if (!wasOpen) {
      // Re-triggered rather than left on the element: reopening on another
      // component should play the same entrance, not sit still.
      root.classList.remove("in");
      // The token durations are already 0 under prefers-reduced-motion;
      // reading the preference here too means the class is never applied, so
      // there is no animation to fill and no forced reflow to pay for.
      if (TD.motion.enabled) {
        void root.offsetWidth;
        root.classList.add("in");
      }
      reflow();
    }

    if (TD.state) {
      TD.commit({ sel: id, tab: currentTab === DEFAULT_TAB ? "" : currentTab }, { silent: true });
      syncSelection(id);
    }
    if (!opts.silentFocus) {
      const closeButton = root.querySelector(".dw-close");
      if (closeButton) closeButton.focus({ preventScroll: true });
    }
  }

  function close() {
    if (!root || root.hidden) return;
    root.hidden = true;
    root.classList.remove("in");
    delete document.documentElement.dataset.drawer;
    const id = currentId;
    currentId = "";
    if (TD.state) {
      TD.commit({ sel: "", tab: "" }, { silent: true });  // no selection, no tab
      syncSelection("");
    }
    reflow();

    // The table rebuilds its rows on every render, so the button that opened
    // the drawer is usually a detached node by now; the row is found again by
    // id rather than the focus being dropped on <body>.
    let target = opener && document.contains(opener) ? opener : null;
    if (!target && id) target = document.querySelector(`[data-open="${CSS.escape(id)}"]`);
    opener = null;
    openerId = "";
    if (target) target.focus({ preventScroll: true });
  }

  /* --- Keyboard ------------------------------------------------------------ */

  /* Escape closes when the focus is inside the drawer, and otherwise only when
     nothing else has already claimed the key — a listbox popover in the filter
     strip calls preventDefault on its own Escape, so checking that is what
     keeps one key from closing two things. */
  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape" || event.defaultPrevented) return;
    if (!drawer.isOpen()) return;
    close();
  });

  /* --- Boot ---------------------------------------------------------------- */

  function sync() {
    const state = TD.state || {};
    // A component page is not a drawer: a `sel` that survived in memory, or
    // arrived on a hand-written link, must not open one over the page.
    if (state.view === "component") {
      if (drawer.isOpen()) close();
      return;
    }
    if (state.sel && rowById(state.sel)) {
      // From the URL, so no focus steal: the reader asked for a page, not for
      // the caret to land in a close button they did not press.
      open(state.sel, state.tab, { silentFocus: true });
    } else if (drawer.isOpen()) {
      close();
    }
  }

  // drawer.js is inlined before app.js, so TD.state does not exist yet. A
  // microtask runs after the whole <script> — app.js included — has finished,
  // and a frame after that gives the shell its first layout to measure.
  queueMicrotask(() => {
    if (!TD.state) return;
    requestAnimationFrame(sync);
  });

  addEventListener("resize", () => { if (drawer.isOpen()) measureTabs(); });

  // No popstate listener here: app.js owns history and calls `sync` after it
  // has re-read the URL and repainted the view.

  /* --- Public API ---------------------------------------------------------- */

  drawer.open = open;
  drawer.close = close;
  drawer.sync = sync;
  drawer.isOpen = () => !!root && !root.hidden;
})();
