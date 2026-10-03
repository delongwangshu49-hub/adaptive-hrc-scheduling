"""USD binding and actual readback for scene-only continuous rehearsals."""

import math

from pxr import Gf, UsdGeom

from .inspection import obstacles
from .layout import local, world
from .model import require
from .trials import Rehearsal


class TrialScene:
    def __init__(self, scene, trial="T1"):
        self.scene = scene
        self.load(trial)

    def load(self, trial):
        self.run = Rehearsal(trial, [p["id"] for p in self.scene.config["people"]])
        scene = self.scene
        scene.reset(self.run.fixture)
        scene.attr(scene.stage.GetPrimAtPath("/World"), "trial", trial)
        if trial == "T1":
            root = scene.stage.GetPrimAtPath(scene.mapping["PRODUCT-1.BOTTOM"])
            scene.attr(root, "sceneBatchId", "SCN-T1-BATCH-BOTTOM")
            scene.attr(root, "materialStatus", "DISPLAY_RELEASED_NOT_INVENTORY_EVENT")
        if trial == "T4":
            scene.interior(scene.mapping["PRODUCT-1"], True)

        scene.attr(scene.stage.GetPrimAtPath("/World"), "timeline", "RESET_ON_TRIAL_CHANGE")
        self.paths = dict(scene.mapping)
        self.paths["SCN-EMPTY-HOOK"] = "/World/Trial/EmptyHookReadback"
        scene.group(self.paths["SCN-EMPTY-HOOK"])
        scene.attr(
            scene.stage.GetPrimAtPath(self.paths["SCN-EMPTY-HOOK"]), "sceneId", "SCN-EMPTY-HOOK"
        )
        if trial == "T3":
            p = "/World/Trial/MepBatch"
            self.paths["SCN-MEP-BATCH"] = p
            scene.group(p)
            scene.shape(p + "/Carrier", (0, 0, 0.1), (1.2, 0.8, 0.2), "teal", collision=True)
            scene.shape(p + "/Contents", (0, 0, 0.45), (1, 0.6, 0.5), "wood", collision=True)
            scene.attr(scene.stage.GetPrimAtPath(p), "sceneId", "SCN-MEP-BATCH")
            scene.attr(scene.stage.GetPrimAtPath(p), "equipmentChoice", "UNKNOWN_SCENE_CARRIER")
        if trial == "T4":
            p = "/World/Trial/Product2"
            self.paths["SCN-PRODUCT-2"] = p
            scene.group(p)
            scene.frame(p + "/Bottom")
            scene.frame(p + "/Top", 3)
            for i, (x, y) in enumerate(((-2.9, -1.4), (2.9, -1.4), (-2.9, 1.4), (2.9, 1.4))):
                scene.shape(p + f"/Column{i}", (x, y, 1.6), (0.2, 0.2, 2.8), "teal")
            proxy = scene.shape(p + "/Occupancy", (0, 0, 1.6), (6, 3, 3.2), "red", collision=True)
            proxy.CreateVisibilityAttr("invisible")
            scene.label(p + "/Label", "SCN PRODUCT 2", (-2, -2, 0.03), 0.3, "teal")
            scene.attr(scene.stage.GetPrimAtPath(p), "sceneId", "SCN-PRODUCT-2")
            scene.attr(scene.stage.GetPrimAtPath(p), "mapping", "SECOND_PRODUCT_SPACE_WITNESS_ONLY")
        # A scene inspection overrides the fixture's positions without pretending
        # that the frozen production state has executed these moves.
        for name, pos in self.run.positions.items():
            if name in self.paths:
                scene.set_position(self.paths[name], pos)
        scene.attr(
            scene.stage.GetPrimAtPath("/World"),
            "stateAuthority",
            "TRIAL_READBACK_NOT_FIXTURE_SNAPSHOT",
        )
        if trial in ("T2", "T4"):
            scene.set_crane((36, 10, 0.6))
        self.fault = None
        self.trace = []
        self._bounds = None
        self._bound_index = None
        self.readback()

    def restart(self):
        """Explicit same-trial reset without rebuilding immutable scene geometry."""
        self.clear_fault()
        self.run.reset()
        for name, pos in self.run.positions.items():
            if name in self.paths:
                self.scene.set_position(self.paths[name], pos)
        if self.run.name in ("T2", "T4"):
            self.scene.set_crane((36, 10, 0.6))
        from .model import POSES

        self.scene.set_joints(POSES[0])
        hp = self.scene.mapping["HST1"]
        self.scene.set_position(hp + "/Spreader", (0, 0, 4.9))
        ops = UsdGeom.Xformable(self.scene.stage.GetPrimAtPath(hp + "/Rope")).GetOrderedXformOps()
        ops[0].Set(Gf.Vec3d(0, 0, 5.15))
        ops[-1].Set(Gf.Vec3f(0.04, 0.04, 0.5))
        for name in ("WELD1", "CR1", "TEST1", "HST1"):
            self.scene.attr(
                self.scene.stage.GetPrimAtPath(self.scene.mapping[name]), "owner", "NONE"
            )
        self._bounds = None
        self._bound_index = None
        self.trace = []
        self.readback()

    def bounds(self):
        a = self.run.action
        if not a:
            return []
        if self._bound_index == self.run.index and self._bounds is not None:
            return self._bounds
        ignored = [self.paths[a.actor]] if a.actor in self.paths else []
        if a.equipment:
            equipment = a.equipment.split("_")[0]
            ignored.append(self.scene.mapping[equipment])
            if equipment == "CR1":
                ignored.extend(["/World/Factory/Rail0", "/World/Factory/Rail1"])
        # Local shape-only marker has no collider; all stationary physical bodies
        # and all people, including those already moved, remain in the sweep.
        self._bounds = obstacles(self.scene, ignored)
        self._bound_index = self.run.index
        return self._bounds

    def inject(self, kind):
        self.clear_fault()
        a = self.run.action
        require(a is not None and a.points, "INJECT_REQUIRES_MOTION")
        p = (
            a.points[-1]
            if kind in ("handoff_occupied", "target_occupied", "occupied")
            else a.points[len(a.points) // 2]
        )
        path = "/World/Trial/Injected"
        if kind == "person":
            self.scene.shape(path, (p[0], p[1], 0.95), (0.6, 0.6, 1.9), "red", collision=True)
        else:
            self.scene.shape(path, (p[0], p[1], p[2] + a.height), (1, 1, 2), "red", collision=True)
        self.scene.attr(self.scene.stage.GetPrimAtPath(path), "fault", kind)
        self.fault = kind
        self._bounds = None

    def clear_fault(self):
        self.scene.stage.RemovePrim("/World/Trial/Injected")
        self.fault = None
        self._bounds = None

    def advance(self, dt, single_step=False):
        a = self.run.action
        snapshot = self.run.advance(dt, self.bounds(), single_step)
        for name, pos in self.run.positions.items():
            if name in self.paths:
                self.scene.set_position(self.paths[name], pos)
        if a and a.equipment and a.actor:
            pos = self.run.positions[a.actor]
            if a.equipment.startswith("CR1"):
                self.scene.set_crane(
                    pos, 0 if a.equipment.endswith("EMPTY") else a.size[2] - 0.6, a.size[:2]
                )
            elif a.equipment == "HST1":
                hp = self.scene.mapping["HST1"]
                self.scene.set_position(hp, (pos[0], pos[1], 0))
                end = pos[2] + a.size[2] - 0.2
                self.scene.set_position(hp + "/Spreader", (0, 0, end))
                ops = UsdGeom.Xformable(
                    self.scene.stage.GetPrimAtPath(hp + "/Rope")
                ).GetOrderedXformOps()
                ops[0].Set(Gf.Vec3d(0, 0, (5.4 + end) / 2))
                ops[-1].Set(Gf.Vec3f(0.04, 0.04, 5.4 - end))
        if a and a.equipment and a.actor:
            pos = self.run.positions[a.actor]
            if a.equipment.startswith("CR1"):
                height = 0 if a.equipment.endswith("EMPTY") else a.size[2] - 0.6
                actual_hook = self.scene.scene_position(self.scene.mapping["CR1"] + "/Trolley/Hook")
                require(
                    math.dist(actual_hook, (pos[0], pos[1], pos[2] + height + 0.6)) <= 0.01,
                    "CR1_HOOK_READBACK",
                )
            elif a.equipment == "HST1":
                actual_spreader = self.scene.scene_position(
                    self.scene.mapping["HST1"] + "/Spreader"
                )
                require(
                    math.dist(actual_spreader, (pos[0], pos[1], pos[2] + a.size[2] - 0.2)) <= 0.01,
                    "HST1_SPREADER_READBACK",
                )
        for name in ("WELD1", "CR1", "TEST1", "HST1"):
            self.scene.attr(
                self.scene.stage.GetPrimAtPath(self.scene.mapping[name]),
                "owner",
                self.run.owners.get(name, "NONE"),
            )
        snapshot["actual_world_positions"] = self.readback()
        snapshot["action"] = a.label if a else "COMPLETE"
        self.trace.append(snapshot)
        return snapshot

    def readback(self):
        actual = {}
        for name, pos in self.run.positions.items():
            if name not in self.paths:
                continue
            read = self.scene.world_position(self.paths[name])
            require(math.dist(world(pos), read) <= 0.01, "TRIAL_USD_READBACK:" + name)
            actual[name] = read
        for name, path in (
            ("R1-TCP", self.scene.tcp_path),
            ("HST1-SPREADER", self.scene.mapping["HST1"] + "/Spreader"),
            ("CR1-HOOK", self.scene.mapping["CR1"] + "/Trolley/Hook"),
        ):
            actual[name] = self.scene.world_position(path)
        return actual

    def set_layers(self, layer, visible):
        if layer == "roles":
            paths = [p + "/Role" for k, p in self.scene.mapping.items() if k in self.run.people]
        elif layer == "routes":
            paths = ["/World/Routes"]
        elif layer == "envelopes":
            paths = [
                str(p.GetPath())
                for p in self.scene.stage.Traverse()
                if p.GetName() in ("Occupancy", "Collision")
            ]
        else:
            raise ValueError("UNKNOWN_LAYER")
        for path in paths:
            obj = UsdGeom.Imageable(self.scene.stage.GetPrimAtPath(path))
            obj.MakeVisible() if visible else obj.MakeInvisible()
        return {"layer": layer, "visible": visible, "paths": len(paths)}


def check_person_routes(scene, app, capture=None):
    """All 15 routes checked independently; concurrent walking is a later task."""
    from .layout import PERSON_STATIONS, person_home, person_path
    from .model import sweep

    scene.reset("mep_wait")
    records = []
    for i, person in enumerate(scene.config["people"]):
        name = person["id"]
        for j, p in enumerate(scene.config["people"]):
            scene.set_position(scene.mapping[p["id"]], person_home(j))
        points = person_path(i, PERSON_STATIONS[name])
        obs = obstacles(scene, [scene.mapping[name]])
        sweep([(x, y, z + 0.95) for x, y, z in points], (0.6, 0.6, 1.9), obs)
        samples = []
        for start, end in zip(points, points[1:]):
            for k in range(25):
                pos = tuple(a + (b - a) * k / 24 for a, b in zip(start, end))
                scene.set_position(scene.mapping[name], pos)
                read = scene.world_position(scene.mapping[name])
                require(math.dist(local(read), pos) < 0.001, "PERSON_READBACK")
                samples.append(read)
                if capture and name == "E1" and start[0] == -1 and end[0] > 30 and k == 12:
                    capture("person_crossing", "Crossing")
            app.update()
        records.append(
            {
                "person": name,
                "points_local": points,
                "samples_world": samples,
                "obstacles": len(obs),
                "crossing": "CR1_IDLE_ONLY",
            }
        )
    return records
