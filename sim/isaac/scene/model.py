"""Pure, inspectable S13 scene semantics. Never emits production events.

Positions are metres; rotations are degrees; masses are kg after conversion.
All dimensions beyond the frozen product envelope are research assumptions.
"""

import copy
import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path

ZONES = {
    "PRE": (6, 10),
    "J2": (16, 10),
    "BUF": (26, 10),
    "J3": (36, 10),
    "F1": (36, 24),
    "Q1": (26, 24),
    "OUT1": (16, 24),
}
EQUIPMENT = {
    "CUT1": "MANUAL_CUTTER",
    "WELD1": "MANUAL_WELDER",
    "R1": "ROBOT",
    "HST1": "COMPONENT_HOIST_FORM_UNKNOWN",
    "CR1": "OPERATED_GANTRY",
    "TEST1": "SHARED_TEST_GROUP",
}
FIXTURES = (
    "initial",
    "dual_frame",
    "joining",
    "structure",
    "mep_wait",
    "sr_w2",
    "quarantine",
    "outbound",
    "manual_weld",
    "robot_demo",
)
AXES = ("Z", "Y", "Y", "X", "Y", "X")
LINKS = ((0, 0, 0.65), (0.85, 0, 0), (0.75, 0, 0), (0.22, 0, 0), (0.18, 0, 0), (0.25, 0, 0))
LIMITS = ((-170, 170), (-90, 90), (-135, 135), (-180, 180), (-120, 120), (-180, 180))
ROBOT_BASE = (20.8, 10, 0.5)
POSES = ((0, -35, 65, 0, -20, 0), (20, -45, 75, 15, -25, 20), (-20, -25, 50, -15, -15, -20))


def require(value, message):
    if not value:
        raise ValueError(message)


def key(domain_id):
    return "id_" + domain_id.encode("utf-8").hex()


def load_config(path):
    raw = Path(path).read_bytes()
    config = json.loads(raw)
    require(
        config["units"]["length"] == "m"
        and config["units"]["mass"] == "t"
        and config["units"]["time"] == "h",
        "UNIT_MISMATCH",
    )
    ids = [
        x["id"]
        for group in ("resources", "people", "products", "components")
        for x in config[group]
    ]
    require(len(ids) == len(set(ids)), "DUPLICATE_ID")
    resources = {r["id"]: r for r in config["resources"]}
    expected = set(ZONES) | set(EQUIPMENT) | {"FIX-J2", "FIX-J3", "ROUTE-COMP", "ROUTE-MODULE"}
    require(set(resources) == expected, "RESOURCE_SET")
    require(
        {r["id"] for r in resources.values() if r["kind"] == "EQUIPMENT"} == set(EQUIPMENT),
        "EQUIPMENT_IDENTITY",
    )
    require(
        {r["id"] for r in resources.values() if r["kind"] == "FIXTURE"} == {"FIX-J2", "FIX-J3"},
        "FIXTURE_IDENTITY",
    )
    require(
        resources["BUF"]["capacity"] == 2
        and all(resources[n]["capacity"] == 1 for n in expected - {"BUF"}),
        "CAPACITY",
    )
    require(resources["HST1"]["load_t"] == 3 and resources["CR1"]["load_t"] == 12, "LOAD")
    require(len(config["products"]) == 1, "S13_SINGLE_PRODUCT_FIXTURE")
    require([c["quantity"] for c in config["components"]] == [1, 1, 4], "COMPONENT_QUANTITY")
    config["source_sha256"] = hashlib.sha256(raw).hexdigest()
    return config


@dataclass(frozen=True)
class Box:
    name: str
    center: tuple
    size: tuple

    def overlaps(self, other, margin=0):
        return all(
            # USD float dimensions introduce ~1e-8 m rounding at intended contact.
            # One micrometre is numerical contact tolerance, not safety clearance.
            abs(a - b) < (s + t) / 2 + margin - 1e-6
            for a, b, s, t in zip(self.center, other.center, self.size, other.size, strict=True)
        )


def sweep(points, size, obstacles, margin=0):
    """Continuous conservative AABB sweep of each axis-aligned segment."""
    require(len(points) >= 2, "EMPTY_ROUTE")
    for start, end in zip(points, points[1:]):
        require(sum(abs(a - b) > 1e-9 for a, b in zip(start, end)) <= 1, "NON_AXIS_ROUTE")
        box = Box(
            "sweep",
            tuple((a + b) / 2 for a, b in zip(start, end)),
            tuple(s + abs(a - b) for s, a, b in zip(size, start, end)),
        )
        for obstacle in obstacles:
            require(not box.overlaps(obstacle, margin), "COLLISION:" + obstacle.name)


def matmul(a, b):
    return [[sum(a[i][k] * b[k][j] for k in range(4)) for j in range(4)] for i in range(4)]


def identity():
    return [[float(i == j) for j in range(4)] for i in range(4)]


def fk(angles):
    require(len(angles) == 6, "SIX_JOINTS_REQUIRED")
    t = identity()
    for i, v in enumerate(ROBOT_BASE):
        t[i][3] = v
    points = [ROBOT_BASE]
    for angle, axis, link, limit in zip(angles, AXES, LINKS, LIMITS, strict=True):
        require(math.isfinite(angle) and limit[0] <= angle <= limit[1], "JOINT_LIMIT")
        c, s = math.cos(math.radians(angle)), math.sin(math.radians(angle))
        r = identity()
        i, j = {"X": (1, 2), "Y": (2, 0), "Z": (0, 1)}[axis]
        r[i][i], r[j][j], r[i][j], r[j][i] = c, c, -s, s
        tr = identity()
        for k, v in enumerate(link):
            tr[k][3] = v
        t = matmul(matmul(t, r), tr)
        points.append(tuple(t[k][3] for k in range(3)))
    return t, points


def robot_check(angles, obstacles=()):
    transform, points = fk(angles)
    # Enclosing link boxes are conservative, including revolute joint housings.
    boxes = []
    for index, (a, b) in enumerate(zip(points, points[1:])):
        box = Box(
            f"link{index + 1}",
            tuple((x + y) / 2 for x, y in zip(a, b)),
            tuple(abs(x - y) + 0.18 for x, y in zip(a, b)),
        )
        for obstacle in obstacles:
            require(not box.overlaps(obstacle), "ROBOT_COLLISION:" + obstacle.name)
        boxes.append(box)
    for i, left in enumerate(boxes):
        for right in boxes[i + 3 :]:
            require(not left.overlaps(right), "ROBOT_SELF_COLLISION")
    return transform


def reachable_bound(target):
    return math.dist(target, ROBOT_BASE) <= sum(math.dist((0, 0, 0), x) for x in LINKS)


def phase_record(config, code, mode_kind=None, unit=0):
    activity = next(a for a in config["activities"] if a["code"] == code)
    mode = next(m for m in activity["modes"] if mode_kind is None or m["kind"] == mode_kind)
    work = mode["units"][unit] if mode["units"] else None
    return {
        "code": code,
        "mode": mode["kind"],
        "unit": unit,
        "people": sorted(r["id"] for r in work["roles"]) if work else [],
        "equipment": sorted(work["equipment"]) if work else [],
        "person_state": "WORK" if work and work["roles"] else "UNASSIGNED",
        "declared_seconds": (work["base_h"] if work else activity["wait_h"]) * 3600,
        "production_receipt": False,
        "quality": "UNKNOWN",
    }


def check_phase(config, record):
    expected = phase_record(config, record["code"], record["mode"], record["unit"])
    require(record == expected, "PHASE_RESPONSIBILITY_OR_STATE")
    return True


class SceneState:
    """Synthetic inspection state, deliberately separate from the execution kernel."""

    def __init__(self, config, fixture="initial"):
        require(fixture in FIXTURES, "UNKNOWN_FIXTURE")
        self.config, self.fixture = config, fixture
        self.reset()

    def reset(self):
        p = self.config["products"][0]["id"]
        self.product_id = p
        self.entities = {
            c["id"]: {
                "product": p,
                "kind": c["kind"],
                "location": "PRE",
                "position": (6, 7.5 + i * 2.5, 0.6),
                "mass_kg": c["mass_t"] * 1000,
                "quantity": c["quantity"],
            }
            for i, c in enumerate(self.config["components"])
        }
        self.owners = {}
        self.phase = None
        self.route = None
        self.quality = "UNKNOWN"
        self.joints = list(POSES[0])
        self.velocities = {k: (0, 0, 0) for k in self.entities}
        self.wall_visible = True
        self.faces = []
        if self.fixture in ("dual_frame", "manual_weld", "robot_demo"):
            for part, y in (("BOTTOM", 7.5), ("TOP", 12.5)):
                self.place(p + "." + part, "J2", (16, y, 0.6))
            self.owners["FIX-J2"] = p + ".BOTTOM"
            self.owners["WELD1" if self.fixture != "robot_demo" else "R1"] = p
            self.phase = phase_record(
                self.config, "W-B", "HR-seq" if self.fixture == "robot_demo" else "H"
            )
        elif self.fixture == "joining":
            self.place(p + ".BOTTOM", "J3", (36, 7.5, 0.6))
            self.place(p + ".TOP", "BUF", (26, 12.5, 0.6))
        elif self.fixture in ("structure", "mep_wait", "sr_w2", "quarantine", "outbound"):
            for part, z in (("BOTTOM", 0.6), ("TOP", 3.6), ("COLUMNS", 0.8)):
                self.place(p + "." + part, "J3", (36, 10, z))
            self.merge()
            location = {"structure": "J3", "quarantine": "Q1", "outbound": "OUT1"}.get(
                self.fixture, "F1"
            )
            self.place(p, location, (*ZONES[location], 0.6))
            if self.fixture in ("mep_wait", "sr_w2"):
                self.faces = ["WET"]
                self.owners["TEST1"] = p
                self.phase = phase_record(self.config, "WAIT-TEST")
        self.validate()

    def place(self, entity, location, position):
        require(entity in self.entities and location in ZONES, "UNKNOWN_PLACEMENT")
        previous = copy.deepcopy(self.entities[entity])
        self.entities[entity].update(location=location, position=tuple(position))
        try:
            self.validate()
        except ValueError:
            self.entities[entity] = previous
            raise

    def validate(self):
        require(self.quality == "UNKNOWN", "NO_SYNTHETIC_QUALITY_PASS")
        for zone in ZONES:
            occupants = [e for e in self.entities.values() if e["location"] == zone]
            require(
                len(occupants) <= 2
                if zone == "BUF"
                else len({e["product"] for e in occupants}) <= 1,
                "CAPACITY:" + zone,
            )
        for name, entity in self.entities.items():
            require(entity["location"] in ZONES, "UNKNOWN_LOCATION")
            x, y = ZONES[entity["location"]]
            px, py, _ = entity["position"]
            sx, sy = (1.6, 1.6) if entity["kind"] == "COLUMNS" else (6, 3)
            require(
                abs(px - x) + sx / 2 <= 4 + 1e-8 and abs(py - y) + sy / 2 <= 4 + 1e-8,
                "BAY_CONTAINMENT:" + name,
            )
        if self.product_id in self.entities:
            require(
                not any(k.startswith(self.product_id + ".") for k in self.entities),
                "MERGE_DUPLICATE",
            )
            require(len(self.entities[self.product_id].get("lineage", [])) == 3, "LINEAGE")
        for owner in self.owners.values():
            require(isinstance(owner, str), "EXCLUSIVE_RESOURCE")
        if self.phase:
            check_phase(self.config, self.phase)
            if self.phase["code"] == "WAIT-TEST":
                require(self.owners.get("TEST1") == self.product_id, "TEST_HOLD")
        return True

    def claim(self, resource, owner):
        require(resource not in self.owners, "RESOURCE_BUSY:" + resource)
        self.owners[resource] = owner

    def merge(self):
        members = [self.product_id + "." + s for s in ("BOTTOM", "TOP", "COLUMNS")]
        require(
            all(k in self.entities and self.entities[k]["location"] == "J3" for k in members),
            "MERGE_NOT_LANDED",
        )
        mass = sum(self.entities[k]["mass_kg"] for k in members)
        for k in members:
            del self.entities[k]
        self.entities[self.product_id] = {
            "product": self.product_id,
            "kind": "MODULE",
            "location": "J3",
            "position": (36, 10, 0.6),
            "mass_kg": mass,
            "quantity": 1,
            "lineage": members,
        }
        self.velocities = {self.product_id: (0, 0, 0)}
        self.validate()

    def snapshot(self):
        return copy.deepcopy(
            {
                "entities": self.entities,
                "owners": self.owners,
                "route": self.route,
                "quality": self.quality,
                "joints": self.joints,
                "velocities": self.velocities,
                "faces": self.faces,
                "wall_visible": self.wall_visible,
                "phase": self.phase,
            }
        )


class Transfer:
    """S13 kinematic inspection only. No scheduling or production acknowledgement."""

    def __init__(self, equipment, source, target, size, mass_t, rigging_t=0, obstacles=()):
        require(equipment in ("HST1", "CR1"), "NOT_LIFT_EQUIPMENT")
        require(
            mass_t > 0
            and rigging_t >= 0
            and mass_t + rigging_t <= (3 if equipment == "HST1" else 12),
            "OVERLOAD",
        )
        require(all(math.isfinite(v) for v in (*source, *target, *size)), "NONFINITE")
        self.equipment, self.source, self.target, self.size = (
            equipment,
            tuple(source),
            tuple(target),
            tuple(size),
        )
        # Root is bottom-center; conservative envelope includes rigging above load.
        travel_z = 4.2 if equipment == "HST1" else 1.0
        lane = 4 if equipment == "HST1" else 17
        self.points = [
            self.source,
            (source[0], source[1], travel_z),
            (source[0], lane, travel_z),
            (target[0], lane, travel_z),
            (target[0], target[1], travel_z),
            self.target,
        ]
        self.duration_seconds = 120.0  # inspection clock, not production duration
        self.speed_limits_m_s = (2.5, 2.5, 0.5)
        segment_seconds = self.duration_seconds / (len(self.points) - 1)
        self.peak_speed_m_s = tuple(
            max(
                1.875 * abs(a[axis] - b[axis]) / segment_seconds
                for a, b in zip(self.points, self.points[1:])
            )
            for axis in range(3)
        )
        require(
            all(v <= limit for v, limit in zip(self.peak_speed_m_s, self.speed_limits_m_s)),
            "KINEMATIC_SPEED_LIMIT",
        )
        for point in self.points:
            if equipment == "CR1":
                require(
                    4 <= point[0] <= 38
                    and 6.5 <= point[1] <= 27.5
                    and 1 <= point[2] + size[2] <= 7,
                    "GANTRY_TRAVEL",
                )
        centers = [(x, y, z + size[2] / 2) for x, y, z in self.points]
        sweep(centers, size, obstacles)
        if equipment == "CR1":
            for y in (0.75, 30.5):
                sweep([(p[0], y, 4) for p in self.points], (4, 1.5, 8), obstacles)
        self.state, self.attached, self.position, self.progress = (
            "RESERVED",
            False,
            self.source,
            0.0,
        )
        self.reservation = self.target

    def attach(self):
        require(self.state == "RESERVED", "ATTACH_STATE")
        self.attached = True
        self.state = "ATTACHED"

    def sample(self, fraction):
        require(self.attached and self.state != "RELEASED", "NOT_ATTACHED")
        require(self.progress <= fraction <= 1, "NON_MONOTONE_ROUTE")
        count = len(self.points) - 1
        scaled = min(fraction * count, count - 1e-12)
        index = int(scaled)
        u = scaled - index
        smooth = u * u * u * (10 + u * (-15 + 6 * u))
        self.position = tuple(
            a + (b - a) * smooth for a, b in zip(self.points[index], self.points[index + 1])
        )
        self.progress, self.state = fraction, "IN_TRANSIT"
        return self.position

    def land(self, actual_position, actual_yaw=0):
        require(
            self.attached
            and self.progress == 1
            and math.dist(actual_position, self.target) <= 0.01
            and abs(actual_yaw) <= 0.1,
            "ARRIVAL_MISMATCH",
        )
        self.state = "LANDED"

    def detach(self):
        require(self.state == "LANDED", "NOT_LANDED")
        self.attached, self.state = False, "RELEASED"
