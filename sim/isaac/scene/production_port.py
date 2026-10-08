"""Command-driven USD kinematic execution with live geometric readback.

This port is an S15 mechanism witness, not a rigid-body dynamics or industrial
qualification model. It reuses the original target geometry, not its trial script.
"""

import json
from types import SimpleNamespace

from pxr import Gf, UsdGeom, UsdPhysics

from adaptive_hrc_scheduling.contracts.codec import as_data, decode, require
from adaptive_hrc_scheduling.domain import production as m
from adaptive_hrc_scheduling.logistics_geometry import (
    close,
    interpolate,
    motion_fraction,
)
from adaptive_hrc_scheduling.production_geometry import (
    FORK_OPERATOR_DY,
    standing_point,
    validate_service,
)
from adaptive_hrc_scheduling.production_pedestrians import fork_walk_phases, walk_yaw
from adaptive_hrc_scheduling.production_supports import RACK_POST_X

from .model import key
from .production_support_port import SupportPort
from .target_layout import PERSON_SIZE, check_crane_structure, check_route


class USDProductionPort:
    def __init__(self, scene):
        self.scene = scene

    def reset(self, config, run_id, epoch):
        self.config, self.run_id, self.epoch = config, run_id, epoch
        self.scene.build()
        self.scene.stage.RemovePrim("/World/Loads")
        self.scene.stage.RemovePrim("/World/S15")
        for ident in tuple(self.scene.run.kinds):
            self.scene.mapping.pop(ident, None)
        aliases = {
            "FORK-01": "SCN-FORK-01",
            "CART-01": "SCN-CART-01",
            "WELD-J2": "SCN-WELD-J2",
            "WELD-J3": "SCN-WELD-J3",
        }
        for ident, old in aliases.items():
            self.scene.mapping[ident] = self.scene.mapping[old]
        self.mapping = self.scene.mapping
        # Keep the operator clear of the retracted transfer tray while retaining
        # the real handle contact and every existing collision-enabled part.
        self.scene.set_position(self.mapping["CART-01"] + "/Handle", (0, -0.85, 1.1))
        self.scene.set_position(self.mapping["CART-01"] + "/HandlePost", (0, -0.85, 0.65))
        for name in ("Mast0", "Mast1", "Guard", "Controls", "Forks/Tine0", "Forks/Tine1"):
            UsdPhysics.CollisionAPI.Apply(
                self.scene.stage.GetPrimAtPath(self.mapping["FORK-01"] + "/" + name)
            )
        for name in (
            "Handle",
            "HandlePost",
            "Tray",
            "TransferTray",
            "Wheel00",
            "Wheel01",
            "Wheel10",
            "Wheel11",
        ):
            UsdPhysics.CollisionAPI.Apply(
                self.scene.stage.GetPrimAtPath(self.mapping["CART-01"] + "/" + name)
            )
        for name in (
            "Handle",
            "HandlePost",
            "Tray",
            "Meter",
            "Display",
            "Wheel00",
            "Wheel01",
            "Wheel10",
            "Wheel11",
        ):
            UsdPhysics.CollisionAPI.Apply(
                self.scene.stage.GetPrimAtPath(self.mapping["TEST1"] + "/" + name)
            )
        self.ops = {o.id: o for o in config.operations}
        self.routes = {r.id: r for r in config.routes}
        self.places = {p.id: p.position for p in config.places}
        self.loads = {x.id: x for x in (*config.lots, *config.entities)}
        # S15 bounded steel racks retain the original trestles, moved to the
        # outer support lines so the declared short-pack fork approaches fit.
        for name in ("RECEIVE", "STEEL", "PRE-IN", "PRE-OUT"):
            x, y, z = self.places[name]
            for index, dx in enumerate((-2.7, 2.7)):
                self.scene.set_position(
                    "/World/Static/" + key(name + "-support-" + str(index)),
                    (x + dx, y + 0.8, z / 2),
                )
        # Retain the original four material-rack posts inside the approved
        # SC01 attachment area, clear of movable contact bars.
        for name in ("MEP-RECEIVE", "MEP-STORE", "KIT", "F1-KIT"):
            x, y, z = self.places[name]
            for index, dx in enumerate((-RACK_POST_X, RACK_POST_X)):
                self.scene.set_position(
                    "/World/Static/" + key(name + "-support-" + str(index)),
                    (x + dx, y + 0.8, z / 2),
                )
        self.support_aliases = {}
        support_positions = {}
        self.variable_ports = {
            c.place_id for layout in config.support_layouts for c in layout.contacts
        }
        for place in config.places:
            if place.parent is None or place.id in self.variable_ports:
                continue
            if place.parent == "J3" and place.id.endswith((".TOP", ".COLUMNS")):
                continue
            point = tuple(place.position)
            self.support_aliases[place.id] = support_positions.setdefault(point, place.id)
            if self.support_aliases[place.id] != place.id:
                continue
            x, y, z = place.position
            if place.parent == "PRE-OUT" and place.id.endswith(".COLUMNS"):
                y += 0.7
            spread = (
                0.2
                if place.id.startswith("PRE-IN.") and place.id.endswith(".ST-C.04.NET")
                else 0.45
            )
            for index, dx in enumerate((-spread, spread)):
                ident = place.id + "-support-" + str(index)
                self.scene.shape(
                    "/World/Static/" + key(ident),
                    (x + dx, y, z - 0.02),
                    (0.06, 0.5, 0.04),
                    "light",
                    collision=True,
                )
                self.scene.attr(
                    self.scene.stage.GetPrimAtPath("/World/Static/" + key(ident)),
                    "obstacleId",
                    ident,
                )

        self.devices = {d.id: d for d in config.devices}
        self.people = {p.id for p in config.people}
        self.running = {}
        self.expected = {}
        self.attached = set()
        self.samples = []
        self.receiver_receipts = {}
        self.material_done = set()
        self.input_samples = {}
        self.support_port = SupportPort(self)
        self.quantities = {x.id: x.quantity if x.arrived else 0 for x in config.lots}
        for x in self.loads.values():
            path = "/World/S15/Loads/" + key(x.id)
            self.scene.ident(x.id, path, (-30, 0, 0))
            self.scene.shape(
                path + "/Envelope", (0, 0, x.size_m[2] / 2), x.size_m, "steel", collision=True
            )
            if x.initial_location in self.places:
                self.put(x.id, self.places[x.initial_location])
            if x.id in self.quantities:
                self.scene.attr(self.prim(x.id), "s15Quantity", self.quantities[x.id])
        for d in config.devices:
            if d.kind in ("FIXED", "FIXTURE"):
                self.expected[d.id] = self.position(d.id)
            else:
                size = next(
                    (
                        x.size_m
                        for x in self.loads.values()
                        if x.initial_location == d.initial_location
                    ),
                    (6, 3, 0.2),
                )
                if d.id == "CR1" and d.initial_location == "CRANE-PARK":
                    self.put("CR1-HOOK", self.places[d.initial_location])
                    self.put("CR1", (30, 0, 0))
                else:
                    self.carrier(d.id, self.places[d.initial_location], size, empty=True)
            self.scene.attr(self.prim(d.id), "s15Available", True)
        for p in config.person_positions:
            point = standing_point(config, p.person_id, p.location)
            if p.person_id == "P1" and p.location == self.devices["FORK-01"].initial_location:
                v = self.position("FORK-01")
                point = (v[0], v[1] + 1.8 + FORK_OPERATOR_DY, 0.2)
            if p.person_id == "E1" and p.location == self.devices["CART-01"].initial_location:
                v = self.position("CART-01")
                point = (v[0], v[1] - 1.35, 0)
            self.put(p.person_id, point)
        self.scene.attr(self.scene.stage.GetPrimAtPath("/World"), "productionDispatchEnabled", True)
        self.scene.attr(
            self.scene.stage.GetPrimAtPath("/World"), "s15Scope", "KINEMATIC_SYNTHETIC_WITNESS_ONLY"
        )

    def prim(self, ident):
        prim = self.scene.stage.GetPrimAtPath(self.mapping[ident])
        require(bool(prim), "MISSING_USD_ENTITY:" + ident)
        return prim

    def position(self, ident):
        self.prim(ident)
        return tuple(self.scene.world_position(self.mapping[ident]))

    def put(self, ident, point):
        self.prim(ident)
        self.scene.set_position(self.mapping[ident], point)
        self.expected[ident] = tuple(point)

    def check_actual(self, ident):
        require(
            ident in self.expected and close(self.position(ident), self.expected[ident]),
            "ACTUAL_POSITION_DRIFT:" + ident,
        )

    def controls_ok(self, command):
        op = self.ops[command.operation_id]
        if not op.route_id or op.action == "WALK":
            return
        device = self.routes[op.route_id].device_id
        for binding in command.roles:
            qualification = next(r.qualification for r in op.roles if r.id == binding.role_id)
            if qualification not in ("FORK", "CART", "TOOL"):
                continue
            hand = (
                UsdGeom.Xformable(self.prim(binding.person_id))
                .ComputeLocalToWorldTransform(0)
                .Transform(Gf.Vec3d(0, 0.5, 1.05))
            )
            control = self.scene.world_position(
                self.mapping[device] + ("/Controls" if qualification == "FORK" else "/Handle")
            )
            require(
                close(tuple(hand), tuple(control), 0.1), "ACTUAL_CONTROL_REACH:" + binding.person_id
            )

    def carrier(self, ident, point, size, *, empty=False):
        if ident == "CR1":
            hook = (point[0], point[1], point[2] + size[2] + 0.6)
            self.put("CR1-HOOK", hook)
            self.put("CR1", (point[0], 0, 0))
            self.scene.set_position("/World/Crane/Trolley", (0, point[1], 0))
            self.hook_visual(hook, size)
        elif ident == "FORK-01":
            self.put(ident, (point[0], point[1] - 1.8, 0))
            self.scene.set_position(self.mapping[ident] + "/Forks", (0, 0, point[2]))
        elif ident == "CART-01":
            self.put(ident, (point[0], point[1] - 1.1, 0))
            self.scene.set_position(
                self.mapping[ident] + "/TransferTray",
                (0, -0.15 if empty else 0.65, point[2] - 0.05),
            )
        else:
            self.put(ident, point)

    def hook_visual(self, hook, size=None):
        ops = UsdGeom.Xformable(
            self.scene.stage.GetPrimAtPath("/World/Crane/Trolley/Rope")
        ).GetOrderedXformOps()
        ops[0].Set(Gf.Vec3d(0, 0, (9.1 + hook[2]) / 2))
        ops[-1].Set(Gf.Vec3f(0.05, 0.05, 9.1 - hook[2]))
        if size is not None:
            UsdGeom.Xformable(
                self.scene.stage.GetPrimAtPath("/World/Hook/Rig")
            ).GetOrderedXformOps()[-1].Set(Gf.Vec3f(size[0] / 6, size[1] / 3, 1))

    def preflight(self, command):
        if command.service:
            validate_service(self.config, command.service)
            self.ops[command.operation_id] = command.service.operation
            if command.service.route:
                self.routes[command.service.route.id] = command.service.route

        op = self.ops[command.operation_id]
        if op.branch:
            expected_owner = f"ATTEMPT:{op.activity_id}:{op.attempt_index}:{op.branch.revision}"
            for resource in op.equipment:
                owner = self.prim(resource).GetAttribute("s13:s18Owner").Get()
                require(
                    owner in (None, "", expected_owner)
                    if op.unit_index == 0
                    else owner == expected_owner,
                    "ACTUAL_SIMULATION_RESOURCE_OWNER:" + resource,
                )
            if op.production_mode == "HR-seq" and op.branch.phase == "UNLOAD":
                require(
                    self.prim("R1").GetAttribute("s13:s18Stopped").Get() is True,
                    "ACTUAL_SIMULATION_STOP_NOT_CONFIRMED",
                )
        for ident in (
            *op.equipment,
            *(r.person_id for r in command.roles),
            *((op.entity_id,) if op.entity_id and not op.component_inputs else ()),
        ):
            self.check_actual(ident)
        for ident in op.equipment:
            require(
                self.prim(ident).GetAttribute("s13:s15Available").Get() is True,
                "ACTUAL_DEVICE_FAILED:" + ident,
            )
        if command.id not in self.material_done:
            self.check_inputs(op)
            self.check_outputs(op)
        if op.route_id:
            if op.entity_id in self.loads:
                for location in (op.location, op.target):
                    if location in self.variable_ports:
                        require(self.landing_supports(location), "ACTUAL_SUPPORT_LAYOUT_NOT_READY")
            self.check_path(command)
        if op.action == "SUPPORT_CHANGE" and command.id not in self.running:
            elapsed = getattr(self.support_port, "sampled", {}).get(command.resume_of, 0)
            self.support_port.check_paths(command, elapsed)

    def check_outputs(self, op):
        from adaptive_hrc_scheduling.production_geometry import output_shapes

        outputs = output_shapes(self.config, op)
        if not outputs:
            return
        consumed = {
            a.lot_id for a in op.material_inputs if a.quantity >= self.quantities[a.lot_id] - 1e-9
        }
        excluded = consumed | set(op.component_inputs) | {i for i, _, _ in outputs}
        obstacles = self.scene.actual_obstacles(excluded)
        for _, point, size in outputs:
            check_route((point, point), size, obstacles)

    def check_inputs(self, op):
        """Read every consumed object before any material effect is applied."""
        inputs = {a.lot_id: a.quantity for a in op.material_inputs}
        inputs.update({i: None for i in op.component_inputs})
        if not inputs:
            return ()
        samples = []
        cache = UsdGeom.BBoxCache(
            0, [UsdGeom.Tokens.default_], useExtentsHint=False, ignoreVisibility=True
        )
        supports = [
            p
            for p in self.scene.stage.Traverse()
            if str(p.GetPath()).startswith("/World/Static/")
            and p.HasAPI(UsdPhysics.CollisionAPI)
            and p.GetAttribute("s13:obstacleId")
            and str(p.GetAttribute("s13:obstacleId").Get()).startswith(op.location + "-support-")
        ]
        for ident, quantity in inputs.items():
            prim = self.prim(ident)
            require(prim.GetAttribute("s13:sceneId").Get() == ident, "ACTUAL_INPUT_IDENTITY")
            self.check_actual(ident)
            point = self.position(ident)
            location = next(
                (p.place_id for p in op.input_places if p.lot_id == ident),
                next(
                    (p.place_id for p in op.component_input_places if p.entity_id == ident),
                    op.location,
                ),
            )
            supports = self.landing_supports(location)
            require(close(point, self.places[location]), "ACTUAL_INPUT_NOT_AT_STATION:" + ident)
            require(
                UsdGeom.Imageable(prim).ComputeVisibility() != UsdGeom.Tokens.invisible,
                "ACTUAL_INPUT_INVISIBLE:" + ident,
            )
            size = self.loads[ident].size_m
            bounds = [cache.ComputeWorldBound(p).ComputeAlignedRange() for p in supports]
            require(
                any(
                    abs(b.GetMax()[2] - point[2]) < 0.002
                    and all(
                        b.GetMin()[axis] < point[axis] + size[axis] / 2
                        and b.GetMax()[axis] > point[axis] - size[axis] / 2
                        for axis in (0, 1)
                    )
                    for b in bounds
                ),
                "ACTUAL_INPUT_UNSUPPORTED:" + ident,
            )
            if quantity is not None:
                actual = prim.GetAttribute("s13:s15Quantity").Get()
                require(
                    isinstance(actual, (int, float))
                    and actual >= quantity - 1e-9
                    and abs(actual - self.quantities[ident]) < 1e-9,
                    "ACTUAL_INPUT_QUANTITY:" + ident,
                )
            samples.append(
                m.InputReadback(
                    ident, tuple(point), actual if quantity is not None else None, True, True
                )
            )
        return tuple(samples)

    def check_path(self, command):
        op = self.ops[command.operation_id]
        route = self.routes[op.route_id]
        mobile = [
            r.person_id
            for r in command.roles
            if op.action == "WALK"
            or next(x.qualification for x in op.roles if x.id == r.role_id)
            in ("FORK", "CART", "TOOL")
        ]
        moving = [
            op.entity_id,
            *mobile,
            *(
                ([route.device_id, "CR1-HOOK"] if route.device_id == "CR1" else [route.device_id])
                if route.device_id
                else []
            ),
        ]
        obstacles = self.scene.actual_obstacles(moving)
        points = tuple((p.x, p.y, p.z) for p in route.points)
        if op.action == "WALK" and op.entity_id in ("E1", "QA1"):
            device = "CART-01" if op.entity_id == "E1" else "TEST1"
            cart = self.position(device)
            contact = (cart[0], cart[1] + (-1.35 if device == "CART-01" else 1.25), 0)
            if any(close(p, contact) for p in (points[0], points[-1])):
                # The operator's hands contact the real handle at departure /
                # arrival. Retain every other vehicle part and the full human
                # occupancy envelope; never disable the handle's CollisionAPI.
                contacts = {
                    self.mapping[device] + "/Handle",
                    self.mapping[device] + "/HandlePost",
                }
                obstacles = [b for b in obstacles if b.name not in contacts]
        size = (
            self.loads[op.entity_id].size_m
            if op.entity_id in self.loads
            else PERSON_SIZE
            if op.entity_id in self.people
            else (0.8, 1.1, 1.2)
        )
        if op.action == "WALK" and op.entity_id == "P1":
            import math

            fork = self.position("FORK-01")
            fork = (fork[0], fork[1] + 1.8, fork[2])
            operator = (fork[0], fork[1] + FORK_OPERATOR_DY, 0.2)
            phases, turns = fork_walk_phases(
                points,
                fork,
                leaving=close(points[0], operator),
                entering=close(points[-1], operator),
                tolerance=0.002,
            )
            for index in range(len(points) - 1):
                parts, yaw = phases.get(index, ((), 0))
                contacts = {self.mapping["FORK-01"] + "/" + part for part in parts}
                check_route(
                    points[index : index + 2],
                    (1.2, 0.6, 1.9) if yaw else size,
                    [b for b in obstacles if b.name not in contacts],
                )
            for index, parts in turns.items():
                p = points[index]
                for box in obstacles:
                    if box.name in {self.mapping["FORK-01"] + "/" + part for part in parts}:
                        continue
                    low = tuple(a - s / 2 for a, s in zip(box.center, box.size))
                    high = tuple(a + s / 2 for a, s in zip(box.center, box.size))
                    dx, dy = (max(low[i] - p[i], 0, p[i] - high[i]) for i in (0, 1))
                    require(
                        not (
                            low[2] < p[2] + 1.9
                            and high[2] > p[2]
                            and math.hypot(dx, dy) < math.hypot(0.3, 0.6) - 1e-6
                        ),
                        "ACTUAL_WALK_TURN_COLLISION:" + box.name,
                    )
        elif op.action == "EMPTY_RETURN" and op.entity_id == "CR1":
            check_route(tuple((x, y, z - 0.6) for x, y, z in points), (6, 3, 0.8), obstacles)
        elif (
            not (op.action == "EMPTY_RETURN" and route.device_id in ("FORK-01", "CART-01", "TEST1"))
            and route.device_id != "TEST1"
        ):
            check_route(points, size, obstacles)
        if route.device_id == "CR1":
            require(
                all(18 <= x <= 54 and 8 <= y <= 36 for x, y, z in points), "ACTUAL_CRANE_COVERAGE"
            )
            if op.entity_id in self.loads:
                require(all(z + size[2] + 0.6 <= 8.2 for x, y, z in points), "ACTUAL_HEADROOM")
                check_route(points, (size[0], size[1], size[2] + 0.6), obstacles)
            check_crane_structure(tuple((x, y, z + size[2] + 0.6) for x, y, z in points), obstacles)
        if route.device_id == "FORK-01":
            # Sweep the standing-operator fork's actual rigid parts, not a solid
            # enclosing cuboid that incorrectly fills its open mast and cab.
            parts = [((0, -1.8, 0.14), (1.5, 2.6, 0.18)), ((0, -2.7, 1), (1.3, 0.1, 1.6))]
            parts += [((dx, -0.75, 1.25), (0.1, 0.12, 2.5)) for dx in (-0.65, 0.65)]
            for offset, dimensions in parts:
                check_route(
                    tuple(
                        (x + offset[0], y + offset[1], offset[2] - dimensions[2] / 2)
                        for x, y, z in points
                    ),
                    dimensions,
                    obstacles,
                )
            tine_y = 0.35 if op.action == "EMPTY_RETURN" else 1.55
            tine_spread = (
                0.2
                if op.entity_id in self.loads and self.loads[op.entity_id].size_m[0] < 1.5
                else 0.65
            )
            for dx in (-tine_spread, tine_spread):
                check_route(
                    tuple((x + dx, y - 1.8 + tine_y, z - 0.12) for x, y, z in points),
                    (0.12, 1.3, 0.12),
                    obstacles,
                )
        elif route.device_id in ("CART-01", "TEST1"):
            # Sweep the real cart parts, including the tray and handle. A solid
            # vehicle cuboid would fill the empty space beside this narrow cart.
            cache = UsdGeom.BBoxCache(
                0, [UsdGeom.Tokens.default_], useExtentsHint=False, ignoreVisibility=True
            )
            device = route.device_id
            base = self.position(device)
            names = (
                (
                    "Deck",
                    "Handle",
                    "HandlePost",
                    "Tray",
                    "TransferTray",
                    "Wheel00",
                    "Wheel01",
                    "Wheel10",
                    "Wheel11",
                )
                if device == "CART-01"
                else (
                    "Deck",
                    "Handle",
                    "HandlePost",
                    "Tray",
                    "Meter",
                    "Display",
                    "Wheel00",
                    "Wheel01",
                    "Wheel10",
                    "Wheel11",
                )
            )
            for name in names:
                prim = self.scene.stage.GetPrimAtPath(self.mapping[device] + "/" + name)
                bounds = cache.ComputeWorldBound(prim).ComputeAlignedRange()
                dimensions = tuple(bounds.GetSize())
                offset = tuple(v - b for v, b in zip(bounds.GetMidpoint(), base))
                cart_points = tuple(
                    (
                        x + offset[0],
                        y - (1.1 if device == "CART-01" else 0) + offset[1],
                        (0 if device == "CART-01" else z) + offset[2] - dimensions[2] / 2,
                    )
                    for x, y, z in points
                )
                if name == "TransferTray":
                    dy = -0.15 if op.action == "EMPTY_RETURN" else 0.65
                    cart_points = tuple(
                        (x, y - 1.1 + dy, z - 0.05 - dimensions[2] / 2) for x, y, z in points
                    )
                check_route(cart_points, dimensions, obstacles)
        for binding in command.roles:
            qualification = next(r.qualification for r in op.roles if r.id == binding.role_id)
            if op.action == "WALK" or qualification not in ("FORK", "CART", "TOOL"):
                continue
            dy, dz = (
                (FORK_OPERATOR_DY, 0.2)
                if qualification == "FORK"
                else (-2.45, 0)
                if qualification == "CART"
                else (1.25, 0)
            )
            check_route(tuple((p[0], p[1] + dy, dz) for p in points), PERSON_SIZE, obstacles)

    def start(self, run):
        self.running[run.command.id] = run
        op = self.ops[run.command.operation_id]
        if op.action == "SUPPORT_CHANGE":
            self.support_port.start(run)
        if op.action == "RETURN" and op.target == "EXTERNAL":
            self.input_samples[run.command.id] = self.check_inputs(op)
        for binding in run.command.roles:
            if next(r.qualification for r in op.roles if r.id == binding.role_id) == "TOOL":
                UsdGeom.Xformable(self.prim(binding.person_id)).GetOrderedXformOps()[-1].Set(180)
        self.controls_ok(run.command)
        if op.handover:
            self.scene.attr(
                self.prim("FIX-J2"), "s18Handover", json.dumps(as_data(op.handover), sort_keys=True)
            )
        if op.branch:
            for resource in op.equipment:
                prim = self.prim(resource)
                self.scene.attr(prim, "s18Definition", op.branch.definition_id)
                self.scene.attr(prim, "s18Revision", op.branch.revision)
                self.scene.attr(prim, "s18Output", op.branch.output_revision)
                self.scene.attr(prim, "s18Assumption", op.branch.assumption_revision)
                self.scene.attr(prim, "s18JointSet", op.branch.joint_set_id)
                self.scene.attr(prim, "s18Phase", op.branch.phase)
                self.scene.attr(prim, "s18Terminal", op.branch.terminal)
                self.scene.attr(
                    prim,
                    "s18Owner",
                    f"ATTEMPT:{op.activity_id}:{op.attempt_index}:{op.branch.revision}",
                )
            if op.production_mode == "HR-seq" and op.branch.phase != "UNLOAD":
                self.scene.attr(self.prim("R1"), "s18Stopped", op.branch.phase != "ROBOT")
        if op.route_id and self.routes[op.route_id].device_id == "FORK-01":
            tine_spread = (
                0.2
                if op.entity_id in self.loads and self.loads[op.entity_id].size_m[0] < 1.5
                else 0.65
            )
            tine_y = 0.35 if op.action == "EMPTY_RETURN" else 1.55
            for i, dx in enumerate((-tine_spread, tine_spread)):
                self.scene.set_position(
                    self.mapping["FORK-01"] + f"/Forks/Tine{i}", (dx, tine_y, -0.06)
                )
        if op.route_id and self.routes[op.route_id].device_id == "CART-01":
            point = (
                self.places[op.location] if not run.command.resume_of else self.position("CART-01")
            )
            if not run.command.resume_of:
                self.scene.set_position(
                    self.mapping["CART-01"] + "/TransferTray",
                    (0, -0.15 if op.action == "EMPTY_RETURN" else 0.65, point[2] - 0.05),
                )
        if run.command.resume_of in self.attached:
            self.attached.add(run.command.id)

    def world_event(self, event):
        if event.kind == "ARRIVAL":
            self.put(event.entity_id, self.places[event.evidence_id])
            self.quantities[event.entity_id] = self.loads[event.entity_id].quantity
            self.scene.attr(
                self.prim(event.entity_id), "s15Quantity", self.quantities[event.entity_id]
            )
        if event.kind in ("FAILURE", "REPAIR") and event.entity_id in self.devices:
            self.scene.attr(self.prim(event.entity_id), "s15Available", event.kind == "REPAIR")

    def preflight_world(self, event):
        if event.kind == "ARRIVAL":
            if event.evidence_id in self.variable_ports:
                require(self.landing_supports(event.evidence_id), "SUPPORT_NOT_READY:ACTUAL")
            point = self.places[event.evidence_id]
            try:
                check_route(
                    (point, point),
                    self.loads[event.entity_id].size_m,
                    self.scene.actual_obstacles((event.entity_id,)),
                )
            except ValueError as exc:
                raise ValueError("ACTUAL_WORLD_OCCUPIED:" + str(exc)) from exc

    def landing_supports(self, location):
        if location in self.variable_ports:
            return self.support_port.for_location(location)
        static_location = self.support_aliases.get(location, location)
        supports = [
            p
            for p in self.scene.stage.Traverse()
            if str(p.GetPath()).startswith("/World/Static/")
            and p.HasAPI(UsdPhysics.CollisionAPI)
            and p.GetAttribute("s13:obstacleId")
            and str(p.GetAttribute("s13:obstacleId").Get()).startswith(
                static_location + "-support-"
            )
        ]
        if location.startswith("J3.") and location.endswith((".COLUMNS", ".TOP")):
            ident = location.removeprefix("J3.").rsplit(".", 1)[0] + (
                ".BOTTOM" if location.endswith(".COLUMNS") else ".COLUMNS"
            )
            prim = self.scene.stage.GetPrimAtPath(self.mapping[ident] + "/Envelope")
            if (
                prim
                and prim.HasAPI(UsdPhysics.CollisionAPI)
                and UsdGeom.Imageable(prim).ComputeVisibility() != UsdGeom.Tokens.invisible
            ):
                supports.append(prim)
        return supports

    def support_ok(self, op, point):
        route = self.routes[op.route_id]
        size = self.loads[op.entity_id].size_m if op.entity_id in self.loads else (0, 0, 0)
        if route.device_id == "CR1":
            scale = (
                UsdGeom.Xformable(self.scene.stage.GetPrimAtPath("/World/Hook/Rig"))
                .GetOrderedXformOps()[-1]
                .Get()
            )
            return (
                close(self.position("CR1-HOOK"), (point[0], point[1], point[2] + size[2] + 0.6))
                and abs(scale[0] * 6 - size[0]) < 0.001
                and abs(scale[1] * 3 - size[1]) < 0.001
            )
        if route.device_id == "FORK-01":
            v = self.position("FORK-01")
            top = self.scene.world_position(self.mapping["FORK-01"] + "/Forks")
            tines = [
                self.scene.world_position(self.mapping["FORK-01"] + f"/Forks/Tine{i}")
                for i in (0, 1)
            ]
            return close(point, (v[0], v[1] + 1.8, top[2])) and all(
                abs(t[2] + 0.06 - point[2]) < 0.001
                and abs(t[0] - point[0]) < size[0] / 2
                and abs(t[1] - point[1]) < size[1] / 2 + 0.65
                for t in tines
            )
        if route.device_id == "CART-01":
            tray = self.scene.world_position(self.mapping["CART-01"] + "/TransferTray")
            return (
                abs(tray[2] + 0.05 - point[2]) < 0.001
                and abs(tray[0] - point[0]) < 0.325
                and abs(tray[1] - point[1]) < 0.55
            )
        return True

    def simulation_stage(self, op, done):
        if op.handover:
            raw = self.prim("FIX-J2").GetAttribute("s13:s18Handover").Get()
            change = decode(m.Handover, json.loads(raw))
            require(change == op.handover, "ACTUAL_HANDOVER_PHASE_DRIFT")
            return dict(branch=None, handover=change)
        if not op.branch:
            return dict(branch=None)
        fixture = self.prim("FIX-J2")

        def read(name):
            return fixture.GetAttribute("s13:" + name).Get()

        branch = m.Branch(
            read("s18Definition"),
            read("s18Revision"),
            read("s18Output"),
            read("s18Assumption"),
            read("s18JointSet"),
            read("s18Phase"),
            read("s18Terminal"),
        )
        require(branch == op.branch, "ACTUAL_SIMULATION_STAGE_DRIFT")
        # The process itself is a symbolic timed unit. Position/exit/stop/owner
        # predicates come from this live stage and are read before dispatch completion.
        isolated = all(
            not close(self.position(p.id), standing_point(self.config, p.id, "J2"))
            for p in self.config.people
        )
        if op.branch.phase == "ROBOT":
            require(isolated, "ACTUAL_SIMULATION_ISOLATION")
            if done:
                self.scene.attr(self.prim("R1"), "s18Stopped", True)
        stopped = (
            self.prim("R1").GetAttribute("s13:s18Stopped").Get() is True
            if op.production_mode == "HR-seq"
            else True
        )
        owners = tuple(
            m.Ownership(i, self.prim(i).GetAttribute("s13:s18Owner").Get()) for i in op.equipment
        )
        return dict(branch=branch, isolated=isolated, robot_stopped=stopped, stage_owners=owners)

    def step(self, command_id, now_h):
        run = self.running[command_id]
        c = run.command
        op = self.ops[c.operation_id]
        if op.action == "RECEIVE_EXTERNAL" or op.action == "RETURN" and op.target == "EXTERNAL":
            return self.external_proof(run, now_h)
        self.preflight(c)
        if op.action == "SUPPORT_CHANGE":
            return self.support_port.step(run, now_h)
        if moving_device := (self.routes[op.route_id].device_id if op.route_id else None):
            if moving_device in ("FORK-01", "CART-01", "TEST1"):
                self.controls_ok(c)
        if command_id in self.attached and op.entity_id in self.loads:
            require(self.support_ok(op, self.position(op.entity_id)), "ACTUAL_SUPPORT_DRIFT")
        roles = {
            r.person_id: next(x.location for x in op.role_locations if x.person_id == r.role_id)
            for r in c.roles
        }
        moving = op.route_id is not None
        fraction = min(
            1, max(0, (now_h - run.started_h) / max(1e-12, run.earliest_end_h - run.started_h))
        )
        fraction = run.start_progress + (1 - run.start_progress) * fraction
        done = now_h + 1e-10 >= run.earliest_end_h
        if moving:
            fraction = motion_fraction(
                SimpleNamespace(
                    routes=tuple(self.routes.values()),
                    setup_h=self.config.setup_h,
                    load_h=self.config.load_h,
                    unload_h=self.config.unload_h,
                ),
                op,
                run,
                now_h,
            )
            if fraction <= 0 and not done:
                return None
            route = self.routes[op.route_id]
            points = tuple((p.x, p.y, p.z) for p in route.points)
            point = interpolate(points, fraction, route.speed_m_s, route.vertical_speed_m_s)
            size = self.loads[op.entity_id].size_m if op.entity_id in self.loads else (0, 0, 0)
            self.put(op.entity_id, point)
            if op.action == "WALK":
                yaw = 0
                if op.entity_id == "P1":
                    fork = self.position("FORK-01")
                    fork = (fork[0], fork[1] + 1.8, fork[2])
                    operator = (fork[0], fork[1] + FORK_OPERATOR_DY, 0.2)
                    phases, _ = fork_walk_phases(
                        points,
                        fork,
                        leaving=close(points[0], operator),
                        entering=close(points[-1], operator),
                        tolerance=0.002,
                    )
                    yaw = walk_yaw(points, point, phases)
                rotation = UsdGeom.Xformable(self.prim(op.entity_id)).GetOrderedXformOps()[-1]
                rotation.Set(yaw)
                require(abs(float(rotation.Get()) - yaw) < 1e-6, "ACTUAL_WALK_YAW")
            if op.action == "EMPTY_RETURN" and op.entity_id == "CR1":
                self.put("CR1-HOOK", point)
                self.put("CR1", (point[0], 0, 0))
                self.scene.set_position("/World/Crane/Trolley", (0, point[1], 0))
                self.hook_visual(point)
            elif route.device_id:
                self.carrier(route.device_id, point, size, empty=op.action == "EMPTY_RETURN")
            for r in c.roles:
                qual = next(x.qualification for x in op.roles if x.id == r.role_id)
                if op.action == "WALK":
                    self.put(r.person_id, point)
                    roles[r.person_id] = op.target if done else "IN_TRANSIT"
                elif qual in ("FORK", "CART", "TOOL"):
                    v = self.position(route.device_id)
                    dest = (
                        (v[0], v[1] + 1.8 + FORK_OPERATOR_DY, 0.2)
                        if qual == "FORK"
                        else (v[0], v[1] + 1.25, 0)
                        if qual == "TOOL"
                        else (v[0], v[1] - 1.35, 0)
                    )
                    self.put(r.person_id, dest)
                    roles[r.person_id] = op.target if done else "IN_TRANSIT"
            self.controls_ok(c)
            require(
                op.action == "EMPTY_RETURN" or self.support_ok(op, point), "ACTUAL_SUPPORT_MISMATCH"
            )
            self.attached.add(command_id)
            actual = self.position(
                "CR1-HOOK"
                if op.action == "EMPTY_RETURN" and op.entity_id == "CR1"
                else op.entity_id
            )
            if op.action == "EMPTY_RETURN" and op.entity_id in ("FORK-01", "CART-01"):
                body = self.position(op.entity_id)
                support = self.scene.world_position(
                    self.mapping[op.entity_id]
                    + ("/Forks" if op.entity_id == "FORK-01" else "/TransferTray")
                )
                actual = (
                    body[0],
                    body[1] + (1.8 if op.entity_id == "FORK-01" else 1.1),
                    support[2] + (0 if op.entity_id == "FORK-01" else 0.05),
                )
        else:
            if not done:
                return None
            if command_id not in self.material_done:
                self.input_samples[command_id] = self.check_inputs(op)
                self.material_effect(op)
                self.material_done.add(command_id)
            actual = self.places[op.target or op.location]
            if op.entity_id:
                actual = self.position(op.entity_id)
        if done and op.target in self.places and op.entity_id in self.loads:
            support = self.places[op.target]
            require(close(actual, support), "ACTUAL_LANDING_MISMATCH")
            cache = UsdGeom.BBoxCache(
                0, [UsdGeom.Tokens.default_], useExtentsHint=False, ignoreVisibility=True
            )
            supports = self.landing_supports(op.target)
            require(
                supports
                and any(
                    abs(cache.ComputeWorldBound(p).ComputeAlignedRange().GetMax()[2] - actual[2])
                    < 0.002
                    for p in supports
                ),
                "NO_ACTUAL_STATION_SUPPORT",
            )
        detached = done
        if done and moving and op.entity_id in self.loads:
            carrier = self.routes[op.route_id].device_id
            if carrier == "CR1":
                self.put("CR1-HOOK", (actual[0], actual[1], 8))
                self.hook_visual((actual[0], actual[1], 8))
                detached = (
                    self.position("CR1-HOOK")[2] - actual[2] - self.loads[op.entity_id].size_m[2]
                    > 0.7
                )
            elif carrier == "FORK-01":
                for i, dx in enumerate((-0.65, 0.65)):
                    self.scene.set_position(
                        self.mapping[carrier] + f"/Forks/Tine{i}", (dx, 0.35, -0.06)
                    )
                tine = self.scene.world_position(self.mapping[carrier] + "/Forks/Tine0")
                detached = abs(tine[1] - actual[1]) > self.loads[op.entity_id].size_m[1] / 2 + 0.65
            elif carrier == "CART-01":
                self.scene.set_position(
                    self.mapping[carrier] + "/TransferTray", (0, -0.15, actual[2] - 0.05)
                )
                tray = self.scene.world_position(self.mapping[carrier] + "/TransferTray")
                detached = abs(tray[1] - actual[1]) > self.loads[op.entity_id].size_m[1] / 2 + 0.55
            require(detached, "ACTUAL_DETACH_FAILED")
        proof = m.Readback(
            "ISAAC_USD",
            self.run_id,
            self.epoch,
            c.id,
            now_h,
            op.entity_id,
            op.target or op.location if done else "IN_TRANSIT",
            op.target or op.location
            if done
            else self.routes[op.route_id].device_id or op.entity_id,
            tuple(actual),
            tuple(m.PersonPosition(p, loc) for p, loc in roles.items()),
            True,
            True,
            command_id in self.attached or not moving,
            done,
            detached,
            False,
            "USD-" + c.id + "-" + str(len(self.samples)),
            1 if done else min(fraction, 1 - 1e-12),
            inputs=self.input_samples.get(command_id, ()),
            **self.simulation_stage(op, done),
        )
        self.samples.append(proof)
        if done and op.branch and op.branch.terminal:
            for resource in op.release_resources:
                self.scene.attr(self.prim(resource), "s18Owner", "")
        return proof

    def material_effect(self, op):
        if op.action not in ("WORK", "CONVERT", "SCRAP", "RETURN"):
            return
        self.check_inputs(op)
        for amount in op.material_inputs:
            self.quantities[amount.lot_id] -= amount.quantity
            self.scene.attr(self.prim(amount.lot_id), "s15Quantity", self.quantities[amount.lot_id])
            if self.quantities[amount.lot_id] <= 1e-9:
                UsdGeom.Imageable(self.prim(amount.lot_id)).MakeInvisible()
                self.scene.stage.GetPrimAtPath(self.mapping[amount.lot_id] + "/Envelope").RemoveAPI(
                    UsdPhysics.CollisionAPI
                )
        for amount in op.material_outputs:
            self.put(
                amount.lot_id,
                self.places[
                    next(p.place_id for p in op.output_places if p.lot_id == amount.lot_id)
                ],
            )
            self.quantities[amount.lot_id] = amount.quantity
            self.scene.attr(self.prim(amount.lot_id), "s15Quantity", amount.quantity)
            UsdGeom.Imageable(self.prim(amount.lot_id)).MakeVisible()
        for component in op.component_outputs:
            self.put(component, self.places[op.location])
            require(
                close(self.position(component), self.places[op.location]),
                "COMPONENT_OUTPUT_READBACK",
            )
        if op.component_inputs:
            for component in op.component_inputs:
                UsdGeom.Imageable(self.prim(component)).MakeInvisible()
                self.scene.stage.GetPrimAtPath(self.mapping[component] + "/Envelope").RemoveAPI(
                    UsdPhysics.CollisionAPI
                )
            self.put(op.entity_id, self.places[op.location])

    def external_proof(self, run, now_h):
        """Observe a receiver-owned USD interface; dispatch cannot manufacture a receipt."""
        c = run.command
        op = self.ops[c.operation_id]
        receiver_path = "/World/S15/Receiver/" + key(c.id)
        receiver = self.scene.stage.GetPrimAtPath(receiver_path)
        if not receiver or not receiver.GetAttribute("s13:receiptId"):
            return None

        def value(name):
            attr = receiver.GetAttribute("s13:" + name)
            return attr.Get() if attr else None

        require(
            (value("runId"), value("epoch"), value("commandId"), value("productId"))
            == (self.run_id, self.epoch, c.id, c.product_id),
            "RECEIVER_IDENTITY",
        )
        receipt = value("receiptId")
        require(bool(receipt) and receipt not in self.receiver_receipts, "RECEIVER_RECEIPT_REUSED")
        actual = self.position(op.entity_id)
        size = self.loads[op.entity_id].size_m
        require(
            actual[0] - size[0] / 2 > 60
            if op.action == "RECEIVE_EXTERNAL"
            else actual[0] + size[0] / 2 < 0,
            "NO_ACTUAL_EXTERNAL_DEPARTURE",
        )
        deck = self.scene.stage.GetPrimAtPath(receiver_path + "/Deck")
        require(bool(deck), "NO_RECEIVER_SUPPORT")
        cache = UsdGeom.BBoxCache(0, [UsdGeom.Tokens.default_], False, True)
        bounds = cache.ComputeWorldBound(deck).ComputeAlignedRange()
        require(
            abs(bounds.GetMax()[2] - actual[2]) < 0.002
            and all(
                bounds.GetMin()[i] <= actual[i] - size[i] / 2
                and actual[i] + size[i] / 2 <= bounds.GetMax()[i]
                for i in (0, 1)
            ),
            "RECEIVER_SUPPORT_MISMATCH",
        )
        require(now_h + 1e-10 >= run.earliest_end_h, "EARLY_RECEIVER")
        self.receiver_receipts[receipt] = c.id
        self.expected[op.entity_id] = actual
        proof = m.Readback(
            "ISAAC_USD",
            self.run_id,
            self.epoch,
            c.id,
            now_h,
            op.entity_id,
            "EXTERNAL",
            "EXTERNAL",
            actual,
            (),
            True,
            True,
            True,
            True,
            True,
            True,
            receipt,
            1,
            self.input_samples.get(c.id, ()),
        )
        self.samples.append(proof)
        return proof
