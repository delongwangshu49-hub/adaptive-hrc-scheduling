"""Continuous, scene-only R5 witnesses with named operators and bounded slots.

This is a deterministic geometry rehearsal, not a dispatch backend. Inspection
seconds are not process durations; no production contracts are imported here.
"""

import copy
import math
from dataclasses import dataclass, field

from .model import Box, require
from .target_layout import (
    CART_SIZE,
    CONTROL,
    FIXED,
    FORK_SIZE,
    HOMES,
    LOADS,
    PADS,
    PEOPLE,
    PERSON_SIZE,
    TASK_BY_ID,
    WalkGraph,
    check_crane_structure,
    check_route,
    length,
    parked_crane_boxes,
    static_boxes,
)

TRIALS = ("T1", "T2", "T3", "T4")


def shift(p, offset):
    return tuple(a + b for a, b in zip(p, offset))


def sample(points, fraction, reference=None):
    clock = points if reference is None else reference
    require(len(points) == len(clock), "MOTION_CLOCK_SIZE")
    distances = [math.dist(a, b) for a, b in zip(clock, clock[1:])]
    left = fraction * sum(distances)
    for a, b, d in zip(points, points[1:], distances):
        if left <= d and d > 0:
            f = left / d
            return tuple(x + (y - x) * f for x, y in zip(a, b))
        left -= d
    return points[-1]


@dataclass
class Phase:
    label: str
    paths: dict = field(default_factory=dict)
    sizes: dict = field(default_factory=dict)
    roles: dict = field(default_factory=dict)
    seconds: float = 2
    start: tuple = ()
    finish: tuple = ()
    task: str = ""
    load: str = ""
    state: str = "PREPARE"
    concurrent: bool = False
    holds: dict = field(default_factory=dict)
    clock: tuple = ()

    def position(self, name, fraction):
        return sample(self.paths[name], fraction, self.clock or None)


class TargetRun:
    def __init__(self, name="T1", combined=False):
        require(name in TRIALS, "UNKNOWN_TRIAL")
        self.name = name
        self.combined = combined
        self.reset()

    def reset(self):
        self.positions = dict(HOMES)
        self.positions.update({k: (v.center[0], v.center[1], 0) for k, v in FIXED.items()})
        self.positions.update(
            {
                "CR1-HOOK": (30, 18, 8),
                "SCN-FORK-01": (6, 5.2, 0),
                "SCN-CART-01": (6, 21.9, 0),
                "TEST1": PADS["TEST-PARK"],
            }
        )
        self.kinds, self.locations, self.support = {}, {}, {}
        self.slots = {k: None for k in PADS}
        self.released = set()
        self.owners = {}
        self.external_signal = False
        self.paused, self.speed = False, 1.0
        self.index, self.part, self.elapsed = 0, 0.0, 0.0
        self.events, self.routes = [], []
        self.status, self.blocked = "READY", None
        self.phases, self._entered, self._done = [], False, set()
        self.faults = set()
        self.extensions = {"SCN-FORK-01": 1.0, "SCN-CART-01": 1.0}
        self.person_state = {
            p: {"task": "UNASSIGNED", "state": "WAIT", "reason": "NO_TASK"} for p in PEOPLE
        }
        if self.name == "T1":
            self.add_load("SCN-STEEL-001", "steel", "RECEIVE")
        elif self.name == "T2":
            self.add_load("SCN-MODULE-001", "module", "J3")
            self.add_load("SCN-FRAME-001", "frame", "PRE-OUT")
            self.released.update(self.kinds)
        elif self.name == "T3":
            self.add_load("SCN-MEP-001", "mep", "MEP-RECEIVE")
        else:
            for i, pad in enumerate(("FG1", "FG2", "OUT1"), 1):
                self.add_load(f"SCN-FG-P{i}", "module", pad)
            self.released.update(self.kinds)
        self._planned = copy.deepcopy(self.positions)
        self._planned_locations = dict(self.locations)
        self._compile()
        for i, phase in enumerate(self.phases):
            for person in (*phase.roles, *phase.paths):
                if person in PEOPLE:
                    phase.holds.setdefault(person, phase.task or f"PHASE:{i}")
        self.initial = copy.deepcopy(self.positions)

    def add_load(self, name, kind, pad):
        require(self.slots[pad] is None, "TARGET_FULL:" + pad)
        self.kinds[name] = kind
        self.positions[name] = PADS[pad]
        self.locations[name] = pad
        self.support[name] = "PAD:" + pad
        self.slots[pad] = name

    @property
    def action(self):
        return self.phases[self.index] if self.index < len(self.phases) else None

    def claim(self, resource, owner):
        resource = "CR1" if resource == "CR1-HOOK" else resource
        require(resource not in self.owners, "RESOURCE_BUSY:" + resource)
        self.owners[resource] = owner

    def signal_external(self):
        require(self.name == "T4", "NO_EXTERNAL_INTERFACE")
        require(not self.external_signal, "DUPLICATE_EXTERNAL_SIGNAL")
        self.external_signal = True
        self.events.append(
            {"time": self.elapsed, "signal": "SCENE_EXTERNAL_RECEIVER_READY_NOT_RECEIVED_EVENT"}
        )

    def planned_obstacles(self, exclude=()):
        obs = static_boxes()
        if "CR1-HOOK" not in exclude:
            obs.extend(parked_crane_boxes(self._planned["CR1-HOOK"]))
        for n, p in self._planned.items():
            if n in exclude or n in FIXED or n == "CR1-HOOK":
                continue
            size = self.size(n)
            obs.append(Box(n, shift(p, (0, 0, size[2] / 2)), size))
        return obs

    def size(self, name):
        if name in PEOPLE:
            return PERSON_SIZE
        if name in self.kinds:
            return LOADS[self.kinds[name]][0]
        return {
            "SCN-FORK-01": FORK_SIZE,
            "SCN-CART-01": CART_SIZE,
            "TEST1": (0.8, 1.1, 1.2),
            "CR1-HOOK": (0.4, 0.4, 0.4),
        }[name]

    def add(self, phase):
        for name, points in phase.paths.items():
            require(
                math.dist(self._planned[name], points[0]) < 1e-6, "PLANNED_DISCONTINUITY:" + name
            )
            self._planned[name] = points[-1]
        self.phases.append(phase)

    def walk(self, who, end, task="APPROACH"):
        start = self._planned[who]
        if math.dist(start, end) < 1e-8:
            return
        try:
            points = WalkGraph(self.planned_obstacles((who,))).route(start, end)
        except ValueError as exc:
            raise ValueError(f"{exc}:{who}:{task}:{start}->{end}") from exc
        self.routes.append(
            {
                "person": who,
                "task": task,
                "start": start,
                "target": end,
                "points": points,
                "walked_m": length(points),
                "same_graph_shortest_m": length(points),
                "method": "DIJKSTRA_LEGAL_GRAPH",
            }
        )
        self.add(
            Phase(
                "WALK " + who + " / " + task,
                {who: points},
                {who: PERSON_SIZE},
                seconds=max(1, length(points) / 1.2),
                task=task,
                state="WALK",
            )
        )

    def transfer(self, task_id, load):
        t = TASK_BY_ID[task_id]
        require(self._planned_locations[load] == t.source, "PLAN_SOURCE")
        require(
            self.kinds[load] == t.load or (self.kinds[load] == "steel" and t.load == "steel"),
            "PLAN_LOAD",
        )
        size = self.size(load)
        if t.carrier == "CR1":
            # Ground operator, rigger and signal person remain in declared clear
            # control positions throughout motion. Rigger first approaches load.
            for p, spot in CONTROL.items():
                self.walk(p, spot, task_id)
            receiver = (PADS[t.target][0] + 4.5, PADS[t.target][1] + 2.5, 0)
            self.walk(t.receiver, receiver, task_id + " RECEIVE")
            hook = self._planned["CR1-HOOK"]
            target_hook = shift(PADS[t.source], (0, 0, size[2] + 0.6))
            points = (
                hook,
                (hook[0], hook[1], 8),
                (target_hook[0], hook[1], 8),
                (target_hook[0], target_hook[1], 8),
                target_hook,
            )
            roles = {**CONTROL, t.receiver: receiver}
            lock_start = len(self.phases)
            self.add(
                Phase(
                    "EMPTY HOOK APPROACH " + task_id,
                    {"CR1-HOOK": points},
                    {"CR1-HOOK": (*size[:2], 0.8)},
                    roles,
                    max(2, length(points)),
                    task=task_id,
                    state="OPERATE",
                )
            )
            rig_spot = (PADS[t.source][0] + 2, PADS[t.source][1] - 2.3, 0)
            self.walk("Lrig", rig_spot, task_id + " RIG")
            self.add(
                Phase("RIG / HOOK STATIONARY " + task_id, roles={"Lrig": rig_spot}, task=task_id)
            )
            self.walk("Lrig", CONTROL["Lrig"], task_id + " WITHDRAW")
            paths = {
                load: t.points,
                "CR1-HOOK": tuple(shift(p, (0, 0, size[2] + 0.6)) for p in t.points),
            }
            sizes = {load: size, "CR1-HOOK": (*size[:2], 0.8)}
        else:
            carrier = t.carrier
            offset = (0, -1.8 if carrier == "SCN-FORK-01" else -1.1, 0)
            root = self._planned[carrier]
            spot = (
                shift(root, (-1.3, 0, 0))
                if carrier == "SCN-FORK-01"
                else shift(root, (0, -1.25, 0))
            )
            relative = (0, -0.4, 0.2) if carrier == "SCN-FORK-01" else (0, -1.25, 0)
            ride = shift(root, relative)
            if math.dist(self._planned[t.operator], ride) > 1e-6:
                self.walk(t.operator, spot, task_id + " BOARD_OR_GRIP")
                if carrier == "SCN-FORK-01":
                    board = (spot, shift(spot, (0, 0, 0.2)), (ride[0], spot[1], 0.2), ride)
                    self.add(
                        Phase(
                            "BOARD STANDING CONTROL PLATFORM / " + t.operator,
                            {t.operator: board},
                            {t.operator: PERSON_SIZE},
                            task="BOARD",
                            state="PREPARE",
                        )
                    )
            receiver = (PADS[t.target][0] + 2.5, PADS[t.target][1] + 2.5, 0)
            self.walk(t.receiver, receiver, task_id + " RECEIVE")
            roles = {t.receiver: receiver}
            carrier_points = tuple((p[0] + offset[0], p[1] + offset[1], 0) for p in t.points)
            require(math.dist(root, carrier_points[0]) < 1e-6, "CARRIER_NOT_AT_SOURCE")
            paths = {
                load: t.points,
                carrier: carrier_points,
                t.operator: tuple(shift(p, relative) for p in carrier_points),
            }
            sizes = {load: size, carrier: self.size(carrier), t.operator: PERSON_SIZE}
        if t.carrier != "CR1":
            lock_start = len(self.phases)
        reserve_start = len(self.phases)
        self.add(
            Phase(
                "LOAD / CHECK SUPPORT " + task_id,
                roles={**roles, t.operator: self._planned[t.operator]},
                start=("reserve", task_id, load),
                task=task_id,
                load=load,
            )
        )
        self.add(
            Phase(
                "CARRY " + task_id,
                paths,
                sizes,
                roles,
                max(3, length(t.points) / 0.6),
                start=("attach", task_id, load),
                task=task_id,
                load=load,
                state="OPERATE",
                clock=t.points,
            )
        )
        self.add(
            Phase(
                "LAND / RECEIVER HANDOFF " + task_id,
                roles={**roles, t.operator: self._planned[t.operator]},
                finish=("land", task_id, load),
                task=task_id,
                load=load,
            )
        )
        self._planned_locations[load] = t.target
        if t.carrier == "CR1":
            a = self._planned["CR1-HOOK"]
            points = (a, (a[0], a[1], 8), (30, a[1], 8), (30, 18, 8))
            self.add(
                Phase(
                    "EMPTY HOOK RETURN " + task_id,
                    {"CR1-HOOK": points},
                    {"CR1-HOOK": (*size[:2], 0.8)},
                    CONTROL,
                    max(2, length(points)),
                    task=task_id,
                    state="OPERATE",
                    finish=("release", task_id, load),
                )
            )
        else:
            self.add(
                Phase(
                    "RELEASE TRANSPORT " + task_id, finish=("release", task_id, load), task=task_id
                )
            )
        for phase in self.phases[lock_start:]:
            phase.holds.update({k: task_id for k in (t.carrier, t.operator, t.receiver)})
            if t.carrier == "CR1":
                phase.holds.update({k: task_id for k in CONTROL})
        for phase in self.phases[reserve_start:]:
            phase.holds["SLOT:" + t.target] = task_id

    def empty_return(self, task_ids, carrier, operator):
        lock_start = len(self.phases)
        self.add(
            Phase(
                "RETRACT SUPPORT BEFORE EMPTY RETURN",
                roles={operator: self._planned[operator]},
                seconds=2,
                finish=("retract", carrier),
                task=carrier,
                load=carrier,
                state="RETRACT",
            )
        )
        # Reverse the actual outbound carrier route, retaining its person.
        phases = [p for p in self.phases if p.label.startswith("CARRY") and p.task in task_ids]
        for previous in reversed(phases):
            paths = {
                n: tuple(reversed(p)) for n, p in previous.paths.items() if n in (carrier, operator)
            }
            # The operator has stayed at the equipment after each handoff.
            if math.dist(self._planned[operator], paths[operator][0]) > 1e-6:
                self.walk(operator, paths[operator][0], "EMPTY_RETURN")
            self.add(
                Phase(
                    "EMPTY RETURN " + previous.task,
                    paths,
                    {n: self.size(n) for n in paths},
                    seconds=max(2, length(paths[carrier])),
                    task="EMPTY_RETURN",
                    state="OPERATE",
                )
            )
        for phase in self.phases[lock_start:]:
            phase.holds.update({carrier: "EMPTY_RETURN", operator: "EMPTY_RETURN"})

    def _compile(self):
        if self.combined:
            self.crossing()
            self.walk("W1", (32, 16, 0), "CLEAR_CRANE_CONTROL")
            self.walk("W2", (52, 16, 0), "CLEAR_CRANE_CONTROL")
        if self.name == "T1":
            self.walk("QA1", (9, 8, 0), "RECEIVING_INSPECTION")
            self.add(
                Phase(
                    "INSPECT / SCENE RELEASE STEEL",
                    roles={"QA1": (9, 8, 0)},
                    finish=("release_batch", "SCN-STEEL-001"),
                )
            )
            for task in ("S01", "S02"):
                self.transfer(task, "SCN-STEEL-001")
            self.walk("W1", (13, 9, 0), "CUT_PREP")
            self.add(
                Phase(
                    "CUT ABSTRACT / FIXED MACHINE / NO PROCESS RECEIPT",
                    holds={"CUT1": "CUT"},
                    roles={"W1": (13, 9, 0)},
                    seconds=4,
                    task="CUT1",
                    state="OPERATE",
                )
            )
            self.transfer("S03", "SCN-STEEL-001")
            self.empty_return(("S01", "S02", "S03"), "SCN-FORK-01", "P1")
            self.transfer("S04", "SCN-STEEL-001")
        elif self.name == "T2":
            for task in ("M01", "M02", "M03", "M04"):
                self.transfer(task, "SCN-MODULE-001")
            for task in ("C01", "C02", "C03"):
                self.transfer(task, "SCN-FRAME-001")
        elif self.name == "T3":
            self.crossing()
            for who, point in (("W1", (32, 16, 0)), ("W2", (52, 16, 0))):
                self.walk(who, point, "FIXED_WELD")
            self.add(
                Phase(
                    "TWO INDEPENDENT FIXED WELD STATIONS",
                    holds={"SCN-WELD-J2": "WELD", "SCN-WELD-J3": "WELD"},
                    roles={"W1": (32, 16, 0), "W2": (52, 16, 0)},
                    seconds=4,
                    task="SCN-WELD-J2+SCN-WELD-J3",
                    state="OPERATE",
                )
            )
            self.walk("QA1", (8, 24, 0), "INSPECT_MEP")
            self.add(
                Phase(
                    "INSPECT / SCENE RELEASE MEP",
                    roles={"QA1": (8, 24, 0)},
                    finish=("release_batch", "SCN-MEP-001"),
                )
            )
            for task in ("P01", "P02", "P03"):
                self.transfer(task, "SCN-MEP-001")
            self.empty_return(("P01", "P02", "P03"), "SCN-CART-01", "E1")
            self.walk("AF1", (52, 32, 0), "HANDOFF_COMPLETE_CLEAR_TEST_ROUTE")
            self.walk("QA1", (55, 35.25, 0), "TEST_PUSH")
            test_start = len(self.phases)
            for reverse in (False, True):
                a, b = (
                    (PADS["TEST-USE"], PADS["TEST-PARK"])
                    if reverse
                    else (PADS["TEST-PARK"], PADS["TEST-USE"])
                )
                if reverse:
                    self.walk("QA1", (55, 26.25, 0), "TEST_RETRIEVE")
                route = (a, (57, a[1], 0), (57, b[1], 0), b)
                paths = {"TEST1": route, "QA1": tuple(shift(p, (0, 1.25, 0)) for p in route)}
                self.add(
                    Phase(
                        "TEST RETRIEVE" if reverse else "TEST DELIVER",
                        paths,
                        {"TEST1": self.size("TEST1"), "QA1": PERSON_SIZE},
                        seconds=length(route),
                        task="TEST1",
                        state="OPERATE",
                    )
                )
                if not reverse:
                    self.walk("QA1", (57, 32, 0), "TEST_DEPLOYED_WITHDRAW")
                    self.add(
                        Phase(
                            "TEST HELD / PERSON RELEASED / QUALITY UNKNOWN",
                            seconds=5,
                            task="TEST1",
                            state="WAIT",
                        )
                    )
            for phase in self.phases[test_start:]:
                phase.holds["TEST1"] = "TEST1"
        else:
            self.add(
                Phase(
                    "BUFFER FULL / P3 WAITS AT OUT1 / SIGNAL EXTERNAL READY",
                    start=("wait_external",),
                    task="B+1",
                    state="WAIT",
                )
            )
            self.transfer("F03", "SCN-FG-P1")
            self.transfer("F01", "SCN-FG-P3")

    def crossing(self):
        # A real crossing: both start together, W2 yields deterministically
        # before a shared route corridor, then proceeds from the same point.
        paths = {}
        for p, end in (("W1", (57, 18, 0)), ("W2", (45, 29, 0))):
            paths[p] = WalkGraph(self.planned_obstacles(("W1", "W2", "Lrig", "Lop"))).route(
                self._planned[p], end
            )
        # Clear the crossing endpoints before the concurrent request.
        self.walk("Lop", (57, 38, 0), "CLEAR_CROSSING")
        self.walk("Lrig", (45, 36, 0), "CLEAR_CROSSING")
        self.add(
            Phase(
                "TWO PEOPLE CROSS / W2 YIELDS TO W1",
                paths,
                {p: PERSON_SIZE for p in paths},
                seconds=sum(length(p) / 1.2 for p in paths.values()),
                task="CROSSING",
                state="WALK",
                concurrent=True,
            )
        )

    def _effect(self, effect):
        if not effect:
            return
        op, *args = effect
        if op == "retract":
            self.extensions[args[0]] = 0.0
            return
        if op == "release_batch":
            self.released.add(args[0])
            return
        if op == "wait_external":
            require(
                all(self.slots[p] is not None for p in ("FG1", "FG2", "OUT1")), "B_PLUS_ONE_MISSING"
            )
            require(self.external_signal, "WAIT_EXTERNAL_RECEIVER_BUFFER_FULL")
            return
        task_id, load = args
        t = TASK_BY_ID[task_id]
        if op == "reserve":
            require(load in self.released and "unreleased" not in self.faults, "BATCH_NOT_RELEASED")
            require(
                self.slots[t.source] == load and "source_missing" not in self.faults,
                "SOURCE_MISSING",
            )
            require(
                self.slots[t.target] is None and "target_full" not in self.faults,
                "TARGET_FULL:" + t.target,
            )
            keys = (t.carrier, t.operator, t.receiver, "SLOT:" + t.target)
            require(len(set(keys)) == len(keys), "DUPLICATE_ROLE")
            for k in keys:
                require(self.owners.get(k) in (None, task_id), "RESOURCE_BUSY:" + k)
        elif op == "attach":
            require(self.owners.get(t.carrier) == task_id, "NO_CARRIER_LOCK")
            require(self.support[load] == "PAD:" + t.source, "NO_SOURCE_SUPPORT")
            if t.carrier in self.extensions:
                require(self.extensions[t.carrier] == 1, "SUPPORT_NOT_EXTENDED")
            self.support[load] = "CARRIER:" + t.carrier
        elif op == "land":
            require(self.slots[t.target] is None, "TARGET_FULL:" + t.target)
            require(math.dist(self.positions[load], PADS[t.target]) < 1e-6, "NOT_LANDED")
            require(self.support[load] == "CARRIER:" + t.carrier, "NOT_ATTACHED")
            self.slots[t.source] = None
            self.slots[t.target] = load
            self.locations[load] = t.target
            self.support[load] = "PAD:" + t.target
        elif op == "release":
            require(self.support[load] == "PAD:" + t.target, "EARLY_RELEASE")
        else:
            raise ValueError("UNKNOWN_EFFECT")

    def snapshot(self):
        return copy.deepcopy(
            {
                "trial": self.name,
                "index": self.index,
                "elapsed": self.elapsed,
                "part_elapsed": self.part,
                "status": self.status,
                "blocked": self.blocked,
                "paused": self.paused,
                "positions": self.positions,
                "slots": self.slots,
                "extensions": self.extensions,
                "support": self.support,
                "owners": self.owners,
                "people": self.person_state,
                "quality": "UNKNOWN",
                "production_receipt": False,
                "external_signal": self.external_signal,
                "task": self.action.task if self.action else "COMPLETE",
            }
        )

    def advance(self, dt, obstacles=(), single_step=False):
        require(math.isfinite(dt) and dt >= 0, "INVALID_DT")
        if not self.action or (self.paused and not single_step):
            return self.snapshot()
        a = self.action
        try:
            for resource, owner in a.holds.items():
                allowed = (owner,) if self._entered else (None, owner)
                reason = "PERSON_DOUBLE_TASK:" if resource in PEOPLE else "RESOURCE_BUSY:"
                require(self.owners.get(resource) in allowed, reason + resource)
            for n, p in FIXED.items():
                require(
                    self.positions[n] == (p.center[0], p.center[1], 0), "FIXED_MACHINE_MOVED:" + n
                )
            require("operator_missing" not in self.faults, "OPERATOR_MISSING")
            if "CR1-HOOK" in a.paths:
                require(all(p in a.roles for p in CONTROL), "MISSING_CRANE_ROLE")
                check_crane_structure(a.paths["CR1-HOOK"], obstacles)
            for vehicle, person in (("SCN-FORK-01", "P1"), ("SCN-CART-01", "E1"), ("TEST1", "QA1")):
                if vehicle in a.paths:
                    require(person in a.paths, "UNOPERATED_VEHICLE:" + vehicle)
            for p, at in a.roles.items():
                require(
                    p in self.positions and math.dist(self.positions[p], at) < 0.02,
                    "ROLE_NOT_AT_STATION:" + p,
                )
                require(
                    self.owners.get(p) in (None, a.holds.get(p, a.task)), "PERSON_DOUBLE_TASK:" + p
                )
            for n, path in a.paths.items():
                resource = "CR1" if n == "CR1-HOOK" else n
                require(
                    self.owners.get(resource) in (None, a.holds.get(resource, a.task)),
                    "RESOURCE_BUSY:" + resource,
                )
                if self._entered and not a.concurrent:
                    require(
                        math.dist(self.positions[n], a.position(n, self.part / a.seconds)) < 0.02,
                        "ACTOR_LEFT_MOTION:" + n,
                    )
                checked = tuple(shift(p, (0, 0, -0.6)) for p in path) if n == "CR1-HOOK" else path
                check_route(checked, a.sizes[n], obstacles)
            if a.label.startswith("CARRY") and a.task in TASK_BY_ID:
                carrier = TASK_BY_ID[a.task].carrier
                if carrier == "SCN-FORK-01":
                    for dx in (-0.65, 0.65):
                        check_route(
                            tuple(shift(p, (dx, -0.25, -0.12)) for p in a.paths[a.load]),
                            (0.12, 1.3, 0.12),
                            obstacles,
                        )
                elif carrier == "SCN-CART-01":
                    check_route(
                        tuple(shift(p, (0, -0.45, -0.1)) for p in a.paths[a.load]),
                        (0.65, 1.1, 0.1),
                        obstacles,
                    )
            if not self._entered:
                for n, path in a.paths.items():
                    require(
                        math.dist(self.positions[n], path[0]) < 1e-6, "DISCONTINUOUS_START:" + n
                    )
                self._effect(a.start)
                self.owners.update(a.holds)
                self._entered = True
                self.events.append(
                    {
                        "time": self.elapsed,
                        "start": a.label,
                        "slots": dict(self.slots),
                        "support": dict(self.support),
                    }
                )
            step = min(dt * self.speed, a.seconds - self.part)
            self.part += step
            self.elapsed += step
            for p in PEOPLE:
                self.person_state[p] = {
                    "task": a.task if p in a.roles or p in a.paths else "UNASSIGNED",
                    "state": a.state if p in a.roles or p in a.paths else "WAIT",
                    "reason": "" if p in a.roles or p in a.paths else "NO_TASK",
                }
            if a.concurrent:
                # Reserve the entire intersecting corridor for the first route.
                # Both requests remain live; second waits at its actual start.
                first, second = tuple(a.paths)
                first_seconds = length(a.paths[first]) / 1.2
                self.positions[first] = sample(a.paths[first], min(1, self.part / first_seconds))
                self.positions[second] = sample(
                    a.paths[second],
                    max(0, (self.part - first_seconds) / (a.seconds - first_seconds)),
                )
                if self.part <= first_seconds:
                    self.person_state[second] = {
                        "task": "CROSSING",
                        "state": "YIELD",
                        "reason": "CORRIDOR_RESERVED:" + first,
                    }
            else:
                for n, path in a.paths.items():
                    self.positions[n] = a.position(n, self.part / a.seconds)
            self.status, self.blocked = "RUNNING", None
            if self.part >= a.seconds:
                for n, path in a.paths.items():
                    self.positions[n] = path[-1]
                self._effect(a.finish)
                self.events.append(
                    {
                        "time": self.elapsed,
                        "finish": a.label,
                        "slots": dict(self.slots),
                        "support": dict(self.support),
                    }
                )
                self.index += 1
                following = self.action.holds if self.action else {}
                for resource, owner in a.holds.items():
                    if following.get(resource) != owner:
                        del self.owners[resource]
                self.part, self._entered = 0, False
                if not self.action:
                    self.status = "COMPLETE_GEOMETRY_ONLY"
        except ValueError as exc:
            self.status, self.blocked = "BLOCKED", str(exc)
        return self.snapshot()
