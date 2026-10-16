"""Finite model corrections; production inputs, clocks and routes stay unchanged.

Passive fittings are authored kinematics, not strength or rigid-body proof.
"""

import math

from pxr import Gf, UsdGeom, UsdPhysics

PROFILE = "EMERGENCY-LIMITED-MODEL-r1"


def cube(scene, path, position, size, color="light"):
    if not scene.stage.GetPrimAtPath(path):
        scene.shape(path, position, size, color, collision=True)
    else:
        ops = UsdGeom.Xformable(scene.stage.GetPrimAtPath(path)).GetOrderedXformOps()
        ops[0].Set(Gf.Vec3d(*position))
        ops[1].Set(Gf.Vec3f(*size))
    scene.attr(scene.stage.GetPrimAtPath(path), "modelCorrection", PROFILE)


def vehicle_brace(scene, device):
    path = scene.mapping[device]
    hy = float(
        UsdGeom.Xformable(scene.stage.GetPrimAtPath(path + "/HandlePost"))
        .GetOrderedXformOps()[0]
        .Get()[1]
    )
    edge = math.copysign(0.3, hy)
    cube(
        scene,
        path + "/CorrectionHandleBrace",
        (0, (hy + edge) / 2, 0.20),
        (0.05, abs(hy - edge) + 0.05, 0.05),
    )


def equipment(scene):
    for fixture in ("FIX-J2", "FIX-J3"):
        path = scene.mapping[fixture]
        for i, x in enumerate((-2.5, 0, 2.5)):
            for j, y in enumerate((-1.45, 1.45)):
                cube(
                    scene,
                    path + f"/CorrectionLeg{i}{j}",
                    (x, y, 0.15),
                    (0.12, 0.12, 0.30),
                    "orange",
                )
    cube(scene, scene.mapping["R1"] + "/CorrectionPlinth", (0, 0, 0.05), (0.6, 0.6, 0.10))
    for device in ("SCN-WELD-J2", "SCN-WELD-J3"):
        path = scene.mapping[device]
        cube(scene, path + "/CorrectionBase", (0, 0, 0.025), (1.3, 0.7, 0.05), "dark")
        cube(scene, path + "/CorrectionCableSocket", (0, -0.36, 0.4), (0.08, 0.08, 0.08), "dark")
    for device in ("SCN-FORK-01", "SCN-CART-01", "TEST1"):
        path = scene.mapping[device]
        for i in range(2):
            for j in range(2):
                wheel = scene.stage.GetPrimAtPath(path + f"/Wheel{i}{j}")
                # Keep real tyre geometry below the unchanged fork access datum.
                height = 0.1875 if device == "SCN-FORK-01" else 0.25
                ops = UsdGeom.Xformable(wheel).GetOrderedXformOps()
                old = ops[0].Get()
                ops[0].Set(Gf.Vec3d(old[0], old[1], height / 2))
                ops[1].Set(Gf.Vec3f(0.24, 0.24, height))
                UsdPhysics.CollisionAPI.Apply(wheel)
        if device == "SCN-FORK-01":
            ops = UsdGeom.Xformable(scene.stage.GetPrimAtPath(path + "/Deck")).GetOrderedXformOps()
            ops[0].Set(Gf.Vec3d(0, 0, 0.125))
            ops[1].Set(Gf.Vec3f(1.5, 2.6, 0.15))
            cube(
                scene,
                path + "/CorrectionDashboardPost",
                (0, 0.35, 0.625),
                (0.12, 0.12, 0.85),
                "dark",
            )
            cube(
                scene,
                path + "/CorrectionDashboardBrace",
                (0, 0.325, 1.025),
                (0.12, 0.17, 0.05),
                "dark",
            )
        else:
            for i, x in enumerate((-0.32, 0.32)):
                for j, y in enumerate((-0.24, 0.24)):
                    cube(
                        scene,
                        path + f"/CorrectionTrayPost{i}{j}",
                        (x, y, 0.46),
                        (0.05, 0.05, 0.46),
                        "teal",
                    )
            vehicle_brace(scene, device)
    for i, y in enumerate((4, 40)):
        old = "/World/Crane/Bogie" + str(i)
        scene.stage.RemovePrim(old)
        scene.group(old)
        pieces = [
            ((0, y, 0.6805), (4, 1.4, 0.039)),
            ((0, y - 0.5005, 0.3805), (4, 0.399, 0.561)),
            ((0, y + 0.5005, 0.3805), (4, 0.399, 0.561)),
        ]
        for low, high in ((-2, -1.751), (-1.249, 1.249), (1.751, 2)):
            x, width = (low + high) / 2, high - low
            pieces.append(((x, y, 0.4115), (width, 0.602, 0.499)))
            pieces.extend(
                ((x, y + sign * 0.1965, 0.131), (width, 0.209, 0.062)) for sign in (-1, 1)
            )
        for n, (position, size) in enumerate(pieces):
            cube(scene, old + "/Part" + str(n), position, size, "orange")
        for j, x in enumerate((-1.5, 1.5)):
            scene.set_position(f"/World/Crane/Wheel{i}{j}", (x, y, 0.41))
            UsdPhysics.CollisionAPI.Apply(scene.stage.GetPrimAtPath(f"/World/Crane/Wheel{i}{j}"))
            axle = scene.beam(
                f"/World/Crane/CorrectionAxle{i}{j}",
                (x, y - 0.5, 0.41),
                (x, y + 0.5, 0.41),
                0.05,
                "dark",
            )
            UsdPhysics.CollisionAPI.Apply(axle.GetPrim())
    path = scene.mapping["CUT1"]
    # Keep the inlet detail inside the original cutter housing footprint.
    # PRE-IN remains the original separate point-process staging face; no
    # new continuous physical material-feed motion is claimed.
    scene.set_position(path + "/FeedExtension", (0, -0.3, 0.7))
    UsdGeom.Xformable(scene.stage.GetPrimAtPath(path + "/FeedExtension")).GetOrderedXformOps()[
        -1
    ].Set(Gf.Vec3f(0.2, 0.2, 0.7))
    UsdPhysics.CollisionAPI.Apply(scene.stage.GetPrimAtPath(path + "/FeedExtension"))
    for i in range(6):
        cube(scene, path + "/Roller" + str(i), (0, -0.6 + i * 0.24, 0.72), (1.5, 0.12, 0.16))
        UsdPhysics.CollisionAPI.Apply(scene.stage.GetPrimAtPath(path + "/Roller" + str(i)))
    cube(scene, path + "/CorrectionInlet", (0, -0.525, 0.72), (1.55, 0.35, 0.16))
    guard_ops = UsdGeom.Xformable(scene.stage.GetPrimAtPath(path + "/Guard")).GetOrderedXformOps()
    guard_ops[0].Set(Gf.Vec3d(0, -0.65, 1.2))
    guard_ops[1].Set(Gf.Vec3f(1, 0.1, 0.5))
    cube(scene, path + "/CorrectionGuardPost", (0, -0.65, 0.875), (0.05, 0.05, 0.15))


def presence(port, ident, exists):
    """Only delivered/created/consumed facts establish physical presence."""
    prim = port.prim(ident)
    obj = UsdGeom.Imageable(prim)
    body = port.scene.stage.GetPrimAtPath(port.mapping[ident] + "/Envelope")
    if exists:
        obj.MakeVisible()
        UsdPhysics.CollisionAPI.Apply(body)
    else:
        obj.MakeInvisible()
        body.RemoveAPI(UsdPhysics.CollisionAPI)
    port.scene.attr(prim, "physicalExists", exists)
