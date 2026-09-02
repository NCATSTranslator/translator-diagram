"""Ordering components the way data moves through them.

The dashboard's rows run from the data sources to the user, which is the order
someone explaining Translator draws on a whiteboard. Nothing records that
order; it has to be derived from the dependency edges the component files
already carry, which is itself a test of whether those edges are worth
recording.
"""

from dataclasses import dataclass

from .components import ComponentFile, Edge

# Components nothing feeds and nothing consumes sort last rather than first. A
# component with no recorded edges is not a data source, it is a gap in the
# data — putting it at the top of a flow-ordered table would state something
# false about the architecture.
NO_EDGES_DEPTH = 10_000


@dataclass(frozen=True)
class Inbound:
    """An edge arriving from another component, seen from the target's side.

    `kind` is the key it was written under on the *other* component's file:
    "the ARS gets results from this" and "the UI calls this" are different
    facts about this component, and only the far side records either.
    """

    id: str
    kind: str
    planned: bool = False


@dataclass(frozen=True)
class Neighbours:
    """Everything one component's edges connect it to, both directions."""

    gets_results_from: tuple[Edge, ...] = ()
    calls: tuple[Edge, ...] = ()
    used_by: tuple[Inbound, ...] = ()

    def __bool__(self) -> bool:
        return bool(self.gets_results_from or self.calls or self.used_by)


def neighbours(components: list[ComponentFile]) -> dict[str, Neighbours]:
    """Each component's edges, resolved against the components we have.

    One traversal, and the only one. `isolated` draws a left bar meaning "no
    recorded edges in either direction" while the page draws a chip per edge;
    if those came from two traversals that resolved ids differently, a row
    would eventually carry the bar and the chips at once. Everything here is
    built on this, so they cannot disagree.

    Resolution is the same rule `flow_depths` has always applied: match ids
    case-insensitively against the files that exist, drop an id no file
    matches, and drop a self-edge. An unknown id is a broken reference, and
    `tests/test_component_files.py` is where that is caught — silently
    ignoring it here would be the second place it could hide.
    """
    known = {c.id.lower(): c.id for c in components}

    def resolve(edges: list[Edge], source: str) -> list[Edge]:
        out = []
        for edge in edges:
            target = known.get(edge.id.lower())
            if target and target != source:
                out.append(Edge(id=target, planned=edge.planned))
        return out

    outgoing = {
        c.id: (resolve(c.gets_results_from, c.id), resolve(c.calls, c.id))
        for c in components
    }
    inbound: dict[str, list[Inbound]] = {c.id: [] for c in components}
    for cid, (results, calls) in outgoing.items():
        # A component named under both keys is one neighbour, not two: the
        # results edge is the stronger claim, so it wins the single chip.
        seen: set[str] = set()
        for kind, edges in (("gets_results_from", results), ("calls", calls)):
            for edge in edges:
                if edge.id not in seen:
                    seen.add(edge.id)
                    inbound[edge.id].append(
                        Inbound(id=cid, kind=kind, planned=edge.planned)
                    )
    return {
        cid: Neighbours(
            gets_results_from=tuple(results),
            calls=tuple(calls),
            # No natural order on the far side, so a stable one: the ids are
            # somebody else's list, not this component's judgement.
            used_by=tuple(sorted(inbound[cid], key=lambda i: i.id.lower())),
        )
        for cid, (results, calls) in outgoing.items()
    }


def _upstream_within(
    components: list[ComponentFile],
) -> dict[str, set[str]]:
    """Each component's upstream ids, restricted to components we have."""
    return {
        cid: {edge.id for edge in n.gets_results_from + n.calls}
        for cid, n in neighbours(components).items()
    }


def _downstream_from(upstream: dict[str, set[str]]) -> dict[str, set[str]]:
    out: dict[str, set[str]] = {cid: set() for cid in upstream}
    for cid, ups in upstream.items():
        for up in ups:
            out[up].add(cid)
    return out


def flow_depths(components: list[ComponentFile]) -> dict[str, int]:
    """Longest path from a data source to each component.

    Longest rather than shortest: a component should sort after everything it
    depends on, and the shortest path would place `ars` — which calls both
    `jaeger` and the whole Shepherd chain — beside the shared services it
    happens to call directly.

    Cycles are tolerated rather than rejected. The diagram's validator does not
    check for them (issue #11), so a cycle can reach this code, and a table
    that refuses to render is worse than one that breaks a tie arbitrarily.
    """
    upstream = _upstream_within(components)
    downstream = _downstream_from(upstream)
    by_id = {c.id: c for c in components}

    depth: dict[str, int] = {}
    visiting: set[str] = set()

    def compute(cid: str) -> int:
        if cid in depth:
            return depth[cid]
        if cid in visiting:
            # Re-entered through a cycle. Treat this edge as contributing
            # nothing rather than recursing forever; some ordering is picked,
            # and it is stable because the inputs are sorted.
            return 0
        visiting.add(cid)
        candidates = [compute(up) + 1 for up in sorted(upstream[cid])]
        if by_id[cid].fed_by_external:
            # An external source feeds this component, so it starts one step
            # into the flow rather than at the very top.
            candidates.append(1)
        depth[cid] = max(candidates, default=0)
        visiting.discard(cid)
        return depth[cid]

    for cid in sorted(by_id):
        compute(cid)

    for cid in depth:
        if not upstream[cid] and not downstream[cid] and not by_id[cid].externals:
            depth[cid] = NO_EDGES_DEPTH
    return depth


def in_flow_order(components: list[ComponentFile]) -> list[ComponentFile]:
    """Components from the data sources to the user.

    Ties break on layer then id, so components that sit at the same depth stay
    grouped by the part of the system they belong to.
    """
    depths = flow_depths(components)
    return sorted(
        components,
        key=lambda c: (depths[c.id], c.layer or "￿", c.id.lower()),
    )


def order_conflicts(
    components: list[ComponentFile], position: dict[str, int]
) -> list[tuple[str, str, bool]]:
    """Recorded results edges that run backwards through a written order.

    `(component, the thing it gets results from, planned)` for every edge whose
    source sits later than its target. `position` maps an id to its place in
    whatever order the caller decided on — passed in rather than loaded,
    because this module may not import the one that reads `config/`, and
    because a check that took `config/flow-steps.yaml` as a parameter would be
    a check about one file rather than about an order.

    `gets_results_from` only, and that is the whole design. Results flow along
    the pipeline, so a results edge from a later stage is a contradiction:
    either the placement is wrong or the edge is. `calls` says "uses this
    service" and nothing about position — eleven recorded calls run backwards
    and every one of them is correct, nine being calls to the tracing service,
    which sits in Engineering at the end of the page. A check that fires eleven
    times on the day it ships is a check somebody switches off.

    A component the order does not place is skipped rather than assumed: it has
    no position to contradict.
    """
    conflicts = []
    for cid, edges in neighbours(components).items():
        here = position.get(cid)
        if here is None:
            continue
        for edge in edges.gets_results_from:
            there = position.get(edge.id)
            if there is not None and there > here:
                conflicts.append((cid, edge.id, edge.planned))
    return sorted(conflicts)


def isolated(components: list[ComponentFile]) -> list[str]:
    """Ids with no recorded edges in either direction.

    Surfaced rather than hidden: these are the components the dependency data
    says nothing about, and on a page arguing that the data is worth recording,
    the holes are part of the argument.
    """
    depths = flow_depths(components)
    return sorted(cid for cid, d in depths.items() if d == NO_EDGES_DEPTH)
