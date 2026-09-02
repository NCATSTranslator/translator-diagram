/*
  web/layout.js under node, with no browser and no payload.

  The map's geometry is the half of the view with judgement in it — which
  component sits beside which, where a long edge runs, what happens to a
  component the privacy filter removed — and it is testable precisely because
  layout.js touches no DOM and reads no globals but its own namespace. The
  fixture is small on purpose: seven components with one `part_of` pair, one
  ubiquitous component, a same-rank edge, a back edge, two externals and one
  edge pointing at a component that is not there. Every rule the picture
  depends on shows up in it at least once.
*/

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const ROOT = path.join(__dirname, "..", "..");
const LAYOUT = path.join(ROOT, "src", "translator_diagram", "web", "layout.js");

/* The real thing, when a build is lying about. `--include-private` is the one
   that has every component in it, so it is tried first; the published build is
   a fair second because the rules under test are the same either way. A
   checkout with neither is not a failure — the fixture below covers every rule
   on its own — but a checkout with one must pass on it, because the fixture is
   seven boxes and the payload is twenty-six with a rail, a hidden component
   and six edges crossing the widest row. */
function realPayload() {
  const candidates = [
    path.join(ROOT, "data", "dashboard-private", "overview.json"),
    path.join(ROOT, "data", "dashboard-map", "overview.json"),
    path.join(ROOT, "data", "dashboard", "overview.json"),
  ];
  for (const file of candidates) {
    try {
      const data = JSON.parse(fs.readFileSync(file, "utf8"));
      if (Array.isArray(data.rows) && data.rows.length && Array.isArray(data.stages)) {
        return { file, data };
      }
    } catch { /* not built, or half-written by a build running right now */ }
  }
  return null;
}

globalThis.TD = {};
vm.runInThisContext(fs.readFileSync(LAYOUT, "utf8"), { filename: "layout.js" });
const TD = globalThis.TD;

const STAGES = [
  { step: 1, title: "Ingest", description: "where data arrives", components: ["a1", "a2"] },
  // b3 is listed between the two Pair members deliberately: the stage file's
  // order is the starting point, and keeping the pair together has to survive
  // something being written between them.
  { step: 2, title: "Middle", description: "the middle", components: ["b1", "b3", "b2"] },
  { step: 4, title: "Users", description: "who reads it", components: ["c1", "u1"] },
];

const ROWS = [
  { id: "a1", name: "Alpha one", owner: "One", environments: {} },
  { id: "a2", name: "Alpha two", owner: "One", environments: {} },
  { id: "b1", name: "Beta one", owner: "Two", part_of: "Pair", environments: {} },
  { id: "b2", name: "Beta two", owner: "Two", part_of: "Pair", environments: {} },
  { id: "b3", name: "Beta three", owner: "Two", environments: {} },
  { id: "c1", name: "Gamma", owner: "Three", environments: {} },
  { id: "u1", name: "Everywhere", owner: "Three", diagram: { ubiquitous: true }, environments: {} },
  { id: "h1", name: "Hidden", owner: "Three", diagram: { hide: true }, environments: {} },
];

const EDGES = [
  { from: "a1", to: "b1", kind: "results", planned: false },
  { from: "a2", to: "b3", kind: "results", planned: false },
  { from: "b1", to: "c1", kind: "results", planned: false },
  { from: "b3", to: "b2", kind: "calls", planned: false },
  { from: "c1", to: "a1", kind: "calls", planned: false },
  { from: "b1", to: "u1", kind: "calls", planned: false },
  { from: "Source", to: "a1", kind: "external_in", planned: false },
  { from: "c1", to: "User", kind: "external_out", planned: false },
  // The published build drops withheld components from `rows` but an edge can
  // still name one, so this must not reach the picture.
  { from: "gone", to: "c1", kind: "results", planned: false },
];

const EXTERNALS = [
  { name: "Source", direction: "in" },
  { name: "User", direction: "out" },
];

const input = () => ({ stages: STAGES, rows: ROWS, edges: EDGES, externals: EXTERNALS });
const compute = () => TD.layout.compute(input());

const byId = (scene) => {
  const found = new Map();
  scene.nodes.concat(scene.rail).forEach((node) => found.set(node.id, node));
  scene.externals.forEach((ext) => found.set(ext.name, ext));
  return found;
};

const rankOrder = (scene, rank) =>
  scene.nodes.filter((node) => node.rank === rank)
    .sort((a, b) => a.x - b.x).map((node) => node.id);

test("rank follows the stage order, and a hidden component is not drawn", () => {
  const scene = compute();
  const found = byId(scene);
  assert.equal(found.get("a1").rank, 0);
  assert.equal(found.get("a2").rank, 0);
  assert.equal(found.get("b1").rank, 1);
  assert.equal(found.get("b2").rank, 1);
  assert.equal(found.get("b3").rank, 1);
  assert.equal(found.get("c1").rank, 2);
  assert.equal(found.has("h1"), false);
  // The lane keeps the stage's own step number, which is not its index: a
  // published build can lose a whole stage and the rest must not renumber.
  assert.deepEqual(scene.lanes.map((lane) => lane.step), [1, 2, 4]);
  assert.equal(scene.lanes[0].title, "Ingest");
});

test("a component in no stage lands in the last rank rather than vanishing", () => {
  const scene = TD.layout.compute({
    stages: STAGES,
    rows: ROWS.concat([{ id: "orphan", name: "Orphan", owner: "One", environments: {} }]),
    edges: EDGES,
    externals: EXTERNALS,
  });
  const orphan = scene.nodes.find((node) => node.id === "orphan");
  assert.ok(orphan, "the orphan is drawn");
  assert.equal(orphan.rank, STAGES.length - 1);
});

test("part_of members stay next to each other after the sweeps", () => {
  const scene = compute();
  const order = rankOrder(scene, 1);
  assert.equal(order.length, 3);
  assert.equal(Math.abs(order.indexOf("b1") - order.indexOf("b2")), 1,
    `Pair split by ${order.join(", ")}`);
  const group = scene.groups.find((g) => g.label === "Pair");
  assert.ok(group, "the pair gets a rectangle");
  assert.deepEqual(group.members.slice().sort(), ["b1", "b2"]);
});

test("the same payload twice gives the same scene", () => {
  assert.deepEqual(compute(), compute());
  // Deep equality would pass on two objects that merely agree; the path
  // strings are what the browser actually draws, so they are compared as text.
  assert.equal(
    JSON.stringify(compute().edges.map((edge) => edge.path)),
    JSON.stringify(compute().edges.map((edge) => edge.path)),
  );
});

test("a ubiquitous component goes to the rail and takes no rank", () => {
  const scene = compute();
  assert.deepEqual(scene.rail.map((node) => node.id), ["u1"]);
  assert.equal(scene.rail[0].rank, null);
  assert.equal(scene.nodes.some((node) => node.id === "u1"), false);
  // Right of every lane, so no lane node can sit under it.
  const widest = Math.max(...scene.nodes.map((node) => node.x + node.w));
  assert.ok(scene.rail[0].x > widest, "the rail clears the widest lane");
});

test("externals sit above the first rank and below the last", () => {
  const scene = compute();
  const source = scene.externals.find((ext) => ext.name === "Source");
  const user = scene.externals.find((ext) => ext.name === "User");
  const first = Math.min(...scene.nodes.filter((n) => n.rank === 0).map((n) => n.y));
  const last = Math.max(...scene.nodes.filter((n) => n.rank === 2).map((n) => n.y + n.h));
  assert.ok(source.y + source.h < first, "the inbound external is above rank 0");
  assert.ok(user.y > last, "the outbound external is below the last rank");
});

test("an external nobody has an edge to is not drawn", () => {
  const scene = TD.layout.compute({
    stages: STAGES,
    rows: ROWS,
    edges: EDGES,
    externals: EXTERNALS.concat([{ name: "Nobody", direction: "out" }]),
  });
  assert.equal(scene.externals.some((ext) => ext.name === "Nobody"), false);
});

test("no two boxes overlap", () => {
  const scene = compute();
  const boxes = scene.nodes.concat(scene.rail).map((node) => ({ id: node.id, ...node }))
    .concat(scene.externals.map((ext) => ({ id: ext.name, ...ext })));
  for (let i = 0; i < boxes.length; i += 1) {
    for (let j = i + 1; j < boxes.length; j += 1) {
      const a = boxes[i];
      const b = boxes[j];
      const apart = a.x + a.w <= b.x || b.x + b.w <= a.x
        || a.y + a.h <= b.y || b.y + b.h <= a.y;
      assert.ok(apart, `${a.id} overlaps ${b.id}`);
    }
  }
});

test("an edge whose endpoint is missing is dropped, and the rest survive", () => {
  const scene = compute();
  assert.equal(scene.edges.length, EDGES.length - 1);
  assert.equal(scene.edges.some((edge) => edge.from === "gone"), false);
  // The kinds and the planned flag are carried through, not rebuilt.
  const external = scene.edges.find((edge) => edge.kind === "external_out");
  assert.equal(external.to, "User");
  assert.equal(external.planned, false);
});

test("a stage whose components are all hidden is not a row", () => {
  const scene = TD.layout.compute({
    stages: STAGES,
    rows: ROWS.map((row) => (row.id === "c1" || row.id === "u1"
      ? Object.assign({}, row, { diagram: { hide: true } }) : row)),
    edges: EDGES,
    externals: EXTERNALS,
  });
  assert.deepEqual(scene.lanes.map((lane) => lane.step), [1, 2]);
  assert.equal(scene.nodes.some((node) => node.id === "c1"), false);
  assert.equal(scene.edges.some((e) => e.from === "c1" || e.to === "c1"), false);
  // Its external went with it: a capsule nothing points at is not a fact.
  assert.equal(scene.externals.some((ext) => ext.name === "User"), false);
  // And the rows that remain are still one lane gap apart, with no hole.
  const gap = scene.lanes[1].y - scene.lanes[0].y;
  assert.equal(gap, TD.layout.DEFAULTS.nodeH + TD.layout.DEFAULTS.laneGap);
});

test("the routes are the ones the ranks call for", () => {
  const routes = new Map(compute().edges.map((edge) => [`${edge.from}->${edge.to}`, edge.route]));
  assert.equal(routes.get("a1->b1"), "down");
  assert.equal(routes.get("b3->b2"), "same");
  assert.equal(routes.get("c1->a1"), "up");
  assert.equal(routes.get("b1->u1"), "rail");
  assert.equal(routes.get("Source->a1"), "down");
});

test("every path starts with a move, and every port is on its own box", () => {
  const scene = compute();
  const found = byId(scene);
  const on = (port, node) => {
    const near = (a, b) => Math.abs(a - b) < 0.01;
    const withinX = port.x >= node.x - 0.01 && port.x <= node.x + node.w + 0.01;
    const withinY = port.y >= node.y - 0.01 && port.y <= node.y + node.h + 0.01;
    const onVertical = (near(port.x, node.x) || near(port.x, node.x + node.w)) && withinY;
    const onHorizontal = (near(port.y, node.y) || near(port.y, node.y + node.h)) && withinX;
    return onVertical || onHorizontal;
  };
  scene.edges.forEach((edge) => {
    assert.ok(edge.path.startsWith("M "), `${edge.from}->${edge.to}: ${edge.path.slice(0, 12)}`);
    assert.ok(/^[-\d.MCLQ ]+$/.test(edge.path), `${edge.from}->${edge.to} has a stray command`);
    const a = found.get(edge.from);
    const b = found.get(edge.to);
    assert.ok(on(edge.fromPort, a), `${edge.from}->${edge.to} leaves off ${edge.from}`);
    assert.ok(on(edge.toPort, b), `${edge.from}->${edge.to} arrives off ${edge.to}`);
  });
});

test("the bounds cover everything that was placed", () => {
  const scene = compute();
  const boxes = scene.nodes.concat(scene.rail, scene.externals);
  boxes.forEach((item) => {
    assert.ok(item.x >= 0 && item.y >= 0, `${item.id || item.name} starts off-canvas`);
    assert.ok(item.x + item.w <= scene.bounds.w, `${item.id || item.name} runs off the right`);
    assert.ok(item.y + item.h <= scene.bounds.h, `${item.id || item.name} runs off the bottom`);
  });
});

test("no edge crosses a node it is not attached to", () => {
  const scene = compute();
  assert.deepEqual(scene.violations, []);
});

test("the same rule holds on the real payload", (t) => {
  const real = realPayload();
  if (!real) {
    t.skip("no built overview.json under data/; run build-dashboard first");
    return;
  }
  const { data } = real;
  const edges = (data.edges || []).concat(
    (data.catalog_edges || []).map((edge) => Object.assign({}, edge, { kind: "catalog" })));
  const scene = TD.layout.compute({
    stages: data.stages, rows: data.rows, edges, externals: data.externals || [],
  });
  assert.ok(scene.nodes.length > 0, `${real.file} produced no nodes`);
  const named = scene.violations.slice(0, 6)
    .map((v) => `${v.from}->${v.to} through ${v.through}`).join("; ");
  assert.deepEqual(scene.violations, [], `${real.file}: ${named}`);

  // The other promises, on data a fixture cannot stand in for.
  const boxes = scene.nodes.concat(scene.rail, scene.externals);
  for (let i = 0; i < boxes.length; i += 1) {
    for (let j = i + 1; j < boxes.length; j += 1) {
      const a = boxes[i];
      const b = boxes[j];
      assert.ok(a.x + a.w <= b.x || b.x + b.w <= a.x || a.y + a.h <= b.y || b.y + b.h <= a.y,
        `${a.id || a.name} overlaps ${b.id || b.name}`);
    }
  }
  const hidden = data.rows.filter((row) => row.diagram && row.diagram.hide).map((row) => row.id);
  hidden.forEach((id) => {
    assert.equal(scene.nodes.some((node) => node.id === id), false, `${id} is hidden`);
    assert.equal(scene.edges.some((e) => e.from === id || e.to === id), false,
      `${id} is hidden but still has an edge`);
  });
  scene.lanes.forEach((lane) => {
    assert.ok(lane.count > 0, `step ${lane.step} (${lane.title}) is an empty row`);
  });
});

test("an empty payload gives an empty scene rather than a throw", () => {
  const scene = TD.layout.compute({});
  assert.deepEqual(scene.nodes, []);
  assert.deepEqual(scene.edges, []);
  assert.ok(scene.bounds.w > 0);
});
