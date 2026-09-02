/*
  The map's geometry, and nothing else: no DOM, no colours, no events.

  `TD.layout.compute(input)` turns the payload's stages, rows, edges and
  externals into a scene of rectangles and path strings. It is a pure function
  of its argument — same payload in, byte-identical scene out — which is what
  lets `tests/web/layout.test.js` load this file alone into a bare Node
  context (`globalThis.TD = {}`, then `vm.runInThisContext`) and assert on
  ranks, contiguity, overlap and determinism with no browser.

  The split is deliberate. Layout is the half with judgement in it: which
  component sits beside which, how many edges cross, where a long edge runs.
  That judgement is worth testing, and it is only testable while it is
  separate from the SVG that draws it.

  The picture is a Sugiyama layering — rank from the stage order, order within
  a rank from barycenter sweeps, coordinates from a fixed grid — with five
  things that are not textbook and are here because the data or the reviewer
  asked for them:

  - **No edge may cross a node it is not attached to.** That is a promise, not
    an aspiration: `checkPaths` samples every finished path every 8px against
    every rectangle and collects the hits into `scene.violations`, the unit
    test asserts it is empty on a fixture *and* on the real payload, and
    map.js warns in the console if one ever appears. Everything below about
    routing exists to keep that list empty.
  - **Rows are separated by a gutter, and every horizontal run happens in
    one.** An edge that spans more than one row is orthogonal: down from the
    source's bottom port into the gutter under it, along that gutter to a
    vertical channel with no nodes in it, down the channel, and into the
    target's top port. Adjacent rows keep a cubic, whose y never leaves the
    gap between the two rows and which is therefore safe by construction.
  - **Dummies are the channels.** Six edges run from Retriever and the three
    Shepherds past the whole User-interface row to the component toolkit.
    Each gets a 10px reserved column in every row it crosses; that column is
    what the orthogonal route descends through. Dummies are sorted by the same
    barycenter as everything else and never appear in the output except as a
    corner on a path.
  - A component flagged `diagram.ubiquitous` (jaeger) is answered by nine
    others; ranking it would drag nine edges through the middle, so it goes to
    a rail column right of every row, reached by its own elbow.
  - `part_of` members are kept contiguous inside their row, so the three Dog
    Park tiers and the three Shepherds read as one thing each.

  A rank with no visible components is not a row at all: `diagram.hide` takes a
  component out of the nodes, the edges, the externals and the stage it was in,
  and a stage left empty by that is dropped rather than drawn as a gap.
*/

(() => {
  "use strict";

  const TD = (globalThis.TD = globalThis.TD || {});

  /* Every measurement the picture depends on, in one object so a test can
     shrink the grid and still assert on the same rules. */
  const DEFAULTS = {
    nodeW: 188,
    nodeH: 60,
    colGap: 28,
    dummyW: 10,
    dummyGap: 22,
    laneGap: 96,
    leftPad: 200,
    topPad: 24,
    edgePad: 40,
    railGap: 96,
    extW: 148,
    extH: 36,
    extGap: 64,
    sweeps: 8,
    portStep: 8,
    groupPad: 8,
    corner: 12,
    trackStep: 10,
    tracks: 5,
    marginStep: 20,
    marginTracks: 3,
    arcClear: 22,
    sampleStep: 8,
  };

  /* Two decimals. Paths are compared for equality by the determinism test and
     by nothing else — but a float tail that differs in the last bit would make
     two identical scenes look different, which is the one thing this function
     promises not to do. */
  const r2 = (v) => Math.round(v * 100) / 100;
  const cmpStr = (a, b) => (a < b ? -1 : a > b ? 1 : 0);
  const cx = (n) => n.x + n.w / 2;
  const cy = (n) => n.y + n.h / 2;

  /* --- Order within a row --------------------------------------------------- */

  /* One row re-ordered by barycenter, with `part_of` members held together.

     The groups are the reason this is not a one-line sort: a member's own
     barycenter can put it either side of a neighbour that is not in the group,
     and letting that happen splits Shepherd in half. Members are sorted inside
     the group, the group is placed by its members' mean, and the group moves
     as one unit.

     Ties fall back to the initial index (the stage file's own order) and then
     to the key, so the result does not depend on the engine's sort being
     stable or on the order a Map happened to be built in. */
  function arrange(keys, bary, groupOf, initialIndex) {
    const counts = new Map();
    keys.forEach((key) => {
      const g = groupOf(key);
      if (g) counts.set(g, (counts.get(g) || 0) + 1);
    });

    const units = [];
    const byGroup = new Map();
    keys.forEach((key) => {
      const g = groupOf(key);
      // A group with one member in this row is not a group here: it would draw
      // a rectangle around a single node and say nothing.
      if (!g || counts.get(g) < 2) {
        units.push({ key: `u:${key}`, ids: [key] });
        return;
      }
      let unit = byGroup.get(g);
      if (!unit) {
        unit = { key: `g:${g}`, ids: [] };
        byGroup.set(g, unit);
        units.push(unit);
      }
      unit.ids.push(key);
    });

    const val = (key) => (bary.has(key) ? bary.get(key) : 0);
    const tie = (key) => (initialIndex.has(key) ? initialIndex.get(key) : 0);

    units.forEach((unit) => {
      unit.ids.sort((a, b) => val(a) - val(b) || tie(a) - tie(b) || cmpStr(a, b));
      unit.bary = unit.ids.reduce((sum, id) => sum + val(id), 0) / unit.ids.length;
      unit.tie = unit.ids.reduce((min, id) => Math.min(min, tie(id)), Infinity);
    });
    units.sort((a, b) => a.bary - b.bary || a.tie - b.tie || cmpStr(a.key, b.key));

    const out = [];
    units.forEach((unit) => unit.ids.forEach((id) => out.push(id)));
    return out;
  }

  /* --- Ports ---------------------------------------------------------------- */

  /* Where an edge meets a node — always exactly on the rectangle's border, so
     an arrowhead registered at the path's end sits against that border with
     its body outside the node. Parallel edges leaving the same side are spread
     along it in the order of the far end's position, which stops the four
     edges out of ARS leaving as one thick line. The step shrinks when a side
     is crowded, so a port never falls off the rectangle. */
  function portPos(node, side, index, count, step) {
    if (side === "top" || side === "bottom") {
      const span = count > 1 ? Math.min(step, (node.w - 24) / (count - 1)) : step;
      return {
        x: r2(cx(node) + (index - (count - 1) / 2) * span),
        y: side === "bottom" ? node.y + node.h : node.y,
      };
    }
    const span = count > 1 ? Math.min(step, (node.h - 16) / (count - 1)) : step;
    return {
      x: side === "left" ? node.x : node.x + node.w,
      y: r2(cy(node) + (index - (count - 1) / 2) * span),
    };
  }

  /* --- Path builders --------------------------------------------------------- */

  /* One cubic between two rows, with vertical tangents at both ends. Its y
     never leaves the interval between the two ports — the gap between the two
     rows — so it cannot reach a node in either. That is why adjacent-row edges
     are allowed to stay curved while everything longer is not. */
  function cubicDown(from, to) {
    const pull = Math.max(18, Math.abs(to.y - from.y) * 0.45);
    const sign = to.y >= from.y ? 1 : -1;
    return `M ${r2(from.x)} ${r2(from.y)} C ${r2(from.x)} ${r2(from.y + sign * pull)}`
      + ` ${r2(to.x)} ${r2(to.y - sign * pull)} ${r2(to.x)} ${r2(to.y)}`;
  }

  /* An orthogonal polyline with rounded corners. Every long edge is one of
     these: a straight leg is the only shape whose clearance can be reasoned
     about, which is what makes "no edge crosses a node" a promise rather than
     a hope. */
  function elbow(points, radius) {
    const pts = [];
    points.forEach((p) => {
      const last = pts[pts.length - 1];
      if (last && Math.abs(last.x - p.x) < 0.01 && Math.abs(last.y - p.y) < 0.01) return;
      pts.push(p);
    });
    if (pts.length < 2) {
      const only = pts[0] || { x: 0, y: 0 };
      return `M ${r2(only.x)} ${r2(only.y)} L ${r2(only.x)} ${r2(only.y)}`;
    }
    const towards = (from, to, d) => {
      const len = Math.hypot(to.x - from.x, to.y - from.y) || 1;
      return {
        x: from.x + ((to.x - from.x) / len) * d,
        y: from.y + ((to.y - from.y) / len) * d,
      };
    };
    let d = `M ${r2(pts[0].x)} ${r2(pts[0].y)}`;
    for (let i = 1; i < pts.length - 1; i += 1) {
      const prev = pts[i - 1];
      const cur = pts[i];
      const next = pts[i + 1];
      const r = Math.min(
        radius,
        Math.hypot(cur.x - prev.x, cur.y - prev.y) / 2,
        Math.hypot(next.x - cur.x, next.y - cur.y) / 2,
      );
      const a = towards(cur, prev, r);
      const b = towards(cur, next, r);
      d += ` L ${r2(a.x)} ${r2(a.y)} Q ${r2(cur.x)} ${r2(cur.y)} ${r2(b.x)} ${r2(b.y)}`;
    }
    const end = pts[pts.length - 1];
    return `${d} L ${r2(end.x)} ${r2(end.y)}`;
  }

  /* --- The promise ----------------------------------------------------------- */

  /* Every finished path, sampled, against every rectangle it is not attached
     to.

     This is the check the whole routing scheme exists to pass, so it lives
     here rather than in the test: a caller gets the list in the scene and can
     say so out loud, and the test asserts it is empty on the real payload as
     well as on a fixture. Sampled rather than solved because a Bézier against
     a rectangle has no cheap exact answer, and 8px is a fraction of the
     shortest side of anything on this picture. */
  function samplePath(d, step) {
    const tokens = d.replace(/,/g, " ").trim().split(/\s+/);
    const points = [];
    let i = 0;
    let cursor = { x: 0, y: 0 };
    const push = (x, y) => points.push({ x, y });
    const parts = (a, b) => Math.max(2, Math.ceil(Math.hypot(b.x - a.x, b.y - a.y) / step));
    while (i < tokens.length) {
      const command = tokens[i];
      i += 1;
      if (command === "M") {
        cursor = { x: +tokens[i], y: +tokens[i + 1] };
        i += 2;
        push(cursor.x, cursor.y);
      } else if (command === "L") {
        const to = { x: +tokens[i], y: +tokens[i + 1] };
        i += 2;
        const n = parts(cursor, to);
        for (let s = 1; s <= n; s += 1) {
          push(cursor.x + (to.x - cursor.x) * (s / n), cursor.y + (to.y - cursor.y) * (s / n));
        }
        cursor = to;
      } else if (command === "Q") {
        const c = { x: +tokens[i], y: +tokens[i + 1] };
        const to = { x: +tokens[i + 2], y: +tokens[i + 3] };
        i += 4;
        const n = parts(cursor, to) + 2;
        for (let s = 1; s <= n; s += 1) {
          const t = s / n;
          const u = 1 - t;
          push(u * u * cursor.x + 2 * u * t * c.x + t * t * to.x,
            u * u * cursor.y + 2 * u * t * c.y + t * t * to.y);
        }
        cursor = to;
      } else if (command === "C") {
        const c1 = { x: +tokens[i], y: +tokens[i + 1] };
        const c2 = { x: +tokens[i + 2], y: +tokens[i + 3] };
        const to = { x: +tokens[i + 4], y: +tokens[i + 5] };
        i += 6;
        const n = parts(cursor, to) + 4;
        for (let s = 1; s <= n; s += 1) {
          const t = s / n;
          const u = 1 - t;
          push(u * u * u * cursor.x + 3 * u * u * t * c1.x + 3 * u * t * t * c2.x + t * t * t * to.x,
            u * u * u * cursor.y + 3 * u * u * t * c1.y + 3 * u * t * t * c2.y + t * t * t * to.y);
        }
        cursor = to;
      } else {
        i += 1;
      }
    }
    return points;
  }

  function checkPaths(edges, boxes, step) {
    const violations = [];
    edges.forEach((edge) => {
      const points = samplePath(edge.path, step || DEFAULTS.sampleStep);
      boxes.forEach((box) => {
        const id = box.id || box.name;
        if (id === edge.from || id === edge.to) return;
        // Half a pixel of inset, so a path that runs exactly along a border —
        // which an arc out of a side port deliberately does — is not a hit.
        for (let i = 0; i < points.length; i += 1) {
          const p = points[i];
          if (p.x > box.x + 0.5 && p.x < box.x + box.w - 0.5
            && p.y > box.y + 0.5 && p.y < box.y + box.h - 0.5) {
            violations.push({ from: edge.from, to: edge.to, through: id });
            return;
          }
        }
      });
    });
    return violations;
  }

  /* --- The scene ------------------------------------------------------------- */

  function compute(input) {
    const source = input || {};
    const opt = Object.assign({}, DEFAULTS, source.options || {});
    const stages = Array.isArray(source.stages) ? source.stages : [];
    const rowsIn = Array.isArray(source.rows) ? source.rows : [];
    const edgesIn = Array.isArray(source.edges) ? source.edges : [];
    const externalsIn = Array.isArray(source.externals) ? source.externals : [];

    /* 1. Which components are on the picture at all. */

    const rows = rowsIn.filter((row) => row && row.id && !(row.diagram && row.diagram.hide));
    const byId = new Map();
    rows.forEach((row) => { if (!byId.has(row.id)) byId.set(row.id, row); });

    /* 2. Rank = index in `stages`; the rail is outside the ranks entirely; a
       stage with nothing left in it is not a row. */

    const rankCount = Math.max(1, stages.length);
    const buckets = Array.from({ length: rankCount }, () => []);
    const placed = new Set();
    const railRows = [];

    rows.forEach((row) => {
      if (!(row.diagram && row.diagram.ubiquitous)) return;
      railRows.push(row);
      placed.add(row.id);
    });

    stages.forEach((stage, rank) => {
      const members = stage && Array.isArray(stage.components) ? stage.components : [];
      members.forEach((id) => {
        if (placed.has(id) || !byId.has(id)) return;
        placed.add(id);
        buckets[rank].push(`n:${id}`);
      });
    });

    // Should not happen — build_rows puts every kept row in a stage — but a
    // payload from an older build could name a row no stage lists, and losing
    // it silently would be worse than one crowded row.
    rows.forEach((row) => {
      if (placed.has(row.id)) return;
      placed.add(row.id);
      buckets[rankCount - 1].push(`n:${row.id}`);
    });

    // Empty stages are dropped here rather than hidden later: leaving a rank
    // in the stack with nothing in it puts a 156px hole in the picture where a
    // hidden or withheld component used to be.
    const kept = [];
    buckets.forEach((list, rank) => { if (list.length) kept.push(rank); });
    if (!kept.length) kept.push(rankCount - 1);
    const layers = kept.map((rank) => buckets[rank].slice());
    const rowCount = layers.length;
    const rowOf = new Map();
    layers.forEach((list, row) => list.forEach((key) => rowOf.set(key.slice(2), row)));

    /* 3. Classify every edge by row, before anything has coordinates: a long
       edge needs a channel in each row it crosses, and that changes the
       widths. */

    const declared = new Map();
    externalsIn.forEach((ext) => {
      if (ext && ext.name && !declared.has(ext.name)) {
        declared.set(ext.name, ext.direction === "in" ? "in" : "out");
      }
    });
    const railIds = new Set(railRows.map((row) => row.id));

    const EXT_IN = -1;
    const EXT_OUT = rowCount;
    const work = [];
    edgesIn.forEach((edge, index) => {
      if (!edge || edge.from == null || edge.to == null || edge.from === edge.to) return;
      const fromExternal = edge.kind === "external_in";
      const toExternal = edge.kind === "external_out";
      // A hidden or withheld component leaves its edges pointing at nothing;
      // dropping them here is what keeps the picture honest.
      if (!fromExternal && !byId.has(edge.from)) return;
      if (!toExternal && !byId.has(edge.to)) return;
      if (fromExternal && declared.get(edge.from) !== "in") return;
      if (toExternal && declared.get(edge.to) !== "out") return;

      const a = fromExternal ? EXT_IN : (railIds.has(edge.from) ? null : rowOf.get(edge.from));
      const b = toExternal ? EXT_OUT : (railIds.has(edge.to) ? null : rowOf.get(edge.to));
      if (a === undefined || b === undefined) return;
      const item = {
        edge, index, fromExternal, toExternal, a, b,
        railTouch: a === null || b === null,
      };
      if (item.railTouch) item.route = "rail";
      else if (a === b) item.route = "same";
      else if (b > a) item.route = "down";
      else item.route = "up";
      work.push(item);
    });

    /* 4. Channels. A downward edge gets a 10px column of its own in every row
       it passes over, and the orthogonal route descends through it.

       Where the column starts matters. Appending them and letting the sweeps
       sort it out sent the six edges into the component toolkit out to the
       right margin and back — every dummy inherited the previous row's
       position and eight sweeps never undid it. Each is therefore seeded on
       the straight line between its own two endpoints, measured on the picture
       as it would be with no channels at all. */

    const isDummy = (key) => key.charCodeAt(0) === 100;   // "d"
    const widthOf = (key) => (isDummy(key) ? opt.dummyW : opt.nodeW);
    const gapBefore = (a, b) => ((isDummy(a) || isDummy(b)) ? opt.dummyGap : opt.colGap);
    const rowWidth = (list) => list.reduce(
      (width, key, i) => width + (i ? gapBefore(list[i - 1], key) : 0) + widthOf(key), 0);

    const preWidths = layers.map(rowWidth);
    const preLane = preWidths.reduce((max, w) => Math.max(max, w), opt.nodeW);
    const seed = new Map();
    layers.forEach((list, row) => {
      let x = (preLane - preWidths[row]) / 2;
      list.forEach((key, i) => {
        if (i) x += gapBefore(list[i - 1], key);
        seed.set(key, x + widthOf(key) / 2);
        x += widthOf(key);
      });
    });

    let dummyTotal = 0;
    work.forEach((item) => {
      if (item.route !== "down") return;
      const first = Math.max(0, item.a + 1);
      const last = Math.min(rowCount - 1, item.b - 1);
      if (last < first) return;
      const fromX = seed.get(`n:${item.fromExternal ? item.edge.to : item.edge.from}`);
      const toX = seed.get(`n:${item.toExternal ? item.edge.from : item.edge.to}`);
      const span = item.b - item.a;
      item.dummies = [];
      for (let row = first; row <= last; row += 1) {
        const key = `d:${item.index}:${row}`;
        layers[row].push(key);
        seed.set(key, fromX + (toX - fromX) * (span > 0 ? (row - item.a) / span : 0.5));
        item.dummies.push(key);
        dummyTotal += 1;
      }
    });
    layers.forEach((list, row) => {
      layers[row] = list.slice().sort((a, b) =>
        seed.get(a) - seed.get(b) || (isDummy(a) ? 1 : 0) - (isDummy(b) ? 1 : 0) || cmpStr(a, b));
    });

    /* 5. Barycenter sweeps over the chain graph. */

    const ADJACENT_KINDS = { results: true, calls: true };
    const neighbours = new Map();
    const link = (a, b) => {
      if (!neighbours.has(a)) neighbours.set(a, []);
      neighbours.get(a).push(b);
      if (!neighbours.has(b)) neighbours.set(b, []);
      neighbours.get(b).push(a);
    };
    const layerOf = new Map();
    layers.forEach((list, row) => list.forEach((key) => layerOf.set(key, row)));

    work.forEach((item) => {
      const chain = [];
      if (!item.fromExternal && !item.railTouch) chain.push(`n:${item.edge.from}`);
      (item.dummies || []).forEach((key) => chain.push(key));
      if (!item.toExternal && !item.railTouch) chain.push(`n:${item.edge.to}`);
      if (item.dummies) {
        for (let i = 0; i < chain.length - 1; i += 1) link(chain[i], chain[i + 1]);
        return;
      }
      if (!ADJACENT_KINDS[item.edge.kind]) return;
      if (chain.length === 2) link(chain[0], chain[1]);
    });

    const initialIndex = new Map();
    layers.forEach((list) => list.forEach((key, i) => initialIndex.set(key, i)));

    /* Positions are the real centre x each item would get, not its index in
       the row: a row of seven and a row of one otherwise put their nodes on
       different scales, and the mean of two such numbers means nothing. The
       widths never change — only the order does — so this is cheap to redo. */
    const rowSpan = layers.map(rowWidth);
    const laneWidth = rowSpan.reduce((max, w) => Math.max(max, w), opt.nodeW);
    const posOf = new Map();
    const reindex = () => {
      layers.forEach((list, row) => {
        let x = (laneWidth - rowSpan[row]) / 2;
        list.forEach((key, i) => {
          if (i) x += gapBefore(list[i - 1], key);
          posOf.set(key, x + widthOf(key) / 2);
          x += widthOf(key);
        });
      });
    };
    reindex();

    const groupOf = (key) => {
      if (isDummy(key)) return "";
      const row = byId.get(key.slice(2));
      return row && row.part_of ? String(row.part_of) : "";
    };

    /* Crossings between adjacent layers, counted on the chain graph, used as
       the sweep's own score: barycenter sweeps are not monotone, so the best
       ordering seen is kept rather than the last one reached. Deterministic,
       because the score is a function of the ordering alone. */
    const chainPairs = [];
    neighbours.forEach((list, key) => {
      list.forEach((other) => {
        if (layerOf.get(other) !== layerOf.get(key) + 1) return;
        chainPairs.push([key, other]);
      });
    });
    const crossings = () => {
      let total = 0;
      for (let i = 0; i < chainPairs.length; i += 1) {
        for (let j = i + 1; j < chainPairs.length; j += 1) {
          if (layerOf.get(chainPairs[i][0]) !== layerOf.get(chainPairs[j][0])) continue;
          const da = posOf.get(chainPairs[i][0]) - posOf.get(chainPairs[j][0]);
          const db = posOf.get(chainPairs[i][1]) - posOf.get(chainPairs[j][1]);
          if (da * db < 0) total += 1;
        }
      }
      return total;
    };

    // Contiguity first, and before the score is ever taken: the seeded order
    // can split a `part_of` group, and a snapshot of it would be a legal
    // answer for the "keep the best" loop to come back to.
    layers.forEach((list, row) => {
      const bary = new Map(list.map((key) => [key, posOf.get(key)]));
      layers[row] = arrange(list, bary, groupOf, initialIndex);
    });
    reindex();

    let best = layers.map((list) => list.slice());
    let bestScore = crossings();

    for (let sweep = 0; sweep < opt.sweeps; sweep += 1) {
      const down = sweep % 2 === 0;
      const order = [];
      if (down) for (let i = 1; i < rowCount; i += 1) order.push(i);
      else for (let i = rowCount - 2; i >= 0; i -= 1) order.push(i);

      order.forEach((row) => {
        const reference = down ? row - 1 : row + 1;
        const bary = new Map();
        layers[row].forEach((key) => {
          const all = neighbours.get(key) || [];
          const near = all.filter((n) => layerOf.get(n) === reference);
          // A same-row neighbour counts at half weight. Without it `ui` —
          // which calls two of its own row and is called by the row above —
          // sits wherever the stage file put it, and its two arcs stretch the
          // width of the picture.
          const beside = all.filter((n) => n !== key && layerOf.get(n) === row);
          const weight = near.length + beside.length * 0.5;
          if (!weight) { bary.set(key, posOf.get(key)); return; }
          const sum = near.reduce((total, n) => total + posOf.get(n), 0)
            + beside.reduce((total, n) => total + posOf.get(n), 0) * 0.5;
          bary.set(key, sum / weight);
        });
        layers[row] = arrange(layers[row], bary, groupOf, initialIndex);
        reindex();
      });

      const score = crossings();
      if (score < bestScore) {
        bestScore = score;
        best = layers.map((list) => list.slice());
      }
    }
    best.forEach((list, row) => { layers[row] = list; });
    reindex();

    /* 6. Coordinates. Rows are `nodeH` tall and `laneGap` apart; the band
       between two of them is the gutter every horizontal run happens in. */

    const usedExternals = new Map();
    work.forEach((item) => {
      const name = item.fromExternal ? item.edge.from : item.toExternal ? item.edge.to : "";
      if (!name) return;
      const direction = item.fromExternal ? "in" : "out";
      let entry = usedExternals.get(name);
      if (!entry) { entry = { name, direction, anchors: [] }; usedExternals.set(name, entry); }
      entry.anchors.push(item.fromExternal ? item.edge.to : item.edge.from);
    });
    const hasIn = [...usedExternals.values()].some((e) => e.direction === "in");

    const top0 = opt.topPad + (hasIn ? opt.extH + opt.extGap : 0);
    const rowY = (row) => top0 + row * (opt.nodeH + opt.laneGap);
    const gutterY = (row) => rowY(row) + opt.nodeH + opt.laneGap / 2;

    const lanes = layers.map((list, row) => {
      const stage = stages[kept[row]] || {};
      return {
        row,
        rank: kept[row],
        step: Number.isFinite(stage.step) ? stage.step : kept[row] + 1,
        title: stage.title != null ? String(stage.title) : "",
        description: stage.description != null ? String(stage.description) : "",
        unplaced: !!stage.unplaced,
        x: 0,
        y: rowY(row),
        w: 0,
        h: opt.nodeH,
        bandY: rowY(row) - opt.laneGap / 2,
        bandH: opt.nodeH + opt.laneGap,
        midY: rowY(row) + opt.nodeH / 2,
        count: 0,
      };
    });

    const nodes = [];
    const channel = new Map();
    layers.forEach((list, row) => {
      let x = opt.leftPad + (laneWidth - rowSpan[row]) / 2;
      list.forEach((key, i) => {
        if (i) x += gapBefore(list[i - 1], key);
        if (isDummy(key)) {
          channel.set(key, r2(x + opt.dummyW / 2));
          x += opt.dummyW;
          return;
        }
        nodes.push({
          id: key.slice(2),
          x: r2(x),
          y: rowY(row),
          w: opt.nodeW,
          h: opt.nodeH,
          rank: row,
          lane: row,
          column: lanes[row].count,
          kind: "node",
        });
        lanes[row].count += 1;
        x += opt.nodeW;
      });
    });

    const railX = opt.leftPad + laneWidth + opt.railGap;
    const rail = railRows.map((row, i) => ({
      id: row.id,
      x: railX,
      y: rowY(0) + i * (opt.nodeH + opt.colGap),
      w: opt.nodeW,
      h: opt.nodeH,
      rank: null,
      lane: null,
      column: i,
      kind: "rail",
    }));

    const component = new Map();
    nodes.concat(rail).forEach((node) => component.set(node.id, node));

    /* Externals sit under (or over) the mean x of what they connect to, then
       are pushed apart so two capsules never share a slot. */
    const externals = [];
    const bands = { in: [], out: [] };
    externalsIn.forEach((ext) => {
      const entry = ext && usedExternals.get(ext.name);
      if (!entry || bands[entry.direction].some((e) => e.name === entry.name)) return;
      const anchors = entry.anchors.map((id) => component.get(id)).filter(Boolean);
      if (!anchors.length) return;
      bands[entry.direction].push({
        name: entry.name,
        want: anchors.reduce((sum, node) => sum + cx(node), 0) / anchors.length - opt.extW / 2,
      });
    });
    ["in", "out"].forEach((direction) => {
      const band = bands[direction];
      if (!band.length) return;
      band.sort((a, b) => a.want - b.want || cmpStr(a.name, b.name));
      const low = opt.leftPad;
      const high = Math.max(low, opt.leftPad + laneWidth - opt.extW);
      let cursor = -Infinity;
      band.forEach((ext) => {
        ext.x = Math.max(cursor, Math.max(low, Math.min(high, ext.want)));
        cursor = ext.x + opt.extW + opt.colGap;
      });
      const overflow = band[band.length - 1].x - high;
      if (overflow > 0) band.forEach((ext) => { ext.x = Math.max(0, ext.x - overflow); });
      band.forEach((ext) => {
        externals.push({
          name: ext.name,
          direction,
          x: r2(ext.x),
          y: direction === "in" ? opt.topPad : rowY(rowCount - 1) + opt.nodeH + opt.extGap,
          w: opt.extW,
          h: opt.extH,
          kind: direction === "in" ? "ext-in" : "ext-out",
        });
      });
    });
    const externalByName = new Map();
    externals.forEach((ext) => externalByName.set(ext.name, ext));

    /* 7. Groups: one rectangle per (part_of, row) with two or more members. */

    const groupSeen = new Map();
    const groupList = [];
    nodes.forEach((node) => {
      const label = groupOf(`n:${node.id}`);
      if (!label) return;
      const key = `${label}::${node.rank}`;
      let entry = groupSeen.get(key);
      if (!entry) {
        entry = { label, rank: node.rank, members: [], nodes: [] };
        groupSeen.set(key, entry);
        groupList.push(entry);
      }
      entry.members.push(node.id);
      entry.nodes.push(node);
    });
    const groups = groupList.filter((g) => g.nodes.length > 1).map((g) => {
      const left = g.nodes.reduce((m, n) => Math.min(m, n.x), Infinity);
      const right = g.nodes.reduce((m, n) => Math.max(m, n.x + n.w), -Infinity);
      const top = g.nodes.reduce((m, n) => Math.min(m, n.y), Infinity);
      const bottom = g.nodes.reduce((m, n) => Math.max(m, n.y + n.h), -Infinity);
      return {
        label: g.label,
        rank: g.rank,
        members: g.members.slice(),
        x: r2(left - opt.groupPad),
        y: r2(top - opt.groupPad),
        w: r2(right - left + opt.groupPad * 2),
        h: r2(bottom - top + opt.groupPad * 2),
      };
    });

    /* 8. Routing. Sides first (they need coordinates), then port buckets (an
       offset depends on how many share a side), then the string. */

    const laneRight = opt.leftPad + laneWidth;
    const routed = [];
    const trackUse = new Map();       // gutter row -> horizontal runs so far
    const marginUse = { left: 0, right: 0 };
    const arcUse = new Map();         // row -> arcs over it so far

    /* What each row occupies, so a back edge can be given a vertical channel
       that is free in every row it crosses rather than being sent out to the
       page margin. The margin works and is safe, but two of them drew a pair
       of rounded rectangles around the whole picture: a channel between two
       columns says the same thing in a tenth of the ink. */
    const occupied = layers.map((list, row) => {
      const spans = [];
      let x = opt.leftPad + (laneWidth - rowSpan[row]) / 2;
      list.forEach((key, i) => {
        if (i) x += gapBefore(list[i - 1], key);
        spans.push([x, x + widthOf(key)]);
        x += widthOf(key);
      });
      return spans;
    });
    const channelTaken = [];

    function freeChannel(fromRow, toRow, want) {
      const lo = Math.min(fromRow, toRow) + 1;
      const hi = Math.max(fromRow, toRow) - 1;
      let free = [[opt.leftPad - 60, laneRight + 60]];
      for (let row = lo; row <= hi; row += 1) {
        const next = [];
        free.forEach(([a, b]) => {
          let start = a;
          occupied[row].forEach(([sa, sb]) => {
            const blockA = sa - 14;
            const blockB = sb + 14;
            if (blockB <= start || blockA >= b) return;
            if (blockA > start) next.push([start, Math.min(blockA, b)]);
            start = Math.max(start, blockB);
          });
          if (start < b) next.push([start, b]);
        });
        free = next.filter(([a, b]) => b - a >= 20);
        if (!free.length) return null;
      }
      // Nearest usable point to where the edge would rather be, kept a little
      // away from any channel already handed out so two returns do not merge.
      let bestX = null;
      let bestCost = Infinity;
      free.forEach(([a, b]) => {
        const target = Math.max(a + 10, Math.min(b - 10, want));
        [target, a + 10, b - 10].forEach((candidate) => {
          if (candidate < a + 10 || candidate > b - 10) return;
          const clash = channelTaken.some((used) => Math.abs(used - candidate) < 16) ? 400 : 0;
          const cost = Math.abs(candidate - want) + clash;
          if (cost < bestCost) { bestCost = cost; bestX = candidate; }
        });
      });
      return bestX;
    }

    /* Spread the horizontal runs across the gutter so two of them do not merge
       into one line. Every offset stays well inside half a lane gap, which is
       what keeps the run in empty space. */
    const track = (row) => {
      const n = trackUse.get(row) || 0;
      trackUse.set(row, n + 1);
      return ((n % opt.tracks) - (opt.tracks - 1) / 2) * opt.trackStep;
    };

    work.forEach((item) => {
      const a = item.fromExternal
        ? externalByName.get(item.edge.from) : component.get(item.edge.from);
      const b = item.toExternal
        ? externalByName.get(item.edge.to) : component.get(item.edge.to);
      if (!a || !b || a === b) return;
      const entry = { item, a, b };

      if (item.route === "rail") {
        entry.hook = !item.fromExternal && !item.toExternal;
        if (!entry.hook) {
          entry.sideA = a.y <= b.y ? "bottom" : "top";
          entry.sideB = a.y <= b.y ? "top" : "bottom";
        } else if (a.kind === "rail") {
          entry.sideA = "left";
          entry.sideB = "top";
        } else {
          entry.sideA = "bottom";
          entry.sideB = "left";
        }
      } else if (item.route === "same") {
        const right = cx(b) > cx(a);
        entry.sideA = right ? "right" : "left";
        entry.sideB = right ? "left" : "right";
      } else if (item.route === "down") {
        entry.sideA = "bottom";
        entry.sideB = "top";
      } else {
        // A back edge leaves through the top and arrives at the bottom: the
        // only pair of ports whose approach runs vertically through empty
        // space. Side ports were the first design and cannot be made safe —
        // a neighbour is 28px away and any exit along the row clips it.
        entry.sideA = "top";
        entry.sideB = "bottom";
      }

      const via = (item.dummies || []).map((key) => channel.get(key));
      entry.via = via;
      entry.nextX = via.length ? via[0] : cx(b);
      entry.prevX = via.length ? via[via.length - 1] : cx(a);
      routed.push(entry);
    });

    const portBuckets = new Map();
    const bucketFor = (node, side) => {
      const key = `${node.kind}::${node.id || node.name}::${side}`;
      let list = portBuckets.get(key);
      if (!list) { list = []; portBuckets.set(key, list); }
      return list;
    };
    routed.forEach((entry) => {
      bucketFor(entry.a, entry.sideA).push({ entry, end: "a" });
      bucketFor(entry.b, entry.sideB).push({ entry, end: "b" });
    });
    portBuckets.forEach((list, key) => {
      const side = key.slice(key.lastIndexOf(":") + 1);
      const horizontal = side === "top" || side === "bottom";
      const along = (port) => {
        const { entry, end } = port;
        if (horizontal) return end === "a" ? entry.nextX : entry.prevX;
        return cy(end === "a" ? entry.b : entry.a);
      };
      const across = (port) => {
        const far = port.end === "a" ? port.entry.b : port.entry.a;
        return horizontal ? cy(far) : cx(far);
      };
      list.sort((p, q) => along(p) - along(q) || across(p) - across(q)
        || p.entry.item.index - q.entry.item.index);
      list.forEach((port, i) => {
        port.entry[port.end === "a" ? "indexA" : "indexB"] = i;
        port.entry[port.end === "a" ? "countA" : "countB"] = list.length;
      });
    });

    const edges = routed.map((entry) => {
      const { item, a, b } = entry;
      const from = portPos(a, entry.sideA, entry.indexA, entry.countA, opt.portStep);
      const to = portPos(b, entry.sideB, entry.indexB, entry.countB, opt.portStep);
      let path;

      if (item.route === "down" && !entry.via.length) {
        path = cubicDown(from, to);
      } else if (item.route === "down") {
        const points = [from];
        let x = from.x;
        entry.via.forEach((channelX, i) => {
          const gutter = gutterY(item.a + i) + track(item.a + i);
          points.push({ x, y: gutter });
          points.push({ x: channelX, y: gutter });
          x = channelX;
        });
        const last = gutterY(item.b - 1) + track(item.b - 1);
        points.push({ x, y: last });
        points.push({ x: to.x, y: last });
        points.push(to);
        path = elbow(points, opt.corner);
      } else if (item.route === "same") {
        const gap = entry.sideA === "right" ? to.x - from.x : from.x - to.x;
        if (gap > 0 && gap <= opt.colGap + 0.01) {
          // Adjacent nodes already have a clear corridor between their facing
          // sides. Sending that short edge up and back used half the 28px gap
          // for each bend, so both legs met at one x and drew a zero-width
          // U-turn — the arrow looked crushed between the boxes.
          path = elbow([from, to], 0);
        } else {
          // Out into the gap beside each node, up to at least `arcClear` above
          // the row, across, and back down: an intervening neighbour is never
          // crossed because no leg of the trip is at node height inside the
          // row.
          const dir = entry.sideA === "right" ? 1 : -1;
          const n = arcUse.get(item.a) || 0;
          arcUse.set(item.a, n + 1);
          const arcY = rowY(item.a) - opt.arcClear - (n % 3) * 10;
          const step = Math.min(14, opt.colGap / 2);
          path = elbow([
            from,
            { x: from.x + dir * step, y: from.y },
            { x: from.x + dir * step, y: arcY },
            { x: to.x - dir * step, y: arcY },
            { x: to.x - dir * step, y: to.y },
            to,
          ], Math.min(opt.corner, step));
        }
      } else if (item.route === "up" && item.a - item.b === 1) {
        const gutter = gutterY(item.b) + track(item.b);
        path = elbow([from, { x: from.x, y: gutter }, { x: to.x, y: gutter }, to], opt.corner);
      } else if (item.route === "up") {
        const want = (cx(a) + cx(b)) / 2;
        let margin = freeChannel(item.a, item.b, want);
        if (margin == null) {
          // Nothing between the columns is free the whole way up; the page
          // margin always is.
          const side = want < opt.leftPad + laneWidth / 2 ? "left" : "right";
          const n = marginUse[side];
          marginUse[side] += 1;
          const offset = (n % opt.marginTracks) * opt.marginStep;
          margin = side === "left" ? opt.leftPad - 42 - offset : laneRight + 30 + offset;
        }
        channelTaken.push(margin);
        const upper = gutterY(item.a - 1) + track(item.a - 1);
        const lower = gutterY(item.b) + track(item.b);
        path = elbow([
          from,
          { x: from.x, y: upper },
          { x: margin, y: upper },
          { x: margin, y: lower },
          { x: to.x, y: lower },
          to,
        ], opt.corner);
      } else if (entry.hook) {
        const lane = a.kind === "rail" ? b : a;
        const gutter = gutterY(lane.rank) + track(lane.rank);
        const g = laneRight + 20;
        path = a.kind === "rail"
          ? elbow([from, { x: g, y: from.y }, { x: g, y: gutter },
            { x: to.x, y: gutter }, to], opt.corner)
          : elbow([from, { x: from.x, y: gutter }, { x: g, y: gutter },
            { x: g, y: to.y }, to], opt.corner);
      } else {
        // The rail's own external (jaeger → Engineering) hangs off the far
        // right, so it drops beside the rail and turns in under the last row.
        const band = to.y + (from.y < to.y ? -opt.extGap / 2 : opt.extGap / 2);
        path = elbow([from, { x: from.x, y: band }, { x: to.x, y: band }, to], opt.corner);
      }

      return Object.assign({}, item.edge, {
        path,
        route: item.route,
        crosscutting: item.railTouch,
        fromPort: { x: r2(from.x), y: r2(from.y), side: entry.sideA },
        toPort: { x: r2(to.x), y: r2(to.y), side: entry.sideB },
      });
    });

    /* 9. Bounds, then the promise. */

    let right = laneRight;
    let bottom = rowY(rowCount - 1) + opt.nodeH;
    rail.forEach((node) => {
      right = Math.max(right, node.x + node.w);
      bottom = Math.max(bottom, node.y + node.h);
    });
    externals.forEach((ext) => {
      right = Math.max(right, ext.x + ext.w);
      bottom = Math.max(bottom, ext.y + ext.h);
    });
    if (marginUse.right) {
      right = Math.max(right, laneRight + 30 + (opt.marginTracks - 1) * opt.marginStep);
    }

    const bounds = { w: r2(right + opt.edgePad), h: r2(bottom + opt.edgePad) };
    lanes.forEach((lane) => { lane.w = bounds.w; });

    const violations = checkPaths(edges, nodes.concat(rail, externals), opt.sampleStep);

    return {
      nodes,
      lanes,
      externals,
      rail,
      edges,
      groups,
      bounds,
      violations,
      meta: {
        laneWidth,
        leftPad: opt.leftPad,
        laneGap: opt.laneGap,
        nodeH: opt.nodeH,
        railX: rail.length ? railX : null,
        dummies: dummyTotal,
        crossings: bestScore,
        options: opt,
      },
    };
  }

  TD.layout = {
    compute, DEFAULTS, arrange, portPos, elbow, cubicDown, samplePath, checkPaths,
  };
})();
