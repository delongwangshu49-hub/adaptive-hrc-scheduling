"""P050 design-only color reference r3; no scheduler or UI dependencies.

The caller supplies the complete delivered work set for one run/epoch and
canonical adjacency from verified projections, never just the visible rows.
"""

from collections import Counter
from collections.abc import Iterable, Mapping


def assign(
    keys: Iterable[str],
    edges: Iterable[tuple[str, str]],
    existing: Mapping[str, int] | None = None,
) -> tuple[dict[str, int], list[tuple[str, str]]]:
    """Preserve cached hues; return every CURRENT same-color edge, sorted.

    Historical cache entries survive but do not affect current graph degree or
    color load. Self edges are intra-work segments and are ignored. Invalid
    endpoint identities and invalid cached slots fail before assigning anything.
    """
    if isinstance(keys, (str, bytes)):
        raise ValueError("keys must be a collection of work identities")
    current = list(keys)
    if any(not isinstance(k, str) or not k.strip() for k in current):
        raise ValueError("work identity must be a nonempty string")
    if len(set(current)) != len(current):
        raise ValueError("duplicate work identity")
    colors = dict(existing) if existing is not None else {}
    for key, slot in colors.items():
        if not isinstance(key, str) or not key.strip():
            raise ValueError("invalid cached identity")
        if type(slot) is not int or slot not in range(4):
            raise ValueError("cached slot must be an integer from 0 to 3")
    neighbors: dict[str, set[str]] = {k: set() for k in current}
    canonical: set[tuple[str, str]] = set()
    for edge in edges:
        if not isinstance(edge, (list, tuple)) or len(edge) != 2:
            raise ValueError("edge must have two endpoints")
        a, b = edge
        if not isinstance(a, str) or not isinstance(b, str):
            raise ValueError("edge endpoints must be work identities")
        if a not in neighbors or b not in neighbors:
            raise ValueError("edge endpoint outside current delivered set")
        if a != b:
            canonical.add(tuple(sorted((a, b))))
            neighbors[a].add(b)
            neighbors[b].add(a)
    pending = set(current) - colors.keys()
    load = Counter(colors[k] for k in current if k in colors)
    while pending:
        key = min(
            pending,
            key=lambda k: (
                -len({colors[n] for n in neighbors[k] if n in colors}),
                -len(neighbors[k]),
                k,
            ),
        )
        used = Counter(colors[n] for n in neighbors[key] if n in colors)
        safe = [slot for slot in range(4) if slot not in used]
        colors[key] = min(
            safe or list(range(4)),
            key=lambda slot: (used[slot], load[slot], slot),
        )
        load[colors[key]] += 1
        pending.remove(key)
    # Always scan edges, including replans with no new work keys.
    collisions = sorted((a, b) for a, b in canonical if colors[a] == colors[b])
    return colors, collisions
