"""S10 independent log reconstruction for C04-1.0 / C03-0.3.

Only immutable record definitions are shared with execution. No execution,
contract-validation, scheduling, or human-state predicates are imported.
Missing evidence takes precedence over a verdict; detected violations remain
in the report even when its overall status is INCOMPLETE.
"""

import hashlib
import json
import math
import types
from dataclasses import asdict, dataclass, field, fields, is_dataclass
from functools import lru_cache
from time import perf_counter
from typing import Annotated, Literal, Union, get_args, get_origin, get_type_hints

from adaptive_hrc_scheduling.domain import building as b
from adaptive_hrc_scheduling.metrics import delivery_metrics, integrate_segment

# Independent minimum requirements from the frozen C03 activity/mode tables.
# These are role slots, not a restriction on qualified replacement workers.
_CREWS = {
    "KIT": "P1",
    "CUT": "P1",
    "MV-IN-B": "P1 Lrig Lsig",
    "MV-IN-T": "P1 Lrig Lsig",
    "MV-B": "P1 Lrig Lsig",
    "MV-T": "P1 Lrig Lsig",
    "W-B": "W1",
    "W-T": "W1",
    "JOIN-IN": "Lop Lrig Lsig",
    "MOVE-F": "Lop Lrig Lsig",
    "MOVE-OUT": "Lop Lrig Lsig",
    "W-3D": "W1 W2",
    "Q-STR": "QA1 W2",
    "COAT": "C1",
    "WAIT-COAT": "QA1",
    "FLOOR": "AF1 AF2",
    "MEP-E": "E1",
    "MEP-P": "PL1",
    "Q-MEP": "QA1 E1 PL1",
    "LINING": "AF1 AF2",
    "Q-LIN": "QA1",
    "WPROOF": "T1",
    "TEST-SET": "T1",
    "Q-POND": "QA1 T1",
    "TILE": "T1 T2",
    "EXT": "AF1 AF2",
    "Q-EXT": "QA1 AF1",
    "PAINT": "C1",
    "FIT": "AF1 E1 PL1",
    "Q-FIN": "QA1 E1 PL1",
    "PACK": "P1 AF1",
    "Q-PACK": "QA1",
}
_QUALIFICATIONS = {
    "P1": "PREP",
    "W1": "WELD",
    "W2": "WELD",
    "OP1": "ROBOT",
    "AF1": "ASSEMBLE",
    "AF2": "ASSEMBLE",
    "E1": "ELECTRIC",
    "PL1": "PLUMB",
    "T1": "WET",
    "T2": "WET",
    "C1": "COAT",
    "QA1": "QA",
    "Lop": "CRANE",
    "Lrig": "RIG",
    "Lsig": "SIGNAL",
}
_EQUIPMENT = {
    "CUT": {"CUT1"},
    "W-B": {"WELD1", "FIX-J2"},
    "W-T": {"WELD1", "FIX-J2"},
    "W-3D": {"WELD1", "FIX-J3"},
    "MV-IN-B": {"HST1"},
    "MV-IN-T": {"HST1"},
    "MV-B": {"HST1"},
    "MV-T": {"HST1"},
    "JOIN-IN": {"CR1"},
    "MOVE-F": {"CR1"},
    "MOVE-OUT": {"CR1"},
    "Q-MEP": {"TEST1"},
    "TEST-SET": {"TEST1"},
    "Q-POND": {"TEST1"},
    "Q-EXT": {"TEST1"},
    "Q-FIN": {"TEST1"},
}


@dataclass
class Finding:
    rule: str
    object_id: str
    time_h: float
    code: str
    severity: str = "FAIL"
    event_id: str | None = None


@dataclass
class Report:
    status: str
    findings: list[Finding]
    metrics: dict
    reconstructed: dict
    rule_scope: dict
    report_version: str = "S10-1.1"

    def to_dict(self):
        return asdict(self)


def close(a, c):
    # Comparison only: never used to admit an early completion or release.
    return math.isclose(a, c, rel_tol=1e-10, abs_tol=1e-10)


def calendar(person, t):
    phase = t % person.calendar.period_h
    windows = person.calendar.windows
    for w in windows:
        if w.start_h <= phase < w.end_h:
            return "WAIT", t - phase + w.end_h
        if phase < w.start_h:
            return ("REST" if phase >= windows[0].end_h else "OFF_SHIFT"), t - phase + w.start_h
    return "OFF_SHIFT", t - phase + person.calendar.period_h + windows[0].start_h


def _json(text):
    def pairs(items):
        result = {}
        for k, v in items:
            if k in result:
                raise ValueError("duplicate JSON member")
            result[k] = v
        return result

    return json.loads(
        text, object_pairs_hook=pairs, parse_constant=lambda x: (_ for _ in ()).throw(ValueError(x))
    )


@lru_cache(maxsize=None)
def _hints(kind):
    return get_type_hints(kind, include_extras=True)


def _shape(value, kind):
    """Independent structural boundary and canonical numeric normalization."""
    origin, args = get_origin(kind), get_args(kind)
    if origin is Annotated:
        result = _shape(value, args[0])
        # Metadata names belong to immutable types; inequalities are local.
        if "nonnegative" in args and result < 0 or "positive" in args and result <= 0:
            raise ValueError("numeric bound")
        return result
    if origin is Literal:
        if value not in args or isinstance(value, bool):
            raise ValueError("literal")
        return value
    if origin in (types.UnionType, Union):
        for option in args:
            try:
                return _shape(value, option)
            except (ValueError, TypeError):
                pass
        raise ValueError("union")
    if origin is tuple:
        if not isinstance(value, tuple):
            raise ValueError("tuple")
        return [_shape(x, args[0]) for x in value]
    if is_dataclass(kind):
        if type(value) is not kind:
            raise ValueError("record type")
        hints = _hints(kind)
        return {f.name: _shape(getattr(value, f.name), hints[f.name]) for f in fields(kind)}
    if kind is float:
        if type(value) not in (int, float) or not math.isfinite(value):
            raise ValueError("finite number")
        return float(value)
    if type(value) is not kind and not (kind is type(None) and value is None):
        raise ValueError("primitive type")
    return value


@dataclass
class _Attempt:
    number: int
    mode: str
    units: int = 0
    complete: bool = False
    invalid: bool = False
    waiting: float | None = None
    released: bool = False
    roles: dict = field(default_factory=dict)
    state: str = "NOT_READY"
    prepared: bool = False


class _Audit:
    def __init__(self, config, snapshot, window):
        self.c, self.s, self.window = config, snapshot, window
        self.findings = []
        self.event = None
        self.t = 0.0
        self.a = {a.id: a for a in config.activities}
        self.p = {p.id: p for p in config.products}
        self.people = {p.id: p for p in config.people}
        self.resources = {r.id: r for r in config.resources}
        self.evidence = {e.id: e for e in config.evidence}
        self.components = {c.id: c for c in config.components}
        self.materials = {m.id: m for m in config.materials}
        self.material_state = {
            m.id: [m.arrived, m.identified, m.released, None] for m in config.materials
        }
        self.locations = {
            **{p.id: "UNASSEMBLED" for p in config.products},
            **{c.id: "UNFABRICATED" for c in config.components},
        }
        self.residencies = set()
        self.locks = {}
        self.attempts = {}
        self.attempt_history = {}
        self.product_states = {p.id: "RELEASED" for p in config.products}
        self.running = {}
        self.services = {}
        self.spans = []
        self.rests = []
        self.units = []
        self.quality = {}
        self.ready, self.received, self.cancelled = {}, {}, {}
        self.failed, self.held, self.released = set(), set(), set()
        self.installed = {p.id: set() for p in config.products}
        self.water = set()
        self.moves = {}
        self.transits = set()
        self.handovers = set()
        self.repaired = set()
        self.external_ids = set()
        self.external_facts = {}
        self.occupancy = {r.id: 0.0 for r in config.resources if r.kind in ("BAY", "BUFFER")}
        self.wip = 0.0
        self.wait_hours = 0.0
        self.move_count = 0
        self.move_hours = 0.0
        self.repair_hours = 0.0
        self.pending_waits = []
        self.idle_residency = 0.0

    def remember_attempt(self, aid, attempt):
        self.attempts[aid] = attempt
        self.attempt_history[aid, attempt.number] = attempt
        return attempt

    def current_attempt(self, aid, mode):
        if aid not in self.attempts:
            return self.remember_attempt(aid, _Attempt(0, mode))
        return self.attempts[aid]

    def issue(self, rule, obj, code, incomplete=False, time=None):
        item = Finding(
            rule,
            obj,
            self.t if time is None else time,
            code,
            "INCOMPLETE" if incomplete else "FAIL",
            self.event.id if self.event else None,
        )
        if item not in self.findings:
            self.findings.append(item)

    def need(self, condition, rule, obj, code, incomplete=False):
        if not condition:
            self.issue(rule, obj, code, incomplete)
        return condition

    def evidence_ok(self, ids, revisions=None, rule="R18", obj=None):
        obj = obj or (self.event.entity_id if self.event else self.c.id)
        self.need(bool(ids), rule, obj, "MISSING_QUALIFICATION_BINDINGS")
        if revisions is not None:
            self.need(len(ids) == len(revisions), rule, obj, "QUALIFICATION_BINDING")
        valid = bool(ids)
        for i, eid in enumerate(ids):
            e = self.evidence.get(eid)
            ok = e is not None and e.status == "PASS" and e.basis != "UNRESOLVED"
            if e and e.basis == "SYNTHETIC_TEST":
                ok = ok and self.c.purpose == "SYNTHETIC_TEST_ONLY"
            if revisions is not None:
                ok = ok and i < len(revisions) and e is not None and e.revision == revisions[i]
            self.need(ok, rule, obj, "QUALIFICATION:" + eid)
            valid = valid and ok
        return valid

    def configuration(self):
        c = self.c
        self.need(
            c.schema_version == "C04-1.0"
            and c.specification == "C03-0.3"
            and asdict(c.units)
            == {"time": "h", "rate": "h^-1", "exposure": "F.h", "mass": "t", "length": "m"},
            "R18",
            c.id,
            "VERSION_OR_UNITS",
        )
        self.need(
            self.s.schema_version == c.schema_version and self.s.config_id == c.id,
            "R18",
            c.id,
            "SNAPSHOT_VERSION",
        )
        canonical = (
            json.dumps(
                _shape(c, b.Configuration),
                ensure_ascii=False,
                sort_keys=True,
                indent=2,
                allow_nan=False,
            )
            + "\n"
        )
        self.need(
            hashlib.sha256(canonical.encode("utf-8")).hexdigest() == self.s.config_sha256,
            "R18",
            c.id,
            "CONFIGURATION_DIGEST",
        )
        self.need(
            math.isfinite(self.window) and self.window > 0 and self.s.time_h == self.window,
            "R17",
            c.id,
            "COMMON_WINDOW",
            True,
        )
        for rows in (
            c.products,
            c.components,
            c.materials,
            c.activities,
            c.people,
            c.resources,
            c.evidence,
        ):
            self.need(len(rows) == len({x.id for x in rows}), "R01", c.id, "DUPLICATE_ID")
        self.need(0 < c.cap <= 1 and c.min_rest_h > 0, "R10", c.id, "HUMAN_PARAMETERS")
        for p in c.people:
            self.need(
                p.calendar.period_h > 0
                and bool(p.calendar.windows)
                and all(0 <= w.start_h < w.end_h <= p.calendar.period_h for w in p.calendar.windows)
                and all(
                    x.end_h <= y.start_h for x, y in zip(p.calendar.windows, p.calendar.windows[1:])
                ),
                "R10",
                p.id,
                "CALENDAR",
            )
        required_quality = {"Q-STR", "Q-MEP", "Q-LIN", "Q-POND", "Q-EXT", "Q-FIN", "Q-PACK"}
        required_wait = {"WAIT-COAT", "WAIT-W", "WAIT-TEST", "WAIT-TILE", "WAIT-PAINT"}
        for p in c.products:
            acts = {a.code: a for a in c.activities if a.product_id == p.id}
            codes = {code for edge in b.STEEL_EDGES for code in edge[:2]}
            self.need(
                set(acts) == codes and len(acts) == sum(a.product_id == p.id for a in c.activities),
                "R18",
                p.id,
                "FROZEN_ACTIVITY_SET",
            )
            edges = {
                (self.a[e.source].code, self.a[e.target].code, e.relation)
                for e in c.edges
                if e.source in self.a
                and e.target in self.a
                and self.a[e.source].product_id == p.id
                and self.a[e.target].product_id == p.id
            }
            self.need(edges == set(b.STEEL_EDGES), "R02", p.id, "FROZEN_EDGES")
            for code in required_quality:
                self.need(
                    code in acts and acts[code].quality_evidence is not None,
                    "R11",
                    p.id,
                    "REQUIRED_QUALITY:" + code,
                )
            for code in required_wait:
                self.need(
                    code in acts
                    and acts[code].release_evidence is not None
                    and acts[code].wait_h > 0,
                    "R02",
                    p.id,
                    "REQUIRED_WAIT:" + code,
                )
            base = {"B-ST", "B-FL", "B-EN", "B-WT", "B-ME", "B-FI", "B-PR"}
            extra = {"B-BRANCH", "B-EXTRA-BASIN", "B-EXTRA-SOCKET"}
            self.need(
                {i.id for i in p.bom} == base | (extra if p.variant == "SR-W2" else set()),
                "R12",
                p.id,
                "VARIANT_BOM",
            )
            self.need(
                len(p.bom) == len({i.id for i in p.bom})
                and all(
                    (i.quantity, i.unit) == ((18, "m2") if i.id == "B-FL" else (1, "set"))
                    for i in p.bom
                ),
                "R12",
                p.id,
                "FROZEN_BOM_QUANTITY_UNIT",
            )
            comps = [x for x in c.components if x.product_id == p.id]
            self.need(
                sorted((x.kind, x.quantity) for x in comps)
                == [("BOTTOM", 1), ("COLUMNS", 4), ("TOP", 1)],
                "R01",
                p.id,
                "COMPONENT_BOM",
            )
            if p.variant == "SR-W2":
                for code, minimum in (("MEP-P", 4), ("Q-FIN", 3)):
                    self.need(
                        code in acts and all(len(m.units) >= minimum for m in acts[code].modes),
                        "R12",
                        p.id,
                        "VARIANT_WORK_UNITS:" + code,
                    )
        for a in c.activities:
            self.need(a.product_id in self.p, "R01", a.id, "PRODUCT_REFERENCE")
            move_codes = {"MV-IN-B", "MV-IN-T", "MV-B", "MV-T", "JOIN-IN", "MOVE-F", "MOVE-OUT"}
            expected_kinds = (
                {"H", "HR-seq"}
                if a.code in ("W-B", "W-T")
                else {
                    "MOVE"
                    if a.code in move_codes
                    else "WAIT"
                    if a.code in required_wait
                    else "GATE"
                    if a.code == "READY"
                    else "H-team"
                }
            )
            self.need(
                {m.kind for m in a.modes} == expected_kinds and len(a.modes) == len(expected_kinds),
                "R18",
                a.id,
                "FROZEN_MODE_SET",
            )
            for m in a.modes:
                self.need(bool(m.units) == (a.code in _CREWS), "R18", a.id, "FROZEN_LABOR_UNITS")
                self.need(
                    "G5" in m.qualification_ids and bool(m.qualification_revisions),
                    "R18",
                    a.id,
                    "REQUIRED_METHOD_QUALIFICATION",
                )
                if m.kind == "HR-seq":
                    required = {
                        "G2-" + x
                        for x in (
                            "JOINT",
                            "WPS",
                            "PROGRAM",
                            "FIXTURE",
                            "PEOPLE",
                            "ISOLATION",
                            "INSPECTION",
                            "OUTPUT",
                        )
                    }
                    self.need(
                        required <= set(m.qualification_ids),
                        "R03",
                        a.id,
                        "HR_EQUIVALENT_OUTPUT_BINDINGS",
                    )
                self.need(
                    a.code == "READY" or a.wait_h > 0 or bool(m.units),
                    "R18",
                    a.id,
                    "MISSING_LABOR_UNITS",
                )
                for u in m.units:
                    role_ids = set(_CREWS.get(a.code, "").split())
                    if m.kind == "HR-seq":
                        self.need(u.phase in ("SETUP", "ROBOT", "UNLOAD"), "R03", a.id, "HR_PHASE")
                        role_ids = set() if u.phase == "ROBOT" else {"OP1"}
                    required_roles = {
                        rid: "HOIST"
                        if rid == "P1" and a.code.startswith("MV-")
                        else _QUALIFICATIONS[rid]
                        for rid in role_ids
                    }
                    self.need(
                        {r.id: r.qualification for r in u.roles} == required_roles
                        and len(u.roles) == len(required_roles),
                        "R04",
                        a.id,
                        "FROZEN_ROLE_REQUIREMENTS",
                    )
                    equipment = (
                        {"R1", "FIX-J2"} if m.kind == "HR-seq" else _EQUIPMENT.get(a.code, set())
                    )
                    self.need(
                        equipment <= set(u.equipment) <= set(self.resources)
                        and len(u.equipment) == len(set(u.equipment)),
                        "R05",
                        a.id,
                        "FROZEN_EQUIPMENT_REQUIREMENTS",
                    )
                    self.need(
                        u.base_h > 0 and (u.phase == "ROBOT" or bool(u.roles)),
                        "R04",
                        a.id,
                        "LABOR_ROLES",
                    )
                    if a.code in ("W-B", "W-T", "W-3D"):
                        expected = (
                            {"R1", "FIX-J2"}
                            if m.kind == "HR-seq"
                            else {"WELD1", "FIX-J3" if a.code == "W-3D" else "FIX-J2"}
                        )
                        self.need(
                            expected <= set(u.equipment), "R05", a.id, "FROZEN_WELD_EQUIPMENT"
                        )
                    if a.code == "W-3D":
                        self.need(
                            len(u.roles) == 2 and all(r.qualification == "WELD" for r in u.roles),
                            "R04",
                            a.id,
                            "FROZEN_WELD_CREW",
                        )
                    if a.move:
                        self.need(a.move.equipment in u.equipment, "R08", a.id, "MOVE_EQUIPMENT")
            for mid in a.material_ids:
                mat = self.materials.get(mid)
                self.need(
                    mat is not None and mat.product_id == a.product_id and mat.activity_id == a.id,
                    "R12",
                    a.id,
                    "MATERIAL_IDENTITY",
                )

    def ancestors(self, aid):
        found = set()
        pending = [aid]
        while pending:
            item = pending.pop()
            for edge in self.c.edges:
                if edge.target == item and edge.source not in found:
                    found.add(edge.source)
                    pending.append(edge.source)
        return found

    def prerequisites(self, aid):
        for prev in self.ancestors(aid):
            att = self.attempts.get(prev)
            if not self.need(att is not None, "R02", aid, "MISSING_PREDECESSOR:" + prev, True):
                continue
            self.need(att.complete and not att.invalid, "R02", aid, "PREDECESSOR:" + prev)
            if self.a[prev].quality_evidence:
                q = self.quality.get((prev, att.number))
                self.need(q is not None, "R02", aid, "MISSING_QUALITY:" + prev, True)
                if q:
                    self.need(
                        q["result"] == "PASS" and q["valid"], "R02", aid, "QUALITY_ANCESTOR:" + prev
                    )
            if self.a[prev].release_evidence:
                self.need(att.released, "R02", aid, "PROCESS_RELEASE:" + prev)

    def capacity(self):
        for loc, resource in self.resources.items():
            entries = [r for r in self.residencies if r[1] == loc]
            count = len({r[0] if loc == "BUF" else r[2] for r in entries})
            self.need(count <= resource.capacity, "R05", loc, "RESIDENCY_CAPACITY")

    def reserve(self, entity, location, pid, reserved=False):
        owner = entity if location == "BUF" else pid
        self.residencies.add((entity, location, owner, reserved))
        self.capacity()

    def acquire(self, ids, owner):
        self.need(len(ids) == len(set(ids)), "R04", owner, "DUPLICATE_RESOURCE_ROLE")
        for rid in ids:
            self.need(rid not in self.failed, "R13", owner, "FAILED_RESOURCE:" + rid)
            self.need(
                rid not in self.locks or self.locks[rid] == owner,
                "R04" if rid in self.people else "R05",
                owner,
                "RESOURCE_OVERLAP:" + rid,
            )
            self.locks[rid] = owner

    def unlock(self, owner, keep=()):
        self.locks = {k: v for k, v in self.locks.items() if v != owner or k in keep}

    def advance_area(self, t):
        dt = t - self.t
        if dt < 0:
            self.issue("R16", self.c.id, "EVENT_TIME_ORDER")
            return
        for loc in self.occupancy:
            self.occupancy[loc] += dt * len(
                {r[0] if loc == "BUF" else r[2] for r in self.residencies if r[1] == loc}
            )
        # Product-equivalent physical WIP: components count once per product;
        # cancelled physical WIP stays until receipt/explicit clearance to Q1.
        physical = {
            r[2] if r[2] in self.p else self.components[r[0]].product_id
            for r in self.residencies
            if r[1] != "Q1" and (r[2] in self.p or r[0] in self.components)
        }
        self.wip += dt * len(physical - set(self.ready) - set(self.received))
        active = {self.a[aid].product_id for aid in self.running}
        active |= {s["product_id"] for s in self.services.values()}
        waiting = {
            self.a[aid].product_id
            for aid, att in self.attempts.items()
            if att.waiting is not None
            and not att.complete
            and not att.invalid
            and att.state != "CANCELLED"
        }
        self.idle_residency += dt * len(physical - active - waiting - set(self.ready))
        self.wait_hours += dt * sum(
            a.waiting is not None and not a.complete and not a.invalid and a.state != "CANCELLED"
            for a in self.attempts.values()
        )
        self.t = t

    def faces(self, a):
        others = set(self.running) | {
            aid
            for aid, att in self.attempts.items()
            if att.waiting is not None and not att.complete and not att.invalid and aid != a.id
        }
        for aid in others:
            other = self.a[aid]
            if a.product_id != other.product_id and a.location != other.location:
                continue
            permitted = any(
                {pair.first, pair.second} == {a.face, other.face}
                and pair.qualification_id in self.evidence
                and self.evidence[pair.qualification_id].status == "PASS"
                for pair in self.c.face_pairs
            )
            self.need(permitted, "R06", a.id, "WORK_FACE:" + aid)

    def unit_start(self, e, d):
        a = self.a[e.entity_id]
        m = next(x for x in a.modes if x.id == d["mode_id"])
        idx = d["unit_index"]
        u = m.units[idx]
        self.need(
            m.enabled and m.output_revision == self.p[a.product_id].revision,
            "R03",
            a.id,
            "MODE_OUTPUT_OR_DISABLED",
        )
        self.evidence_ok(m.qualification_ids, m.qualification_revisions, "R03", a.id)
        self.evidence_ok((u.checkpoint_id,), rule="R09", obj=a.id)
        if a.quality_evidence:
            self.evidence_ok((a.quality_evidence,), rule="R11", obj=a.id)
        self.need(a.product_id in self.released, "R13", a.id, "UNRELEASED_PRODUCT")
        self.need(
            a.product_id not in self.cancelled and a.product_id not in self.received,
            "R13",
            a.id,
            "NEW_COMMITMENT_AFTER_CANCEL_OR_RECEIPT",
        )
        self.need(a.product_id not in self.held, "R11", a.id, "QUALITY_HOLD")
        self.prerequisites(a.id)
        att = self.current_attempt(a.id, m.id)
        self.need(
            att.number == e.attempt == d["attempt"]
            and att.units == idx
            and att.mode == m.id
            and not att.complete
            and not att.invalid,
            "R09",
            a.id,
            "ATTEMPT_PROGRESS_MODE",
        )
        self.need(
            d["activity_id"] == a.id
            and d["start_h"] == self.t
            and d["end_h"] > self.t
            and d["state"] == "ACTIVE",
            "R09",
            a.id,
            "UNIT_ANCHOR",
        )
        if a.wait_h:
            self.need(
                att.waiting is not None and self.t >= att.waiting and att.released,
                "R02",
                a.id,
                "WAIT_DUAL_GATE",
            )
        roles = {r["role_id"]: r["person_id"] for r in d["roles"]}
        self.need(
            len(roles) == len(d["roles"])
            and set(roles) == {r.id for r in u.roles}
            and len(set(roles.values())) == len(roles),
            "R04",
            a.id,
            "ROLE_SET",
        )
        for r in u.roles:
            p = self.people.get(roles.get(r.id))
            self.need(
                p is not None and r.qualification in p.qualifications,
                "R04",
                a.id,
                "ROLE_QUALIFICATION:" + r.id,
            )
            if p:
                state, bound = calendar(p, self.t)
                self.need(
                    state == "WAIT" and d["end_h"] <= bound and d["end_h"] <= p.valid_until_h,
                    "R10",
                    p.id,
                    "WORK_CALENDAR",
                )
                if r.id in att.roles and att.roles[r.id] != p.id:
                    self.need(
                        (a.id, att.roles[r.id], p.id) in self.handovers,
                        "R09",
                        a.id,
                        "UNCHARGED_HANDOVER",
                    )
        att.roles = roles
        att.state, att.prepared = "RUNNING", True
        self.product_states[a.product_id] = "IN_PROCESS"
        self.need(tuple(d["equipment"]) == u.equipment, "R05", a.id, "EQUIPMENT_SET")
        self.need(a.location not in self.failed, "R13", a.id, "FAILED_LOCATION")
        self.faces(a)
        if a.code == "Q-POND" and self.locks.get("TEST1") == a.product_id + ".TEST":
            self.locks.pop("TEST1")
        self.acquire(
            list(roles.values()) + list(u.equipment) + ([a.move.route] if a.move else []), a.id
        )
        if a.code == "KIT":
            self.reserve(a.product_id + ".RAW", "PRE", a.product_id)
        elif not a.move and a.code != "CUT":
            entity = a.product_id + (".BOTTOM" if a.code == "W-B" else ".TOP")
            entity = entity if a.code in ("W-B", "W-T") else a.product_id
            self.need(self.locations[entity] == a.location, "R01", entity, "WORK_LOCATION")
        if idx == 0:
            mids = (
                (a.product_id + ".REPAIR-TEST-KIT",)
                if a.code == "TEST-SET" and att.number
                else a.material_ids
            )
            for mid in mids:
                self.need(
                    self.material_state[mid][3] == a.id, "R12", mid, "MISSING_CONSUMPTION", True
                )
        if a.move:
            self.need(a.id in self.moves, "R08", a.id, "MISSING_RESERVATION", True)
            self.need(a.product_id not in self.water, "R08", a.id, "TEST_NOT_DRAINED")
        self.need(a.id not in self.running, "R09", a.id, "DUPLICATE_UNIT_START")
        self.running[a.id] = dict(d)
        self.units.append((a.id, dict(d), u))

    def move_reserved(self, e, d):
        a = self.a[e.entity_id]
        move = a.move
        self.need(move is not None, "R08", a.id, "UNDECLARED_MOVE")
        if move is None:
            return
        self.need(d["move"] == json.loads(json.dumps(asdict(move))), "R08", a.id, "MOVE_BINDING")
        self.evidence_ok(move.qualification_ids, move.qualification_revisions, "R08", a.id)
        self.need(
            move.source not in self.failed and move.target not in self.failed,
            "R13",
            a.id,
            "FAILED_MOVE_LOCATION",
        )
        p = self.p[a.product_id]
        for eid in move.entity_ids:
            comp = self.components.get(eid)
            self.need(
                eid == a.product_id or comp is not None and comp.product_id == a.product_id,
                "R01",
                eid,
                "FOREIGN_COMPONENT",
            )
            src = "PRE" if comp and comp.kind == "COLUMNS" and a.code == "JOIN-IN" else move.source
            self.need(self.locations.get(eid) == src, "R08", eid, "MOVE_SOURCE")
            mass = comp.mass_t if comp else p.mass_t
            self.need(
                mass + p.rigging_t <= self.resources[move.equipment].load_t, "R08", eid, "OVERLOAD"
            )
            self.reserve(eid, move.target, a.product_id, True)
        observed = {
            (r["entity_id"], r["location"], r["owner"], r["reserved"]) for r in d["residencies"]
        }
        self.need(observed == self.residencies, "R07", a.id, "RESIDENCY_LEDGER")
        self.moves[a.id] = 0

    def arrival(self, e, d):
        a = self.a[e.entity_id]
        run = self.running.get(a.id)
        if not self.need(run is not None, "R08", a.id, "MISSING_MOVE_START", True):
            return
        move = a.move
        done = d["sub_landings"]
        self.need(
            0 < done <= len(move.landing_h) and done == self.moves[a.id] + 1,
            "R08",
            a.id,
            "LANDING_SEQUENCE",
        )
        when = run["start_h"] + move.landing_h[done - 1] * run["multiplier"]
        self.need(self.t == when and run["state"] == "ACTIVE", "R08", a.id, "LANDING_TIME_OR_HOLD")
        entities = move.entity_ids[:done] if a.code == "JOIN-IN" else move.entity_ids
        self.need(
            tuple(d["entities"]) == entities and d["target"] == move.target,
            "R01",
            a.id,
            "LANDING_IDENTITY",
        )
        newly = entities[-1:] if a.code == "JOIN-IN" else entities
        for eid in newly:
            self.need(eid in self.transits, "R08", eid, "MISSING_TRANSIT", True)
        for eid in entities:
            self.residencies = {r for r in self.residencies if r[0] != eid}
            self.reserve(eid, move.target, a.product_id)
            self.locations[eid] = move.target
            self.transits.discard(eid)
        self.moves[a.id] = done
        if a.code == "JOIN-IN" and done == len(move.entity_ids):
            for eid in entities:
                self.locations[eid] = "INCORPORATED"
            self.residencies = {r for r in self.residencies if r[0] not in entities}
            self.locations[a.product_id] = "J3"
            self.reserve(a.product_id, "J3", a.product_id)

    def unit_complete(self, e, d):
        a = self.a[e.entity_id]
        run = self.running.get(a.id)
        if not self.need(run is not None, "R09", a.id, "MISSING_UNIT_START", True):
            return
        self.need(
            self.t == run["end_h"] and run["state"] == "ACTIVE",
            "R09",
            a.id,
            "EARLY_OR_HELD_COMPLETION",
        )
        self.need(
            all(d[k] == run[k] for k in run if k != "landings_done"),
            "R09",
            a.id,
            "CHANGED_UNIT_COMMITMENT",
        )
        m = next(m for m in a.modes if m.id == run["mode_id"])
        att = self.attempts[a.id]
        att.units += 1
        att.state = "COMPLETED" if att.units == len(m.units) else "PAUSED_AT_CHECKPOINT"
        self.spans.append(
            (run["start_h"], self.t, tuple(r["person_id"] for r in run["roles"]), "WORK", a.id)
        )
        del self.running[a.id]
        keep = ("R1", "FIX-J2") if m.kind == "HR-seq" and att.units < len(m.units) else ()
        self.unlock(a.id, keep)
        if a.code == "TEST-SET":
            self.locks["TEST1"] = a.product_id + ".TEST"
            self.water.add(a.product_id)
        if a.code == "Q-POND":
            self.locks.pop("TEST1", None)
            self.water.discard(a.product_id)
        if a.move:
            self.need(
                self.moves.get(a.id) == len(a.move.landing_h), "R08", a.id, "MISSING_LANDING", True
            )
            self.move_count += len(a.move.entity_ids)
            self.move_hours += self.t - run["start_h"]

    def activity_complete(self, aid, attempt):
        a = self.a[aid]
        att = self.attempts.get(aid)
        if not self.need(att is not None, "R09", aid, "MISSING_ATTEMPT", True):
            return
        m = next(m for m in a.modes if m.id == att.mode)
        self.need(
            att.number == attempt and att.units == len(m.units) and not att.complete,
            "R09",
            aid,
            "FALSE_ACTIVITY_COMPLETION",
        )
        att.complete = True
        att.state = "COMPLETED"
        if a.code == "CUT":
            self.residencies = {r for r in self.residencies if r[0] != a.product_id + ".RAW"}
            for comp in self.components.values():
                if comp.product_id == a.product_id:
                    self.need(
                        self.locations[comp.id] == "UNFABRICATED",
                        "R01",
                        comp.id,
                        "DUPLICATE_FABRICATION",
                    )
                    self.locations[comp.id] = "PRE"
                    self.reserve(comp.id, "PRE", a.product_id)
        for mid in a.material_ids:
            self.need(self.material_state[mid][3] == aid, "R12", mid, "INSTALL_WITHOUT_MATERIAL")
            self.installed[a.product_id].update(self.materials[mid].bom_ids)

    def invalidation(self, aid, include_self=True):
        affected = {x for x in self.a if aid in self.ancestors(x)} | (
            {aid} if include_self else set()
        )
        for x in affected:
            for (aid, _), attempt in self.attempt_history.items():
                if aid == x:
                    attempt.invalid = True
                    attempt.released = False
                    if x not in self.running or not self.a[x].move:
                        attempt.state, attempt.prepared = "FAILED", False
            for key, q in self.quality.items():
                if key[0] == x:
                    q["valid"] = False
            if x in self.running and not self.a[x].move:
                run = self.running.pop(x)
                self.spans.append(
                    (run["start_h"], self.t, tuple(r["person_id"] for r in run["roles"]), "WORK", x)
                )
                self.unlock(x)
        pid = self.a[aid].product_id
        self.held.add(pid)
        self.product_states[pid] = "QUALITY_HOLD"
        self.ready.pop(pid, None)

    def external(self, e, d):
        eid, kind, obj = d["id"], d["kind"], d["entity_id"]
        self.need(eid not in self.external_ids, "R16", obj, "DUPLICATE_EXTERNAL")
        self.external_ids.add(eid)
        self.external_facts[eid] = d
        self.need(d["time_h"] == self.t and e.entity_id == eid, "R16", obj, "FACT_TIME_ID")
        if kind.startswith("MATERIAL_"):
            state = self.material_state[obj]
            self.need(state[3] is None, "R12", obj, "MATERIAL_FACT_AFTER_CONSUMPTION")
            idx = {"MATERIAL_ARRIVAL": 0, "MATERIAL_IDENTIFY": 1, "MATERIAL_RELEASE": 2}[kind]
            if idx == 2:
                self.need(all(state[:2]), "R12", obj, "UNIDENTIFIED_RELEASE")
            state[idx] = True
        elif kind == "PROCESS_RELEASE":
            a = self.a[obj]
            att = self.attempts.get(obj)
            self.evidence_ok((a.release_evidence, "G4"), rule="R02", obj=obj)
            if self.need(
                att is not None and att.waiting is not None, "R02", obj, "MISSING_WAIT", True
            ):
                self.need(self.t >= att.waiting, "R02", obj, "EARLY_PROCESS_RELEASE")
                att.released = True
                if not a.modes[0].units:
                    att.complete = True
                    att.state = "COMPLETED"
        elif kind == "QUALITY_RESULT":
            a, att = self.a[obj], self.attempts.get(obj)
            key = (obj, d["attempt"])
            self.need(key not in self.quality, "R11", obj, "QUALITY_OVERWRITE")
            self.need(
                att is not None and att.complete and att.number == d["attempt"] and not att.invalid,
                "R11",
                obj,
                "QUALITY_WITHOUT_INSPECTION",
            )
            self.evidence_ok((a.quality_evidence,), rule="R11", obj=obj)
            self.quality[key] = {
                "result": d["value"],
                "valid": True,
                "time_h": self.t,
                "inspector": att.roles.get("QA1") if att else None,
            }
            if d["value"] != "PASS":
                self.invalidation(obj, False)
        elif kind == "INVALIDATE":
            self.invalidation(obj)
        elif kind == "CANCEL":
            self.cancelled[obj] = self.t
            self.ready.pop(obj, None)
            self.product_states[obj] = "CANCEL_PENDING"
            for (aid, _), att in self.attempt_history.items():
                if self.a[aid].product_id == obj and att.state in (
                    "NOT_READY",
                    "PAUSED_AT_CHECKPOINT",
                    "WAITING_RELEASE",
                ):
                    att.state = "CANCELLED"
        elif kind == "RECEIVED":
            self.need(
                obj in self.ready and obj not in self.cancelled and self.locations[obj] == "OUT1",
                "R15",
                obj,
                "RECEIPT_WITHOUT_READY",
            )
            self.received[obj] = self.t
            self.locations[obj] = "EXTERNAL"
            self.product_states[obj] = "RECEIVED"
            self.residencies = {r for r in self.residencies if r[2] != obj}
        elif kind == "ORDER_ARRIVAL":
            self.need(self.t >= self.p[obj].release_h, "R13", obj, "EARLY_RELEASE")
            self.released.add(obj)
        elif kind == "FAILURE":
            self.failed.add(obj)
            for aid, run in list(self.running.items()):
                a = self.a[aid]
                deps = set(run["equipment"]) | {a.location}
                if a.move:
                    deps |= {a.move.source, a.move.target, a.move.route}
                if obj in deps:
                    if a.move:
                        run["state"] = "EMERGENCY_HOLD"
                    else:
                        self.invalidation(aid)
            for service in self.services.values():
                if service["kind"] == "CLEANUP" and obj in {
                    "CR1",
                    "ROUTE-MODULE",
                    service["source"],
                    service["target"],
                }:
                    service["state"] = "EMERGENCY_HOLD"
        elif kind == "REPAIR":
            self.failed.discard(obj)
        else:
            self.issue("R18", obj, "UNKNOWN_FACT", True)

    def check_ready(self, pid):
        if not self.need(pid not in self.ready, "R16", pid, "DUPLICATE_READY"):
            return
        self.need(
            pid not in self.cancelled
            and pid not in self.held
            and pid not in self.water
            and self.locations[pid] == "OUT1",
            "R15",
            pid,
            "READY_STATE",
        )
        for a in self.a.values():
            if a.product_id != pid or a.code == "READY":
                continue
            att = self.attempts.get(a.id)
            self.need(
                att is not None and att.complete and not att.invalid,
                "R15",
                pid,
                "READY_INCOMPLETE_ACTIVITY:" + a.code,
            )
            if a.quality_evidence:
                q = self.quality.get((a.id, att.number if att else 0))
                self.need(
                    q is not None and q["result"] == "PASS" and q["valid"],
                    "R15",
                    pid,
                    "READY_QUALITY:" + a.code,
                )
        self.need({i.id for i in self.p[pid].bom} <= self.installed[pid], "R15", pid, "READY_BOM")
        self.ready[pid] = self.t
        self.product_states[pid] = "READY"
        aid = next(a.id for a in self.a.values() if a.product_id == pid and a.code == "READY")
        self.remember_attempt(
            aid, _Attempt(0, self.a[aid].modes[0].id, complete=True, state="COMPLETED")
        )

    def event_record(self, e):
        kind = e.kind
        d = _json(e.reason) if e.reason.startswith("{") else {}
        if kind == "UNIT_START":
            self.unit_start(e, d)
        elif kind == "UNIT_COMPLETE":
            self.unit_complete(e, d)
        elif kind == "ACTIVITY_COMPLETE":
            self.activity_complete(e.entity_id, e.attempt)
        elif kind == "MATERIAL_CONSUMED":
            mid = e.entity_id
            mat, state = self.materials[mid], self.material_state[mid]
            self.need(
                mat.product_id == d["product"] and mat.activity_id == d["activity"],
                "R01",
                mid,
                "MATERIAL_OWNER",
            )
            self.need(all(state[:3]) and state[3] is None, "R12", mid, "KIT_NOT_AVAILABLE")
            state[3] = d["activity"]
        elif kind == "MOVE_RESERVED":
            self.move_reserved(e, d)
        elif kind == "ARRIVAL_CONFIRMED":
            self.arrival(e, d)
        elif kind == "IN_TRANSIT":
            runs = [
                (aid, r)
                for aid, r in self.running.items()
                if self.a[aid].move and e.entity_id in self.a[aid].move.entity_ids
            ]
            self.need(len(runs) == 1, "R08", e.entity_id, "TRANSIT_WITHOUT_MOVE")
            if runs:
                aid, run = runs[0]
                move = self.a[aid].move
                i = move.entity_ids.index(e.entity_id)
                prev = move.landing_h[i - 1] if i else 0
                lift = (
                    run["start_h"] + (prev + (move.landing_h[i] - prev) * 0.4) * run["multiplier"]
                )
                self.need(self.t == lift, "R08", e.entity_id, "LIFT_TIME")
            self.locations[e.entity_id] = "IN_TRANSIT"
            self.transits.add(e.entity_id)
        elif kind == "WAIT_START":
            a = self.a[e.entity_id]
            # C05 writes the child WAIT_START immediately before the parent's
            # REPAIR_COMPLETE at the same tick. Buffer only that exact causal
            # pair; never sort arbitrary events or infer a missing completion.
            if e.attempt == 1 and any(
                s["kind"] == "REPAIR" and s["product_id"] == a.product_id and s["end_h"] == self.t
                for s in self.services.values()
            ):
                self.pending_waits.append(e)
                return
            att = self.current_attempt(a.id, a.modes[0].id)
            self.need(
                a.wait_h > 0 and d["until"] == self.t + a.wait_h and att.number == e.attempt,
                "R02",
                a.id,
                "WAIT_IDENTITY_DURATION",
            )
            for edge in self.c.edges:
                if edge.target == a.id:
                    prev = self.attempts.get(edge.source)
                    self.need(prev is not None and prev.complete, "R02", a.id, "WAIT_PREDECESSOR")
            att.waiting = d["until"]
            att.state = "WAITING_RELEASE"
        elif kind == "EXTERNAL":
            self.external(e, d)
        elif kind == "READY":
            self.check_ready(e.entity_id)
        elif kind == "ORDER_ARRIVAL":
            self.need(self.t >= self.p[e.entity_id].release_h, "R13", e.entity_id, "EARLY_RELEASE")
            self.released.add(e.entity_id)
        elif kind in ("REST_START", "PROTECTIVE_REST"):
            ids = d["people"] if kind == "REST_START" else [e.entity_id]
            end = d["until"] if kind == "REST_START" else self.t + self.c.min_rest_h
            self.need(end >= self.t + self.c.min_rest_h, "R10", e.entity_id, "REST_DURATION")
            for pid in ids:
                self.need(pid not in self.locks, "R09", pid, "REST_DURING_COMMITMENT")
                self.rests.append((self.t, end, pid))
        elif kind.endswith("_START") and kind in (
            "HANDOVER_START",
            "RESTORE_START",
            "REPAIR_START",
            "CLEANUP_START",
        ):
            self.service_start(e, d)
        elif kind in (
            "HANDOVER_COMPLETE",
            "RESTORE_COMPLETE",
            "REPAIR_COMPLETE",
            "REPAIR_STOPPED",
            "CLEANUP_LANDED",
        ):
            self.service_end(e, d)
        elif kind == "CLEANUP_IN_TRANSIT":
            services = [
                s
                for s in self.services.values()
                if s["product_id"] == e.entity_id and s["kind"] == "CLEANUP"
            ]
            self.need(
                len(services) == 1 and self.t == services[0]["start_h"] + 0.4,
                "R13",
                e.entity_id,
                "CLEANUP_TRANSIT",
            )
            self.locations[e.entity_id] = "IN_TRANSIT"
        elif kind == "COMPLETED":
            self.activity_complete(e.entity_id, e.attempt)
        elif kind not in (
            "REJECTED",
            "INVALIDATED",
            "EMERGENCY_HOLD",
            "INTERRUPTED_REQUIRES_INSPECTION",
        ):
            self.issue("R18", e.entity_id, "UNKNOWN_EVENT_KIND:" + kind, True)

    def service_start(self, e, d):
        s = dict(d["service"] if e.kind == "REPAIR_START" else d)
        kind, aid, pid = s["kind"], s["activity_id"], s["product_id"]
        self.need(s["start_h"] == self.t and s["end_h"] > self.t, "R09", aid, "SERVICE_TIME")
        self.need(len(s["people"]) == len(set(s["people"])), "R04", aid, "SERVICE_ROLES")
        extra = []
        if kind == "HANDOVER":
            att = self.attempts.get(aid)
            self.need(
                att is not None and att.units > 0 and not att.complete and aid not in self.running,
                "R09",
                aid,
                "HANDOVER_CHECKPOINT",
            )
            self.need(
                set(s["people"]) == {s["outgoing_person"], s["replacement_person"]}
                and s["outgoing_person"] != s["replacement_person"],
                "R04",
                aid,
                "HANDOVER_PEOPLE",
            )
            self.need(s["end_h"] == self.t + 0.1, "R09", aid, "HANDOVER_DURATION")
        elif kind == "RESTORE":
            self.need(
                s["end_h"] == self.t + 0.1
                and any(x[0] == aid and x[2] in s["people"] for x in self.handovers),
                "R09",
                aid,
                "RESTORE_WITHOUT_HANDOVER",
            )
        elif kind == "REPAIR":
            q = self.quality.get((aid, 0))
            self.need(
                self.a[aid].code == "Q-POND"
                and aid not in self.repaired
                and q is not None
                and q["result"] == "FAIL",
                "R11",
                aid,
                "REPAIR_LIMIT_OR_CAUSE",
            )
            self.evidence_ok(("G7", "G4"), rule="R11", obj=aid)
            self.need(set(s["people"]) == {"QA1", "T1"}, "R04", aid, "REPAIR_ROLES")
            mid = d["replacement_kit"]
            state = self.material_state[mid]
            self.need(
                mid == pid + ".REPAIR-KIT" and all(state[:3]) and state[3] is None,
                "R11",
                mid,
                "REPAIR_MATERIAL",
            )
            state[3] = s["id"]
            self.repaired.add(aid)
            self.prerequisites(aid)
        elif kind == "CLEANUP":
            self.need(pid in self.cancelled or pid in self.held, "R13", pid, "CLEARANCE_CAUSE")
            self.need(
                self.locations[pid] == s["source"]
                and s["source"] in ("J3", "F1", "OUT1")
                and s["target"] == "Q1"
                and pid not in self.water,
                "R13",
                pid,
                "CLEARANCE_LOCATION",
            )
            self.need(
                not any(self.a[x].product_id == pid for x in self.running),
                "R13",
                pid,
                "CLEARANCE_COMMITTED_TAIL",
            )
            self.need(
                s["source"] not in self.failed and s["target"] not in self.failed,
                "R13",
                pid,
                "CLEARANCE_FAILED_LOCATION",
            )
            self.need(s["end_h"] == self.t + 1, "R13", pid, "CLEARANCE_DURATION")
            self.evidence_ok(("G1", "G6", "G7"), rule="R13", obj=pid)
            self.need(
                len(s["people"]) == 3
                and all(
                    q in self.people[p].qualifications
                    for p, q in zip(s["people"], ("CRANE", "RIG", "SIGNAL"))
                ),
                "R04",
                pid,
                "CLEARANCE_ROLES",
            )
            self.need(
                self.p[pid].mass_t + self.p[pid].rigging_t <= self.resources["CR1"].load_t,
                "R08",
                pid,
                "CLEARANCE_OVERLOAD",
            )
            self.reserve(pid, "Q1", pid, True)
            extra = ["CR1", "ROUTE-MODULE"]
        for person in s["people"]:
            p = self.people[person]
            state, end = calendar(p, self.t)
            self.need(
                state == "WAIT" and s["end_h"] <= min(end, p.valid_until_h),
                "R10",
                person,
                "SERVICE_CALENDAR",
            )
        self.units.append(
            (
                aid,
                {**s, "roles": [{"person_id": p} for p in s["people"]], "service_kind": kind},
                None,
            )
        )
        self.acquire(s["people"] + extra, s["id"])
        self.services[s["id"]] = s

    def service_end(self, e, d):
        kind = {
            "HANDOVER_COMPLETE": "HANDOVER",
            "RESTORE_COMPLETE": "RESTORE",
            "REPAIR_COMPLETE": "REPAIR",
            "REPAIR_STOPPED": "REPAIR",
            "CLEANUP_LANDED": "CLEANUP",
        }[e.kind]
        candidates = [
            s
            for s in self.services.values()
            if s["kind"] == kind and e.entity_id in (s["activity_id"], s["product_id"])
        ]
        if not self.need(len(candidates) == 1, "R09", e.entity_id, "MISSING_SERVICE_START", True):
            return
        s = candidates[0]
        self.need(
            self.t == s["end_h"] and s["state"] == "ACTIVE",
            "R13",
            e.entity_id,
            "SERVICE_FALSE_COMPLETION",
        )
        self.spans.append(
            (
                s["start_h"],
                self.t,
                tuple(s["people"]),
                kind if kind in ("HANDOVER", "RESTORE") else "WORK",
                s["id"],
            )
        )
        self.unlock(s["id"])
        del self.services[s["id"]]
        if kind == "HANDOVER":
            self.need(
                d == {"incoming": s["replacement_person"], "outgoing": s["outgoing_person"]},
                "R09",
                s["activity_id"],
                "HANDOVER_IDENTITY",
            )
            self.handovers.add((s["activity_id"], s["outgoing_person"], s["replacement_person"]))
        if kind == "REPAIR":
            self.repair_hours += self.t - s["start_h"]
            if e.kind == "REPAIR_COMPLETE":
                self.prerequisites(s["activity_id"])
                self.need(
                    s["product_id"] not in self.cancelled,
                    "R11",
                    s["product_id"],
                    "REPAIR_AFTER_CANCEL",
                )
                for code in ("WPROOF", "WAIT-W", "TEST-SET", "WAIT-TEST", "Q-POND"):
                    a = next(
                        a
                        for a in self.a.values()
                        if a.code == code and a.product_id == s["product_id"]
                    )
                    self.remember_attempt(
                        a.id,
                        _Attempt(
                            1,
                            a.modes[0].id,
                            len(a.modes[0].units) if code == "WPROOF" else 0,
                            complete=code == "WPROOF",
                            state="COMPLETED" if code == "WPROOF" else "NOT_READY",
                            prepared=code == "WPROOF",
                        ),
                    )
                self.held.discard(s["product_id"])
                self.product_states[s["product_id"]] = "IN_PROCESS"
                waiting = [
                    x
                    for x in self.pending_waits
                    if self.a[x.entity_id].product_id == s["product_id"] and x.time_h == self.t
                ]
                for event in waiting:
                    self.pending_waits.remove(event)
                    self.event_record(event)
        if kind == "CLEANUP":
            pid = s["product_id"]
            self.need(
                self.locations[pid] == "IN_TRANSIT", "R13", pid, "MISSING_CLEARANCE_TRANSIT", True
            )
            self.residencies = {r for r in self.residencies if r[2] != pid}
            self.reserve(pid, "Q1", pid)
            self.locations[pid] = "Q1"
            self.product_states[pid] = "QUARANTINED"
            self.ready.pop(pid, None)
            self.move_count += 1
            self.move_hours += self.t - s["start_h"]

    def replay(self):
        self.released = {p.id for p in self.c.products if p.release_h == 0}
        seen = set()
        for i, e in enumerate(self.s.events, 1):
            self.event = e
            self.need(e.id not in seen, "R16", e.entity_id, "DUPLICATE_EVENT")
            seen.add(e.id)
            # C05 publishes contiguous EV-n IDs. A gap is missing evidence;
            # a backward sequence is a protocol violation, not auto-sorted.
            self.need(e.id == f"EV-{i}", "R16", e.entity_id, "EVENT_SEQUENCE_GAP", True)
            self.need(
                e.schema_version == "C04-1.0" and e.config_id == self.c.id,
                "R18",
                e.entity_id,
                "EVENT_VERSION",
            )
            if not self.need(
                math.isfinite(e.time_h) and 0 <= e.time_h <= self.window,
                "R17",
                e.entity_id,
                "EVENT_WINDOW",
            ):
                continue
            self.advance_area(e.time_h)
            if e.kind in ("UNIT_START", "READY", "CLEANUP_START"):
                # Declared scenario facts have priority over a new commitment.
                # Manual adapter facts are causal arrivals, not prescient input.
                pending = {f.id for f in self.s.scenario.events if f.time_h <= e.time_h}
                self.need(
                    pending <= self.external_ids, "R16", e.entity_id, "DISPATCH_BEFORE_DUE_FACT"
                )
            try:
                self.event_record(e)
            except (
                KeyError,
                ValueError,
                TypeError,
                IndexError,
                StopIteration,
                AttributeError,
            ) as error:
                self.issue(
                    "R18", e.entity_id, "MISSING_OR_MALFORMED_RECORD:" + type(error).__name__, True
                )
        self.event = None
        self.need(not self.pending_waits, "R11", self.c.id, "WAIT_WITHOUT_REPAIR_COMPLETION", True)
        self.advance_area(self.window)
        for aid, run in self.running.items():
            if run["end_h"] <= self.window and run["state"] != "EMERGENCY_HOLD":
                self.issue("R09", aid, "MISSING_COMPLETION", True)
            self.spans.append(
                (
                    run["start_h"],
                    self.window,
                    tuple(r["person_id"] for r in run["roles"]),
                    "WORK",
                    aid,
                )
            )
        for s in self.services.values():
            if s["end_h"] <= self.window and s["state"] != "EMERGENCY_HOLD":
                self.issue("R09", s["id"], "MISSING_SERVICE_COMPLETION", True)
            self.spans.append(
                (
                    s["start_h"],
                    self.window,
                    tuple(s["people"]),
                    s["kind"] if s["kind"] in ("HANDOVER", "RESTORE") else "WORK",
                    s["id"],
                )
            )
        self.compare_snapshot()

    def compare_snapshot(self):
        self.need(
            {p.product_id for p in self.s.products} == set(self.p)
            and len(self.s.products) == len(self.p),
            "R01",
            self.c.id,
            "PRODUCT_COVERAGE",
            True,
        )
        self.need(
            {c.component_id for c in self.s.components} == set(self.components)
            and len(self.s.components) == len(self.components),
            "R01",
            self.c.id,
            "COMPONENT_COVERAGE",
            True,
        )
        for item in (*self.s.products, *self.s.components):
            eid = item.product_id if isinstance(item, b.ProductState) else item.component_id
            self.need(self.locations.get(eid) == item.location, "R01", eid, "POSITION_DISAGREEMENT")
            if isinstance(item, b.ProductState):
                self.need(
                    item.state == self.product_states[eid], "R13", eid, "PRODUCT_STATE_DISAGREEMENT"
                )
                self.need(
                    item.ready_h == self.ready.get(eid)
                    and (item.state in ("READY", "RECEIVED")) == (eid in self.ready),
                    "R15",
                    eid,
                    "READY_SUMMARY_DISAGREEMENT",
                )
                self.need(item.cancelled == (eid in self.cancelled), "R13", eid, "CANCEL_SUMMARY")
                self.need(
                    set(item.installed_bom) == self.installed[eid], "R12", eid, "INSTALLED_BOM"
                )
                self.need(item.water_present == (eid in self.water), "R08", eid, "WATER_SUMMARY")
            else:
                self.need(
                    item.incorporated == (self.locations[eid] == "INCORPORATED"),
                    "R01",
                    eid,
                    "INCORPORATION_SUMMARY",
                )
        observed = {(r.entity_id, r.location, r.owner, r.reserved) for r in self.s.residencies}
        self.need(
            observed == self.residencies and len(observed) == len(self.s.residencies),
            "R07",
            self.c.id,
            "FINAL_RESIDENCY_LEDGER",
        )
        self.need(
            {(x.resource_id, x.owner) for x in self.s.locks} == set(self.locks.items())
            and len(self.s.locks) == len(self.locks),
            "R05",
            self.c.id,
            "FINAL_LOCK_LEDGER",
        )
        self.need(
            {r.activity_id for r in self.s.running} == set(self.running)
            and len(self.s.running) == len(self.running),
            "R09",
            self.c.id,
            "RUNNING_COVERAGE",
            True,
        )
        for r in self.s.running:
            if r.activity_id in self.running:
                expected = dict(self.running[r.activity_id])
                expected["landings_done"] = self.moves.get(r.activity_id, 0)
                self.need(
                    json.loads(json.dumps(asdict(r))) == expected,
                    "R09",
                    r.activity_id,
                    "RUNNING_COMMITMENT",
                )
        observed_attempts = {(a.activity_id, a.number): a for a in self.s.attempts}
        self.need(
            len(observed_attempts) == len(self.s.attempts), "R09", self.c.id, "DUPLICATE_ATTEMPT"
        )
        self.need(
            set(observed_attempts) <= set(self.attempt_history),
            "R09",
            self.c.id,
            "UNRECORDED_ATTEMPT",
        )
        for (aid, number), att in self.attempt_history.items():
            item = observed_attempts.get((aid, number))
            if self.need(item is not None, "R09", aid, "MISSING_ATTEMPT_SUMMARY", True):
                self.need(
                    item.completed_units == att.units and item.mode_id == att.mode,
                    "R09",
                    aid,
                    "ATTEMPT_SUMMARY_PROGRESS",
                )
                self.need(
                    item.state == att.state
                    and item.wait_until_h == att.waiting
                    and item.prepared == att.prepared,
                    "R09",
                    aid,
                    "ATTEMPT_STATE_DISAGREEMENT",
                )
                if self.a[aid].product_id not in self.cancelled and not att.invalid:
                    self.need(
                        (item.state == "COMPLETED") == att.complete,
                        "R09",
                        aid,
                        "ATTEMPT_SUMMARY_COMPLETION",
                    )
        self.need(set(self.s.failed_resources) == self.failed, "R13", self.c.id, "FAILURE_LEDGER")
        self.need(
            {s.id for s in self.s.services} == set(self.services)
            and len(self.s.services) == len(self.services),
            "R13",
            self.c.id,
            "SERVICE_COVERAGE",
            True,
        )
        for service in self.s.services:
            if service.id in self.services:
                self.need(
                    json.loads(json.dumps(asdict(service))) == self.services[service.id],
                    "R13",
                    service.id,
                    "SERVICE_STATE_DISAGREEMENT",
                )
        self.need(
            {x.material_id for x in self.s.materials} == set(self.materials)
            and len(self.s.materials) == len(self.materials),
            "R12",
            self.c.id,
            "MATERIAL_COVERAGE",
            True,
        )
        for x in self.s.materials:
            self.need(
                self.material_state.get(x.material_id)
                == [x.arrived, x.identified, x.released, x.consumed_by],
                "R12",
                x.material_id,
                "MATERIAL_LEDGER",
            )
        observed = {(q.activity_id, q.attempt): q for q in self.s.quality}
        self.need(
            set(observed) == set(self.quality) and len(observed) == len(self.s.quality),
            "R11",
            self.c.id,
            "QUALITY_HISTORY",
            True,
        )
        self.need(
            len({q.id for q in self.s.quality}) == len(self.s.quality),
            "R11",
            self.c.id,
            "DUPLICATE_QUALITY_ID",
        )
        for key, q in self.quality.items():
            if key not in observed:
                continue
            item, a = observed[key], self.a[key[0]]
            self.need(
                item.result == q["result"]
                and item.product_id == a.product_id
                and item.valid == q["valid"]
                and item.time_h == q["time_h"]
                and item.inspector_id == q["inspector"]
                and item.product_revision == self.p[a.product_id].revision
                and item.criterion_revision == self.evidence[a.quality_evidence].revision,
                "R11",
                key[0],
                "QUALITY_RECORD_DISAGREEMENT",
            )
        # Scenario is execution-only evidence, never a planning input.
        self.need(
            len({f.id for f in self.s.scenario.events}) == len(self.s.scenario.events),
            "R13",
            self.c.id,
            "DUPLICATE_SCENARIO_FACT",
        )
        for fact in self.s.scenario.events:
            if fact.id in self.external_facts:
                self.need(
                    asdict(fact) == self.external_facts[fact.id],
                    "R13",
                    fact.entity_id,
                    "SCENARIO_FACT_DISAGREEMENT",
                )
            if fact.time_h <= self.window:
                self.need(
                    fact.id in self.external_ids,
                    "R13",
                    fact.entity_id,
                    "MISSING_EXOGENOUS_FACT",
                    True,
                )

    def humans(self):
        totals, trajectories = {}, {}
        reported = {p.person_id: p for p in self.s.people}
        self.need(
            set(reported) == set(self.people) and len(reported) == len(self.s.people),
            "R17",
            self.c.id,
            "PEOPLE_COVERAGE",
            True,
        )
        self.need(
            all(x.person_id in self.people for x in self.s.intervals),
            "R10",
            self.c.id,
            "UNKNOWN_PERSON",
        )
        for pid, person in self.people.items():
            rows = [x for x in self.s.intervals if x.person_id == pid]
            f, area, peak, end = person.initial_f, 0.0, person.initial_f, 0.0
            durations = {}
            trajectory = []
            for row in rows:
                self.t = row.start_h
                if not self.need(
                    row.start_h == end and row.end_h > row.start_h and row.end_h <= self.window,
                    "R17",
                    pid,
                    "PERSON_INTERVAL_COVERAGE",
                    True,
                ):
                    continue
                spans = [x for x in self.spans if pid in x[2] and x[0] <= row.start_h < x[1]]
                self.need(len(spans) <= 1, "R04", pid, "PERSON_DOUBLE_WORK")
                if spans:
                    expected = spans[0][3]
                    boundary = spans[0][1]
                else:
                    rests = [x for x in self.rests if x[2] == pid and x[0] <= row.start_h < x[1]]
                    expected, boundary = (
                        ("REST", max(x[1] for x in rests))
                        if rests
                        else calendar(person, row.start_h)
                    )
                    future_starts = [x[0] for x in self.spans if pid in x[2] and x[0] > row.start_h]
                    future_starts += [
                        x[0] for x in self.rests if x[2] == pid and x[0] > row.start_h
                    ]
                    boundary = min([boundary, *future_starts])
                self.need(
                    row.activity == expected and row.end_h <= boundary,
                    "R10",
                    pid,
                    "ACTIVITY_OR_CALENDAR",
                )
                rate = (
                    person.recovery_rate
                    if expected in ("REST", "OFF_SHIFT")
                    else person.wait_rate
                    if expected == "WAIT"
                    else person.work_rate
                )
                self.need(close(row.rate, rate), "R10", pid, "ACTIVITY_RATE")
                dt = row.end_h - row.start_h
                new, inc, local_peak = integrate_segment(
                    f, dt, rate, expected in ("REST", "OFF_SHIFT")
                )
                self.need(
                    close(row.start_f, f) and close(row.end_f, new) and close(row.exposure, inc),
                    "R10",
                    pid,
                    "INDEPENDENT_INTEGRAL",
                )
                # Numerical comparison of derived sums only. No cap clipping.
                self.need(
                    local_peak <= self.c.cap or close(local_peak, self.c.cap),
                    "R10",
                    pid,
                    "CAP_EXCEEDED",
                )
                self.need(
                    row.start_f <= self.c.cap and row.end_f <= self.c.cap,
                    "R10",
                    pid,
                    "RECORDED_CAP_EXCEEDED",
                )
                trajectory.append(
                    (row.start_h, row.end_h, f, rate, expected in ("REST", "OFF_SHIFT"))
                )
                durations[expected] = durations.get(expected, 0.0) + dt
                area += inc
                peak = max(peak, local_peak)
                f, end = new, row.end_h
            self.need(end == self.window, "R17", pid, "MISSING_PERSON_TAIL", True)
            if pid in reported:
                h = reported[pid]
                self.need(
                    close(h.fatigue, f) and close(h.exposure, area) and close(h.peak, peak),
                    "R10",
                    pid,
                    "HUMAN_SUMMARY_DISAGREEMENT",
                )
            totals[pid] = {
                "fatigue": f,
                "exposure_F_h": area,
                "peak": peak,
                "hours": durations,
                "covered_until_h": end,
            }
            trajectories[pid] = trajectory

        def fatigue_at(pid, t):
            if t == 0:
                return self.people[pid].initial_f
            for start, end, f, rate, recovery in trajectories[pid]:
                if start <= t <= end:
                    return integrate_segment(f, t - start, rate, recovery)[0]
            self.issue("R10", pid, "MISSING_START_F", True, t)
            return 0.0

        for aid, run, unit in self.units:
            self.t = run["start_h"]
            sample = max((fatigue_at(r["person_id"], self.t) for r in run["roles"]), default=0.0)
            if unit is not None:
                multiplier = 1 + unit.kappa * sample
                self.need(
                    close(run["sampled_max_f"], sample)
                    and close(run["multiplier"], multiplier)
                    and close(run["end_h"], self.t + unit.base_h * multiplier),
                    "R09",
                    aid,
                    "SAMPLED_DURATION",
                )
            elif run["service_kind"] == "REPAIR":
                after = max(
                    fatigue_at(r["person_id"], self.t) + self.people[r["person_id"]].work_rate * 0.5
                    for r in run["roles"]
                )
                self.need(
                    close(run["end_h"], self.t + 0.5 + (1 + 0.5 * after)),
                    "R11",
                    aid,
                    "REPAIR_DIAGNOSIS_AND_LABOR",
                )
            for r in run["roles"]:
                pid = r["person_id"]
                forecast = fatigue_at(pid, self.t) + self.people[pid].work_rate * (
                    run["end_h"] - self.t
                )
                self.need(
                    forecast <= self.c.cap or close(forecast, self.c.cap),
                    "R10",
                    pid,
                    "UNIT_PROTECTION",
                )
        self.t = self.window
        return totals


def check_run(
    config,
    snapshot,
    *,
    window_h=None,
    plan=None,
    observation=None,
    computation_samples=(),
    order_weights=None,
    candidate_trace=False,
):
    """Audit an actual prefix [0,T]; a valid unfinished prefix can PASS.

    Planning checks certify supplied observations/plan structure only. Paired
    dynamic-policy nonanticipation is explicitly outside S10 (S12).
    Missing plans never become proof of a planned schedule's feasibility.
    """
    started = perf_counter()
    try:
        if type(candidate_trace) is not bool:
            raise ValueError("candidate_trace")
        _shape(config, b.Configuration)
        _shape(snapshot, b.ExecutionSnapshot)
        if window_h is not None and (
            type(window_h) not in (int, float) or not math.isfinite(window_h) or window_h <= 0
        ):
            raise ValueError("window")
        if plan is not None:
            _shape(plan, b.Plan)
        if observation is not None:
            _shape(observation, b.PlanningObservation)
    except (ValueError, TypeError, AttributeError):
        return Report(
            "INCOMPLETE",
            [Finding("R18", "input", 0, "MALFORMED_TYPED_EVIDENCE", "INCOMPLETE")],
            {"validity": "DIAGNOSTIC_ONLY"},
            {},
            {},
        )
    audit = _Audit(config, snapshot, snapshot.time_h if window_h is None else window_h)
    try:
        audit.configuration()
        audit.replay()
        people = audit.humans()
    except (ValueError, KeyError, TypeError, IndexError, AttributeError, StopIteration) as error:
        audit.issue("R18", config.id, "UNREADABLE_EVIDENCE:" + type(error).__name__, True)
        people = {}
    scope = {f"R{i:02}": "ACTUAL_LOG" for i in range(1, 19)}
    scope["R14"] = "NO_PLAN_SUPPLIED; S12_POLICY_NONANTICIPATION_NOT_TESTED"
    if plan is not None or observation is not None:
        scope["R14"] = "SUPPLIED_VISIBILITY_ONLY; S12_POLICY_NONANTICIPATION_NOT_TESTED"
        if audit.need(
            plan is not None and observation is not None,
            "R14",
            config.id,
            "MISSING_PLANNING_EVIDENCE",
            True,
        ):
            audit.need(
                plan.observation_id == observation.id
                and plan.config_id == config.id
                and observation.config_id == config.id
                and observation.sampled_h <= observation.received_h <= observation.observed_h,
                "R14",
                plan.observation_id,
                "OBSERVATION_ID_TIME",
            )
            visible = {p.product_id for p in observation.products}
            for p in observation.products:
                audit.need(
                    p.product_id in audit.p
                    and audit.p[p.product_id].release_h <= observation.sampled_h,
                    "R14",
                    p.product_id,
                    "FUTURE_PRODUCT_LEAK",
                )
            event_times = {e.id: e.time_h for e in snapshot.events}
            completed_at = {}
            for e in snapshot.events:
                if e.kind in ("ACTIVITY_COMPLETE", "COMPLETED"):
                    completed_at.setdefault(e.entity_id, []).append(e.time_h)
                elif e.kind == "EXTERNAL":
                    try:
                        fact = _json(e.reason)
                        if fact["kind"] == "PROCESS_RELEASE":
                            a = audit.a.get(fact["entity_id"])
                            if a and not a.modes[0].units:
                                completed_at.setdefault(a.id, []).append(e.time_h)
                    except (ValueError, KeyError, TypeError):
                        pass  # Replay already records missing/malformed evidence.
                elif e.kind == "READY":
                    for a in config.activities:
                        if a.product_id == e.entity_id and a.code == "READY":
                            completed_at.setdefault(a.id, []).append(e.time_h)
            for p in observation.products:
                audit.need(
                    all(
                        aid in audit.a
                        and audit.a[aid].product_id == p.product_id
                        and any(t <= observation.sampled_h for t in completed_at.get(aid, ()))
                        for aid in p.completed_activity_ids
                    ),
                    "R14",
                    p.product_id,
                    "UNOBSERVED_COMPLETION",
                )
            audit.need(
                all(
                    eid in event_times and event_times[eid] <= observation.sampled_h
                    for eid in observation.event_ids
                ),
                "R14",
                observation.id,
                "FUTURE_EVENT_LEAK",
            )
            for command in plan.commands:
                a = audit.a.get(command.activity_id)
                audit.need(
                    a is not None
                    and a.product_id in visible
                    and command.issued_h >= observation.observed_h,
                    "R14",
                    command.id,
                    "UNOBSERVED_DISPATCH",
                )
                if not candidate_trace:
                    audit.issue("R09", command.id, "PLAN_REQUIRES_ACTUAL_OR_CANDIDATE_TRACE", True)
            audit.need(
                {x.product_id for x in plan.predicted_ready} == visible,
                "R17",
                observation.id,
                "PLANNING_EVALUATION_SET",
            )
            if candidate_trace:
                _check_candidate_trace(audit, plan, observation)
                scope["R14"] = (
                    "STATIC_INITIAL_CANDIDATE_TRACE; S12_POLICY_NONANTICIPATION_NOT_TESTED"
                )
    if candidate_trace and (plan is None or observation is None):
        audit.issue("R14", config.id, "MISSING_PLANNING_EVIDENCE", True)
    costs = []
    for sample in computation_samples:
        if audit.need(
            isinstance(sample, dict)
            and set(sample) == {"wall_ms", "budget_ms", "fallback"}
            and all(
                isinstance(sample[k], (float, int))
                and not isinstance(sample[k], bool)
                and math.isfinite(sample[k])
                and sample[k] >= 0
                for k in ("wall_ms", "budget_ms")
            )
            and isinstance(sample["fallback"], bool),
            "R17",
            config.id,
            "COMPUTATION_SAMPLE",
        ):
            costs.append(sample)
    try:
        result_metrics = delivery_metrics(
            config.products,
            audit.ready,
            audit.cancelled,
            audit.received,
            audit.window,
            order_weights,
        )
    except (ValueError, TypeError):
        audit.issue("R17", config.id, "MISSING_OR_INVALID_ORDER_WEIGHTS", True)
        result_metrics = {"products": [], "orders": []}
    result_metrics.update(
        {
            "window_h": audit.window,
            "people": people,
            "sum_exposure_F_h": sum(x["exposure_F_h"] for x in people.values()),
            "max_exposure_F_h": max((x["exposure_F_h"] for x in people.values()), default=None),
            "wip_product_h": audit.wip,
            "occupancy_entity_or_product_h": audit.occupancy,
            "process_wait_activity_h": audit.wait_hours,
            "idle_residency_product_h": audit.idle_residency,
            "labor_person_h": sum(
                sum(
                    v
                    for k, v in x["hours"].items()
                    if k in ("WORK", "HANDOVER", "RESTORE", "SUPERVISE")
                )
                for x in people.values()
            ),
            "labor_wait_person_h": sum(x["hours"].get("WAIT", 0) for x in people.values()),
            "moves_completed": audit.move_count,
            "move_equipment_h": audit.move_hours,
            "move_open_prefix_h": sum(
                audit.window - r["start_h"] for aid, r in audit.running.items() if audit.a[aid].move
            )
            + sum(
                audit.window - s["start_h"]
                for s in audit.services.values()
                if s["kind"] == "CLEANUP"
            ),
            "repair_service_h": audit.repair_hours,
            "repair_open_prefix_h": sum(
                audit.window - s["start_h"]
                for s in audit.services.values()
                if s["kind"] == "REPAIR"
            ),
            "repair_attempts": len(audit.repaired),
            "computation": {
                "count": len(costs),
                "wall_ms": sum(x["wall_ms"] for x in costs) if costs else None,
                "budget_violations": sum(x["wall_ms"] > x["budget_ms"] for x in costs)
                if costs
                else None,
                "fallback_rate": sum(x["fallback"] for x in costs) / len(costs) if costs else None,
            },
            "checker_wall_ms": (perf_counter() - started) * 1000,
        }
    )
    status = (
        "INCOMPLETE"
        if any(f.severity == "INCOMPLETE" for f in audit.findings)
        else "FAIL"
        if audit.findings
        else "PASS"
    )
    result_metrics["validity"] = "VERIFIED_SYNTHETIC" if status == "PASS" else "DIAGNOSTIC_ONLY"
    return Report(
        status,
        audit.findings,
        result_metrics,
        {
            "locations": audit.locations,
            "residencies": sorted(audit.residencies),
            "materials": audit.material_state,
            "ready_h": audit.ready,
            "cancelled_h": audit.cancelled,
            "received_h": audit.received,
            "attempts": {aid: asdict(att) for aid, att in audit.attempts.items()},
            "attempt_history": [
                {"activity_id": aid, **asdict(att)}
                for (aid, _), att in audit.attempt_history.items()
            ],
            "product_states": dict(audit.product_states),
            "services": list(audit.services.values()),
            "locks": dict(audit.locks),
            "quality": [
                {"activity_id": k[0], "attempt": k[1], **v} for k, v in audit.quality.items()
            ],
            "failed_resources": sorted(audit.failed),
            "water_present": sorted(audit.water),
        },
        scope,
        "S10-1.2" if candidate_trace else "S10-1.1",
    )


def _check_candidate_trace(audit, plan, observation):
    """S11 opt-in: one-to-one command/actual-start matching, independent of decoder.

    Full replay above verifies every actual resource, gate and human interval.
    This static interface binds command work/time/crew/revision, not an S12 online
    policy. Revision reconstruction is restricted to pristine, scenario-free
    candidates without repair/handover services. Old unbound calls stay incomplete.
    """
    s = audit.s
    audit.need(
        not s.scenario.events
        and not any(
            e.kind in ("HANDOVER_START", "RESTORE_START", "REPAIR_START", "CLEANUP_START")
            for e in s.events
        ),
        "R14",
        observation.id,
        "STATIC_TRACE_SCOPE",
    )
    audit.need(
        observation.state_revision == 0
        and not observation.event_ids
        and not observation.unavailable_resources
        and len(observation.people) == len(audit.c.people)
        and {
            h.person_id: (h.fatigue, h.exposure, h.peak, h.rest_until_h) for h in observation.people
        }
        == {p.id: (p.initial_f, 0, p.initial_f, 0) for p in audit.c.people}
        and all(
            p.state == "RELEASED"
            and p.location == "UNASSEMBLED"
            and p.cancelled is False
            and not p.completed_activity_ids
            for p in observation.products
        ),
        "R14",
        observation.id,
        "INITIAL_STATE_TRACE_MISMATCH",
    )
    audit.need(bool(plan.commands), "R09", plan.observation_id, "EMPTY_CANDIDATE", True)
    audit.need(plan.status == "CANDIDATE", "R09", plan.observation_id, "CANDIDATE_STATUS")
    audit.need(
        observation.sampled_h == observation.received_h == observation.observed_h == 0,
        "R14",
        observation.id,
        "STATIC_INITIAL_OBSERVATION_REQUIRED",
    )
    audit.need(
        tuple(c.id for c in plan.commands) == s.consumed_commands
        and len(set(c.id for c in plan.commands)) == len(plan.commands),
        "R09",
        plan.observation_id,
        "COMMAND_TRACE_ID_COVERAGE",
    )
    starts = []
    changes = 0
    boundaries = {x.end_h for x in s.intervals}
    for e in s.events:
        revision = changes + sum(t <= e.time_h for t in boundaries)
        if e.kind in ("REST_START", "EXTERNAL"):
            changes += 1
        if e.kind == "UNIT_START":
            try:
                d = _json(e.reason)
                starts.append(
                    (
                        e.entity_id,
                        d["mode_id"],
                        d["attempt"],
                        d["unit_index"],
                        e.time_h,
                        revision,
                        tuple((r["role_id"], r["person_id"]) for r in d["roles"]),
                    )
                )
                changes += 1
            except (KeyError, TypeError, ValueError):
                audit.issue("R09", e.entity_id, "UNREADABLE_CANDIDATE_START", True)
        elif e.kind == "READY":
            activities = [
                a for a in audit.c.activities if a.product_id == e.entity_id and a.code == "READY"
            ]
            if len(activities) == 1:
                a = activities[0]
                starts.append((a.id, a.modes[0].id, 0, 0, e.time_h, revision, ()))
                changes += 1
        elif e.kind == "REJECTED":
            audit.issue("R09", e.entity_id, "CANDIDATE_CONTAINS_REJECTION")
    signatures = [
        (
            c.activity_id,
            c.mode_id,
            c.attempt,
            c.unit_index,
            c.issued_h,
            c.expected_revision,
            tuple((r.role_id, r.person_id) for r in c.roles),
        )
        for c in plan.commands
    ]
    audit.need(signatures == starts, "R09", plan.observation_id, "COMMAND_START_TRACE_MISMATCH")
    audit.need(
        s.revision == changes + len(boundaries),
        "R09",
        plan.observation_id,
        "FINAL_CANDIDATE_REVISION_MISMATCH",
    )
    visible = {p.product_id for p in observation.products}
    audit.need(
        visible == set(audit.p) == set(audit.ready)
        and not audit.running
        and all(
            aid in audit.attempts and audit.attempts[aid].state == "COMPLETED" for aid in audit.a
        ),
        "R15",
        plan.observation_id,
        "CANDIDATE_NOT_COMPLETE",
    )
    audit.need(
        len(plan.predicted_ready) == len(visible)
        and all(
            x.product_id in audit.ready and x.ready_h == audit.ready[x.product_id]
            for x in plan.predicted_ready
        ),
        "R15",
        plan.observation_id,
        "PREDICTION_TRACE_MISMATCH",
    )
