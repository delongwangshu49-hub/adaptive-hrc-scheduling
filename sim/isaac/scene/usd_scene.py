"""Original procedural USD geometry. Imports require the installed Isaac runtime."""

import json
import math

from pxr import Gf, Sdf, UsdGeom, UsdLux, UsdPhysics, UsdShade

from .layout import CORE_ORIGIN, RACKS, SUPPLY, VERSION, local, person_home
from .model import AXES, EQUIPMENT, LINKS, ROBOT_BASE, ZONES, SceneState, key

PALETTE = {
    "floor": (0.16, 0.20, 0.24),
    "steel": (0.18, 0.28, 0.34),
    "light": (0.72, 0.77, 0.78),
    "orange": (0.95, 0.33, 0.055),
    "yellow": (0.95, 0.69, 0.09),
    "blue": (0.06, 0.37, 0.61),
    "teal": (0.08, 0.64, 0.60),
    "white": (0.90, 0.93, 0.91),
    "dark": (0.035, 0.055, 0.07),
    "red": (0.75, 0.12, 0.09),
    "wood": (0.56, 0.39, 0.23),
    "water": (0.08, 0.45, 0.66),
    "hud_white": (0.9, 0.93, 0.91),
    "hud_yellow": (0.95, 0.69, 0.09),
    "hud_dark": (0.025, 0.04, 0.055),
}
# Original bitmap alphabet converted to one quad mesh per label, no font/texture asset.
FONT = dict(
    zip(
        "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-./: ",
        [
            "01110/10001/10001/11111/10001/10001/10001",
            "11110/10001/10001/11110/10001/10001/11110",
            "01111/10000/10000/10000/10000/10000/01111",
            "11110/10001/10001/10001/10001/10001/11110",
            "11111/10000/10000/11110/10000/10000/11111",
            "11111/10000/10000/11110/10000/10000/10000",
            "01111/10000/10000/10111/10001/10001/01111",
            "10001/10001/10001/11111/10001/10001/10001",
            "11111/00100/00100/00100/00100/00100/11111",
            "00111/00010/00010/00010/10010/10010/01100",
            "10001/10010/10100/11000/10100/10010/10001",
            "10000/10000/10000/10000/10000/10000/11111",
            "10001/11011/10101/10101/10001/10001/10001",
            "10001/11001/10101/10011/10001/10001/10001",
            "01110/10001/10001/10001/10001/10001/01110",
            "11110/10001/10001/11110/10000/10000/10000",
            "01110/10001/10001/10001/10101/10010/01101",
            "11110/10001/10001/11110/10100/10010/10001",
            "01111/10000/10000/01110/00001/00001/11110",
            "11111/00100/00100/00100/00100/00100/00100",
            "10001/10001/10001/10001/10001/10001/01110",
            "10001/10001/10001/10001/10001/01010/00100",
            "10001/10001/10001/10101/10101/11011/10001",
            "10001/10001/01010/00100/01010/10001/10001",
            "10001/10001/01010/00100/00100/00100/00100",
            "11111/00001/00010/00100/01000/10000/11111",
            "01110/10001/10011/10101/11001/10001/01110",
            "00100/01100/00100/00100/00100/00100/01110",
            "01110/10001/00001/00010/00100/01000/11111",
            "11110/00001/00001/01110/00001/00001/11110",
            "00010/00110/01010/10010/11111/00010/00010",
            "11111/10000/10000/11110/00001/00001/11110",
            "01110/10000/10000/11110/10001/10001/01110",
            "11111/00001/00010/00100/01000/01000/01000",
            "01110/10001/10001/01110/10001/10001/01110",
            "01110/10001/10001/01111/00001/00001/01110",
            "00000/00000/00000/11111/00000/00000/00000",
            "00000/00000/00000/00000/00000/00110/00110",
            "00001/00010/00010/00100/01000/01000/10000",
            "00000/00100/00100/00000/00100/00100/00000",
            "00000/00000/00000/00000/00000/00000/00000",
        ],
    )
)


class BuildingScene:
    def __init__(self, stage, config, fixture="initial"):
        self.stage, self.config = stage, config
        self.materials = {}
        self.mapping = {}
        self.fixture = fixture
        self.build()

    def attr(self, prim, name, value):
        if isinstance(value, bool):
            kind = Sdf.ValueTypeNames.Bool
        elif isinstance(value, (int, float)):
            kind = Sdf.ValueTypeNames.Double
        elif isinstance(value, list):
            kind = Sdf.ValueTypeNames.String
            value = json.dumps(value)
        else:
            kind = Sdf.ValueTypeNames.String
        prim.CreateAttribute("s13:" + name, kind, custom=True).Set(value)

    def group(self, path, position=(0, 0, 0), domain_id=None):
        x = UsdGeom.Xform.Define(self.stage, path)
        ops = x.GetOrderedXformOps()
        (ops[0] if ops else x.AddTranslateOp()).Set(Gf.Vec3d(*position))
        if domain_id:
            if domain_id in self.mapping:
                raise ValueError("DUPLICATE_USD_ID:" + domain_id)
            self.mapping[domain_id] = path
            self.attr(x.GetPrim(), "domainId", domain_id)
        return x

    def material(self, name):
        if name not in self.materials:
            m = UsdShade.Material.Define(self.stage, "/World/Looks/" + name)
            s = UsdShade.Shader.Define(self.stage, m.GetPath().AppendChild("Surface"))
            s.CreateIdAttr("UsdPreviewSurface")
            s.CreateInput("diffuseColor", Sdf.ValueTypeNames.Color3f).Set(Gf.Vec3f(*PALETTE[name]))
            s.CreateInput("roughness", Sdf.ValueTypeNames.Float).Set(
                0.48 if name == "steel" else 0.7
            )
            s.CreateInput("metallic", Sdf.ValueTypeNames.Float).Set(
                0.65 if name == "steel" else 0.05
            )
            if name.startswith("hud_"):
                s.GetInput("diffuseColor").Set(Gf.Vec3f(0))
                s.GetInput("metallic").Set(0)
                s.CreateInput("emissiveColor", Sdf.ValueTypeNames.Color3f).Set(
                    Gf.Vec3f(*PALETTE[name])
                )
            m.CreateSurfaceOutput().ConnectToSource(s.ConnectableAPI(), "surface")
            self.materials[name] = m
        return self.materials[name]

    def shape(self, path, position, size, color="steel", kind="cube", collision=False):
        schema = {
            "cube": UsdGeom.Cube,
            "cylinder": UsdGeom.Cylinder,
            "sphere": UsdGeom.Sphere,
            "capsule": UsdGeom.Capsule,
        }[kind]
        obj = schema.Define(self.stage, path)
        if kind == "cube":
            obj.CreateSizeAttr(1)
        elif kind == "sphere":
            obj.CreateRadiusAttr(0.5)
        else:
            obj.CreateRadiusAttr(0.5)
            obj.CreateHeightAttr(1)
        if kind == "capsule" and collision:
            obj.CreateRadiusAttr(size[0] / 2)
            obj.CreateHeightAttr(size[2])
            size = (1, 1, 1)
        obj.AddTranslateOp().Set(Gf.Vec3d(*position))
        obj.AddScaleOp().Set(Gf.Vec3f(*size))
        obj.CreateDisplayColorAttr([Gf.Vec3f(*PALETTE[color])])
        UsdShade.MaterialBindingAPI.Apply(obj.GetPrim()).Bind(self.material(color))
        if collision:
            UsdPhysics.CollisionAPI.Apply(obj.GetPrim())
        return obj

    def beam(self, path, start, end, width=0.08, color="steel"):
        delta = Gf.Vec3d(*end) - Gf.Vec3d(*start)
        obj = self.shape(
            path,
            tuple((a + b) / 2 for a, b in zip(start, end)),
            (width, width, delta.GetLength()),
            color,
            "cylinder",
        )
        obj.AddOrientOp().Set(Gf.Quatf(Gf.Rotation(Gf.Vec3d(0, 0, 1), delta).GetQuat()))
        # Orientation must precede nonuniform scale (T R S).
        ops = obj.GetOrderedXformOps()
        obj.SetXformOpOrder([ops[0], ops[2], ops[1]])
        return obj

    def label(self, path, text, position, height=0.4, color="white"):
        points, indices = [], []
        unit = height / 7
        for char_index, char in enumerate(text.upper()):
            for row, line in enumerate(FONT.get(char, FONT[" "]).split("/")):
                for col, on in enumerate(line):
                    if on != "1":
                        continue
                    x, y, z = position
                    x += (char_index * 6 + col) * unit
                    y += (6 - row) * unit
                    base = len(points)
                    points.extend(
                        [
                            (x, y, z),
                            (x + unit * 0.88, y, z),
                            (x + unit * 0.88, y + unit * 0.88, z),
                            (x, y + unit * 0.88, z),
                        ]
                    )
                    indices.extend(range(base, base + 4))
        mesh = UsdGeom.Mesh.Define(self.stage, path)
        mesh.CreatePointsAttr(points)
        mesh.CreateFaceVertexCountsAttr([4] * (len(points) // 4))
        mesh.CreateFaceVertexIndicesAttr(indices)
        mesh.CreateSubdivisionSchemeAttr("none")
        mesh.CreateDoubleSidedAttr(True)
        UsdShade.MaterialBindingAPI.Apply(mesh.GetPrim()).Bind(self.material(color))

    def set_position(self, path, position):
        UsdGeom.Xformable(self.stage.GetPrimAtPath(path)).GetOrderedXformOps()[0].Set(
            Gf.Vec3d(*position)
        )

    def world_matrix(self, path):
        return UsdGeom.XformCache().GetLocalToWorldTransform(self.stage.GetPrimAtPath(path))

    def world_position(self, path):
        return tuple(self.world_matrix(path).ExtractTranslation())

    def scene_position(self, path):
        """Actual USD world readback converted to the documented core frame."""
        return local(self.world_position(path))

    def scene_matrix(self, path):
        matrix = self.world_matrix(path)
        p = local(matrix.ExtractTranslation())
        matrix.SetTranslateOnly(Gf.Vec3d(*p))
        return matrix

    def supply(self):
        root = "/World/Supply"
        self.group(root)
        for name, (center, size, label, slots) in SUPPLY.items():
            p = root + "/" + key(name)
            obj = self.group(p)
            self.attr(obj.GetPrim(), "sceneId", name)
            self.attr(obj.GetPrim(), "mapping", "SCENE_RESERVATION_NOT_DOMAIN_CAPACITY")
            self.attr(obj.GetPrim(), "displaySlots", slots)
            x, y, _ = center
            self.shape(p + "/Pad", (x, y, 0.01), (*size, 0.012), "dark")
            self.label(
                p + "/Label",
                label,
                (x - size[0] / 2 + 0.3, y + size[1] / 2 - 0.8, 0.035),
                0.36,
                "teal",
            )
            for j, cy in enumerate((y - size[1] / 2, y + size[1] / 2)):
                self.shape(p + f"/Border{j}", (x, cy, 0.03), (size[0], 0.05, 0.02), "teal")
            if name != "SCN-KIT":
                rack = next(r for r in RACKS if r.name == name)
                self.shape(p + "/Rack", rack.center, rack.size, "light", collision=True)
                for j in range(3):
                    self.shape(
                        p + f"/Shelf{j}",
                        (-10, y, 0.4 + j * 0.45),
                        (1.8, size[1] - 1, 0.06),
                        "steel",
                    )
            # Distinct material classes and pick faces, with explicit scene IDs.
            if name == "SCN-STEEL":
                for j in range(3):
                    stock = self.shape(
                        p + f"/Batch{j}",
                        (-7, 12.5 + j * 0.35, 0.7),
                        (6, 0.22, 0.2),
                        "steel",
                        collision=True,
                    )
                    self.attr(stock.GetPrim(), "sceneId", name + f"-B{j}")
                for j, bx in enumerate((-9, -5)):
                    self.shape(
                        p + f"/LongSupport{j}",
                        (bx, 12.85, 0.3),
                        (0.4, 1.2, 0.6),
                        "light",
                        collision=True,
                    )
                self.label(
                    p + "/LoadNote", "COLUMNS 4T / CR1 ONLY", (-9.5, 10.8, 0.035), 0.23, "yellow"
                )
            elif name == "SCN-PANELS":
                for j in range(4):
                    panel = self.shape(
                        p + f"/Panel{j}",
                        (-7, 19, 0.18 + j * 0.13),
                        (3, 2, 0.1),
                        "light",
                        collision=True,
                    )
                    self.attr(panel.GetPrim(), "sceneId", name + f"-P{j}")
            else:
                for j in range(slots):
                    bx, by = x - 1.5 + j * 1.6, y - 1.3
                    batch = self.shape(
                        p + f"/Batch{j}",
                        (bx, by, 0.45),
                        (1.3, 0.9, 0.75),
                        "red" if name in ("SCN-RECEIVE", "SCN-RETURN") else "wood",
                        collision=True,
                    )
                    self.attr(batch.GetPrim(), "sceneId", name + f"-B{j}")
                    self.attr(batch.GetPrim(), "inventorySemantics", "NOT_IMPLEMENTED")
                    self.label(
                        p + f"/BatchLabel{j}",
                        "MEP"
                        if name == "SCN-MEP"
                        else "HOLD"
                        if name in ("SCN-RECEIVE", "SCN-RETURN")
                        else "KIT",
                        (bx - 0.5, by - 0.25, 0.84),
                        0.2,
                        "dark",
                    )
        # Low supports preserve full raw stock extraction and HST clearance.
        for name, x, y in (
            ("INPUT", 1, 7),
            ("CUT-OUTPUT", 6, 7.5),
            ("J3-SUPPLY", 28.5, 14.5),
            ("F1-SUPPLY", 32, 27.5),
        ):
            p = root + "/" + key("SCN-" + name)
            self.group(p)
            self.attr(self.stage.GetPrimAtPath(p), "sceneId", "SCN-" + name)
            self.attr(self.stage.GetPrimAtPath(p), "mapping", "SCENE_RESERVATION")
            for j, dx in enumerate((-2, 2) if name in ("INPUT", "CUT-OUTPUT") else (-0.4, 0.4)):
                self.shape(
                    p + f"/Support{j}", (x + dx, y, 0.25), (0.3, 0.7, 0.5), "light", collision=True
                )
            self.label(p + "/Label", name, (x - 2, y - 1, 0.035), 0.22, "yellow")
        self.label(root + "/CutNote", "CUT ONLY / SHAPE ABSTRACT", (-2, 9.1, 0.035), 0.21, "yellow")
        self.label(root + "/Reserved", "SCN / NO INVENTORY EVENTS", (-12, 37, 0.035), 0.3, "yellow")
        self.shape(root + "/NorthWalk", (14, 37.5, 0.02), (54, 1, 0.015), "teal")
        self.shape(root + "/WestWalk", (-1, 26, 0.02), (0.8, 23, 0.015), "teal")
        for i, x in enumerate(range(9, 30, 2)):
            self.shape(root + f"/Crossing{i}", (x, 17, 0.025), (0.5, 4, 0.02), "teal")
        self.label(root + "/CrossingLabel", "STOP / CR1 PRIORITY", (12, 18.3, 0.04), 0.24, "yellow")
        self.label(
            root + "/RobotBound",
            "R1 LOCAL ONLY / FAR FACE UNREACHABLE",
            (14, 13.8, 0.035),
            0.2,
            "yellow",
        )

    def build(self):
        # Keep viewport camera prim identities stable across fixture resets.
        # Replacing an active camera at the same path can leave Hydra rendering
        # its deleted handle even when the viewport reports the new USD matrix.
        if self.stage.GetPrimAtPath("/World"):
            for child in list(self.stage.GetPrimAtPath("/World").GetChildren()):
                if child.GetName() not in ("Cameras", "Looks"):
                    self.stage.RemovePrim(child.GetPath())
        self.materials, self.mapping = {}, {}
        self.state = SceneState(self.config, self.fixture)
        world = self.group("/World", CORE_ORIGIN)
        self.attr(world.GetPrim(), "layoutVersion", VERSION)
        self.attr(world.GetPrim(), "coordinateFrame", "CORE_LOCAL_PLUS_WORLD_ORIGIN_14_4_0")
        self.stage.SetDefaultPrim(world.GetPrim())
        UsdGeom.SetStageMetersPerUnit(self.stage, 1)
        UsdGeom.SetStageUpAxis(self.stage, UsdGeom.Tokens.z)
        UsdPhysics.SetStageKilogramsPerUnit(self.stage, 1)
        self.attr(world.GetPrim(), "purpose", "SYNTHETIC_INSPECTION_ONLY")
        self.attr(world.GetPrim(), "fixture", self.fixture)
        self.attr(world.GetPrim(), "inputSha256", self.config["source_sha256"])
        self.attr(world.GetPrim(), "productionDispatchEnabled", False)
        self.attr(world.GetPrim(), "quality", "UNKNOWN")
        for name in ("Factory", "Entities", "Resources", "People", "Routes", "Faces", "Cameras"):
            self.group("/World/" + name)
        self.factory()
        self.supply()
        self.equipment()
        self.people()
        self.entities()
        if not self.stage.GetPrimAtPath("/World/Cameras/Overview"):
            self.cameras()
        self.label(
            "/World/Factory/Disclosure", "S13 / SYNTHETIC / GEOMETRY ONLY", (2, 31.8, 0.03), 0.55
        )
        self.label(
            "/World/Factory/Disclosure2",
            "QUALITY UNKNOWN / HR DISABLED",
            (2, 30.95, 0.03),
            0.38,
            "yellow",
        )
        self.label(
            "/World/Factory/Fixture",
            "STATE / " + self.fixture.replace("_", " "),
            (2, 29.9, 0.03),
            0.42,
            "teal",
        )
        # Keep the engine scene stable across content resets. Deleting and recreating
        # the same physics prim before Kit consumes notices invalidates its registry.
        physics = UsdPhysics.Scene.Define(self.stage, "/PhysicsScene")
        physics.CreateGravityDirectionAttr(Gf.Vec3f(0, 0, -1))
        physics.CreateGravityMagnitudeAttr(9.81)
        dome = UsdLux.DomeLight.Define(self.stage, "/World/Lighting/Fill")
        dome.CreateIntensityAttr(650)
        sun = UsdLux.DistantLight.Define(self.stage, "/World/Lighting/Sun")
        sun.CreateIntensityAttr(2500)
        sun.CreateAngleAttr(1.0)
        sun.AddRotateXYZOp().Set(Gf.Vec3f(25, -30, -25))
        # Dynamic contact witness separate from product load claims.
        probe = self.shape(
            "/World/ContactProbe", (1, 28, 1.4), (0.3, 0.3, 0.3), "orange", collision=True
        )
        UsdPhysics.RigidBodyAPI.Apply(probe.GetPrim())
        UsdPhysics.MassAPI.Apply(probe.GetPrim()).CreateMassAttr(1)

    def factory(self):
        p = "/World/Factory"
        self.shape(p + "/Ground", (16, 18, -0.15), (60, 44, 0.3), "floor", collision=True)
        for name, (x, y) in ZONES.items():
            path = p + "/" + key(name)
            self.group(path, domain_id=name)
            color = "teal" if name == "F1" else "yellow" if name in ("Q1", "OUT1") else "blue"
            self.shape(path + "/Pad", (x, y, 0.008), (8, 8, 0.012), "dark")
            for index, (cx, cy, sx, sy) in enumerate(
                (
                    (x - 4, y, 0.045, 8),
                    (x + 4, y, 0.045, 8),
                    (x, y - 4, 8, 0.045),
                    (x, y + 4, 8, 0.045),
                )
            ):
                self.shape(path + f"/Border{index}", (cx, cy, 0.022), (sx, sy, 0.015), color)
            self.label(path + "/Label", name, (x - 3.7, y + 3, 0.03), 0.6, color)
            if name in ("J2", "BUF"):
                for i, sy in enumerate((7.5, 12.5)):
                    self.label(
                        path + f"/Slot{i}",
                        "BOTTOM" if i == 0 else "TOP",
                        (x - 2.8, sy - 1.9, 0.03),
                        0.25,
                    )
            support_rows = (
                (7.5, 10, 12.5) if name == "J3" else (7.5, 12.5) if name in ("J2", "BUF") else (y,)
            )
            for row, cy in enumerate(support_rows):
                for i, (dx, dy) in enumerate(((-2, -1.35), (2, -1.35), (-2, 1.35), (2, 1.35))):
                    self.shape(
                        path + f"/Support{row}_{i}",
                        (x + dx, cy + dy, 0.3),
                        (0.4, 0.3, 0.6),
                        "light",
                        collision=True,
                    )
        for name, y, width in (("ROUTE-COMP", 4, 4), ("ROUTE-MODULE", 17, 6)):
            path = "/World/Routes/" + key(name)
            self.group(path, domain_id=name)
            for i, dy in enumerate((-width / 2, width / 2)):
                self.shape(path + f"/Edge{i}", (21, y + dy, 0.027), (40, 0.06, 0.02), "yellow")
            self.label(path + "/Label", name, (3, y - 0.25, 0.035), 0.42, "yellow")
        # Stable landings for the compact four-column set, before assembly.
        for name, position in (
            ("ColumnPalletPRE", (6, 12.5, 0.3)),
            ("ColumnPalletJ3", (36, 10, 0.3)),
        ):
            self.shape(p + "/" + name, position, (1.6, 1.6, 0.6), "light", collision=True)
        # Architectural layer is switchable; no hidden collision barrier added.
        shell = self.group(p + "/Shell")
        for x in (-14, -4, 6, 16, 26, 36, 46):
            for y in (-4, 40):
                self.shape(
                    str(shell.GetPath()) + "/Column" + key(str(x) + "_" + str(y)),
                    (x, y, 5),
                    (0.24, 0.24, 10),
                    "light",
                )
        self.shape(p + "/Shell/NorthBeam", (16, 40, 9.8), (60, 0.3, 0.4), "light")
        south = self.shape(p + "/Shell/SouthBeam", (16, -4, 9.8), (60, 0.3, 0.4), "light")
        south.CreateVisibilityAttr("invisible")
        roof = self.shape(p + "/Shell/Roof", (16, 18, 10.1), (60, 44, 0.16), "light")
        roof.CreateVisibilityAttr("invisible")

    def equipment(self):
        locations = {
            "CUT1": (1, 10, 0),
            "WELD1": (32, 11, 0) if self.fixture in ("structure", "joining") else (12, 10, 0),
            "R1": ROBOT_BASE,
            "HST1": (6, 4, 0),
            "CR1": (26, 0, 0),
            "TEST1": (32, 25, 0),
            "FIX-J2": (16, 7.5, 0),
            "FIX-J3": (36, 10, 0),
        }
        for name, position in locations.items():
            p = "/World/Resources/" + key(name)
            root = self.group(p, position, name)
            self.attr(root.GetPrim(), "classification", EQUIPMENT.get(name, "FIXTURE"))
            self.attr(root.GetPrim(), "owner", self.state.owners.get(name, "NONE"))
            self.label(p + "/Label", name, (-1, -1.2, 0.04), 0.27, "yellow")
            if name.startswith("FIX"):
                for i, x in enumerate((-2.5, 0, 2.5)):
                    self.shape(
                        p + f"/Cross{i}", (x, 0, 0.4), (0.2, 3.2, 0.2), "orange", collision=True
                    )
                    for j, y in enumerate((-1.6, 1.6)):
                        self.shape(p + f"/Clamp{i}{j}", (x, y, 0.6), (0.22, 0.22, 0.28), "yellow")
                continue
            if name == "CR1":
                self.crane(p)
            elif name == "R1":
                self.robot(p)
            elif name == "HST1":
                self.attr(root.GetPrim(), "mechanicalForm", "UNKNOWN_FUNCTIONAL_ENVELOPE")
                self.shape(p + "/Crosshead", (0, 0, 5.5), (6.6, 3.7, 0.2), "teal")
                for i, (x, y) in enumerate(
                    ((-3.25, -1.7), (3.25, -1.7), (-3.25, 1.7), (3.25, 1.7))
                ):
                    self.shape(
                        p + f"/FunctionalSupport{i}",
                        (x, y, 2.75),
                        (0.12, 0.12, 5.5),
                        "teal",
                        collision=True,
                    )
                self.beam(p + "/Rope", (0, 0, 5.4), (0, 0, 4.9), 0.04, "dark")
                self.group(p + "/Spreader", (0, 0, 4.9))
                for i, y in enumerate((-1.2, 1.2)):
                    self.shape(p + f"/Spreader/Bar{i}", (0, y, 0), (5.7, 0.12, 0.15), "yellow")
                for i, x in enumerate((-2.7, 2.7)):
                    self.shape(p + f"/Spreader/Cross{i}", (x, 0, 0), (0.12, 2.5, 0.15), "yellow")
                    for j, y in enumerate((-1.2, 1.2)):
                        self.beam(
                            p + f"/Spreader/Sling{i}{j}", (x, y, 0), (x, y, -0.4), 0.035, "dark"
                        )
                self.label(p + "/UnknownForm", "FORM U / 3T", (-2.8, 0, 0.04), 0.25, "teal")
            elif name == "CUT1":
                self.shape(p + "/Bed", (0, 0, 0.8), (1.5, 0.8, 0.3), "blue", collision=True)
                for i, x in enumerate((-0.6, 0.6)):
                    self.shape(p + f"/Leg{i}", (x, 0, 0.35), (0.2, 0.65, 0.7), "steel")
                blade = self.shape(
                    p + "/Blade", (0, 0, 1.35), (0.55, 0.06, 0.55), "light", "cylinder"
                )
                blade.AddRotateXOp().Set(90)
                self.shape(p + "/Guard", (0.1, 0, 1.58), (0.6, 0.23, 0.18), "yellow")
                self.shape(p + "/Control", (0.65, -0.4, 1.05), (0.22, 0.15, 0.3), "dark")
            elif name == "WELD1":
                self.shape(p + "/Power", (0, 0, 0.6), (0.65, 0.6, 1.05), "blue", collision=True)
                self.shape(p + "/Panel", (0, -0.306, 0.85), (0.48, 0.02, 0.24), "dark")
                self.shape(p + "/Bottle", (0.55, 0, 0.75), (0.25, 0.25, 1.4), "teal", "cylinder")
                self.beam(p + "/Cable", (0, -0.32, 0.6), (1, -0.5, 0.12), 0.035, "dark")
                self.beam(p + "/Torch", (1, -0.5, 0.12), (1.25, -0.5, 0.2), 0.065, "orange")
                self.attr(root.GetPrim(), "relocation", "CONTINUOUS_T3_INSPECTION_ONLY")
            elif name == "TEST1":
                self.shape(p + "/Cart", (0, 0, 0.65), (0.8, 0.55, 0.8), "teal", collision=True)
                for i, x in enumerate((-0.3, 0.3)):
                    self.shape(p + f"/Wheel{i}", (x, 0, 0.15), (0.18, 0.18, 0.18), "dark", "sphere")
                self.shape(p + "/Meter", (0, 0, 1.12), (0.5, 0.35, 0.2), "yellow")
                self.shape(p + "/Display", (0, -0.181, 1.12), (0.35, 0.015, 0.12), "dark")
                self.attr(root.GetPrim(), "hold", "TEST-SET THROUGH Q-POND")

    def crane(self, p):
        for i, y in enumerate((0.75, 30.5)):
            self.shape(
                "/World/Factory/Rail" + str(i),
                (21, y, 0.08),
                (42, 0.18, 0.16),
                "steel",
                collision=True,
            )
            self.shape(p + f"/Bogie{i}", (0, y, 0.45), (4, 1.1, 0.6), "orange", collision=True)
            for j, x in enumerate((-1.4, 1.4)):
                self.shape(p + f"/Wheel{i}{j}", (x, y, 0.26), (0.5, 0.55, 0.5), "dark", "sphere")
                self.beam(p + f"/Leg{i}{j}", (x, y, 0.75), (0, y, 8), 0.25, "orange")
            self.shape(
                p + f"/LegCollision{i}", (0, y, 4.3), (0.35, 0.35, 7.3), "orange", collision=True
            )
        self.shape(p + "/Girder", (0, 15.625, 8.35), (0.65, 30.45, 0.7), "orange", collision=True)
        for x in (-0.4, 0.4):
            self.beam(
                p + "/Guard" + str(abs(x)).replace(".", "_") + ("a" if x < 0 else "b"),
                (x, 0.75, 9),
                (x, 30.5, 9),
                0.05,
                "yellow",
            )
        trolley = self.group(p + "/Trolley", (0, 17, 0))
        self.shape(str(trolley.GetPath()) + "/Body", (0, 0, 8.85), (1.1, 1.2, 0.3), "blue")
        self.group(p + "/Trolley/Hook", (0, 0, 4.8))
        self.shape(p + "/Trolley/Hook/Block", (0, 0, 0), (0.4, 0.35, 0.4), "yellow")
        for i, y in enumerate((-1.2, 1.2)):
            self.shape(p + f"/Trolley/Hook/Bar{i}", (0, y, -0.4), (5.8, 0.12, 0.18), "yellow")
        for i, x in enumerate((-2.8, 2.8)):
            self.shape(p + f"/Trolley/Hook/Cross{i}", (x, 0, -0.4), (0.12, 2.6, 0.18), "yellow")
            for j, y in enumerate((-1.2, 1.2)):
                self.beam(p + f"/Trolley/Hook/Bridle{i}{j}", (0, 0, 0), (x, y, -0.4), 0.04, "dark")
                self.beam(
                    p + f"/Trolley/Hook/Sling{i}{j}", (x, y, -0.4), (x, y, -0.6), 0.035, "dark"
                )
        self.beam(p + "/Trolley/Rope", (0, 0, 8.7), (0, 0, 4.8), 0.055, "dark")
        self.label(p + "/Capacity", "CR1 / 12T / OPERATED", (-2, 28, 0.04), 0.23, "orange")

    def set_crane(self, position, load_height=3.2, footprint=(6, 3)):
        x, y, z = position
        p = self.mapping["CR1"]
        self.set_position(p, (x, 0, 0))
        self.set_position(p + "/Trolley", (0, y, 0))
        hook = z + load_height + 0.6
        self.set_position(p + "/Trolley/Hook", (0, 0, hook))
        rope = UsdGeom.Xformable(self.stage.GetPrimAtPath(p + "/Trolley/Rope"))
        ops = rope.GetOrderedXformOps()
        ops[0].Set(Gf.Vec3d(0, 0, (8.7 + hook) / 2))
        ops[-1].Set(Gf.Vec3f(0.055, 0.055, 8.7 - hook))
        # Original adjustable spreader A: stays within the declared load footprint.
        hx, hy = footprint[0] / 2 - 0.2, footprint[1] / 2 - 0.3
        hp = p + "/Trolley/Hook"
        for i, y in enumerate((-hy, hy)):
            bar = UsdGeom.Xformable(self.stage.GetPrimAtPath(hp + f"/Bar{i}"))
            bar.GetOrderedXformOps()[0].Set(Gf.Vec3d(0, y, -0.4))
            bar.GetOrderedXformOps()[1].Set(Gf.Vec3f(footprint[0] - 0.2, 0.12, 0.18))
        for i, x in enumerate((-hx, hx)):
            cross = UsdGeom.Xformable(self.stage.GetPrimAtPath(hp + f"/Cross{i}"))
            cross.GetOrderedXformOps()[0].Set(Gf.Vec3d(x, 0, -0.4))
            cross.GetOrderedXformOps()[1].Set(Gf.Vec3f(0.12, 2 * hy + 0.2, 0.18))
            for j, y in enumerate((-hy, hy)):
                for name, start, end in (
                    (f"Bridle{i}{j}", (0, 0, 0), (x, y, -0.4)),
                    (f"Sling{i}{j}", (x, y, -0.4), (x, y, -0.6)),
                ):
                    obj = UsdGeom.Xformable(self.stage.GetPrimAtPath(hp + "/" + name))
                    delta = Gf.Vec3d(*end) - Gf.Vec3d(*start)
                    op = obj.GetOrderedXformOps()
                    op[0].Set(Gf.Vec3d(*[(a + b) / 2 for a, b in zip(start, end)]))
                    op[1].Set(Gf.Quatf(Gf.Rotation(Gf.Vec3d(0, 0, 1), delta).GetQuat()))
                    op[2].Set(Gf.Vec3f(0.035, 0.035, delta.GetLength()))

    def robot(self, p):
        self.attr(
            self.stage.GetPrimAtPath(p),
            "qualification",
            "HR_MODE_DISABLED / QUALIFICATION_UNVERIFIED",
        )
        self.shape(p + "/Base", (0, 0, -0.2), (0.6, 0.6, 0.4), "dark", collision=True)
        self.joint_paths = []
        parent = p
        for i, (axis, link) in enumerate(zip(AXES, LINKS)):
            joint = self.group(parent + f"/Joint{i + 1}")
            getattr(joint, "AddRotate" + axis + "Op")().Set(self.state.joints[i])
            jp = str(joint.GetPath())
            self.joint_paths.append(jp)
            self.attr(joint.GetPrim(), "jointAxis", axis)
            self.shape(jp + "/Housing", (0, 0, 0), (0.26, 0.26, 0.26), "dark", "sphere")
            self.beam(
                jp + "/Link",
                (0, 0, 0),
                link,
                0.065 if i == 5 else 0.18,
                "light" if i == 5 else "orange",
            )
            self.beam(
                jp + "/Axis",
                (0, 0, 0),
                tuple(0.32 if k == "XYZ".index(axis) else 0 for k in range(3)),
                0.022,
                "teal",
            )
            parent = jp + "/End"
            self.group(parent, link)
        self.tcp_path = parent + "/TCP"
        self.group(self.tcp_path)
        self.shape(self.tcp_path + "/Tip", (0, 0, 0), (0.08, 0.08, 0.08), "yellow", "sphere")
        self.shape(p + "/Controller", (-1, 0, 0.15), (0.55, 0.5, 1.3), "light", collision=True)
        self.shape(p + "/DedicatedPower", (-1, 0.7, 0), (0.55, 0.5, 1), "blue")
        self.attr(
            self.stage.GetPrimAtPath(p + "/DedicatedPower"),
            "mappingAssumption",
            "R1_SUBASSEMBLY_NOT_WELD1",
        )
        self.label(p + "/Mode", "GEOMETRY DEMO / HR DISABLED", (-2, 0.8, -0.46), 0.21, "yellow")
        radius = sum(math.dist((0, 0, 0), link) for link in LINKS)
        for i in range(48):
            a, b = math.tau * i / 48, math.tau * (i + 1) / 48
            self.beam(
                p + f"/ReachBound/Arc{i}",
                (radius * math.cos(a), radius * math.sin(a), -0.45),
                (radius * math.cos(b), radius * math.sin(b), -0.45),
                0.025,
                "teal",
            )
        self.attr(self.stage.GetPrimAtPath(p), "reachBoundMetres", radius)
        self.attr(
            self.stage.GetPrimAtPath(p),
            "wholeFrameCoverage",
            "NOT_QUALIFIED_FAR_FACE_OUTSIDE_BOUND",
        )

    def set_joints(self, angles):
        from .model import robot_check

        robot_check(angles)
        for path, angle in zip(self.joint_paths, angles, strict=True):
            UsdGeom.Xformable(self.stage.GetPrimAtPath(path)).GetOrderedXformOps()[1].Set(angle)
        self.state.joints = list(angles)

    def people(self):
        roles = self.state.phase["people"] if self.state.phase else []
        for i, person in enumerate(self.config["people"]):
            name = person["id"]
            position = person_home(i)
            if name in roles:
                position = (13.5, 9.3 + roles.index(name) * 0.7, 0)
            p = "/World/People/" + key(name)
            root = self.group(p, position, name)
            self.attr(
                root.GetPrim(), "laborState", "WORK" if name in roles else "UNASSIGNED_NOT_REST"
            )
            self.shape(p + "/Torso", (0, 0, 1.15), (0.42, 0.25, 0.6), "blue", "capsule")
            self.shape(p + "/Vest", (0, -0.14, 1.15), (0.43, 0.035, 0.38), "orange")
            self.shape(p + "/Head", (0, 0, 1.65), (0.25, 0.25, 0.3), "wood", "sphere")
            self.shape(p + "/Helmet", (0, 0, 1.81), (0.3, 0.3, 0.13), "yellow", "sphere")
            for j, x in enumerate((-0.13, 0.13)):
                self.beam(p + f"/Leg{j}", (x, 0, 0.15), (x, 0, 0.88), 0.14, "dark")
                self.beam(p + f"/Arm{j}", (x * 2, 0, 1.42), (x * 2, -0.08, 0.95), 0.12, "blue")
            proxy = self.shape(
                p + "/Collision", (0, 0, 0.95), (0.6, 0.6, 1.3), "red", "capsule", True
            )
            proxy.CreateVisibilityAttr("invisible")
            self.label(p + "/Role", name, (-0.3, -0.65, 0.035), 0.2, "yellow")

    def frame(self, p, z=0):
        for i, y in enumerate((-1.4, 1.4)):
            self.shape(p + f"/Long{i}", (0, y, z + 0.1), (6, 0.2, 0.2), "steel")
        for i, x in enumerate((-2.9, 2.9)):
            self.shape(p + f"/End{i}", (x, 0, z + 0.1), (0.2, 2.6, 0.2), "steel")
        for i, x in enumerate((-2, -1, 0, 1, 2)):
            self.shape(p + f"/Joist{i}", (x, 0, z + 0.09), (0.08, 2.6, 0.16), "light")

    def entities(self):
        product = self.state.product_id
        if product not in self.state.entities:
            logical = self.group("/World/Entities/" + key(product), domain_id=product)
            self.attr(logical.GetPrim(), "state", "UNASSEMBLED_NO_BODY")
        for name, entity in self.state.entities.items():
            p = "/World/Entities/" + key(name)
            root = self.group(p, entity["position"], name)
            for k, v in entity.items():
                if k != "position":
                    self.attr(root.GetPrim(), k, v)
            kind = entity["kind"]
            if kind in ("BOTTOM", "TOP"):
                if self.fixture == "initial":
                    for i in range(4):
                        self.shape(
                            p + f"/RawStock{i}", (0, (i - 1.5) * 0.2, 0.1), (6, 0.16, 0.2), "steel"
                        )
                    self.attr(root.GetPrim(), "fabricationState", "RAW_COMPONENT_BATCH")
                    size = (6, 0.8, 0.2)
                else:
                    self.frame(p)
                    size = (6, 3, 0.2)
            elif kind == "COLUMNS":
                for i, (x, y) in enumerate(((-0.5, -0.5), (0.5, -0.5), (-0.5, 0.5), (0.5, 0.5))):
                    self.shape(p + f"/Column{i}", (x, y, 1.4), (0.18, 0.18, 2.8), "steel")
                size = (1.6, 1.6, 2.8)
            else:
                self.frame(p + "/Bottom")
                self.frame(p + "/Top", 3)
                for i, (x, y) in enumerate(((-2.9, -1.4), (2.9, -1.4), (-2.9, 1.4), (2.9, 1.4))):
                    self.shape(p + f"/Column{i}", (x, y, 1.6), (0.2, 0.2, 2.8), "steel")
                size = (6, 3, 3.2)
                if self.fixture != "structure":
                    self.interior(p, self.fixture == "sr_w2")
            proxy = self.shape(p + "/Occupancy", (0, 0, size[2] / 2), size, "red", collision=True)
            proxy.CreateVisibilityAttr("invisible")
            self.attr(proxy.GetPrim(), "role", "CONSERVATIVE_OCCUPANCY_NOT_LOAD_DYNAMICS")
        # After merge, components map to lineage subroots, not independent bodies.
        if product in self.state.entities:
            p = self.mapping[product]
            for suffix, sub in (
                ("BOTTOM", "Bottom"),
                ("TOP", "Top"),
                ("COLUMNS", "ColumnsLineage"),
            ):
                path = p + "/" + sub
                prim = self.stage.GetPrimAtPath(path)
                if not prim:
                    prim = self.group(path).GetPrim()
                self.mapping[product + "." + suffix] = path
                self.attr(prim, "domainId", product + "." + suffix)
                self.attr(prim, "consumedInto", product)

    def interior(self, p, extra):
        self.shape(p + "/B_FL/Subfloor", (0, 0, 0.25), (5.6, 2.6, 0.1), "light")
        for i, x in enumerate((-2, -1, 0, 1, 2)):
            self.shape(p + f"/B_FL/PanelSeam{i}", (x, 0, 0.307), (0.015, 2.6, 0.008), "dark")
        # Cutaway south wall: visible state is independent of collision occupancy.
        self.shape(p + "/B_EN/North", (0, 1.34, 1.65), (5.6, 0.12, 2.7), "white")
        self.shape(p + "/B_EN/Insulation", (0, 1.425, 1.65), (5.6, 0.045, 2.7), "yellow")
        self.shape(p + "/B_EN/Cladding", (0, 1.46, 1.65), (5.6, 0.025, 2.7), "blue")
        east = self.shape(p + "/B_EN/East", (2.84, 0, 1.65), (0.12, 2.6, 2.7), "light")
        if self.fixture in ("mep_wait", "sr_w2"):
            east.CreateVisibilityAttr("invisible")
        self.shape(p + "/B_EN/WestLow", (-2.84, 0, 0.7), (0.12, 2.6, 0.8), "light")
        self.shape(p + "/B_EN/Window", (-2.83, 0, 1.9), (0.14, 1.5, 1.4), "blue")
        wall = self.shape(p + "/B_EN/South", (0, -1.34, 1.65), (5.6, 0.12, 2.7), "white")
        wall.CreateVisibilityAttr("invisible")
        self.shape(p + "/B_WT/WetTray", (2, -0.75, 0.33), (1.8, 1.25, 0.045), "water")
        for i, x in enumerate((1.2, 1.6, 2, 2.4, 2.8)):
            self.shape(p + f"/B_WT/TileX{i}", (x, -0.75, 0.359), (0.015, 1.25, 0.006), "white")
        for i, y in enumerate((-1.2, -0.8, -0.4)):
            self.shape(p + f"/B_WT/TileY{i}", (2, y, 0.359), (1.8, 0.015, 0.006), "white")
        self.shape(p + "/B_FI/Partition", (0.95, 0, 1.55), (0.09, 2.5, 2.5), "light")
        self.shape(p + "/B_FI/WetDoor", (0.88, 0.5, 1.35), (0.05, 0.7, 2.1), "wood")
        self.shape(p + "/B_FI/EntryDoor", (-1.9, -1.3, 1.35), (0.85, 0.07, 2.1), "wood")
        self.shape(p + "/B_FI/CeilingCutaway", (0, 0.95, 2.95), (5.6, 0.65, 0.05), "white")
        self.shape(p + "/B_FI/Cabinet", (-1.8, 0.9, 0.75), (1.6, 0.5, 0.9), "wood")
        self.shape(p + "/B_FI/Counter", (-1.8, 0.9, 1.22), (1.7, 0.58, 0.06), "white")
        self.shape(p + "/B_FI/Basin", (2.3, 0.75, 0.94), (0.6, 0.5, 0.25), "white")
        self.shape(p + "/B_FI/Vanity", (2.3, 0.75, 0.59), (0.5, 0.45, 0.5), "wood")
        self.shape(p + "/B_FI/ToiletBase", (2.3, -0.8, 0.45), (0.3, 0.4, 0.2), "white")
        self.shape(p + "/B_FI/Toilet", (2.3, -0.8, 0.65), (0.5, 0.7, 0.4), "white", "sphere")
        self.beam(p + "/B_FI/ShowerRiser", (2.72, -0.7, 0.6), (2.72, -0.7, 2.5), 0.04, "light")
        self.shape(
            p + "/B_FI/ShowerHead", (2.65, -0.7, 2.5), (0.22, 0.22, 0.04), "light", "cylinder"
        )
        self.shape(p + "/B_ME/VentInterface", (2.72, 0.65, 2.6), (0.14, 0.4, 0.3), "dark")
        self.shape(p + "/B_WT/MembraneEdge", (2, -1.38, 0.4), (1.8, 0.04, 0.15), "teal")
        self.beam(p + "/B_ME/WaterMain", (-2.6, 1.12, 0.5), (2.5, 1.12, 0.5), 0.065, "blue")
        self.beam(p + "/B_ME/Drain", (2.5, -0.8, 0.4), (2.5, 1.12, 0.4), 0.10, "dark")
        self.beam(p + "/B_ME/Riser", (2.5, 1.12, 0.5), (2.5, 1.12, 1), 0.06, "blue")
        self.shape(p + "/B_ME/CableTray", (0, 1.1, 2.7), (5.4, 0.15, 0.09), "yellow")
        self.shape(p + "/B_ME/Distribution", (-2.5, 1.22, 1.9), (0.4, 0.13, 0.6), "dark")
        for i, x in enumerate((-2, -0.4, 1.7)):
            self.shape(p + f"/B_ME/Socket{i}", (x, 1.265, 1.1), (0.13, 0.04, 0.16), "white")
        if extra:
            self.shape(p + "/B_FI/ExtraBasin", (1.45, 0.75, 0.94), (0.5, 0.5, 0.25), "teal")
            self.beam(p + "/B_ME/ExtraBranch", (1.45, 1.12, 0.5), (1.45, 0.75, 0.95), 0.06, "blue")
            self.shape(p + "/B_ME/ExtraSocket", (1.45, 1.265, 1.35), (0.2, 0.04, 0.16), "yellow")
        if self.fixture == "outbound":
            self.shape(p + "/B_PR/RainCover", (0, 0, 3.17), (5.65, 2.65, 0.04), "teal")
            self.shape(p + "/B_PR/InteriorProtection", (-1.4, 0, 0.325), (2.2, 2.4, 0.018), "wood")
            for i, x in enumerate((-2.7, 2.7)):
                self.shape(p + f"/B_PR/CornerGuard{i}", (x, -1.45, 1.6), (0.22, 0.1, 3.2), "yellow")
        for i, name in enumerate(("D-E", "W-P", "WET", "DRY", "CEIL", "EXT")):
            face = self.group("/World/Faces/" + key(name))
            self.attr(face.GetPrim(), "face", name)
            self.attr(face.GetPrim(), "parallelPermission", "UNKNOWN_CLOSED")
            self.attr(face.GetPrim(), "occupied", name in self.state.faces)
        self.label(
            p + "/WetLabel",
            "WET / TEST1 HELD" if self.state.faces else "QUALITY UNKNOWN",
            (-2.7, -2.2, -0.55),
            0.22,
            "yellow",
        )

    def cameras(self):
        specs = {
            "Overview": ((75, -80, 85), (15, 18, 1)),
            "Supply": ((14, -34, 45), (-6, 17, 0)),
            "PRE": ((-8, -2, 16), (2, 8, 0.5)),
            "Crossing": ((38, -4, 32), (26, 17, 0.8)),
            "Weld": ((37, -10, 32), (23, 12, 1)),
            "Top": ((16, 18, 175), (16, 18, 0)),
            "J2": ((26, -7, 20), (16, 9, 0.7)),
            "J3": ((49, -4, 17), (36, 10, 1)),
            "F1": ((44, 10, 12), (36, 24, 1.2)),
            "Gantry": ((72, -65, 55), (36, 16, 0)),
            "Rigging": ((42, 18, 8), (36, 24, 4.2)),
            "Robot": ((25, 6, 5), (21.6, 10, 1.3)),
            "Q1": ((33, 14, 10), (26, 24, 1)),
            "OUT1": ((23, 14, 10), (16, 24, 1)),
        }
        for name, (eye, target) in specs.items():
            camera = UsdGeom.Camera.Define(self.stage, "/World/Cameras/" + name)
            up = Gf.Vec3d(0, 1, 0) if name == "Top" else Gf.Vec3d(0, 0, 1)
            view = Gf.Matrix4d().SetLookAt(Gf.Vec3d(*eye), Gf.Vec3d(*target), up)
            camera.AddTransformOp().Set(view.GetInverse())
            camera.CreateFocalLengthAttr(
                28
                if name
                in ("Overview", "J2", "J3", "F1", "Q1", "OUT1", "Supply", "PRE", "Crossing", "Weld")
                else 35
            )
            camera.CreateClippingRangeAttr(Gf.Vec2f(0.1, 300))
            hp = str(camera.GetPath()) + "/HUD"
            self.group(hp)
            self.shape(hp + "/Background", (0, -0.29, -2.02), (1.13, 0.085, 0.002), "hud_dark")
            self.label(
                hp + "/Disclosure",
                "S13 SYNTHETIC / GEOMETRY ONLY",
                (-0.54, -0.28, -2),
                0.017,
                "hud_white",
            )
            self.label(
                hp + "/State",
                name.upper() + " / QUALITY UNKNOWN / HR DISABLED",
                (-0.54, -0.315, -2),
                0.015,
                "hud_yellow",
            )
            UsdGeom.Imageable(self.stage.GetPrimAtPath(hp)).MakeInvisible()

    def mapping_check(self):
        expected = {
            r["id"]
            for group in ("resources", "people", "products", "components")
            for r in self.config[group]
        }
        ids = [
            p.GetAttribute("s13:domainId").Get()
            for p in self.stage.Traverse()
            if p.HasAttribute("s13:domainId")
        ]
        if set(ids) != expected or len(ids) != len(expected) or set(self.mapping) != expected:
            raise ValueError("USD_MAPPING_NOT_BIJECTIVE")
        for name, classification in EQUIPMENT.items():
            if (
                self.stage.GetPrimAtPath(self.mapping[name])
                .GetAttribute("s13:classification")
                .Get()
                != classification
            ):
                raise ValueError("USD_EQUIPMENT_CLASSIFICATION:" + name)
        return {
            "domain_ids": len(ids),
            "prims": sum(1 for _ in self.stage.Traverse()),
            "colliders": sum(p.HasAPI(UsdPhysics.CollisionAPI) for p in self.stage.Traverse()),
        }

    def reset(self, fixture=None):
        if fixture:
            self.fixture = fixture
        self.build()
