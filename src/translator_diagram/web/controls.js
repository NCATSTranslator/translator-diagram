/*
  The custom controls. No framework, and no native <select>: a native one
  cannot show an owner's colour, cannot multi-select without turning into a
  scroll box, and paints itself in the operating system's palette rather than
  the page's.

  The cost of replacing it is that every keyboard behaviour a <select> gave
  away free has to be written here — roving tabindex, type-ahead, Home/End,
  Escape, click-outside — so this file is where that lives, once, for every
  control on the page.
*/

(() => {
  "use strict";

  const TD = (globalThis.TD = globalThis.TD || {});
  const ui = (TD.ui = TD.ui || {});
  const esc = (value) => TD.fmt.esc(value);

  let uid = 0;
  const nextId = (prefix) => `${prefix}-${++uid}`;

  /* Inline SVG on currentColor rather than ▾ or ✓: a glyph renders as a
     colour emoji on one platform and as a tofu box on another, and a page
     that must work from file:// cannot fetch an icon font to settle it. */
  const CARET_DOWN = `<svg class="caret-down" viewBox="0 0 10 10" width="9" height="9"
    aria-hidden="true" fill="currentColor"><path d="M5 8 1 3h8z"/></svg>`;
  ui.CARET_DOWN = CARET_DOWN;
  ui.CARET_UP = `<svg class="caret" viewBox="0 0 10 10" width="9" height="9"
    aria-hidden="true" fill="currentColor"><path d="M5 1.5 9 7H1z"/></svg>`;
  ui.CHEVRON = `<svg viewBox="0 0 12 12" width="11" height="11" aria-hidden="true"
    fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"
    stroke-linejoin="round"><path d="M4.5 2.5 8.5 6l-4 3.5"/></svg>`;

  const el = (tag, cls, html) => {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    if (html != null) node.innerHTML = html;
    return node;
  };
  ui.el = el;

  /* --- Listbox ----------------------------------------------------------- */

  /* A menu button plus an ARIA listbox popover. `multi` keeps the popover
     open and toggles, which is what an owner filter has to do; single-select
     closes on choice, which is what a view switch has to do. An option can
     bring its own markup (the owner coins) through `render`. */
  ui.listbox = function listbox(config) {
    const multi = !!config.multi;
    const id = nextId("lb");
    const root = el("div", "lb");
    const button = el("button", "btn");
    button.type = "button";
    button.id = `${id}-btn`;
    button.setAttribute("aria-haspopup", "listbox");
    button.setAttribute("aria-expanded", "false");
    button.setAttribute("aria-controls", `${id}-pop`);

    const pop = el("div", "lb-pop");
    pop.id = `${id}-pop`;
    pop.setAttribute("role", "listbox");
    pop.setAttribute("aria-labelledby", button.id);
    if (multi) pop.setAttribute("aria-multiselectable", "true");
    pop.hidden = true;

    root.append(button, pop);

    let options = config.options || [];
    let value = multi
      ? [...(config.value || [])]
      : (config.value ?? (options[0] ? options[0].value : ""));
    let open = false;
    let typed = "";
    let typedAt = 0;

    const selected = (option) =>
      multi ? value.indexOf(option.value) >= 0 : option.value === value;

    function summary() {
      if (config.summary) return config.summary(value);
      if (!multi) {
        const hit = options.find((option) => option.value === value);
        return hit ? hit.text ?? hit.label : "";
      }
      if (!value.length) return config.placeholder ?? "All";
      if (value.length === 1) return value[0];
      return `${value.length} selected`;
    }

    function paintButton() {
      const set = multi ? value.length > 0 : value !== (config.emptyValue ?? "");
      button.dataset.set = set ? "1" : "0";
      button.innerHTML =
        `<span>${esc(config.label)}</span><span class="val">${esc(summary())}</span>${CARET_DOWN}`;
      const names = multi && value.length ? `: ${value.join(", ")}` : `: ${summary()}`;
      button.setAttribute("aria-label", `${config.label}${names}`);
    }

    function paintOptions() {
      pop.innerHTML = options.map((option, index) => {
        if (option.separator) return '<div class="lb-sep" role="presentation"></div>';
        const body = option.render ? option.render(option) : esc(option.label);
        return `<div class="lb-opt" role="option" data-i="${index}"
          tabindex="-1" aria-selected="${selected(option) ? "true" : "false"}"
          ><span class="tick" aria-hidden="true">✓</span><span class="lbl">${body}</span></div>`;
      }).join("");
    }

    const items = () => [...pop.querySelectorAll(".lb-opt")];

    function focusItem(node) {
      if (!node) return;
      for (const other of items()) {
        other.tabIndex = -1;
        other.classList.remove("active");
      }
      node.tabIndex = 0;
      node.classList.add("active");
      node.focus({ preventScroll: true });
      node.scrollIntoView({ block: "nearest" });
    }

    function place() {
      // The strip can sit low on a short window; flip the popover up rather
      // than let it open off the bottom of the screen.
      pop.classList.remove("up", "right");
      const rect = button.getBoundingClientRect();
      if (rect.bottom + 330 > innerHeight && rect.top > 330) pop.classList.add("up");
      if (rect.left + 260 > innerWidth) pop.classList.add("right");
    }

    function setOpen(next, focusWhich) {
      if (open === next) return;
      open = next;
      pop.hidden = !open;
      button.setAttribute("aria-expanded", open ? "true" : "false");
      if (!open) return;
      place();
      const list = items();
      const chosen = list.find((node) => node.getAttribute("aria-selected") === "true");
      focusItem(focusWhich === "last" ? list[list.length - 1] : chosen || list[0]);
    }

    function choose(index) {
      const option = options[index];
      if (!option || option.separator) return;
      if (multi) {
        // An option with an empty value is the "everything" row: it clears
        // rather than joining the selection, which is the only sane reading
        // of "All owners" sitting in a list of owners.
        if (option.value === "") value = [];
        else if (value.indexOf(option.value) >= 0) {
          value = value.filter((v) => v !== option.value);
        } else value = value.concat([option.value]);
        paintOptions();
        paintButton();
        // By data-i, not by position: a separator is in the options array but
        // not in the node list, so the two indexes are not the same number.
        focusItem(items().find((node) => node.dataset.i === String(index)));
      } else {
        value = option.value;
        paintOptions();
        paintButton();
        setOpen(false);
        button.focus({ preventScroll: true });
      }
      if (config.onChange) config.onChange(multi ? [...value] : value);
    }

    function typeahead(key) {
      const now = Date.now();
      typed = now - typedAt > 700 ? key : typed + key;
      typedAt = now;
      const list = items();
      const start = list.findIndex((node) => node.classList.contains("active"));
      const order = list.map((_, i) => list[(start + 1 + i) % list.length]);
      // The label, not the whole option: every row carries a checkmark span
      // (invisible until selected), and textContent would put a ✓ in front of
      // every letter the reader typed.
      const hit = order.find((node) => {
        const label = node.querySelector(".lbl") || node;
        return (label.textContent || "").trim().toLowerCase().startsWith(typed);
      });
      if (hit) focusItem(hit);
    }

    button.addEventListener("click", () => setOpen(!open));
    button.addEventListener("keydown", (event) => {
      if (event.key === "ArrowDown" || event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        setOpen(true);
      } else if (event.key === "ArrowUp") {
        event.preventDefault();
        setOpen(true, "last");
      }
    });

    pop.addEventListener("click", (event) => {
      const node = event.target.closest(".lb-opt");
      if (node) choose(Number(node.dataset.i));
    });

    pop.addEventListener("keydown", (event) => {
      const list = items();
      const at = list.findIndex((node) => node.classList.contains("active"));
      const key = event.key;
      if (key === "ArrowDown") { event.preventDefault(); focusItem(list[Math.min(at + 1, list.length - 1)]); }
      else if (key === "ArrowUp") { event.preventDefault(); focusItem(list[Math.max(at - 1, 0)]); }
      else if (key === "Home") { event.preventDefault(); focusItem(list[0]); }
      else if (key === "End") { event.preventDefault(); focusItem(list[list.length - 1]); }
      else if (key === "Enter" || key === " ") {
        event.preventDefault();
        if (at >= 0) choose(Number(list[at].dataset.i));
      } else if (key === "Escape") {
        event.preventDefault();
        setOpen(false);
        button.focus({ preventScroll: true });
      } else if (key === "Tab") {
        setOpen(false);
      } else if (key.length === 1 && !event.metaKey && !event.ctrlKey && !event.altKey) {
        typeahead(key.toLowerCase());
      }
    });

    // Pointer-down rather than click: a click that lands on another control
    // should reach it, not be spent closing this popover.
    document.addEventListener("mousedown", (event) => {
      if (open && !root.contains(event.target)) setOpen(false);
    });
    pop.addEventListener("focusout", () => {
      // A frame later: focus is momentarily on <body> while it moves between
      // two options inside the same popover.
      setTimeout(() => {
        if (open && !root.contains(document.activeElement)) setOpen(false);
      }, 0);
    });

    paintOptions();
    paintButton();

    return {
      el: root,
      get value() { return multi ? [...value] : value; },
      set(next) {
        value = multi ? [...(next || [])] : next;
        paintOptions();
        paintButton();
      },
      setOptions(next) {
        options = next || [];
        paintOptions();
        paintButton();
      },
      close() { setOpen(false); },
    };
  };

  /* --- Segmented control -------------------------------------------------- */

  ui.segmented = function segmented(config) {
    const root = el("div", "seg");
    root.setAttribute("role", "radiogroup");
    if (config.label) root.setAttribute("aria-label", config.label);
    const indicator = el("span", "ind");
    root.append(indicator);

    let value = config.value ?? (config.items[0] && config.items[0].value);

    const buttons = config.items.map((item) => {
      const button = el("button", null, esc(item.label));
      button.type = "button";
      button.setAttribute("role", "radio");
      button.dataset.value = item.value;
      root.append(button);
      return button;
    });

    function measure() {
      const active = buttons.find((button) => button.dataset.value === value) || buttons[0];
      if (!active || !active.offsetWidth) return;
      indicator.style.width = `${active.offsetWidth}px`;
      indicator.style.transform = `translateX(${active.offsetLeft - 2}px)`;
    }

    function paint() {
      for (const button of buttons) {
        const on = button.dataset.value === value;
        button.setAttribute("aria-checked", on ? "true" : "false");
        button.tabIndex = on ? 0 : -1;
      }
      measure();
    }

    function pick(next, focus) {
      if (next === value) return;
      value = next;
      paint();
      if (focus) {
        const button = buttons.find((b) => b.dataset.value === value);
        if (button) button.focus({ preventScroll: true });
      }
      if (config.onChange) config.onChange(value);
    }

    root.addEventListener("click", (event) => {
      const button = event.target.closest("button[data-value]");
      if (button) pick(button.dataset.value, false);
    });
    root.addEventListener("keydown", (event) => {
      const at = buttons.findIndex((button) => button.dataset.value === value);
      if (event.key === "ArrowRight" || event.key === "ArrowDown") {
        event.preventDefault();
        pick(buttons[(at + 1) % buttons.length].dataset.value, true);
      } else if (event.key === "ArrowLeft" || event.key === "ArrowUp") {
        event.preventDefault();
        pick(buttons[(at - 1 + buttons.length) % buttons.length].dataset.value, true);
      }
    });

    paint();
    return {
      el: root,
      measure,
      get value() { return value; },
      set(next) { value = next; paint(); },
    };
  };

  /* --- Tooltip ------------------------------------------------------------ */

  /* One instance for the whole page. Two reasons it is not one element per
     anchor: 45 environment cells plus their release chips would be a hundred
     hidden nodes in the DOM, and only one of them can ever be visible, so the
     positioning and the delay logic would be written a hundred times over. */
  const tooltip = (() => {
    let node = null;
    let anchor = null;
    let timer = 0;
    let lastHide = 0;
    let describedId = "";

    function ensure() {
      if (node) return node;
      node = el("div", "tip");
      node.setAttribute("role", "tooltip");
      node.id = "td-tip";
      node.hidden = true;
      document.body.append(node);
      return node;
    }

    function position(target) {
      const tip = ensure();
      const rect = target.getBoundingClientRect();
      const box = tip.getBoundingClientRect();
      const gap = 6;
      let top = rect.top - box.height - gap;
      if (top < 8) top = rect.bottom + gap;
      let left = rect.left + rect.width / 2 - box.width / 2;
      left = Math.max(8, Math.min(left, innerWidth - box.width - 8));
      tip.style.top = `${Math.round(top)}px`;
      tip.style.left = `${Math.round(left)}px`;
    }

    function paint(target, html) {
      const tip = ensure();
      tip.innerHTML = html;
      tip.hidden = false;
      position(target);
      tip.classList.add("on");
      anchor = target;
      // Linked only while shown: an aria-describedby pointing at a hidden
      // node reads as an empty description on some screen readers.
      describedId = target.getAttribute("aria-describedby") || "";
      target.setAttribute("aria-describedby", tip.id);
    }

    function show(target, html) {
      if (!target || !html) return;
      clearTimeout(timer);
      // Warm: the reader is already scanning cells, and a fresh 240ms wait per
      // cell would make the row feel unresponsive.
      const delay = Date.now() - lastHide < 400 ? 0 : 240;
      if (delay === 0) { paint(target, html); return; }
      timer = setTimeout(() => paint(target, html), delay);
    }

    function hide() {
      clearTimeout(timer);
      if (!node || node.hidden) return;
      if (anchor) {
        if (describedId) anchor.setAttribute("aria-describedby", describedId);
        else anchor.removeAttribute("aria-describedby");
      }
      anchor = null;
      describedId = "";
      node.classList.remove("on");
      node.hidden = true;
      lastHide = Date.now();
    }

    /* Delegated, because the table rewrites its body on every filter change
       and a listener bound to a cell would be thrown away with it. */
    function bind(root, selector, build) {
      const enter = (event) => {
        const target = event.target.closest(selector);
        if (!target || !root.contains(target)) return;
        const html = build(target);
        if (html) show(target, html);
      };
      const leave = (event) => {
        const target = event.target.closest(selector);
        if (target) hide();
      };
      root.addEventListener("mouseover", enter);
      root.addEventListener("mouseout", leave);
      root.addEventListener("focusin", enter);
      root.addEventListener("focusout", leave);
    }

    return { show, hide, bind };
  })();

  ui.tooltip = tooltip;
  addEventListener("scroll", () => tooltip.hide(), true);

  /* --- Tabs --------------------------------------------------------------- */

  ui.tabs = function tabs(config) {
    const root = el("div", "tabs");
    root.setAttribute("role", "tablist");
    if (config.label) root.setAttribute("aria-label", config.label);
    let value = config.value ?? (config.tabs[0] && config.tabs[0].id);

    const buttons = config.tabs.map((tab) => {
      const button = el("button", null, esc(tab.label));
      button.type = "button";
      button.setAttribute("role", "tab");
      button.dataset.id = tab.id;
      if (tab.panel) button.setAttribute("aria-controls", tab.panel);
      root.append(button);
      return button;
    });

    function paint() {
      for (const button of buttons) {
        const on = button.dataset.id === value;
        button.setAttribute("aria-selected", on ? "true" : "false");
        button.tabIndex = on ? 0 : -1;
      }
    }

    function pick(next, focus) {
      if (next === value) return;
      value = next;
      paint();
      if (focus) {
        const button = buttons.find((b) => b.dataset.id === value);
        if (button) button.focus({ preventScroll: true });
      }
      if (config.onChange) config.onChange(value);
    }

    root.addEventListener("click", (event) => {
      const button = event.target.closest("button[data-id]");
      if (button) pick(button.dataset.id, false);
    });
    root.addEventListener("keydown", (event) => {
      const at = buttons.findIndex((button) => button.dataset.id === value);
      if (event.key === "ArrowRight") { event.preventDefault(); pick(buttons[(at + 1) % buttons.length].dataset.id, true); }
      else if (event.key === "ArrowLeft") { event.preventDefault(); pick(buttons[(at - 1 + buttons.length) % buttons.length].dataset.id, true); }
      else if (event.key === "Home") { event.preventDefault(); pick(buttons[0].dataset.id, true); }
      else if (event.key === "End") { event.preventDefault(); pick(buttons[buttons.length - 1].dataset.id, true); }
    });

    paint();
    return { el: root, get value() { return value; }, set(next) { value = next; paint(); } };
  };
})();
