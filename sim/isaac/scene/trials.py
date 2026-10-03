"""Deterministic T1-T4 scene rehearsals; no DispatchCommand or ExecutionEvent.

One trial owns one continuous inspection timeline. Changing trial resets all
state explicitly. USD adapter supplies actual bounds/readback at every step.
"""

import copy
import math
from dataclasses import dataclass

from .layout import MATERIAL_PATHS, PERSON_STATIONS, check_site, person_home, person_path
from .model import ZONES, Box, Transfer, require, sweep

TRIALS = ("T1", "T2", "T3", "T4")


def validate_placements(entities):
    require(all(v["zone"] in ZONES for v in entities.values()), "UNKNOWN_PLACEMENT")
    for zone, capacity in (("J2", 1), ("BUF", 2), ("J3", 1), ("F1", 1), ("Q1", 1), ("OUT1", 1)):
        occupants = [v for v in entities.values() if v["zone"] == zone]
        used = len(occupants) if zone == "BUF" else len({v["product"] for v in occupants})
        require(used <= capacity, "CAPACITY:" + zone)
    for key, item in entities.items():
        require(item["product"] == key.split(".")[0], "CROSS_PRODUCT_COMPONENT:" + key)


@dataclass(frozen=True)
class Action:
    label: str
    actor: str | None = None
    points: tuple = ()
    size: tuple = (0, 0, 0)
    height: float = 0
    equipment: str | None = None
    claim: tuple = ()
    release: tuple = ()
    seconds: float = 2


class Rehearsal:
    def __init__(self, name, people):
        require(name in TRIALS, "UNKNOWN_TRIAL")
        self.name, self.people = name, tuple(people)
        self.reset()

    def reset(self):
        self.elapsed = self.part_elapsed = 0.0
        self.index = 0
        self.paused = False
        self.speed = 1.0
        self.status = "READY"
        self.blocked = None
        self.owners = {}
        self.events = []
        self.positions = {p: person_home(i) for i, p in enumerate(self.people)}
        self.positions.update(WELD1=(12, 10, 0), TEST1=(31, 26, 0))
        self.fixture = "initial" if self.name in ("T1", "T3") else "structure"
        self.actions = []
        self._entered = False
        self.product_positions = {}
        if self.name == "T1":
            actor = "PRODUCT-1.BOTTOM"
            self.positions[actor] = MATERIAL_PATHS["steel_to_input"][0]
            self.add_path(
                "STEEL TO PRE INPUT / SCN CARRIER",
                actor,
                MATERIAL_PATHS["steel_to_input"],
                (6, 0.8, 0.2),
                0.1,
            )
            self.walk("P1", PERSON_STATIONS["P1"])
            self.add_path(
                "CUT INPUT FEED",
                actor,
                MATERIAL_PATHS["cut_feed"],
                (6, 0.8, 0.2),
                0.1,
                claim=("CUT1",),
            )
            self.actions.append(
                Action("CUT SHAPE ABSTRACT / NO CUTTING PHYSICS", seconds=3, release=("CUT1",))
            )
            self.add_path(
                "CUT OUTPUT / KIT HANDOFF",
                actor,
                MATERIAL_PATHS["cut_to_output"],
                (6, 0.8, 0.2),
                0.1,
            )
            move = Transfer("HST1", (6, 7.5, 0.6), (16, 7.5, 0.6), (6, 0.8, 0.8), 2)
            self.walk("Lrig", (9, 14.7, 0))
            self.walk("Lsig", (10, 14.7, 0))
            self.positions["HST1"] = (16, 4, 0)
            self.add_path(
                "HST1 EMPTY APPROACH",
                "HST1",
                [(16, 4, 0), (6, 4, 0), (6, 7.5, 0)],
                (6.6, 3.7, 0.2),
                5.5,
                "HST1_EMPTY",
            )
            self.actions.append(Action("HST1 RIG / P1 LRIG LSIG", claim=("HST1", "SCN-X-SUPPLY")))
            self.add_path("HST1 PRE TO J2", actor, move.points, (6, 0.8, 0.8), 0.4, "HST1")
            self.actions.append(Action("HST1 LAND / UNHOOK", release=("SCN-X-SUPPLY",)))
            self.add_path(
                "HST1 EMPTY RETURN",
                "HST1",
                [(16, 7.5, 0), (16, 4, 0), (6, 4, 0)],
                (6.6, 3.7, 0.2),
                5.5,
                "HST1_EMPTY",
                release=("HST1",),
            )
        elif self.name == "T2":
            self.positions["PRODUCT-1"] = (36, 10, 0.6)
            self.actions.append(Action("CR1 RESERVED / PEOPLE APPROACH", claim=("CR1",)))
            for who, dest in (("Lop", (42, 15, 0)), ("Lrig", (31, 8, 0)), ("Lsig", (31, 13, 0))):
                self.walk(who, dest)
            self.actions.append(Action("RIG AT SOURCE / MOTION STOPPED", seconds=3))
            for who, start, end in (
                ("Lrig", (31, 8, 0), (30.5, 8, 0)),
                ("Lsig", (31, 13, 0), (30.5, 13, 0)),
            ):
                self.add_path("WITHDRAW " + who, who, [start, end], (0.6, 0.6, 1.9), 0.95)
            self.actions.append(Action("PEOPLE CLEAR / CR1 ATTACHED", claim=("SCN-X-MODULE",)))
            move = Transfer("CR1", (36, 10, 0.6), (36, 24, 0.6), (6, 3, 3.8), 8, 1)
            self.add_path("CR1 J3 TO F1", "PRODUCT-1", move.points, (6, 3, 3.8), 1.9, "CR1")
            self.actions.append(Action("LOAD LANDED / UNHOOK", seconds=3))
            self.positions["SCN-EMPTY-HOOK"] = (36, 24, 3.8)
            self.add_path(
                "CR1 EMPTY RETURN",
                "SCN-EMPTY-HOOK",
                [(36, 24, 3.8), (36, 24, 5.2), (36, 17, 5.2), (36, 10, 5.2)],
                (6, 3, 0.6),
                0.3,
                "CR1_EMPTY",
                release=("SCN-X-MODULE", "CR1"),
            )
        elif self.name == "T3":
            self.actions.append(Action("WELD1 DISCONNECT / TRANSFER EXCLUSIVE", claim=("WELD1",)))
            self.add_path(
                "WELD1 J2 TO J3", "WELD1", MATERIAL_PATHS["weld_j2_j3"], (2.6, 1.2, 1.5), 0.75
            )
            self.actions.append(Action("WELD1 POSITION / TOOL PREP / NO WELD RECEIPT", seconds=3))
            self.positions["SCN-MEP-BATCH"] = MATERIAL_PATHS["mep_to_f1"][0]
            self.add_path(
                "SCN MEP CARRIER TO F1",
                "SCN-MEP-BATCH",
                MATERIAL_PATHS["mep_to_f1"],
                (1.2, 0.8, 0.7),
                0.35,
                claim=("SCN-X-SUPPLY",),
                release=("SCN-X-SUPPLY",),
            )
            self.add_path(
                "TEST1 DELIVERY / SET",
                "TEST1",
                MATERIAL_PATHS["test_delivery"],
                (0.8, 0.55, 1.3),
                0.65,
                claim=("TEST1",),
            )
            self.actions.append(Action("TEST1 HELD / PERSON RELEASED / QUALITY UNKNOWN", seconds=6))
            self.add_path(
                "TEST1 RETRIEVE",
                "TEST1",
                list(reversed(MATERIAL_PATHS["test_delivery"])),
                (0.8, 0.55, 1.3),
                0.65,
                release=("TEST1", "WELD1"),
            )
        else:
            self.positions["PRODUCT-1"] = (36, 10, 0.6)
            self.positions["SCN-PRODUCT-2"] = (26, 24, 0.6)
            self.product_positions = {"PRODUCT-1": "J3", "SCN-PRODUCT-2": "Q1"}
            for actor, source, target in (
                ("PRODUCT-1", (36, 10, 0.6), (36, 24, 0.6)),
                ("SCN-PRODUCT-2", (26, 24, 0.6), (16, 24, 0.6)),
            ):
                if actor == "SCN-PRODUCT-2":
                    self.positions["SCN-EMPTY-HOOK"] = (36, 24, 3.8)
                    self.add_path(
                        "CR1 EMPTY REPOSITION BETWEEN PRODUCTS",
                        "SCN-EMPTY-HOOK",
                        [(36, 24, 3.8), (36, 24, 5.2), (26, 24, 5.2), (26, 24, 3.8)],
                        (6, 3, 0.6),
                        0.3,
                        "CR1_EMPTY",
                        claim=("CR1",),
                        release=("CR1",),
                    )
                self.actions.append(
                    Action(actor + " REQUEST CR1 / OTHER WAITS", claim=("CR1", "SCN-X-MODULE"))
                )
                move = Transfer("CR1", source, target, (6, 3, 3.8), 8, 1)
                self.add_path(actor + " MOVE", actor, move.points, (6, 3, 3.8), 1.9, "CR1")
                self.actions.append(
                    Action(actor + " LANDED / RELEASE", release=("CR1", "SCN-X-MODULE"))
                )
        self.initial = copy.deepcopy(self.positions)

    def add_path(self, label, actor, points, size, height, equipment=None, claim=(), release=()):
        points = tuple(tuple(p) for p in points)
        check_site(points, size)
        distance = sum(math.dist(a, b) for a, b in zip(points, points[1:]))
        limits = (
            (2.5, 2.5, 0.5)
            if equipment
            else (1.4, 1.4, 0.5)
            if actor in self.people
            else (0.8, 0.8, 0.3)
        )
        duration = max(
            3,
            distance * 2,
            max(
                1.875 * abs(a[i] - b[i]) * (len(points) - 1) / limits[i]
                for a, b in zip(points, points[1:])
                for i in range(3)
            ),
        )
        self.actions.append(
            Action(label, actor, points, size, height, equipment, claim, release, duration)
        )

    def walk(self, who, destination):
        self.add_path(
            "WALK " + who,
            who,
            person_path(self.people.index(who), destination),
            (0.6, 0.6, 1.9),
            0.95,
        )

    def claim(self, resource, owner):
        require(resource not in self.owners, "RESOURCE_BUSY:" + resource)
        self.owners[resource] = owner

    def snapshot(self):
        return copy.deepcopy(
            {
                "trial": self.name,
                "index": self.index,
                "elapsed": self.elapsed,
                "part_elapsed": self.part_elapsed,
                "status": self.status,
                "positions": self.positions,
                "owners": self.owners,
                "quality": "UNKNOWN",
                "production_receipt": False,
                "blocked": self.blocked,
                "paused": self.paused,
            }
        )

    @property
    def action(self):
        return self.actions[self.index] if self.index < len(self.actions) else None

    def advance(self, dt, obstacles=(), single_step=False):
        require(math.isfinite(dt) and dt >= 0, "INVALID_DT")
        if (self.paused and not single_step) or not self.action:
            return self.snapshot()
        a = self.action
        try:
            if a.points:
                centers = [(x, y, z + a.height) for x, y, z in a.points]
                sweep(centers, a.size, obstacles)
                if a.equipment and a.equipment.startswith("HST1"):
                    for dx in (-3.25, 3.25):
                        for dy in (-1.7, 1.7):
                            sweep(
                                [(p[0] + dx, p[1] + dy, 2.75) for p in a.points],
                                (0.12, 0.12, 5.5),
                                obstacles,
                            )
                    sweep([(p[0], p[1], 5.5) for p in a.points], (6.6, 3.7, 0.2), obstacles)
                if a.equipment and a.equipment.startswith("CR1"):
                    for y in (0.75, 30.5):
                        sweep([(p[0], y, 4) for p in a.points], (4, 1.5, 8), obstacles)
            for resource in a.release:
                require(
                    (not self._entered and resource in a.claim)
                    or self.owners.get(resource) == self.name,
                    "WRONG_RELEASE:" + resource,
                )
            if not self._entered:
                if a.actor:
                    require(
                        math.dist(self.positions[a.actor], a.points[0]) < 1e-8,
                        "DISCONTINUOUS_START",
                    )
                for resource in a.claim:
                    require(resource not in self.owners, "RESOURCE_BUSY:" + resource)
                for resource in a.claim:
                    self.claim(resource, self.name)
                self._entered = True
                self.events.append({"time": self.elapsed, "start": a.label})
            step = min(dt * self.speed, a.seconds - self.part_elapsed)
            self.part_elapsed += step
            self.elapsed += step
            if a.actor:
                u = min(
                    self.part_elapsed / a.seconds * (len(a.points) - 1), len(a.points) - 1 - 1e-12
                )
                i, f = int(u), u - int(u)
                f = f * f * f * (10 + f * (-15 + 6 * f))
                self.positions[a.actor] = tuple(
                    x + (y - x) * f for x, y in zip(a.points[i], a.points[i + 1])
                )
                if a.equipment == "HST1":
                    self.positions["HST1"] = (*self.positions[a.actor][:2], 0)
            self.status, self.blocked = "RUNNING", None
            if self.part_elapsed >= a.seconds:
                if a.actor:
                    self.positions[a.actor] = a.points[-1]
                for resource in a.release:
                    require(self.owners.get(resource) == self.name, "WRONG_RELEASE:" + resource)
                    del self.owners[resource]
                self.events.append({"time": self.elapsed, "finish": a.label})
                self.index += 1
                self.part_elapsed = 0
                self._entered = False
                if not self.action:
                    self.status = "COMPLETE_GEOMETRY_ONLY"
        except ValueError as exc:
            self.status, self.blocked = "BLOCKED", str(exc)
        return self.snapshot()


def actor_box(name, position, size=(0.6, 0.6, 1.9)):
    return Box(name, (position[0], position[1], position[2] + size[2] / 2), size)
