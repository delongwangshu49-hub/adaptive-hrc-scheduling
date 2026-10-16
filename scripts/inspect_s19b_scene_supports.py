"""Read-only AABB connectivity screen for the owner's floating-support report.

This reports existing USD collider geometry. It is neither a structural proof nor
a replacement for production admission, and must never feed the planner.
"""

import hashlib
from collections import Counter, deque


def inspect_supports(scene, run_id, request_id):
    from pxr import Usd, UsdGeom, UsdPhysics

    stage = scene.stage
    before = hashlib.sha256(stage.GetRootLayer().ExportToString().encode()).hexdigest()
    cache = UsdGeom.BBoxCache(
        Usd.TimeCode.Default(), [UsdGeom.Tokens.default_, UsdGeom.Tokens.render]
    )
    nodes = []
    for prim in stage.Traverse():
        if not prim.HasAPI(UsdPhysics.CollisionAPI):
            continue
        if UsdPhysics.CollisionAPI(prim).GetCollisionEnabledAttr().Get() is False:
            continue
        if UsdGeom.Imageable(prim).ComputeVisibility() == UsdGeom.Tokens.invisible:
            continue
        bounds = cache.ComputeWorldBound(prim).ComputeAlignedRange()
        if bounds.IsEmpty():
            continue
        minimum, maximum = list(bounds.GetMin()), list(bounds.GetMax())
        obstacle = prim.GetAttribute("s13:obstacleId")
        ident = str(obstacle.Get()) if obstacle else str(prim.GetPath())
        path = str(prim.GetPath())
        category = (
            "PARKING_HOLDER"
            if ident.startswith("SC-HOLDER-")
            else "MOVABLE_SUPPORT_BAR"
            if path.startswith("/World/S15/Supports/")
            else "FIXED_CONTACT_BAR"
            if "-support-" in ident
            and all(
                abs(b - a - size) < 1e-5 for a, b, size in zip(minimum, maximum, (0.06, 0.5, 0.04))
            )
            else None
        )
        nodes.append(dict(path=path, id=ident, minimum=minimum, maximum=maximum, category=category))

    adjacency = [[] for _ in nodes]
    tolerance = 0.002
    for index, first in enumerate(nodes):
        for other in range(index):
            second = nodes[other]
            if all(
                first["minimum"][axis] <= second["maximum"][axis] + tolerance
                and second["minimum"][axis] <= first["maximum"][axis] + tolerance
                for axis in range(3)
            ):
                adjacency[index].append(other)
                adjacency[other].append(index)
    grounded = {i for i, node in enumerate(nodes) if node["minimum"][2] <= 0.05}
    pending = deque(grounded)
    while pending:
        for index in adjacency[pending.popleft()]:
            if index not in grounded:
                grounded.add(index)
                pending.append(index)
    rows = []
    for index, node in enumerate(nodes):
        if node["category"]:
            rows.append(
                {
                    **node,
                    "aabb_connected_to_ground": index in grounded,
                    "touching_colliders": [nodes[j]["path"] for j in adjacency[index]],
                }
            )
    after = hashlib.sha256(stage.GetRootLayer().ExportToString().encode()).hexdigest()
    if before != after:
        raise RuntimeError("SUPPORT_INSPECTION_CHANGED_USD")
    return dict(
        run_id=run_id,
        request_id=request_id,
        scope="READ_ONLY_DIAGNOSTIC",
        method="VISIBLE_COLLIDER_AABB_ADJACENCY_SCREEN_NOT_STRUCTURAL_OR_PHYSICS_PROOF",
        tolerance_m=tolerance,
        collider_count=len(nodes),
        support_geometry_count=len(rows),
        category_counts=dict(Counter(r["category"] for r in rows)),
        disconnected_category_counts=dict(
            Counter(r["category"] for r in rows if not r["aabb_connected_to_ground"])
        ),
        usd_before_sha256=before,
        usd_after_sha256=after,
        geometry=rows,
        finding="LEGACY_SUPPORT_MODELLING_REVIEW_REQUIRED_NO_GEOMETRY_OR_COLLISION_FIX_IN_B1",
    )
