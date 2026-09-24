/*
  The component page: one component, full width, at `?component=<id>`.

  The drawer answers "what is this?" beside the table; this page answers "tell
  me everything about this one, so I can send someone the link". It renders
  the same six panels detail.js gives the drawer, as sections rather than
  tabs, with two things the drawer has no room for: the four environments
  side by side (detail.envMatrix), and the component's own file laid out
  field by field against the schema, so a reader can see which fields nobody
  has filled in yet — the gaps are the point of that section, which is why
  it is the one place on the page that prints a row for an absent value.

  Nothing here is a fact the page invents. Every value comes from the row, the
  schema in the payload, or unknown.yaml; the page only decides where it goes.
  And nothing here touches the document at definition time, so tests/web/ can
  load it under node: `render` is the only function that needs a DOM, and the
  pieces it assembles (`page`, `notFound`, `recordedSection`, `schemaFields`)
  are exposed for the tests.
*/

(() => {
  "use strict";

  const TD = (globalThis.TD = globalThis.TD || {});
  const component = (TD.component = TD.component || {});

  const H = TD.detail.helpers;
  const { esc, DASH, list, filled, mono, note, ext, heading, caption, muted, stack } = H;

  const data = () => TD.DATA || {};
  const rows = () => data().rows || [];
  const repoUrl = () => String(data().repo_url || "").replace(/\/+$/, "");

  /* --- Resolving the id ---------------------------------------------------- */

  /* Exact first, then case-insensitive: references resolve case-insensitively
     everywhere else in this repository, and a link somebody typed as
     `?component=ARAX` should land rather than 404. The caller rewrites the
     URL to the canonical spelling when the two differ. */
  function resolve(id) {
    if (!id) return null;
    const exact = rows().find((row) => row.id === id);
    if (exact) return exact;
    const folded = String(id).toLowerCase();
    return rows().find((row) => String(row.id).toLowerCase() === folded) || null;
  }

  /* The address of a component page, from wherever this page is. Built from
     the path rather than `location.origin`, which is the string "null" on a
     file:// page — and this page has to work from a mail attachment. */
  function permalink(id) {
    const base = String(location.href).split(/[?#]/)[0];
    return `${base}?component=${encodeURIComponent(id)}`;
  }

  /* --- The file, field by field -------------------------------------------- */

  /* Flattens the schema's `properties` into the rows the Recorded section
     draws, in schema order: a scalar or list is one row, a block with its
     own `properties` (identifiers, itrb, connections, diagram, endpoints) is
     one row per key inside it, and `environments` is one row per environment
     the payload names. `endpoints` may carry keys the schema does not name
     (`additionalProperties`), so the file's own extra keys are appended when
     a file is given. Each row is {path, label, description, required, kind}. */
  function schemaFields(schema, recorded) {
    const props = (schema && schema.properties) || {};
    const required = new Set(list(schema && schema.required));
    const out = [];
    const push = (path, spec, parentRequired) => {
      const kind = Array.isArray(spec.type) ? spec.type.find((t) => t !== "null") || spec.type[0]
        : spec.type || (spec.enum ? "string" : spec.$ref ? "array" : "string");
      out.push({
        path,
        label: path.join("."),
        description: String(spec.description || ""),
        required: !!parentRequired,
        kind,
      });
    };
    for (const [key, spec] of Object.entries(props)) {
      if (!spec || typeof spec !== "object") continue;
      const nested = spec.properties && typeof spec.properties === "object" ? spec.properties : null;
      if (key === "environments") {
        const envs = list(TD.ENVS).length ? TD.ENVS : Object.keys(nested || {});
        for (const env of envs) push([key, env], { type: "object", description: `Base URL and location for ${env}.` }, false);
        continue;
      }
      if (nested && spec.type === "object") {
        const inner = new Set(list(spec.required));
        for (const [sub, subSpec] of Object.entries(nested)) push([key, sub], subSpec || {}, inner.has(sub));
        // Keys the file has under this block that the schema does not name
        // (endpoints allows them): shown, so nothing recorded is invisible.
        const block = recorded && recorded[key];
        if (block && typeof block === "object" && !Array.isArray(block)) {
          for (const sub of Object.keys(block)) {
            if (!(sub in nested)) push([key, sub], { type: "string", description: "" }, false);
          }
        }
        continue;
      }
      push([key], spec, required.has(key));
    }
    return out;
  }

  /* Absent, null and empty are three different claims in this format —
     docs/component-metadata.md: absent means "not recorded yet", an explicit
     null or [] means "checked, there is none" — and this is where the
     distinction is finally shown rather than flattened. */
  function fieldState(recorded, path) {
    let node = recorded;
    for (const key of path) {
      if (!node || typeof node !== "object" || !(key in node)) return { state: "absent" };
      node = node[key];
    }
    if (node === null || (Array.isArray(node) && node.length === 0)) return { state: "none", value: node };
    if (typeof node === "object" && !Array.isArray(node) && Object.keys(node).length === 0) {
      return { state: "none", value: node };
    }
    return { state: "recorded", value: node };
  }

  /* A recorded value as HTML. Strings that are URLs become links; a list of
     strings is joined; a list of mappings (repositories, documentation,
     externals) is one line each; a mapping (an environment, an itrb block)
     is `key value` pairs. Nothing here is prose the page wrote. */
  function valueHtml(value) {
    if (value === null || value === undefined) return DASH;
    if (typeof value === "boolean") return value ? "yes" : "no";
    if (typeof value === "string") {
      return /^https?:\/\//i.test(value) ? ext(value, value, "dw-link dw-mono") : mono(value);
    }
    if (typeof value === "number") return mono(String(value));
    if (Array.isArray(value)) {
      if (!value.length) return DASH;
      if (value.every((v) => typeof v !== "object" || v === null)) {
        return value.map((v) => valueHtml(v)).join(", ");
      }
      return stack(value.map((v) => valueHtml(v)));
    }
    const entries = Object.entries(value);
    if (!entries.length) return DASH;
    return entries.map(([k, v]) =>
      `<span class="dw-key">${esc(k)}</span> ${valueHtml(v)}`).join(" · ");
  }

  const STATE_WORDS = {
    recorded: "recorded",
    none: "checked: none",
    absent: "not recorded",
  };

  function fileLinks(row) {
    const repo = repoUrl();
    if (!repo) return "";
    const file = `components/${encodeURIComponent(row.id)}.yaml`;
    return `<a class="btn" href="${esc(`${repo}/blob/main/${file}`)}" target="_blank" rel="noopener">View file</a>
      <a class="btn" href="${esc(`${repo}/edit/main/${file}`)}" target="_blank" rel="noopener">Edit on GitHub</a>`;
  }

  function recordedSection(row) {
    const recorded = row.recorded;
    if (!recorded || typeof recorded !== "object") {
      return muted("This build did not carry the component file.");
    }
    const fields = schemaFields(data().component_schema, recorded);
    if (!fields.length) return muted("This build carries no schema to compare the file against.");
    let recordedCount = 0;
    const body = fields.map((field) => {
      const { state, value } = fieldState(recorded, field.path);
      if (state === "recorded") recordedCount += 1;
      const title = field.description ? ` title="${esc(field.description)}"` : "";
      return `<tr class="cp-f cp-f-${state}">
        <th scope="row"${title}>${esc(field.label)}${field.required
          ? ` <span class="dw-note">required</span>` : ""}</th>
        <td class="cp-state">${STATE_WORDS[state]}</td>
        <td class="cp-value">${state === "recorded" ? valueHtml(value) : DASH}</td>
      </tr>`;
    }).join("");
    const absent = fields.length - recordedCount;
    const summary = `${recordedCount} of ${fields.length} fields recorded${absent
      ? ` · <strong>${absent}</strong> not` : ""}`;
    return caption(`the component's own file, components/${row.id}.yaml, against every field the schema allows`)
      + `<p class="cp-count">${summary}</p>`
      + `<div class="dw-tscroll"><table class="dw-t cp-rec"><thead><tr>
          <th>Field</th><th>State</th><th>Value</th></tr></thead><tbody>${body}</tbody></table></div>`
      + `<p class="dw-cap">“not recorded” means nobody has written the field down yet; “checked: none”
          means someone looked and there is nothing to record. Hover a field name for what it holds.</p>`;
  }

  /* --- Not found ----------------------------------------------------------- */

  /* Every identifier a row carries in another naming space, lowercased, so a
     reader who arrived with an OpenTelemetry service name or an ITRB app name
     is offered the component it belongs to. */
  function aliases(row) {
    const out = [row.id, row.name, row.infores, row.smartapi, (row.itrb || {}).app, row.helm_chart]
      .concat(list(row.otel_services), list(row.chart_names))
      .filter(filled)
      .map((v) => String(v).toLowerCase());
    return out.concat(out.filter((v) => v.startsWith("infores:")).map((v) => v.slice(8)));
  }

  function nearMatches(id) {
    const needle = String(id).toLowerCase();
    if (!needle) return [];
    return rows().filter((row) => aliases(row).some((alias) =>
      alias === needle || alias.includes(needle) || needle.includes(alias)));
  }

  function unknownHits(id) {
    const needle = String(id).toLowerCase();
    return list(data().unknown).filter((entry) => String(entry.name || "").toLowerCase() === needle);
  }

  function rowLink(row) {
    return `<a class="dw-conn" href="?component=${esc(encodeURIComponent(row.id))}" data-go="${esc(row.id)}">${
      TD.owner.coin(row.owner)}<span class="dw-connname">${esc(row.name || row.id)}</span>
      <span class="dw-mono dw-connid">${esc(row.id)}</span></a>`;
  }

  function notFound(id) {
    const near = nearMatches(id);
    const seen = unknownHits(id);
    const redacted = (data().redacted || {}).components;
    const repo = repoUrl();
    const parts = [
      `<h1 class="cp-title">No component with the id ${mono(id)}</h1>`,
      caption("This build carries no component file under that id."),
    ];
    if (near.length) {
      parts.push(heading("Did you mean")
        + `<div class="dw-conns">${near.map(rowLink).join("")}</div>`);
    }
    if (seen.length) {
      parts.push(heading("Seen in the platform, claimed by no component")
        + caption("unknown.yaml records identifiers observed in the wild that no component file claims")
        + stack(seen.map((entry) => {
          const owner = entry.component ? resolve(entry.component) : null;
          const whose = entry.component
            ? ` · ${owner ? `<a href="?component=${esc(encodeURIComponent(owner.id))}" data-go="${esc(owner.id)}">${
              esc(owner.name || owner.id)}</a>` : `${mono(entry.component)} ${note("no file yet")}`}`
            : "";
          return `${mono(entry.name)} ${note(entry.kind || "")} ${note(entry.status || "")}${whose}`;
        })));
    }
    if (redacted) {
      parts.push(caption(`This published build leaves out ${redacted} component${redacted === 1 ? "" : "s"}; `
        + `config/privacy.yaml in the repository names them.`));
    }
    if (repo) {
      parts.push(`<p class="dw-muted">Every component this dashboard knows about has a file under
        ${ext(`${repo}/tree/main/components`, "components/ on GitHub")}.</p>`);
    }
    return `<div class="cp cp-notfound">${parts.join("")}</div>`;
  }

  /* --- The page ------------------------------------------------------------ */

  const SECTIONS = [
    { id: "identity", label: "Identity", render: (row) => TD.detail.panels.overview(row) },
    { id: "environments", label: "Environments", render: (row) => TD.detail.envMatrix(row) },
    { id: "releases", label: "Releases", render: (row) => TD.detail.panels.releases(row) },
    { id: "helm", label: "Helm", render: (row) => TD.detail.panels.helm(row) },
    { id: "smartapi", label: "SmartAPI", render: (row) => TD.detail.panels.smartapi(row) },
    { id: "connections", label: "Connections", render: (row) => TD.detail.panels.connections(row) },
    { id: "recorded", label: "Recorded", render: recordedSection },
  ];

  function actions(row) {
    return `<div class="cp-actions">
      <button type="button" class="btn cp-copy" data-copy="${esc(row.id)}">Copy link</button>
      <a class="btn" href="?view=map&amp;sel=${esc(encodeURIComponent(row.id))}" data-map="${esc(row.id)}">Show on map</a>
      ${fileLinks(row)}
    </div>`;
  }

  function page(row) {
    const nav = SECTIONS.map((section) =>
      `<a href="#${section.id}" data-anchor="${section.id}">${esc(section.label)}</a>`).join("");
    const sections = SECTIONS.map((section) => {
      let html;
      try {
        html = section.render(row);
      } catch (error) {
        // One malformed field costs its section, not the page.
        html = muted(`This section could not be rendered for ${row.id}.`);
        if (typeof console !== "undefined") console.error("component:", error);
      }
      return `<section class="cp-sec" id="${section.id}" aria-labelledby="cp-h-${section.id}">
        <h2 class="cp-h" id="cp-h-${section.id}">${esc(section.label)}</h2>${html}</section>`;
    }).join("");
    return `<div class="cp">
      <header class="cp-head">${TD.detail.header(row, { level: 1 })}${actions(row)}</header>
      <nav class="cp-nav" aria-label="Sections">${nav}</nav>
      ${sections}
    </div>`;
  }

  /* --- Rendering into the view --------------------------------------------- */

  let host = null;
  let renderedFor = "";

  function scrollToAnchor(id) {
    if (!host || !id) return;
    let target = null;
    try { target = host.querySelector(`#${CSS.escape(id)}`); } catch { target = null; }
    const scroller = host.querySelector(".cp-scroll");
    if (!target || !scroller) return;
    const nav = host.querySelector(".cp-nav");
    const cover = nav ? nav.getBoundingClientRect().height : 0;
    scroller.scrollTop += target.getBoundingClientRect().top - scroller.getBoundingClientRect().top - cover - 8;
  }

  async function copyLink(button, id) {
    try {
      await navigator.clipboard.writeText(permalink(id));
      button.textContent = "Copied";
    } catch {
      button.textContent = "Press ⌘C";
    }
    setTimeout(() => { button.textContent = "Copy link"; }, 3000);
  }

  function onClick(event) {
    const go = event.target.closest("[data-go]");
    if (go) {
      event.preventDefault();
      if (resolve(go.dataset.go)) TD.navigate({ component: go.dataset.go });
      return;
    }
    const copy = event.target.closest("[data-copy]");
    if (copy) { copyLink(copy, copy.dataset.copy); return; }
    const toMap = event.target.closest("[data-map]");
    if (toMap) {
      event.preventDefault();
      // The map rings and flies to `sel` when it paints, and the drawer opens
      // on it: the page's "show on map" is the map's own selection.
      TD.navigate({ view: "map", component: "", sel: toMap.dataset.map, tab: "" });
      TD.drawer.sync();
      return;
    }
    const anchor = event.target.closest("[data-anchor]");
    if (anchor) {
      // The document does not scroll (html, body are overflow:hidden), so
      // the browser's own fragment navigation would find the section and
      // move nothing; the page's scroller is moved by hand instead.
      event.preventDefault();
      history.replaceState(null, "", `${location.pathname}${location.search}#${anchor.dataset.anchor}`);
      scrollToAnchor(anchor.dataset.anchor);
      return;
    }
    const disc = event.target.closest("[data-disc]");
    if (disc) {
      const expanded = disc.getAttribute("aria-expanded") === "true";
      disc.setAttribute("aria-expanded", expanded ? "false" : "true");
    }
  }

  function bind(container) {
    if (host === container) return;
    host = container;
    container.addEventListener("click", onClick);
    TD.ui.tooltip.bind(container, "[data-tip]", (target) => {
      const full = target.dataset.full || target.textContent || "";
      if (target.dataset.tip === "say") return esc(full);
      if (target.scrollWidth <= target.clientWidth + 1) return "";
      return esc(full);
    });
  }

  component.render = function render(container) {
    if (!container) return;
    bind(container);
    const asked = (TD.state || {}).component || "";
    const row = resolve(asked);
    if (row && row.id !== asked) {
      // Canonical spelling into the URL, silently: the crumb and Copy link
      // read the state, and must not propagate `?component=ARAX`.
      TD.commit({ component: row.id }, { silent: true });
    }
    const key = row ? row.id : `!${asked}`;
    if (renderedFor !== key || !container.firstChild) {
      container.innerHTML = `<div class="cp-scroll">${row ? page(row) : notFound(asked)}</div>`;
      renderedFor = key;
      container.querySelector(".cp-scroll").scrollTop = 0;
    }
    const hash = /^#([A-Za-z][\w-]*)$/.exec(location.hash || "");
    if (hash && row) requestAnimationFrame(() => scrollToAnchor(hash[1]));
  };

  component.title = function title() {
    const row = resolve((TD.state || {}).component || "");
    return row ? row.name || row.id : "";
  };

  /* For the tests, which render without a document. */
  component.resolve = resolve;
  component.schemaFields = schemaFields;
  component.fieldState = fieldState;
  component.recordedSection = recordedSection;
  component.notFound = notFound;
  component.page = page;
  component.nearMatches = nearMatches;
})();
