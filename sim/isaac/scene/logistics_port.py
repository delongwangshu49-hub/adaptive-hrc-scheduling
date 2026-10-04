"""Command-driven USD kinematic execution with live geometric readback.

This port is an S14 mechanism witness, not a rigid-body dynamics or industrial
qualification model. It reuses the original target geometry, not its trial script.
"""

from pxr import Gf, UsdGeom, UsdPhysics

from adaptive_hrc_scheduling.contracts.codec import require
from adaptive_hrc_scheduling.domain import logistics as m
from adaptive_hrc_scheduling.logistics_geometry import (
    close,
    interpolate,
    motion_fraction,
    standing_point,
)

from .model import key
from .target_layout import CART_SIZE, FORK_SIZE, PERSON_SIZE, check_crane_structure, check_route


class USDLogisticsPort:
    def __init__(self, scene):
        self.scene = scene

    def reset(self, config, run_id, epoch):
        self.config, self.run_id, self.epoch = config, run_id, epoch
        self.scene.build()
        self.scene.stage.RemovePrim("/World/Loads")
        self.scene.stage.RemovePrim("/World/S14")
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
        self.ops = {o.id: o for o in config.operations}
        self.routes = {r.id: r for r in config.routes}
        self.places = {p.id: p.position for p in config.places}
        self.loads = {x.id: x for x in (*config.lots, *config.entities)}
        self.devices = {d.id: d for d in config.devices}
        self.people = {p.id for p in config.people}
        self.running = {}
        self.expected = {}
        self.attached = set()
        self.samples = []
        self.receiver_receipts = {}
        self.material_done = set()
        self.quantities = {x.id: x.quantity if x.arrived else 0 for x in config.lots}
        for x in self.loads.values():
            path = "/World/S14/Loads/" + key(x.id)
            self.scene.ident(x.id, path, (-30, 0, 0))
            self.scene.shape(
                path + "/Envelope", (0, 0, x.size_m[2] / 2), x.size_m, "steel", collision=True
            )
            if x.initial_location in self.places:
                self.put(x.id, self.places[x.initial_location])
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
                    self.carrier(d.id, self.places[d.initial_location], size)
            self.scene.attr(self.prim(d.id), "s14Available", True)
        for p in config.person_positions:
            point = standing_point(config, p.person_id, p.location)
            if p.person_id == "P1" and p.location == self.devices["FORK-01"].initial_location:
                v = self.position("FORK-01")
                point = (v[0], v[1] - 0.4, 0.2)
            if p.person_id == "E1" and p.location == self.devices["CART-01"].initial_location:
                v = self.position("CART-01")
                point = (v[0], v[1] - 1.25, 0)
            self.put(p.person_id, point)
        self.scene.attr(self.scene.stage.GetPrimAtPath("/World"), "productionDispatchEnabled", True)
        self.scene.attr(
            self.scene.stage.GetPrimAtPath("/World"), "s14Scope", "KINEMATIC_SYNTHETIC_WITNESS_ONLY"
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

    def carrier(self, ident, point, size):
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
                self.mapping[ident] + "/TransferTray", (0, 0.65, point[2] - 0.05)
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
        op = self.ops[command.operation_id]
        for ident in (
            *op.equipment,
            *(r.person_id for r in command.roles),
            *((op.entity_id,) if op.entity_id and not op.component_inputs else ()),
        ):
            self.check_actual(ident)
        for ident in op.equipment:
            require(
                self.prim(ident).GetAttribute("s13:s14Available").Get() is True,
                "ACTUAL_DEVICE_FAILED:" + ident,
            )
        if op.route_id:
            self.check_path(command)

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
        size = (
            self.loads[op.entity_id].size_m
            if op.entity_id in self.loads
            else PERSON_SIZE
            if op.entity_id in self.people
            else (0.8, 1.1, 1.2)
        )
        if op.action == "EMPTY_RETURN" and op.entity_id == "CR1":
            check_route(tuple((x, y, z - 0.6) for x, y, z in points), (6, 3, 0.8), obstacles)
        else:
            check_route(points, size, obstacles)
        if route.device_id == "CR1":
            require(
                all(18 <= x <= 54 and 8 <= y <= 36 for x, y, z in points), "ACTUAL_CRANE_COVERAGE"
            )
            if op.entity_id in self.loads:
                require(all(z + size[2] + 0.6 <= 8.2 for x, y, z in points), "ACTUAL_HEADROOM")
                check_route(points, (size[0], size[1], size[2] + 0.6), obstacles)
            check_crane_structure(tuple((x, y, z + size[2] + 0.6) for x, y, z in points), obstacles)
        if route.device_id in ("FORK-01", "CART-01"):
            offset = 1.8 if route.device_id == "FORK-01" else 1.1
            check_route(
                tuple((x, y - offset, 0) for x, y, z in points),
                FORK_SIZE if offset == 1.8 else CART_SIZE,
                obstacles,
            )
        for binding in command.roles:
            qualification = next(r.qualification for r in op.roles if r.id == binding.role_id)
            if op.action == "WALK" or qualification not in ("FORK", "CART", "TOOL"):
                continue
            dy, dz = (
                (-2.2, 0.2)
                if qualification == "FORK"
                else (-2.35, 0)
                if qualification == "CART"
                else (1.25, 0)
            )
            check_route(tuple((p[0], p[1] + dy, dz) for p in points), PERSON_SIZE, obstacles)

    def start(self, run):
        self.running[run.command.id] = run
        op = self.ops[run.command.operation_id]
        for binding in run.command.roles:
            if next(r.qualification for r in op.roles if r.id == binding.role_id) == "TOOL":
                UsdGeom.Xformable(self.prim(binding.person_id)).GetOrderedXformOps()[-1].Set(180)
        self.controls_ok(run.command)
        if op.route_id and self.routes[op.route_id].device_id == "FORK-01":
            for i, dx in enumerate((-0.65, 0.65)):
                self.scene.set_position(
                    self.mapping["FORK-01"] + f"/Forks/Tine{i}", (dx, 1.55, -0.06)
                )
        if run.command.resume_of in self.attached:
            self.attached.add(run.command.id)

    def world_event(self, event):
        if event.kind == "ARRIVAL":
            self.put(event.entity_id, self.places[event.evidence_id])
            self.quantities[event.entity_id] = self.loads[event.entity_id].quantity
        if event.kind in ("FAILURE", "REPAIR") and event.entity_id in self.devices:
            self.scene.attr(self.prim(event.entity_id), "s14Available", event.kind == "REPAIR")

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

    def step(self, command_id, now_h):
        run = self.running[command_id]
        c = run.command
        op = self.ops[c.operation_id]
        if op.action == "RECEIVE_EXTERNAL":
            return self.external_proof(run, now_h)
        self.preflight(c)
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
            fraction = motion_fraction(self.config, op, run, now_h)
            if fraction <= 0 and not done:
                return None
            route = self.routes[op.route_id]
            points = tuple((p.x, p.y, p.z) for p in route.points)
            point = interpolate(points, fraction, route.speed_m_s, route.vertical_speed_m_s)
            size = self.loads[op.entity_id].size_m if op.entity_id in self.loads else (0, 0, 0)
            self.put(op.entity_id, point)
            if op.action == "EMPTY_RETURN" and op.entity_id == "CR1":
                self.put("CR1-HOOK", point)
                self.put("CR1", (point[0], 0, 0))
                self.scene.set_position("/World/Crane/Trolley", (0, point[1], 0))
                self.hook_visual(point)
            elif route.device_id:
                self.carrier(route.device_id, point, size)
            for r in c.roles:
                qual = next(x.qualification for x in op.roles if x.id == r.role_id)
                if op.action == "WALK":
                    self.put(r.person_id, point)
                    roles[r.person_id] = op.target if done else "IN_TRANSIT"
                elif qual in ("FORK", "CART", "TOOL"):
                    v = self.position(route.device_id)
                    dest = (
                        (v[0], v[1] - 0.4, 0.2)
                        if qual == "FORK"
                        else (v[0], v[1] + 1.25, 0)
                        if qual == "TOOL"
                        else (v[0], v[1] - 1.25, 0)
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
        else:
            if not done:
                return None
            if command_id not in self.material_done:
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
            supports = [
                p
                for p in self.scene.stage.Traverse()
                if str(p.GetPath()).startswith("/World/Static/")
                and p.GetAttribute("s13:obstacleId")
                and str(p.GetAttribute("s13:obstacleId").Get()).startswith(op.target + "-support-")
            ]
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
                    self.mapping[carrier] + "/TransferTray", (0, -0.65, actual[2] - 0.05)
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
            fraction if done else min(fraction, 1 - 1e-12),
        )
        self.samples.append(proof)
        return proof

    def material_effect(self, op):
        if op.action not in ("WORK", "CONVERT", "SCRAP", "RETURN"):
            return
        for amount in op.material_inputs:
            self.quantities[amount.lot_id] -= amount.quantity
            if self.quantities[amount.lot_id] <= 1e-9:
                UsdGeom.Imageable(self.prim(amount.lot_id)).MakeInvisible()
                self.scene.stage.GetPrimAtPath(self.mapping[amount.lot_id] + "/Envelope").RemoveAPI(
                    UsdPhysics.CollisionAPI
                )
        for amount in op.material_outputs:
            self.put(amount.lot_id, self.places[op.location])
            self.quantities[amount.lot_id] = amount.quantity
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
        receiver = self.scene.stage.GetPrimAtPath("/World/S14/Receiver")
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
        require(actual[0] - size[0] / 2 > 60, "NO_ACTUAL_EXTERNAL_DEPARTURE")
        deck = self.scene.stage.GetPrimAtPath("/World/S14/Receiver/Deck")
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
        )
        self.samples.append(proof)
        return proof
