"""Original USD target scene; isolated from the frozen production mapping."""

import math
from types import SimpleNamespace

from pxr import Gf, UsdGeom, UsdLux, UsdPhysics

from .model import POSES, Box, key, require
from .person_appearance import apply_person_appearance
from .scene_appearance import apply_scene_appearance
from .target_layout import CONTROL, FIXED, PADS, PEOPLE, TASK_BY_ID, VERSION, static_boxes
from .target_trials import TargetRun
from .usd_scene import BuildingScene


class TargetScene(BuildingScene):
    def __init__(self, stage, config, trial="T1"):
        self.stage, self.config = stage, config
        self.fixture = "mep_wait"
        self.state = SimpleNamespace(faces=[], joints=list(POSES[0]))
        self.run = TargetRun(trial)
        self.build()

    def ident(self, name, path, position=(0, 0, 0)):
        obj = self.group(path, position)
        self.mapping[name] = path
        self.attr(obj.GetPrim(), "sceneId", name)
        self.attr(obj.GetPrim(), "scope", "SCENE_ONLY_TARGET_LAYOUT")
        return obj

    def build(self):
        if self.stage.GetPrimAtPath("/World"):
            for p in list(self.stage.GetPrimAtPath("/World").GetChildren()):
                if p.GetName() not in ("Cameras", "Looks"):
                    self.stage.RemovePrim(p.GetPath())
        self.materials, self.mapping = {}, {}
        self.hook_footprint = (6, 3)
        world = self.group("/World")
        self.stage.SetDefaultPrim(world.GetPrim())
        UsdGeom.SetStageMetersPerUnit(self.stage, 1)
        UsdGeom.SetStageUpAxis(self.stage, UsdGeom.Tokens.z)
        self.attr(world.GetPrim(), "layoutVersion", VERSION)
        self.attr(world.GetPrim(), "coordinateFrame", "WORLD_METRES_NO_CORE_OFFSET")
        self.attr(world.GetPrim(), "productionDispatchEnabled", False)
        self.attr(world.GetPrim(), "quality", "UNKNOWN")
        self.attr(world.GetPrim(), "timeline", "RESET_ON_TRIAL_CHANGE_ONLY")
        self.shape("/World/Factory/Ground", (30, 22, -0.15), (60, 44, 0.3), "floor", collision=True)
        for box in static_boxes():
            if box.name in FIXED:
                continue
            obj = self.shape(
                "/World/Static/" + key(box.name),
                box.center,
                box.size,
                "light" if "support" in box.name else "steel",
                collision=True,
            )
            self.attr(obj.GetPrim(), "obstacleId", box.name)
        for name, (x, y, z) in PADS.items():
            p = "/World/Pads/" + key(name)
            self.ident(name, p)
            small = name.startswith(("MEP", "TEST")) or name in ("KIT", "F1-KIT")
            sx, sy = (3, 3) if small else (7.5, 4.5)
            color = (
                "teal"
                if name.startswith("FG")
                else "yellow"
                if name in ("Q1", "DISPATCH")
                else "blue"
            )
            self.shape(p + "/Pad", (x, y, 0.015), (sx, sy, 0.025), "dark")
            for i, (cx, cy, w, h) in enumerate(
                (
                    (x - sx / 2, y, 0.04, sy),
                    (x + sx / 2, y, 0.04, sy),
                    (x, y - sy / 2, sx, 0.04),
                    (x, y + sy / 2, sx, 0.04),
                )
            ):
                self.shape(p + f"/Edge{i}", (cx, cy, 0.03), (w, h, 0.02), color)
            self.label(p + "/Label", name, (x - sx / 2 + 0.15, y + sy / 2 - 0.5, 0.05), 0.32, color)
            self.attr(self.stage.GetPrimAtPath(p), "capacity", 1)
        for i, y in enumerate((7, 18, 29, 39)):
            self.shape(f"/World/Routes/Lane{i}", (30, y, 0.035), (55, 0.07, 0.02), "teal")
        for name, box in FIXED.items():
            p = "/World/Equipment/" + key(name)
            self.ident(name, p, self.run.positions[name])
            self.attr(self.stage.GetPrimAtPath(p), "fixed", True)
            if name == "R1":
                self.group(p + "/BaseMount", (0, 0, 0.5))
                self.robot(p + "/BaseMount")
                self.set_joints(POSES[0])
            elif name.startswith("FIX-"):
                for i, x in enumerate((-2.5, 0, 2.5)):
                    self.shape(
                        p + f"/Cross{i}", (x, 0, 0.4), (0.2, 3.2, 0.2), "orange", collision=True
                    )
                    for j, y in enumerate((-1.6, 1.6)):
                        self.shape(p + f"/Clamp{i}{j}", (x, y, 0.55), (0.2, 0.2, 0.2), "yellow")
            elif name == "CUT1":
                self.shape(p + "/Housing", (0, 0, 0.9), box.size, "blue", collision=True)
                self.shape(p + "/Control", (-0.85, -0.3, 1.1), (0.15, 0.4, 0.4), "dark")
                self.beam(p + "/FeedExtension", (0, -4.5, 0.8), (0, -0.8, 0.8), 0.2, "light")
                for j in range(6):
                    self.shape(
                        p + f"/Roller{j}", (0, -4.5 + j * 0.7, 0.72), (2.8, 0.15, 0.16), "light"
                    )
                self.shape(p + "/Guard", (0, -0.9, 1.2), (1, 0.2, 0.5), "yellow")
            else:
                self.shape(p + "/Power", (-0.2, 0, 0.7), (0.8, 0.7, 1.3), "blue", collision=True)
                self.shape(p + "/Panel", (-0.2, -0.36, 0.9), (0.6, 0.025, 0.35), "dark")
                self.shape(p + "/Bottle", (0.5, 0, 0.8), (0.25, 0.25, 1.5), "teal", "cylinder")
                self.beam(p + "/Cable", (0, -0.4, 0.4), (1.8, -0.5, 0.3), 0.04, "dark")
                self.beam(p + "/Torch", (1.8, -0.5, 0.3), (2, -0.5, 0.5), 0.07, "orange")
            self.label(p + "/Label", name, (-1, 1, 0.04), 0.22, "yellow")
        self.gantry()
        self.vehicles()
        self.people()
        for name in self.run.kinds:
            p = "/World/Loads/" + key(name)
            self.ident(name, p, self.run.positions[name])
            kind = self.run.kinds[name]
            if kind == "module":
                self.frame(p + "/Bottom")
                self.frame(p + "/Top", 3)
                for i, (x, y) in enumerate(((-2.9, -1.4), (2.9, -1.4), (-2.9, 1.4), (2.9, 1.4))):
                    self.shape(p + f"/Column{i}", (x, y, 1.6), (0.2, 0.2, 2.8), "steel")
                self.interior(p, False)
            elif kind == "frame":
                self.frame(p)
            elif kind == "steel":
                self.attr(self.stage.GetPrimAtPath(p), "parentBatch", "SCN-STEEL-PARENT")
                self.attr(
                    self.stage.GetPrimAtPath(p),
                    "quantityMapping",
                    "ONE_OF_FOUR_COLUMN_BLANKS_SYNTHETIC",
                )
                self.shape(p + "/Cassette", (0, 0, 0.035), (2.8, 0.8, 0.07), "wood")
                self.shape(p + "/Blank", (0, 0, 0.135), (2.8, 0.18, 0.13), "steel")
            else:
                size = self.run.size(name)
                self.shape(
                    p + "/Cargo", (0, 0, size[2] / 2), size, "steel" if kind == "steel" else "wood"
                )
            size = self.run.size(name)
            proxy = self.shape(p + "/Occupancy", (0, 0, size[2] / 2), size, "red", collision=True)
            proxy.CreateVisibilityAttr("invisible")
            self.label(
                p + "/Identity",
                name,
                (-2 if kind == "module" else -0.5, 0, size[2] + 0.02),
                0.25,
                "yellow",
            )
        self.label(
            "/World/Disclosure",
            "S13 TARGET / SCENE ONLY / QUALITY UNKNOWN / HR DISABLED",
            (16, 42, 0.04),
            0.45,
            "yellow",
        )
        for name, at in CONTROL.items():
            self.label(
                "/World/Control/" + name,
                name + " CONTROL",
                (at[0] - 1, at[1] + 0.6, 0.04),
                0.2,
                "orange",
            )
        dome = UsdLux.DomeLight.Define(self.stage, "/World/Lighting/Fill")
        dome.CreateIntensityAttr(650)
        sun = UsdLux.DistantLight.Define(self.stage, "/World/Lighting/Sun")
        sun.CreateIntensityAttr(2500)
        sun.AddRotateXYZOp().Set(Gf.Vec3f(25, -30, -25))
        apply_scene_appearance(self)
        UsdPhysics.Scene.Define(self.stage, "/PhysicsScene")
        if not self.stage.GetPrimAtPath("/World/Cameras/Overview"):
            self.cameras()
        self.sync()

    def people(self):
        for name in PEOPLE:
            p = "/World/People/" + name
            self.ident(name, p, self.run.positions[name])
            self.shape(p + "/Torso", (0, 0, 1.15), (0.42, 0.25, 0.6), "blue", "capsule")
            self.shape(p + "/Vest", (0, 0.14, 1.15), (0.43, 0.035, 0.38), "orange")
            self.shape(p + "/Head", (0, 0, 1.65), (0.25, 0.25, 0.3), "wood", "sphere")
            self.shape(p + "/Helmet", (0, 0, 1.81), (0.3, 0.3, 0.13), "yellow", "sphere")
            for j, x in enumerate((-0.13, 0.13)):
                self.beam(p + f"/Leg{j}", (x, 0, 0.1), (x, 0, 0.88), 0.14, "dark")
                self.shape(p + f"/Boot{j}", (x, 0.06, 0.06), (0.16, 0.24, 0.12), "dark")
                self.beam(p + f"/Arm{j}", (x * 2, 0, 1.4), (x * 2, 0.5, 1.05), 0.12, "blue")
            UsdGeom.Xformable(self.stage.GetPrimAtPath(p)).AddRotateZOp().Set(0)
            if name == "Lop":
                self.shape(p + "/Remote", (0, 0.45, 1.08), (0.4, 0.2, 0.15), "yellow")
            self.label(p + "/Role", name, (-0.3, -0.7, 0.03), 0.2, "yellow")
            proxy = self.shape(
                p + "/Occupancy", (0, 0, 0.95), (0.6, 1.2, 1.9), "red", collision=True
            )
            proxy.CreateVisibilityAttr("invisible")

            apply_person_appearance(self, p, name)

    def vehicles(self):
        for name in ("SCN-FORK-01", "SCN-CART-01", "TEST1"):
            p = "/World/Equipment/" + key(name)
            self.ident(name, p, self.run.positions[name])
            fork = name == "SCN-FORK-01"
            self.shape(
                p + "/Deck",
                (0, 0, 0.14),
                (1.5 if fork else 0.8, 2.6 if fork else 0.6, 0.18),
                "orange" if fork else "teal",
                collision=True,
            )
            for i, x in enumerate((-0.55, 0.55) if fork else (-0.32, 0.32)):
                for j, y in enumerate((-0.9, 0.9) if fork else (-0.24, 0.24)):
                    self.shape(
                        p + f"/Wheel{i}{j}", (x, y, 0.15), (0.24, 0.24, 0.25), "dark", "sphere"
                    )
            if fork:
                for i, x in enumerate((-0.65, 0.65)):
                    self.shape(p + f"/Mast{i}", (x, 1.05, 1.25), (0.1, 0.12, 2.5), "steel")
                self.group(p + "/Forks", (0, 0, 0.8))
                for i, x in enumerate((-0.65, 0.65)):
                    self.shape(p + f"/Forks/Tine{i}", (x, 1.55, -0.06), (0.12, 1.3, 0.12), "light")
                self.shape(p + "/Controls", (0, 0.1, 1.2), (0.6, 0.3, 0.3), "dark")
                self.shape(p + "/Guard", (0, -0.9, 1), (1.3, 0.1, 1.6), "steel")
                self.attr(
                    self.stage.GetPrimAtPath(p),
                    "mechanicalForm",
                    "SYNTHETIC_MULTIDIRECTIONAL_STANDING_OPERATOR_FORK",
                )
                self.attr(
                    self.stage.GetPrimAtPath(p),
                    "loadEnvelope",
                    "2.8x0.8m_60kg_ONLY_NOT_FULL_LONG_STOCK_OR_MODULE",
                )
            else:
                hy = 0.75 if name == "TEST1" else -0.75
                self.beam(p + "/Handle", (-0.3, hy, 1.1), (0.3, hy, 1.1), 0.05, "light")
                self.shape(p + "/HandlePost", (0, hy, 0.65), (0.05, 0.05, 1), "light")
                self.shape(p + "/Tray", (0, 0, 0.75), (0.8, 0.6, 0.12), "teal")
                if name == "TEST1":
                    self.shape(p + "/Meter", (0, 0, 0.96), (0.5, 0.4, 0.25), "yellow")
                    self.shape(p + "/Display", (0, -0.21, 0.96), (0.3, 0.02, 0.14), "dark")
                else:
                    self.shape(p + "/TransferTray", (0, 0.65, 0.75), (0.65, 1.1, 0.1), "light")
            self.label(p + "/Label", name, (-0.7, -1.6, 0.04), 0.2, "yellow")

    def gantry(self):
        p = "/World/Crane"
        self.ident("CR1", p, (30, 0, 0))
        for i, y in enumerate((4, 40)):
            self.shape(p + f"/Bogie{i}", (0, y, 0.4), (4, 1.4, 0.6), "orange", collision=True)
            envelope = self.shape(
                p + f"/SupportEnvelope{i}", (0, y, 4.35), (4, 1.4, 8.7), "orange", collision=True
            )
            envelope.CreateVisibilityAttr("invisible")
            for j, x in enumerate((-1.5, 1.5)):
                self.beam(p + f"/Leg{i}{j}", (x, y, 0.7), (0, y, 8.5), 0.25, "orange")
                self.shape(p + f"/Wheel{i}{j}", (x, y, 0.25), (0.5, 0.6, 0.5), "dark", "sphere")
        self.shape(p + "/Girder", (0, 22, 8.8), (0.7, 37, 0.6), "orange", collision=True)
        self.group(p + "/Trolley", (0, 18, 0))
        self.shape(p + "/Trolley/Body", (0, 0, 9.25), (1, 1.2, 0.3), "blue")
        self.beam(p + "/Trolley/Rope", (0, 0, 9.1), (0, 0, 8), 0.05, "dark")
        self.ident("CR1-HOOK", "/World/Hook", (30, 18, 8))
        self.shape("/World/Hook/Block", (0, 0, 0), (0.4, 0.4, 0.4), "yellow")
        self.group("/World/Hook/Rig")
        UsdGeom.Xformable(self.stage.GetPrimAtPath("/World/Hook/Rig")).AddScaleOp().Set(Gf.Vec3f(1))
        for i, y in enumerate((-1.2, 1.2)):
            self.shape(f"/World/Hook/Rig/Bar{i}", (0, y, -0.4), (5.8, 0.12, 0.18), "yellow")
            for j, x in enumerate((-2.8, 2.8)):
                self.beam(f"/World/Hook/Rig/Bridle{i}{j}", (0, 0, 0), (x, y, -0.4), 0.035, "dark")
                self.beam(f"/World/Hook/Rig/Sling{i}{j}", (x, y, -0.4), (x, y, -0.6), 0.035, "dark")

    def cameras(self):
        specs = {
            "Overview": ((81, -57, 72), (29, 21, 0)),
            "Top": ((30, 22, 120), (30, 22, 0)),
            "Supply": ((-10, -10, 24), (10, 13, 0)),
            "Equipment": ((39, -9, 22), (36, 13, 1)),
            "Crossing": ((62, -15, 35), (42, 13, 0)),
            "Finished": ((-4, 3, 34), (25, 29, 1)),
            "Gantry": ((74, -6, 29), (50, 18, 4)),
            "F1": ((67, 15, 14), (55, 29, 1)),
            "Fork": ((15, -4, 9), (6, 7, 1)),
            "Test": ((65, 19, 10), (55, 27, 1)),
        }
        for name, (eye, target) in specs.items():
            obj = UsdGeom.Camera.Define(self.stage, "/World/Cameras/" + name)
            view = Gf.Matrix4d().SetLookAt(
                Gf.Vec3d(*eye),
                Gf.Vec3d(*target),
                Gf.Vec3d(0, 1, 0) if name == "Top" else Gf.Vec3d(0, 0, 1),
            )
            obj.AddTransformOp().Set(view.GetInverse())
            obj.CreateFocalLengthAttr(28 if name != "Top" else 35)
            obj.CreateClippingRangeAttr(Gf.Vec2f(0.1, 300))

    def sync(self):
        a = self.run.action
        for carrier, extension in self.run.extensions.items():
            if a and a.state == "RETRACT" and a.load == carrier:
                extension = 1 - self.run.part / a.seconds
            path = self.mapping[carrier]
            self.attr(self.stage.GetPrimAtPath(path), "supportExtension", extension)
            if carrier == "SCN-FORK-01":
                for i, dx in enumerate((-0.65, 0.65)):
                    self.set_position(path + f"/Forks/Tine{i}", (dx, 0.35 + 1.2 * extension, -0.06))
            else:
                tray = path + "/TransferTray"
                current = (
                    UsdGeom.Xformable(self.stage.GetPrimAtPath(tray)).GetOrderedXformOps()[0].Get()
                )
                self.set_position(tray, (0, 0.65 * extension, current[2]))
        if a and a.task in TASK_BY_ID and TASK_BY_ID[a.task].carrier == "CR1":
            self.hook_footprint = TASK_BY_ID[a.task].size[:2]
        UsdGeom.Xformable(self.stage.GetPrimAtPath("/World/Hook/Rig")).GetOrderedXformOps()[-1].Set(
            Gf.Vec3f(self.hook_footprint[0] / 6, self.hook_footprint[1] / 3, 1)
        )
        for n, pos in self.run.positions.items():
            if n in self.mapping:
                self.set_position(self.mapping[n], pos)
        x, y, z = self.run.positions["CR1-HOOK"]
        self.set_position(self.mapping["CR1"], (x, 0, 0))
        self.set_position("/World/Crane/Trolley", (0, y, 0))
        ops = UsdGeom.Xformable(
            self.stage.GetPrimAtPath("/World/Crane/Trolley/Rope")
        ).GetOrderedXformOps()
        ops[0].Set(Gf.Vec3d(0, 0, (9.1 + z) / 2))
        ops[-1].Set(Gf.Vec3f(0.05, 0.05, 9.1 - z))
        for n, kind in self.run.kinds.items():
            self.attr(self.stage.GetPrimAtPath(self.mapping[n]), "support", self.run.support[n])
            if self.run.support[n] == "CARRIER:SCN-FORK-01":
                self.set_position(
                    self.mapping["SCN-FORK-01"] + "/Forks", (0, 0, self.run.positions[n][2])
                )
            if self.run.support[n] == "CARRIER:SCN-CART-01":
                self.set_position(
                    self.mapping["SCN-CART-01"] + "/TransferTray",
                    (0, 0.65, self.run.positions[n][2] - 0.05),
                )
        for p, state in self.run.person_state.items():
            yaw = 180 if p == "QA1" and a and a.task == "TEST1" and p in a.paths else 0
            UsdGeom.Xformable(self.stage.GetPrimAtPath(self.mapping[p])).GetOrderedXformOps()[
                -1
            ].Set(yaw)
            for k, v in state.items():
                self.attr(self.stage.GetPrimAtPath(self.mapping[p]), k, v)

    def readback(self):
        actual = {n: self.world_position(self.mapping[n]) for n in self.run.positions}
        for n, pos in self.run.positions.items():
            require(math.dist(actual[n], pos) < 0.001, "TARGET_USD_READBACK:" + n)
        for n, support in self.run.support.items():
            pos = actual[n]
            if support == "CARRIER:CR1":
                expected = (pos[0], pos[1], pos[2] + self.run.size(n)[2] + 0.6)
                require(math.dist(actual["CR1-HOOK"], expected) < 0.001, "HOOK_LOAD_ATTACHMENT")
                require(self.hook_footprint == self.run.size(n)[:2], "SPREADER_FOOTPRINT")
            elif support == "CARRIER:SCN-FORK-01":
                vehicle = actual["SCN-FORK-01"]
                require(
                    math.dist(pos[:2], (vehicle[0], vehicle[1] + 1.8)) < 0.001,
                    "FORK_LOAD_ALIGNMENT",
                )
                top = self.world_position(self.mapping["SCN-FORK-01"] + "/Forks")
                require(abs(top[2] - pos[2]) < 0.001, "FORK_LOAD_SUPPORT")
            elif support == "CARRIER:SCN-CART-01":
                vehicle = actual["SCN-CART-01"]
                require(
                    math.dist(pos[:2], (vehicle[0], vehicle[1] + 1.1)) < 0.001,
                    "TRAY_LOAD_ALIGNMENT",
                )
                tray = self.world_position(self.mapping["SCN-CART-01"] + "/TransferTray")
                require(abs(tray[2] + 0.05 - pos[2]) < 0.001, "TRAY_LOAD_SUPPORT")
                require(
                    abs(tray[0] - pos[0]) < 0.325 and abs(tray[1] - pos[1]) < 0.55,
                    "LOAD_CENTRE_OFF_TRAY",
                )
        return actual

    def actual_obstacles(self, moving=()):
        """Read USD collider bounds; loads/people in a moving group excluded.

        Fork/platform contacts and support-top contact are designed interfaces.
        Other current actors remain obstacles. No cached pre-movement positions.
        """
        ignored = [self.mapping[n] for n in moving if n in self.mapping]
        # Only an active crane motion may exclude its own structure. It is swept
        # separately against all other actors; a parked crane stays an obstacle.
        ignored += ["/World/Factory/Ground"]
        if "CR1-HOOK" in moving or "CR1" in moving:
            ignored += ["/World/Crane", "/World/Hook"]
        cache = UsdGeom.BBoxCache(
            0, [UsdGeom.Tokens.default_], useExtentsHint=False, ignoreVisibility=True
        )
        result = []
        for prim in self.stage.Traverse():
            path = str(prim.GetPath())
            if not prim.HasAPI(UsdPhysics.CollisionAPI) or any(
                path == p or path.startswith(p + "/") for p in ignored
            ):
                continue
            bounds = cache.ComputeWorldBound(prim).ComputeAlignedRange()
            tag = prim.GetAttribute("s13:obstacleId")
            result.append(
                Box(
                    tag.Get() if tag else path, tuple(bounds.GetMidpoint()), tuple(bounds.GetSize())
                )
            )
        return result


class TargetTrialScene:
    def __init__(self, scene, trial="T1"):
        self.scene = scene
        self.trace = []
        self.fault = None
        self.load(trial)

    def load(self, trial, combined=False):
        self.run = TargetRun(trial, combined=combined)
        self._bounds_key = None
        self.scene.run = self.run
        self.scene.build()
        self.trace = []
        self.fault = None

    def restart(self):
        self.load(self.run.name, self.run.combined)

    def inject(self, kind):
        self.clear_fault()
        self.fault = kind
        if kind in ("operator_missing", "unreleased", "source_missing", "target_full"):
            self.run.faults.add(kind)
            return
        a = self.run.action
        require(a is not None and a.paths, "INJECT_REQUIRES_MOTION")
        name, points = next(iter(a.paths.items()))
        p = points[-1] if kind == "occupied" else points[len(points) // 2]
        size = a.sizes[name]
        self.scene.shape(
            "/World/Injected",
            (p[0], p[1], p[2] + size[2] / 2),
            (0.7, 0.7, 1.9),
            "red",
            collision=True,
        )

    def clear_fault(self):
        self._bounds_key = None
        self.scene.stage.RemovePrim("/World/Injected")
        self.run.faults.clear()
        self.fault = None

    def advance(self, dt, single_step=False):
        try:
            self.scene.readback()
        except ValueError as exc:
            self.run.status, self.run.blocked = "BLOCKED", str(exc)
            return self.run.snapshot()
        a = self.run.action
        if a:
            moving = tuple(a.paths)
            if a.task == "BOARD":
                moving += ("SCN-FORK-01",)
            # Driver and forklift form a designed contact group during boarding
            # and transport; handoff checks keep every other actor in the sweep.
            if self._bounds_key != self.run.index:
                self._bounds = self.scene.actual_obstacles(moving)
                self._bounds_key = self.run.index
            obs = self._bounds
        else:
            obs = ()
        snap = self.run.advance(dt, obs, single_step)
        self.scene.sync()
        snap["actual_world_positions"] = self.scene.readback()
        snap["action"] = a.label if a else "COMPLETE"
        self.trace.append(snap)
        return snap

    def readback(self):
        return self.scene.readback()

    def set_layers(self, layer, visible):
        paths = (
            ["/World/Routes"]
            if layer == "routes"
            else [p + "/Role" for n, p in self.scene.mapping.items() if n in PEOPLE]
            if layer == "roles"
            else [
                str(p.GetPath()) for p in self.scene.stage.Traverse() if p.GetName() == "Occupancy"
            ]
        )
        for p in paths:
            obj = UsdGeom.Imageable(self.scene.stage.GetPrimAtPath(p))
            obj.MakeVisible() if visible else obj.MakeInvisible()
        return {"layer": layer, "visible": visible, "paths": len(paths)}
