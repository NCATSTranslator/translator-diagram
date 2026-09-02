/*
  The Map view: one SVG over the scene `layout.js` computed, plus a camera, a
  legend, a toolbar and a minimap.

  Division of labour with layout.js: nothing here decides where anything goes.
  This file turns rectangles and path strings into elements, paints state onto
  them (hover, selection, filtered out), and moves the camera. That is why the
  geometry can be unit-tested and this cannot: everything below needs a
  document.

  Four decisions worth knowing before editing:

  - **The scene is built once.** `app.js` calls `render` on every refresh —
    every keystroke in the search box — and rebuilding 25 nodes and 60 paths
    each time would throw away the camera and re-run the draw-on animation. A
    refresh repaints classes; only a new container rebuilds.
  - **Edge weight is `opacity` on the group, never `stroke-opacity`.** A
    marker is painted as part of the element that references it, so fading the
    stroke alone leaves a solid arrowhead hanging in mid-air.
  - **There are no lane bands.** The rows are read off the alignment of the
    nodes; the step is named once in the left margin, with an accent tick, and
    the page keeps one background colour. Tinted bands behind alternate rows
    were tried and are the thing this view most obviously did not need.
  - **The export is a standalone document, not a screenshot of the DOM.** It
    carries its own `<defs>`, its own background, computed literals for every
    custom property *and* the same values inlined on each element, and it is
    sized from the scene rather than from the viewport — so it opens correctly
    with no stylesheet, no page and no theme around it, and rasterises the same
    way through an `Image`.
*/

(() => {
  "use strict";

  const TD = (globalThis.TD = globalThis.TD || {});
  const map = (TD.map = TD.map || {});
  const NS = "http://www.w3.org/2000/svg";
  const XLINK = "http://www.w3.org/1999/xlink";

  /* --- Element helpers ------------------------------------------------------ */

  function svg(tag, attrs, text) {
    const node = document.createElementNS(NS, tag);
    if (attrs) Object.keys(attrs).forEach((key) => {
      if (attrs[key] != null) node.setAttribute(key, String(attrs[key]));
    });
    if (text != null) node.textContent = String(text);
    return node;
  }

  function html(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text != null) node.textContent = text;
    return node;
  }

  const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));
  const esc = (value) => TD.fmt.esc(value);

  /* --- Edge kinds ----------------------------------------------------------- */

  /* The order is the legend's order, and the `on` flags are what an empty
     `?edges=` means. Cross-cutting and catalog are off because both answer a
     question the reader has not asked yet: nine edges into jaeger, and a
     second opinion from the infores registry about a graph this page records
     by hand. */
  const KINDS = [
    { key: "results", label: "Results", on: true },
    { key: "calls", label: "Calls", on: true },
    { key: "planned", label: "Planned", on: true },
    { key: "externals", label: "Externals", on: true },
    { key: "crosscutting", label: "Cross-cutting", on: false },
    { key: "catalog", label: "Catalog", on: false },
  ];

  /* One edge is one kind, and the first match wins: a planned call to jaeger
     is cross-cutting before it is planned, or turning the rail off would
     leave one dashed line reaching for a column that is not there. */
  function kindOf(edge) {
    if (edge.crosscutting) return "crosscutting";
    if (edge.kind === "catalog") return "catalog";
    if (edge.kind === "external_in" || edge.kind === "external_out") return "externals";
    if (edge.planned) return "planned";
    return edge.kind === "calls" ? "calls" : "results";
  }

  const KIND_WORDS = {
    results: "results", calls: "calls", planned: "planned",
    externals: "external", crosscutting: "cross-cutting", catalog: "catalog says",
  };

  /* --- Module state --------------------------------------------------------- */

  let host = null;         // the #view-map element app.js hands us
  let box = null;          // .mp, the element the camera's viewport is measured on
  let root = null;         // <svg>
  let camera = null;       // <g> carrying the transform
  let scene = null;        // layout.js output
  let minimap = null;
  let viewportRect = null;
  let legend = null;
  let toast = null;
  let firstPaint = true;

  const nodeEls = new Map();
  const extEls = new Map();
  const edgeEls = [];
  const rowById = new Map();
  const nodeById = new Map();
  const neighbours = new Map();
  const edgesOf = new Map();

  let selShown = "";
  let hoverId = "";

  const cam = { x: 0, y: 0, k: 1 };
  const goal = { x: 0, y: 0, k: 1 };
  let frame = 0;
  let minK = 0.5;
  // Whether the camera has been moved on purpose — by a wheel, a drag, or a
  // selection flying to a node. A resize re-fits only while it has not.
  let touched = false;
  const MAX_K = 3;

  /* --- Data --------------------------------------------------------------- */

  function payloadEdges() {
    const data = TD.DATA || {};
    const base = Array.isArray(data.edges) ? data.edges : [];
    const catalog = Array.isArray(data.catalog_edges) ? data.catalog_edges : [];
    // Catalog edges go through the layout whether or not they are shown, so
    // switching them on never moves a node. They cost a channel in the rows
    // they cross, which is the honest price of comparing the two graphs on one
    // picture.
    return base.concat(catalog.map((edge) => Object.assign({}, edge, { kind: "catalog" })));
  }

  /* Unchecking every box is a real state the legend allows, and the URL
     vocabulary has no word for it — an empty `edges=` already means "the
     defaults". It therefore lives here and not in the address bar, and a
     reload comes back with the defaults rather than a blank canvas. */
  let allOff = false;

  function activeKinds() {
    if (allOff) return new Set();
    const chosen = (TD.state && TD.state.edges) || [];
    const set = chosen.length
      ? new Set(chosen)
      : new Set(KINDS.filter((kind) => kind.on).map((kind) => kind.key));
    if (!available("catalog")) set.delete("catalog");
    if (!available("crosscutting")) set.delete("crosscutting");
    return set;
  }

  function available(key) {
    if (key === "catalog") return ((TD.DATA || {}).catalog_edges || []).length > 0;
    if (key === "crosscutting") return !!(scene && scene.rail.length);
    return true;
  }

  /* Prod first, then the environment furthest along the pipeline that reports
     anything. Never a chart's appVersion beside it: that says what should be
     deployed, which is a different claim. */
  function versionOf(row) {
    const cells = row.environments || {};
    const envs = TD.ENVS || [];
    const prod = cells.prod;
    if (prod && prod.deployed && prod.version) return prod.version;
    for (let i = envs.length - 1; i >= 0; i -= 1) {
      const cell = cells[envs[i]];
      if (cell && cell.deployed && cell.version) return cell.version;
    }
    return "";
  }

  function reachability(row) {
    const cells = row.environments || {};
    let ok = false;
    let bad = false;
    (TD.ENVS || []).forEach((env) => {
      const cell = cells[env];
      if (!cell || !cell.deployed) return;
      if (cell.reachable === true) ok = true;
      if (cell.reachable === false) bad = true;
    });
    // A failure outranks a success: three environments answering and one not
    // is news, and a green dot would bury it.
    return bad ? "bad" : ok ? "ok" : "";
  }

  const displayName = (id) => ((rowById.get(id) || {}).name || id);

  /* --- Defs ----------------------------------------------------------------- */

  function buildDefs() {
    const defs = svg("defs");
    const styles = (TD.DATA || {}).owner_styles || {};
    const owners = Object.keys(styles).sort();
    const gradientId = new Map();
    owners.forEach((owner, index) => {
      const id = `mp-metal-${index}`;
      gradientId.set(owner, id);
      const style = styles[owner] || {};
      const stops = Array.isArray(style.metal) && style.metal.length >= 4
        ? style.metal
        : [style.base, style.base, style.base, style.base];
      const gradient = svg("linearGradient", { id, x1: 0, y1: 0, x2: 1, y2: 1 });
      [0, 0.38, 0.72, 1].forEach((offset, i) => {
        gradient.append(svg("stop", { offset, "stop-color": stops[i] || style.base || "#888888" }));
      });
      defs.append(gradient);
    });

    // One clip path for every node, not one per node: the owner rail is a 3px
    // rectangle at x=0 and the clip is applied inside the node's own
    // translated group, where all the rectangles are the same 188x60.
    const clip = svg("clipPath", { id: "mp-nodeclip", clipPathUnits: "userSpaceOnUse" });
    clip.append(svg("rect", { x: 0, y: 0, width: 188, height: 60, rx: 6 }));
    defs.append(clip);

    // refX at the tip so the arrowhead's point lands exactly on the port,
    // which is exactly on the node's border, with the whole body outside it.
    const marker = (id, cls, d) => {
      const m = svg("marker", {
        id, viewBox: "0 0 10 10", refX: 10, refY: 5,
        markerWidth: 6, markerHeight: 6, orient: "auto",
      });
      m.append(svg("path", { d, class: cls }));
      return m;
    };
    defs.append(marker("mp-arrow", "mp-arrow", "M 0 1 L 10 5 L 0 9 z"));
    defs.append(marker("mp-arrow-hollow", "mp-arrow-hollow", "M 0.8 1.8 L 9.2 5 L 0.8 8.2 z"));
    defs.append(marker("mp-arrow-muted", "mp-arrow-muted", "M 0 1 L 10 5 L 0 9 z"));
    return { defs, gradientId };
  }

  /* --- Node ----------------------------------------------------------------- */

  function buildNode(node, gradientId) {
    const row = rowById.get(node.id) || { id: node.id, name: node.id };
    const group = svg("g", {
      class: node.kind === "rail" ? "mp-node mp-rail-node" : "mp-node",
      transform: `translate(${node.x} ${node.y})`,
      tabindex: 0,
      role: "button",
      "data-id": node.id,
      "aria-label": `${row.name || node.id}, ${row.owner || "no owner"}`,
    });
    group.append(svg("rect", { class: "mp-box", width: node.w, height: node.h, rx: 6 }));

    const clipped = svg("g", { "clip-path": "url(#mp-nodeclip)" });
    const gradient = gradientId.get(row.owner);
    const flat = TD.owner.style(row.owner);
    // Resolved to a literal here, not left as a var(): the export inlines the
    // stylesheet's custom properties, and a presentation attribute is not in
    // that stylesheet.
    clipped.append(svg("rect", {
      class: "mp-ownerrail", width: 3, height: node.h,
      fill: gradient ? `url(#${gradient})` : (flat && flat.base) || "transparent",
    }));
    group.append(clipped);

    // The nested SVG is a hard boundary between the name and the category.
    // `truncate` normally adds the ellipsis first, but some renderers report a
    // zero text length while the map is being revealed. Without this viewport
    // their unshortened name can still paint underneath the top-right type.
    const nameBox = svg("svg", {
      class: "mp-namebox", x: 12, y: 0, width: node.w - 22, height: 28, overflow: "hidden",
    });
    const name = svg("text", { class: "mp-name", x: 0, y: 22 }, row.name || node.id);
    name.dataset.full = row.name || node.id;
    nameBox.append(name);
    group.append(nameBox);

    const type = row.type || row.component_type;
    if (type) {
      group.append(svg("text", {
        class: "mp-type", x: node.w - 10, y: 20, "text-anchor": "end",
      }, type));
    }

    group.append(svg("text", { class: "mp-id", x: 12, y: 38 }, node.id));

    let dotX = 15;
    if (row.isolated) {
      group.append(svg("circle", { class: "mp-lonely", cx: dotX, cy: 48, r: 3 }));
      dotX += 13;
    }
    const reach = reachability(row);
    if (reach) {
      group.append(svg("circle", {
        class: reach === "ok" ? "mp-dot-ok" : "mp-dot-bad", cx: dotX, cy: 48, r: 3,
      }));
    }

    const version = versionOf(row);
    if (version) {
      const text = svg("text", { class: "mp-ver", x: node.w - 10, y: 52, "text-anchor": "end" });
      if (TD.table.hasDrift(row)) text.append(svg("tspan", { class: "mp-neq" }, "≠ "));
      text.append(svg("tspan", null, version));
      group.append(text);
    }
    return group;
  }

  /* Truncation by measurement, not by a character count: "UI" and "Translator
     component toolkit" are both in this payload, and a fixed cut would either
     clip the short ones or overflow the long ones. */
  function measuredTextWidth(text, fallbackPerCharacter) {
    if (!text) return 0;
    try {
      const width = text.getComputedTextLength();
      if (Number.isFinite(width) && width > 0) return width;
    } catch { /* detached or hidden SVG: use the conservative fallback below */ }
    return String(text.textContent || "").length * fallbackPerCharacter;
  }

  /* Node width minus the left inset, right inset, measured category and one
     readable gap. Kept pure so the collision rule has a unit test without a
     DOM; the name box enforces the same number as an SVG viewport. */
  function nodeNameLimit(nodeWidth, typeWidth) {
    const category = Math.max(0, Number(typeWidth) || 0);
    return Math.max(24, nodeWidth - 12 - 10 - category - (category ? 8 : 0));
  }

  function truncate(text, limit) {
    const full = text.dataset.full || text.textContent;
    text.dataset.full = full;
    text.textContent = full;
    if (measuredTextWidth(text, 7) <= limit) return;
    let cut = full.length;
    while (cut > 1 && measuredTextWidth(text, 7) > limit) {
      cut -= 1;
      text.textContent = `${full.slice(0, cut)}…`;
    }
  }

  /* --- Build ---------------------------------------------------------------- */

  function build(container) {
    host = container;
    container.innerHTML = "";
    nodeEls.clear();
    extEls.clear();
    edgeEls.length = 0;
    rowById.clear();
    nodeById.clear();
    neighbours.clear();
    edgesOf.clear();

    const data = TD.DATA || {};
    (data.rows || []).forEach((row) => rowById.set(row.id, row));

    scene = TD.layout.compute({
      stages: data.stages || [],
      rows: data.rows || [],
      edges: payloadEdges(),
      externals: data.externals || [],
    });
    scene.nodes.concat(scene.rail).forEach((node) => nodeById.set(node.id, node));

    // layout.js promises no edge crosses a node it is not attached to, and
    // checks itself. If that ever stops being true, say so where a developer
    // will see it rather than leaving the picture quietly wrong.
    if (scene.violations.length) {
      const names = scene.violations.slice(0, 5)
        .map((v) => `${v.from}→${v.to} through ${v.through}`).join("; ");
      console.warn(`TD.map: ${scene.violations.length} edge(s) cross a node: ${names}`);
    }

    const pills = html("div", "mp-pills");
    scene.lanes.forEach((lane) => {
      if (!lane.count) return;
      const pill = html("span", "mp-pill");
      pill.innerHTML = `<b>${esc(lane.step)}</b> ${esc(lane.title)}`;
      pills.append(pill);
    });
    container.append(pills);

    box = html("div", "mp");
    container.append(box);

    root = svg("svg", {
      class: "mp-svg",
      xmlns: NS,
      role: "img",
      "aria-label": "Component map: which component connects to which, in pipeline order",
    });
    const built = buildDefs();
    root.append(built.defs);
    camera = svg("g", { class: "mp-camera" });
    const sceneG = svg("g", { class: "mp-scene", id: "map-scene" });
    camera.append(sceneG);
    root.append(camera);

    const layers = {};
    ["lanes", "groups", "edges", "externals", "nodes", "rail"].forEach((name) => {
      layers[name] = svg("g", { class: `mp-layer mp-${name}` });
      sceneG.append(layers[name]);
    });

    /* Lanes. No band, no rule, no tint: the alignment of the node rows already
       reads as a lane, and the step is named once in the left margin. */
    scene.lanes.forEach((lane) => {
      if (!lane.count) return;
      const g = svg("g", { class: "mp-lane", "data-lane": lane.row });
      g.append(svg("rect", {
        class: "mp-lane-tick", x: 20, y: lane.midY - 12, width: 2, height: 24,
      }));
      g.append(svg("text", {
        class: "mp-lane-step", x: 32, y: lane.midY - 3,
      }, `STEP ${lane.step}`));
      const title = svg("text", { class: "mp-lane-title", x: 32, y: lane.midY + 13 }, lane.title);
      g.append(title);
      g.append(svg("rect", {
        class: "mp-lane-hit", x: 0, y: lane.bandY, width: scene.meta.leftPad - 24,
        height: lane.bandH,
      }));
      g.style.animationDelay = `calc(${lane.row} * var(--stagger))`;
      layers.lanes.append(g);
    });

    /* Groups */
    scene.groups.forEach((group) => {
      const g = svg("g", { class: "mp-group" });
      g.append(svg("rect", {
        class: "mp-group-box", x: group.x, y: group.y, width: group.w, height: group.h, rx: 4,
      }));
      g.append(svg("text", {
        class: "mp-group-label", x: group.x + 2, y: group.y - 6,
      }, group.label.toUpperCase()));
      layers.groups.append(g);
    });

    /* Edges */
    scene.edges.forEach((edge) => {
      const kind = kindOf(edge);
      const g = svg("g", {
        class: `mp-edge k-${kind}`,
        "data-from": edge.from,
        "data-to": edge.to,
        "data-kind": kind,
        "data-word": KIND_WORDS[edge.kind] || KIND_WORDS[kind] || kind,
        "data-planned": edge.planned ? "1" : "0",
      });
      g.append(svg("path", { class: "mp-hit", d: edge.path }));
      const marker = kind === "planned" ? "mp-arrow-hollow"
        : kind === "externals" || kind === "catalog" ? "mp-arrow-muted" : "mp-arrow";
      const line = svg("path", { class: "mp-line", d: edge.path, "marker-end": `url(#${marker})` });
      g.append(line);
      layers.edges.append(g);
      const record = { el: g, line, edge, kind };
      edgeEls.push(record);

      [edge.from, edge.to].forEach((id) => {
        if (!edgesOf.has(id)) edgesOf.set(id, []);
        edgesOf.get(id).push(record);
        if (!neighbours.has(id)) neighbours.set(id, new Set());
      });
      neighbours.get(edge.from).add(edge.to);
      neighbours.get(edge.to).add(edge.from);
    });

    /* Externals */
    scene.externals.forEach((ext) => {
      const g = svg("g", { class: "mp-ext", "data-id": ext.name });
      g.append(svg("rect", {
        class: "mp-ext-box", x: ext.x, y: ext.y, width: ext.w, height: ext.h, rx: 18,
      }));
      g.append(svg("text", {
        class: "mp-ext-label", x: ext.x + ext.w / 2, y: ext.y + ext.h / 2 + 4,
        "text-anchor": "middle",
      }, ext.name));
      layers.externals.append(g);
      extEls.set(ext.name, g);
    });

    /* Nodes and rail */
    scene.nodes.forEach((node) => {
      const g = buildNode(node, built.gradientId);
      layers.nodes.append(g);
      nodeEls.set(node.id, g);
    });
    scene.rail.forEach((node) => {
      const g = buildNode(node, built.gradientId);
      layers.rail.append(g);
      nodeEls.set(node.id, g);
    });

    box.append(root);
    box.append(buildLegend());
    box.append(buildToolbar());
    box.append(buildMinimap());
    toast = html("div", "mp-toast");
    toast.hidden = true;
    box.append(toast);

    nodeEls.forEach((group) => {
      const name = group.querySelector(".mp-name");
      if (!name) return;
      const nameBox = group.querySelector(".mp-namebox");
      const type = group.querySelector(".mp-type");
      const nodeBox = group.querySelector(".mp-box");
      const nodeWidth = Number(nodeBox && nodeBox.getAttribute("width")) || 188;
      const limit = nodeNameLimit(nodeWidth, measuredTextWidth(type, 6));
      if (nameBox) nameBox.setAttribute("width", limit);
      truncate(name, limit);
    });
    root.querySelectorAll(".mp-lane-title").forEach((text) => truncate(text, 148));

    wire();
    size();
    fit(false);
    paint();

    if (firstPaint && TD.motion.enabled) {
      box.classList.add("mp-first");
      drawOn();
    }
    firstPaint = false;
  }

  /* The edges arrive by drawing themselves, once. Their dash pattern is the
     thing that says results from calls, so the animation borrows it as an
     inline style and hands it back at the end rather than fighting the class
     for it. */
  function drawOn() {
    const duration = 320;
    edgeEls.forEach(({ line }) => {
      let length = 0;
      try { length = line.getTotalLength(); } catch { return; }
      if (!length) return;
      line.style.strokeDasharray = `${length}`;
      line.style.strokeDashoffset = `${length}`;
    });
    requestAnimationFrame(() => {
      edgeEls.forEach(({ line }) => {
        if (!line.style.strokeDasharray) return;
        line.style.transition = `stroke-dashoffset ${duration}ms var(--ease)`;
        line.style.strokeDashoffset = "0";
      });
      setTimeout(() => {
        edgeEls.forEach(({ line }) => {
          line.style.transition = "";
          line.style.strokeDasharray = "";
          line.style.strokeDashoffset = "";
        });
        if (box) box.classList.remove("mp-first");
      }, duration + 80);
    });
  }

  /* --- Chrome --------------------------------------------------------------- */

  const ICON = {
    fit: '<svg viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor"'
      + ' stroke-width="1.4" stroke-linecap="round"><path d="M2 6V2h4M14 6V2h-4M2 10v4h4'
      + 'M14 10v4h-4"/></svg>',
    legend: '<svg viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor"'
      + ' stroke-width="1.4" stroke-linecap="round"><path d="M2 4h12M2 8h12M2 12h12"/></svg>',
  };

  function buildToolbar() {
    const bar = html("div", "mp-toolbar");
    const button = (label, title, action, wide) => {
      const el = html("button", `mp-tool${wide ? " wide" : ""}`);
      el.type = "button";
      el.title = title;
      el.setAttribute("aria-label", title);
      el.innerHTML = label;
      el.addEventListener("click", action);
      bar.append(el);
      return el;
    };
    button("−", "Zoom out (−)", () => zoomBy(1 / 1.3));
    button("+", "Zoom in (+)", () => zoomBy(1.3));
    button(ICON.fit, "Fit to view (f)", () => fit(true));
    bar.append(html("span", "mp-toolsep"));
    const toggle = button(ICON.legend, "Legend", () => {
      legend.hidden = !legend.hidden;
      toggle.classList.toggle("on", !legend.hidden);
    });
    toggle.classList.add("on");
    bar.append(html("span", "mp-toolsep"));
    button("SVG", "Download the map as SVG", exportSvg, true);
    button("PNG", "Download the map as PNG at 2×", exportPng, true);
    return bar;
  }

  function buildLegend() {
    legend = html("div", "mp-legend");
    legend.append(html("h3", null, "Edges"));
    const active = activeKinds();
    KINDS.forEach((kind) => {
      if (!available(kind.key)) return;
      const label = document.createElement("label");
      const input = document.createElement("input");
      input.type = "checkbox";
      input.checked = active.has(kind.key);
      input.dataset.kind = kind.key;
      input.addEventListener("change", onLegendChange);
      label.append(input);
      const swatch = svg("svg", { class: "mp-legend-swatch", width: 22, height: 8 });
      const g = svg("g", { class: `mp-edge k-${kind.key}` });
      g.append(svg("path", { class: "mp-line", d: "M1 4 H 21" }));
      swatch.append(g);
      label.append(swatch);
      label.append(html("span", null, kind.label));
      legend.append(label);
    });
    return legend;
  }

  function onLegendChange() {
    const chosen = [...legend.querySelectorAll("input[data-kind]")]
      .filter((input) => input.checked)
      .map((input) => input.dataset.kind);
    allOff = chosen.length === 0;
    TD.commit({ edges: chosen });
  }

  function buildMinimap() {
    minimap = svg("svg", {
      class: "mp-minimap",
      viewBox: `0 0 ${scene.bounds.w} ${scene.bounds.h}`,
      preserveAspectRatio: "xMidYMid meet",
      "aria-hidden": "true",
    });
    const use = svg("use");
    use.setAttribute("href", "#map-scene");
    use.setAttributeNS(XLINK, "xlink:href", "#map-scene");
    minimap.append(use);
    viewportRect = svg("rect", { class: "mp-viewport", x: 0, y: 0, width: 10, height: 10 });
    minimap.append(viewportRect);
    minimap.addEventListener("pointerdown", (event) => {
      const ctm = minimap.getScreenCTM();
      if (!ctm) return;
      const point = new DOMPoint(event.clientX, event.clientY).matrixTransform(ctm.inverse());
      centreOn(point.x, point.y);
    });
    return minimap;
  }

  function say(message) {
    if (!toast) return;
    toast.textContent = message;
    toast.hidden = false;
    clearTimeout(say.timer);
    say.timer = setTimeout(() => { toast.hidden = true; }, 6000);
  }

  /* --- Camera --------------------------------------------------------------- */

  const round = (v) => Math.round(v * 100) / 100;

  function applyCamera() {
    camera.setAttribute("transform",
      `translate(${round(cam.x)} ${round(cam.y)}) scale(${Math.round(cam.k * 1000) / 1000})`);
    if (!viewportRect || !box) return;
    viewportRect.setAttribute("x", round(-cam.x / cam.k));
    viewportRect.setAttribute("y", round(-cam.y / cam.k));
    viewportRect.setAttribute("width", round(box.clientWidth / cam.k));
    viewportRect.setAttribute("height", round(box.clientHeight / cam.k));
  }

  let vx = 0;
  let vy = 0;
  let coasting = false;

  function tick() {
    frame = 0;
    let moving = false;
    if (coasting) {
      vx *= 0.92;
      vy *= 0.92;
      cam.x += vx;
      cam.y += vy;
      goal.x = cam.x;
      goal.y = cam.y;
      if (Math.hypot(vx, vy) < 0.1) coasting = false; else moving = true;
    } else {
      const dx = goal.x - cam.x;
      const dy = goal.y - cam.y;
      const dk = goal.k - cam.k;
      if (Math.abs(dx) > 0.05 || Math.abs(dy) > 0.05 || Math.abs(dk) > 0.0004) {
        // 0.22 a frame settles inside --dur-camera at 60fps, which is what
        // "the camera flies to it" is supposed to feel like.
        cam.x += dx * 0.22;
        cam.y += dy * 0.22;
        cam.k += dk * 0.22;
        moving = true;
      } else {
        cam.x = goal.x;
        cam.y = goal.y;
        cam.k = goal.k;
      }
    }
    applyCamera();
    if (moving) frame = requestAnimationFrame(tick);
  }

  function nudge() {
    if (!TD.motion.enabled) {
      coasting = false;
      cam.x = goal.x;
      cam.y = goal.y;
      cam.k = goal.k;
      applyCamera();
      return;
    }
    if (!frame) frame = requestAnimationFrame(tick);
  }

  function fitScale() {
    if (!box || !scene) return 1;
    const w = box.clientWidth || 1;
    const h = box.clientHeight || 1;
    return Math.min((w - 96) / scene.bounds.w, (h - 64) / scene.bounds.h);
  }

  /* The scene is about 2200 wide, and the view under the finding and the
     filter strip is rarely taller than 900. Fitting that honestly can put the
     whole picture on screen at 0.35, where a 13px name is 4px and the answer
     to "what is this" is a grey smudge. So the fit has a floor: below it the
     picture is fitted to the width and anchored to the top, where the pipeline
     starts, and the minimap says how much is below. */
  const MIN_FIT = 0.5;

  function fit(animate) {
    if (!box || !scene) return;
    const k = clamp(Math.max(fitScale(), MIN_FIT), 0.02, MAX_K);
    minK = Math.min(0.5, k * 0.9);
    // An explicit fit is the reader saying "start again from the whole
    // picture", so the next resize is free to keep fitting it.
    touched = false;
    const height = scene.bounds.h * k;
    goal.k = k;
    goal.x = (box.clientWidth - scene.bounds.w * k) / 2;
    goal.y = height <= box.clientHeight ? (box.clientHeight - height) / 2 : 24;
    coasting = false;
    if (!animate) {
      cam.x = goal.x;
      cam.y = goal.y;
      cam.k = goal.k;
      applyCamera();
      return;
    }
    nudge();
  }

  function zoomAbout(px, py, factor) {
    touched = true;
    const k = clamp(goal.k * factor, minK, MAX_K);
    const ratio = k / goal.k;
    goal.x = px - (px - goal.x) * ratio;
    goal.y = py - (py - goal.y) * ratio;
    goal.k = k;
    coasting = false;
    nudge();
  }

  function zoomBy(factor) {
    if (!box) return;
    zoomAbout(box.clientWidth / 2, box.clientHeight / 2, factor);
  }

  function centreOn(sceneX, sceneY) {
    touched = true;
    goal.x = box.clientWidth / 2 - sceneX * goal.k;
    goal.y = box.clientHeight / 2 - sceneY * goal.k;
    coasting = false;
    nudge();
  }

  function flyTo(node, zoom) {
    if (!box || !node) return;
    touched = true;
    goal.k = clamp(zoom || 1.25, minK, MAX_K);
    goal.x = box.clientWidth / 2 - (node.x + node.w / 2) * goal.k;
    goal.y = box.clientHeight / 2 - (node.y + node.h / 2) * goal.k;
    coasting = false;
    nudge();
  }

  function size() {
    /* Height comes from the flex column; nothing to measure here. */
  }

  /* --- Interaction ---------------------------------------------------------- */

  const pointers = new Map();
  let pinchStart = 0;
  let dragged = false;

  function localPoint(event) {
    const rect = box.getBoundingClientRect();
    return { x: event.clientX - rect.left, y: event.clientY - rect.top };
  }

  function wire() {
    root.addEventListener("wheel", (event) => {
      event.preventDefault();
      const point = localPoint(event);
      const step = event.deltaMode === 1 ? event.deltaY * 16 : event.deltaY;
      zoomAbout(point.x, point.y, Math.exp(-clamp(step, -240, 240) * 0.0016));
    }, { passive: false });

    root.addEventListener("pointerdown", (event) => {
      if (event.button !== 0 && event.pointerType === "mouse") return;
      pointers.set(event.pointerId, localPoint(event));
      root.setPointerCapture(event.pointerId);
      dragged = false;
      coasting = false;
      vx = 0;
      vy = 0;
      if (pointers.size === 2) pinchStart = pinchDistance();
      root.classList.add("dragging");
    });

    root.addEventListener("pointermove", (event) => {
      if (!pointers.has(event.pointerId)) return;
      const previous = pointers.get(event.pointerId);
      const point = localPoint(event);
      pointers.set(event.pointerId, point);
      if (pointers.size >= 2) {
        const distance = pinchDistance();
        if (pinchStart > 0 && distance > 0) {
          const centre = pinchCentre();
          zoomAbout(centre.x, centre.y, distance / pinchStart);
          pinchStart = distance;
        }
        return;
      }
      const dx = point.x - previous.x;
      const dy = point.y - previous.y;
      if (Math.abs(dx) + Math.abs(dy) > 3) { dragged = true; touched = true; }
      cam.x += dx;
      cam.y += dy;
      goal.x = cam.x;
      goal.y = cam.y;
      vx = dx;
      vy = dy;
      applyCamera();
    });

    const release = (event) => {
      if (!pointers.has(event.pointerId)) return;
      pointers.delete(event.pointerId);
      if (pointers.size < 2) pinchStart = 0;
      if (pointers.size === 0) {
        root.classList.remove("dragging");
        if (dragged && TD.motion.enabled && Math.hypot(vx, vy) > 1) {
          coasting = true;
          nudge();
        }
      }
    };
    root.addEventListener("pointerup", release);
    root.addEventListener("pointercancel", release);

    root.addEventListener("dblclick", (event) => { event.preventDefault(); fit(true); });

    root.addEventListener("click", (event) => {
      if (dragged) { dragged = false; return; }
      const node = event.target.closest(".mp-node");
      if (node) select(node.dataset.id);
    });

    root.addEventListener("keydown", (event) => {
      const node = event.target.closest(".mp-node");
      if (!node) return;
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        select(node.dataset.id);
      }
    });

    root.addEventListener("mouseover", (event) => {
      const node = event.target.closest(".mp-node");
      if (node) highlight(node.dataset.id);
    });
    root.addEventListener("mouseout", (event) => {
      if (event.target.closest(".mp-node")) highlight("");
    });
    root.addEventListener("focusin", (event) => {
      const node = event.target.closest(".mp-node");
      if (!node) return;
      highlight(node.dataset.id);
      const placed = nodeById.get(node.dataset.id);
      if (placed) ensureVisible(placed);
    });
    root.addEventListener("focusout", () => highlight(""));

    document.addEventListener("keydown", onKey);
    addEventListener("resize", onResize);
    if (typeof ResizeObserver === "function") {
      // Width only: `size()` sets the height, so watching the height would
      // have the observer answer its own notification for ever.
      let lastWidth = host.clientWidth;
      new ResizeObserver(() => {
        if (host.clientWidth === lastWidth) return;
        lastWidth = host.clientWidth;
        onResize();
      }).observe(host);
    }

    TD.ui.tooltip.bind(box, ".mp-node", (target) => nodeTip(target.dataset.id));
    TD.ui.tooltip.bind(box, ".mp-edge", (target) => edgeTip(target));
    TD.ui.tooltip.bind(box, ".mp-lane", (target) => {
      const lane = scene.lanes[Number(target.dataset.lane)];
      if (!lane) return "";
      return `<span class="title">Step ${esc(lane.step)} · ${esc(lane.title)}</span>`
        + (lane.description ? `<div class="mp-tip-line">${esc(lane.description)}</div>` : "");
    });
  }

  function pinchDistance() {
    const [a, b] = [...pointers.values()];
    return Math.hypot(a.x - b.x, a.y - b.y);
  }
  function pinchCentre() {
    const [a, b] = [...pointers.values()];
    return { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 };
  }

  /* A resize used to re-fit, which threw away wherever the reader had got to —
     and the drawer opening is a resize, so following a `?sel=` link zoomed to
     the component and then immediately zoomed back out. It re-fits only while
     nobody has moved the camera; after that it keeps the scale and holds
     whatever was in the middle of the view in the middle of it. */
  function onResize() {
    if (!box || !host || !host.classList.contains("on")) return;
    const midX = (box.clientWidth / 2 - cam.x) / cam.k;
    const midY = (box.clientHeight / 2 - cam.y) / cam.k;
    size();
    if (!touched) { fit(false); return; }
    goal.k = cam.k;
    goal.x = box.clientWidth / 2 - midX * goal.k;
    goal.y = box.clientHeight / 2 - midY * goal.k;
    cam.x = goal.x;
    cam.y = goal.y;
    applyCamera();
  }

  function onKey(event) {
    if (!TD.state || TD.state.view !== "map" || !box) return;
    const target = event.target;
    if (target && (/^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName) || target.isContentEditable)) return;
    if (event.metaKey || event.ctrlKey || event.altKey) return;
    const pan = 40;
    switch (event.key) {
      case "f": fit(true); break;
      case "0": zoomBy(1 / cam.k); break;
      case "+": case "=": zoomBy(1.3); break;
      case "-": case "_": zoomBy(1 / 1.3); break;
      case "ArrowLeft": goal.x += pan; touched = true; nudge(); break;
      case "ArrowRight": goal.x -= pan; touched = true; nudge(); break;
      case "ArrowUp": goal.y += pan; touched = true; nudge(); break;
      case "ArrowDown": goal.y -= pan; touched = true; nudge(); break;
      // The drawer owns its own Esc; this one only lets go of the ring.
      case "Escape": if (TD.state.sel) TD.commit({ sel: "" }); return;
      default: return;
    }
    event.preventDefault();
  }

  function ensureVisible(node) {
    const left = node.x * cam.k + cam.x;
    const top = node.y * cam.k + cam.y;
    const right = left + node.w * cam.k;
    const bottom = top + node.h * cam.k;
    const margin = 40;
    if (left > margin && top > margin
      && right < box.clientWidth - margin && bottom < box.clientHeight - margin) return;
    flyTo(node, cam.k);
  }

  /* --- Painting ------------------------------------------------------------- */

  function highlight(id) {
    if (hoverId === id) return;
    hoverId = id;
    root.classList.toggle("hovering", !!id);
    nodeEls.forEach((el) => el.classList.remove("lit"));
    extEls.forEach((el) => el.classList.remove("lit"));
    edgeEls.forEach(({ el }) => el.classList.remove("lit"));
    if (!id) return;
    const near = neighbours.get(id) || new Set();
    const light = (key) => {
      const el = nodeEls.get(key) || extEls.get(key);
      if (el) el.classList.add("lit");
    };
    light(id);
    near.forEach(light);
    (edgesOf.get(id) || []).forEach(({ el }) => {
      if (el.style.display !== "none") el.classList.add("lit");
    });
  }

  function paint() {
    if (!scene) return;
    const kinds = activeKinds();
    const visible = new Set(TD.table.visibleRows().map((row) => row.id));

    nodeEls.forEach((el, id) => el.classList.toggle("out", !visible.has(id)));
    edgeEls.forEach(({ el, edge, kind }) => {
      const on = kinds.has(kind);
      el.style.display = on ? "" : "none";
      const dim = (rowById.has(edge.from) && !visible.has(edge.from))
        || (rowById.has(edge.to) && !visible.has(edge.to));
      el.classList.toggle("out", dim);
    });
    extEls.forEach((el, name) => {
      const anchored = edgeEls.some(({ edge, kind }) =>
        kinds.has(kind) && (edge.from === name || edge.to === name));
      el.style.display = anchored ? "" : "none";
    });

    if (legend) {
      legend.querySelectorAll("input[data-kind]").forEach((input) => {
        input.checked = kinds.has(input.dataset.kind);
      });
    }

    const wanted = (TD.state && TD.state.sel) || "";
    if (wanted !== selShown) {
      selShown = wanted;
      nodeEls.forEach((el, id) => el.classList.toggle("sel", id === wanted));
      const node = nodeById.get(wanted);
      if (node) flyTo(node, Math.max(1.25, cam.k));
    }
  }

  function select(id) {
    if (!id || !nodeById.has(id)) return;
    const el = nodeEls.get(id);
    TD.commit({ sel: id });
    if (TD.drawer && TD.drawer.open) TD.drawer.open(id, undefined, { opener: el });
  }

  /* --- Tooltips ------------------------------------------------------------- */

  /* The connections, by name, in the four directions the component files
     record them, plus the externals. "3 in · 5 out" was what this said first
     and it answered nothing: the question a reader has in front of a box on a
     diagram is *which* three, and the whole point of hovering is not having to
     open the drawer to find out. */
  const NAME_CAP = 6;

  function nameList(entries) {
    if (!entries.length) return "";
    const shown = entries.slice(0, NAME_CAP).map((entry) =>
      esc(entry.name) + (entry.planned ? ' <span class="mp-planned">(planned)</span>' : ""));
    const more = entries.length - shown.length;
    return shown.join(", ") + (more > 0 ? `, +${more} more` : "");
  }

  function connectionLines(id) {
    const buckets = {
      from: [], to: [], calls: [], calledBy: [], extIn: [], extOut: [],
    };
    (edgesOf.get(id) || []).forEach(({ edge }) => {
      const planned = !!edge.planned;
      if (edge.kind === "results") {
        if (edge.to === id) buckets.from.push({ name: displayName(edge.from), planned });
        else buckets.to.push({ name: displayName(edge.to), planned });
      } else if (edge.kind === "calls") {
        if (edge.from === id) buckets.calls.push({ name: displayName(edge.to), planned });
        else buckets.calledBy.push({ name: displayName(edge.from), planned });
      } else if (edge.kind === "external_in" && edge.to === id) {
        buckets.extIn.push({ name: edge.from, planned });
      } else if (edge.kind === "external_out" && edge.from === id) {
        buckets.extOut.push({ name: edge.to, planned });
      }
    });
    const byName = (a, b) => a.name.localeCompare(b.name);
    Object.keys(buckets).forEach((key) => buckets[key].sort(byName));

    const lines = [];
    const line = (label, entries) => {
      if (!entries.length) return;
      lines.push(`<div class="mp-tip-line"><span class="k">${label}</span> ${
        nameList(entries)}</div>`);
    };
    line("Gets results from", buckets.from);
    line("Provides results to", buckets.to);
    line("Calls", buckets.calls);
    line("Called by", buckets.calledBy);
    if (buckets.extIn.length || buckets.extOut.length) {
      const parts = [];
      if (buckets.extIn.length) parts.push(`◀ ${nameList(buckets.extIn)}`);
      if (buckets.extOut.length) parts.push(`▶ ${nameList(buckets.extOut)}`);
      lines.push(`<div class="mp-tip-line"><span class="k">Externals</span> ${
        parts.join(" · ")}</div>`);
    }
    if (!lines.length) {
      lines.push('<div class="mp-tip-line"><span class="k">Connections</span> none recorded</div>');
    }
    return lines.join("");
  }

  function nodeTip(id) {
    const row = rowById.get(id);
    if (!row) return "";
    const version = versionOf(row);
    const head = [
      `<span class="title">${esc(row.name || id)}</span>`,
      "<dl>",
      `<dt>Owner</dt><dd>${esc(row.owner || "—")}</dd>`,
    ];
    if (row.type) head.push(`<dt>Type</dt><dd>${esc(row.type)}</dd>`);
    head.push(`<dt>Version</dt><dd>${version ? esc(version) : "—"}${
      TD.table.hasDrift(row) ? ' <span class="mp-neq-tip">≠</span>' : ""}</dd>`);
    head.push("</dl>");
    return head.join("") + connectionLines(id);
  }

  function edgeTip(target) {
    const from = target.dataset.from;
    const to = target.dataset.to;
    const word = target.dataset.word || target.dataset.kind;
    const planned = target.dataset.planned === "1" ? " (planned)" : "";
    return `${esc(displayName(from))} → ${esc(displayName(to))}`
      + `<div class="mp-tip-line"><span class="k">${esc(word)}${planned}</span></div>`;
  }

  /* --- Export --------------------------------------------------------------- */

  /* A standalone document, not a copy of the DOM.

     Two belts and one pair of braces, because a file that opens blank is worse
     than no file: the `.mp` rules are collected out of the page's own inline
     stylesheet with every `var(--x)` replaced by the value this reader's theme
     computed, *and* the paint properties are inlined on each element from
     `getComputedStyle`, so the picture survives a renderer that ignores the
     style block. The size comes from the scene, never from the viewport, or an
     `Image` has no intrinsic dimensions to rasterise at. */
  const PAINT = [
    "fill", "fill-opacity", "fill-rule", "stroke", "stroke-width", "stroke-dasharray",
    "stroke-linecap", "stroke-linejoin", "opacity", "font-family", "font-size",
    "font-weight", "font-style", "letter-spacing", "text-anchor", "paint-order",
  ];

  function collectCss() {
    const computed = getComputedStyle(document.documentElement);
    const rules = [];
    [...document.styleSheets].forEach((sheet) => {
      let list;
      try { list = sheet.cssRules; } catch { return; }
      [...list].forEach((rule) => {
        if (!rule.selectorText || !rule.selectorText.includes(".mp")) return;
        if (/:hover|\.dragging|\.mp-tool|\.mp-legend|\.mp-minimap|\.mp-pill|\.mp-toast/
          .test(rule.selectorText)) return;
        rules.push(rule.cssText);
      });
    });
    return rules.join("\n").replace(
      /var\(\s*(--[\w-]+)\s*(?:,([^()]*))?\)/g,
      (whole, name, fallback) =>
        (computed.getPropertyValue(name) || "").trim() || (fallback || "").trim() || whole,
    );
  }

  function exportText() {
    const computed = getComputedStyle(document.documentElement);
    const page = (computed.getPropertyValue("--page") || "#ffffff").trim();
    const clone = root.cloneNode(true);
    // The class carries `width: 100%`, which in a standalone file leaves a
    // rasteriser with no intrinsic size to draw at.
    clone.removeAttribute("class");
    clone.setAttribute("xmlns", NS);
    clone.setAttribute("xmlns:xlink", XLINK);
    clone.setAttribute("width", scene.bounds.w);
    clone.setAttribute("height", scene.bounds.h);
    clone.setAttribute("viewBox", `0 0 ${scene.bounds.w} ${scene.bounds.h}`);
    const cameraG = clone.querySelector(".mp-camera");
    if (cameraG) cameraG.removeAttribute("transform");
    clone.querySelectorAll(".mp-hit, .mp-lane-hit, use, foreignObject").forEach((el) => el.remove());
    clone.querySelectorAll("[tabindex]").forEach((el) => el.removeAttribute("tabindex"));
    // The lanes carry `animation-delay: calc(n * var(--stagger))` for the
    // first-paint fade; a custom property with nothing to resolve it against
    // is the one thing that would still say `var(` in the finished file.
    clone.querySelectorAll("[style]").forEach((el) => el.style.removeProperty("animation-delay"));

    // Paired by a temporary index rather than by position: the removals above
    // make the clone a subsequence of the original, and walking two lists in
    // step would silently give one element another's colours.
    const originals = [...root.querySelectorAll("*")];
    originals.forEach((el, i) => el.setAttribute("data-mp-x", i));
    const marked = clone.querySelectorAll("[data-mp-x]");
    marked.forEach((copy) => {
      const original = originals[Number(copy.getAttribute("data-mp-x"))];
      copy.removeAttribute("data-mp-x");
      if (!original) return;
      const style = getComputedStyle(original);
      PAINT.forEach((property) => {
        const value = style.getPropertyValue(property);
        if (value) copy.style.setProperty(property, value);
      });
    });
    originals.forEach((el) => el.removeAttribute("data-mp-x"));

    const style = document.createElementNS(NS, "style");
    style.textContent = collectCss();
    const background = svg("rect", {
      x: 0, y: 0, width: scene.bounds.w, height: scene.bounds.h, fill: page,
    });
    clone.insertBefore(background, clone.firstChild);
    clone.insertBefore(style, clone.firstChild);
    return `<?xml version="1.0" encoding="UTF-8"?>\n${new XMLSerializer().serializeToString(clone)}`;
  }

  /* One download path for both formats, with an honest fallback: some embedded
     contexts refuse a programmatic download entirely, and opening the file in
     a tab is better than a button that does nothing. */
  function downloadUrl(url, name, revoke) {
    try {
      const link = document.createElement("a");
      if (!("download" in link)) throw new Error("no download attribute");
      link.href = url;
      link.download = name;
      link.rel = "noopener";
      document.body.append(link);
      link.click();
      link.remove();
      say(`Saved ${name}`);
    } catch {
      const opened = window.open(url, "_blank");
      say(opened
        ? `This browser blocked the download; ${name} opened in a new tab instead.`
        : `This browser blocked the download and the pop-up; allow one to save ${name}.`);
    }
    if (revoke) setTimeout(() => URL.revokeObjectURL(url), 20000);
  }

  function save(blob, name) {
    // blob: URLs are blocked for programmatic downloads from file:// in most
    // browsers; a data URL of the same bytes usually still works.
    if (location.protocol === "file:") {
      const reader = new FileReader();
      reader.onload = () => downloadUrl(reader.result, name, false);
      reader.onerror = () => say(`Could not prepare ${name} for download.`);
      reader.readAsDataURL(blob);
      return;
    }
    downloadUrl(URL.createObjectURL(blob), name, true);
  }

  function exportSvg() {
    save(new Blob([exportText()], { type: "image/svg+xml;charset=utf-8" }),
      "translator-components-map.svg");
  }

  function exportPng() {
    const text = exportText();
    // A data: URL rather than a blob: one — a blob-backed <img> taints the
    // canvas in some browsers and `toBlob` then throws a security error.
    const url = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(text)}`;
    const image = new Image();
    image.decoding = "sync";
    image.onload = () => {
      const canvas = document.createElement("canvas");
      canvas.width = Math.round(scene.bounds.w * 2);
      canvas.height = Math.round(scene.bounds.h * 2);
      const ctx = canvas.getContext("2d");
      const page = (getComputedStyle(document.documentElement)
        .getPropertyValue("--page") || "#ffffff").trim();
      ctx.fillStyle = page;
      ctx.fillRect(0, 0, canvas.width, canvas.height);
      ctx.drawImage(image, 0, 0, canvas.width, canvas.height);
      try {
        if (location.protocol === "file:") {
          downloadUrl(canvas.toDataURL("image/png"), "translator-components-map.png", false);
          return;
        }
        canvas.toBlob((blob) => {
          if (blob) save(blob, "translator-components-map.png");
          else say("This browser could not rasterise the map; the SVG still works.");
        }, "image/png");
      } catch {
        say("This browser could not rasterise the map; the SVG still works.");
      }
    };
    image.onerror = () => say("This browser could not rasterise the map; the SVG still works.");
    image.src = url;
  }

  /* --- Public ------------------------------------------------------------- */

  map.render = function render(container) {
    if (!container) return;
    if (host !== container || !scene) build(container);
    else { size(); paint(); }
  };

  map.fit = () => fit(true);
  map.zoomBy = zoomBy;

  map.focus = function focus(id) {
    if (!nodeById.has(id)) return;
    selShown = id;
    nodeEls.forEach((el, key) => el.classList.toggle("sel", key === id));
    flyTo(nodeById.get(id), Math.max(1.25, cam.k));
  };

  map.setEdgeKinds = function setEdgeKinds(kinds) {
    const list = [...(kinds || [])].filter((kind) => KINDS.some((k) => k.key === kind));
    allOff = list.length === 0;
    TD.commit({ edges: list });
  };

  map.exportSvg = exportSvg;
  map.exportPng = exportPng;
  map.exportText = () => exportText();
  map.KINDS = KINDS;
  map.nodeNameLimit = nodeNameLimit;
})();
