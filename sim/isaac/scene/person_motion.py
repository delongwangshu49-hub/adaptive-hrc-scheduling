"""Bounded visual poses beneath unchanged logical roots and collision proxies."""

from pxr import Gf, Usd, UsdGeom

from .visual_motion import bounded_scale, foot_offset, route_heading


def register_person_motion(scene, identity):
    root = scene.stage.GetPrimAtPath("/World/People/" + identity)
    cache = UsdGeom.BBoxCache(0, ["default"], False, True)
    parts, boxes = [], []
    for prim in Usd.PrimRange(root):
        if not prim.IsA(UsdGeom.Boundable) or prim.GetName() in ("Role", "Occupancy"):
            continue
        boxes.append(cache.ComputeRelativeBound(prim, root).ComputeAlignedRange())
    lo = [min(b.GetMin()[i] for b in boxes) for i in range(3)]
    hi = [max(b.GetMax()[i] for b in boxes) for i in range(3)]
    for prim in root.GetChildren():
        if prim.GetName() in ("Role", "Occupancy"):
            continue
        obj = UsdGeom.Xformable(prim)
        if not obj:
            continue
        originals = obj.GetOrderedXformOps()
        pose = obj.AddTransformOp(opSuffix="s19aVisual")
        pose.Set(Gf.Matrix4d(1))
        obj.SetXformOpOrder([pose, *originals])
        parts.append((prim.GetName(), pose))
    scene._person_motions[identity] = {
        "parts": parts,
        "bounds": (lo, hi),
        "yaw": 0.0,
        "signature": None,
    }


def set_person_pose(scene, identity, yaw=None, *, moving=False, clock_s=0.0, mode="WALK"):
    if identity not in getattr(scene, "_person_motions", {}):
        return
    state = scene._person_motions[identity]
    if mode == "CONTROL_WALK":
        signature = (mode, moving, round(clock_s % 0.8, 12) if moving else None)
        if state["signature"] == signature:
            return
        for name, pose in state["parts"]:
            side = int(name[-1]) if name.startswith(("Leg", "Boot")) else None
            offset = foot_offset(clock_s, side, moving) if side is not None else (0, 0, 0)
            pose.Set(Gf.Matrix4d().SetTranslate(Gf.Vec3d(*offset)))
        state["yaw"] = 0.0
        state["signature"] = signature
        return
    if mode in ("OPERATION", "BACKSTEP", "SIDESTEP"):
        signature = ("CONTROL",)
        if state["signature"] == signature:
            return
        for _, pose in state["parts"]:
            pose.Set(Gf.Matrix4d(1))
        state["yaw"] = 0.0
        state["signature"] = signature
        return
    if yaw is None:
        yaw = state["yaw"]
    signature = (yaw, moving, round(clock_s % 0.8, 12) if moving else None)
    if state["signature"] == signature:
        return
    state["yaw"] = yaw
    state["signature"] = signature
    lo, hi = state["bounds"]
    scale = bounded_scale(hi[0] - lo[0], hi[1] - lo[1], yaw)
    center = Gf.Vec3d((hi[0] + lo[0]) / 2, (hi[1] + lo[1]) / 2, 0)
    rotate = Gf.Matrix4d().SetRotate(Gf.Rotation(Gf.Vec3d(0, 0, 1), yaw))
    matrix = (
        Gf.Matrix4d().SetTranslate(-center)
        * Gf.Matrix4d().SetScale(Gf.Vec3d(scale, scale, 1))
        * rotate
        * Gf.Matrix4d().SetTranslate(center)
    )
    for name, pose in state["parts"]:
        offset = (
            foot_offset(clock_s, int(name[-1]), moving)
            if name[:3] == "Leg"
            else (foot_offset(clock_s, int(name[-1]), moving) if name[:4] == "Boot" else (0, 0, 0))
        )
        pose.Set(Gf.Matrix4d().SetTranslate(Gf.Vec3d(*offset)) * matrix)


def present_route(scene, identity, points, fraction, clock_s, *, moving=True, mode="WALK"):
    if identity not in getattr(scene, "_person_motions", {}):
        return
    heading = route_heading(points, fraction)
    root = scene.stage.GetPrimAtPath("/World/People/" + identity)
    root_yaw = float(UsdGeom.Xformable(root).GetOrderedXformOps()[-1].Get())
    if heading is None:
        set_person_pose(scene, identity, moving=False, clock_s=clock_s)
    else:
        set_person_pose(
            scene, identity, heading - root_yaw, moving=moving, clock_s=clock_s, mode=mode
        )
