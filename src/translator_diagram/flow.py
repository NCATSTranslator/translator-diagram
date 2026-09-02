"""Ordering components the way data moves through them.

Not the dashboard's row order any more. That is written by hand in
`config/flow-steps.yaml`, because twenty recorded edges cannot order
twenty-six components: nothing records the UI calling Name Lookup, so Name
Lookup sorted up beside the data sources. Change the row order there, not here.

What is left is still worth having. `in_flow_order` is the fallback for the
components no stage names and for a build with no config at all; `isolated`
reports the components whose dependencies nothing records, which is a hole in
the data the page shows rather than hides; and the depths behind both are the
honest answer for anything nobody has placed.
"""

from .components import ComponentFile

# Components nothing feeds and nothing consumes sort last rather than first. A
# component with no recorded edges is not a data source, it is a gap in the
# data — putting it at the top of a flow-ordered table would state something
# false about the architecture.
NO_EDGES_DEPTH = 10_000


def _upstream_within(
    components: list[ComponentFile],
) -> dict[str, set[str]]:
    """Each component's upstream ids, restricted to components we have."""
    known = {c.id.lower(): c.id for c in components}
    out: dict[str, set[str]] = {}
    for component in components:
        out[component.id] = {
            known[ref.lower()]
            for ref in component.upstream
            if ref.lower() in known and known[ref.lower()] != component.id
        }
    return out


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


def isolated(components: list[ComponentFile]) -> list[str]:
    """Ids with no recorded edges in either direction.

    Surfaced rather than hidden: these are the components the dependency data
    says nothing about, and on a page arguing that the data is worth recording,
    the holes are part of the argument.
    """
    depths = flow_depths(components)
    return sorted(cid for cid, d in depths.items() if d == NO_EDGES_DEPTH)
