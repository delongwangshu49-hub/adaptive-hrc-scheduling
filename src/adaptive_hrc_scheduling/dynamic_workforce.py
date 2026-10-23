"""P043 workforce extension. C0 and S18 physical admission remain immutable.

Status markers live in the existing failed-resource set so historical record
bytes do not acquire new fields. Only this family interprets the P043 namespace.
"""

from dataclasses import replace
from functools import lru_cache

from .contracts.codec import as_data, require
from .contracts.production import digest, validate
from .contracts.session import digest as sha
from .domain import production as m
from .dynamic_orders import CatalogHistory, templates

VERSION = "P043-PROD-1.0"
SPECIFICATION = "P043-PROD-SPEC-1.0"
KINDS = ("PERSON_ARRIVE", "PERSON_DEPART", "PERSON_ABSENT", "PERSON_RETURN")


@lru_cache(maxsize=1)
def registry():
    # The approved W1/W2/OP1 simulation parameters are the sole tested templates.
    from .contracts.codec import decode

    base = decode(m.Configuration, templates()["SR-W1"])
    return {"P043-" + p.id + "-v1": p for p in base.people if p.id in ("W1", "W2", "OP1")}


@lru_cache(maxsize=1)
def template_hashes():
    return {k: sha(as_data(v)) for k, v in registry().items()}


def marker(kind, pid):
    return "P043." + kind + "." + pid


def status(state, pid):
    for name in ("ABSENT_HOLD", "ABSENT", "DEPARTURE_PENDING", "DEPARTED"):
        if marker(name, pid) in state.failed_resources:
            return name
    return "PRESENT"


def eligible(state, pid):
    return status(state, pid) == "PRESENT"


def off_shift(state, pid):
    return status(state, pid) in ("DEPARTED", "ABSENT")


def control_location(config, pid):
    if "CONTROL-" + pid in {p.id for p in config.places}:
        return "CONTROL-" + pid
    return "CONTROL-W1"


def obligated(state, pid):
    return any(pid == r.person_id for x in state.running for r in x.command.roles) or any(
        a.state != "COMPLETE" and any(r.person_id == pid for r in a.crew)
        for a in state.mode_attempts
    )


def new_person(config, payload):
    from .contracts.codec import decode
    from .domain.building import Person

    tid = payload["parameter_template_id"]
    require(len(payload["person_id"]) <= 50, "WORKFORCE_ID_LENGTH")
    require(tid in registry(), "PERSON_TEMPLATE_UNSUPPORTED")
    base = registry()[tid]
    require(
        template_hashes()[tid] == payload["parameter_template_sha256"], "PERSON_TEMPLATE_DIGEST"
    )
    require(payload["qualification_evidence_id"] == tid + ".QUAL", "PERSON_QUALIFICATION_EVIDENCE")
    require(tuple(payload["qualifications"]) == base.qualifications, "PERSON_QUALIFICATIONS")
    require(0 < payload["valid_until_h"] <= base.valid_until_h, "PERSON_VALIDITY")
    require(payload["initial_f"] <= config.cap, "PERSON_INITIAL_CAP")
    require(payload["calendar_id"] == tid + ".CAL", "PERSON_CALENDAR")
    require(payload["calendar_sha256"] == sha(as_data(base.calendar)), "PERSON_CALENDAR_DIGEST")
    require(payload["arrival_location"] in {p.id for p in config.places}, "PERSON_LOCATION")
    ids = {
        x.id
        for rows in (
            config.people,
            config.products,
            config.devices,
            config.operations,
            config.places,
            config.lots,
            config.entities,
            config.evidence,
            config.routes,
            config.core_activities,
            config.groups,
            config.support_layouts,
        )
        for x in rows
    }
    ids |= {p.order_id for p in config.products}
    require(payload["person_id"] not in ids, "PERSON_ID_USED")
    return decode(
        Person,
        as_data(
            replace(
                base,
                id=payload["person_id"],
                initial_f=payload["initial_f"],
                valid_until_h=payload["valid_until_h"],
            )
        ),
    )


def generate(config, payload, now):
    person = new_person(config, payload)
    require(person.valid_until_h > now, "PERSON_QUALIFICATION_EXPIRED")
    result = replace(
        config,
        schema_version=VERSION,
        specification=SPECIFICATION,
        people=config.people + (person,),
        person_positions=config.person_positions
        + (m.PersonPosition(person.id, payload["arrival_location"]),),
    )
    validate(result)
    return result, person


def validate_configuration(config):
    from .dynamic_orders import validate_dynamic_configuration

    require(config.specification == SPECIFICATION, "WORKFORCE_SPECIFICATION")
    baseline = templates()["SR-W1"]["people"]
    require(as_data(config.people[:15]) == baseline, "WORKFORCE_C0_PEOPLE")
    require(15 <= len(config.people) <= 18, "WORKFORCE_TESTED_LIMIT")
    object_ids = {p.order_id for p in config.products}
    for rows in (
        config.products,
        config.devices,
        config.operations,
        config.places,
        config.lots,
        config.entities,
        config.evidence,
        config.routes,
        config.core_activities,
        config.groups,
        config.support_layouts,
    ):
        object_ids.update(x.id for x in rows)
    require(not {p.id for p in config.people} & object_ids, "WORKFORCE_OBJECT_ID_COLLISION")
    for p in config.people[15:]:
        require(
            any(
                replace(p, id=t.id, initial_f=t.initial_f, valid_until_h=t.valid_until_h) == t
                and p.initial_f <= config.cap
                and p.valid_until_h <= t.valid_until_h
                for t in registry().values()
            ),
            "WORKFORCE_PARAMETER_DRIFT",
        )
    base_ids = {p.id for p in config.people[:15]}
    canonical = replace(
        config,
        schema_version="P042-PROD-1.0",
        specification="P042-PROD-SPEC-1.0",
        people=config.people[:15],
        person_positions=tuple(p for p in config.person_positions if p.person_id in base_ids),
    )
    validate_dynamic_configuration(canonical)


class WorkforceHistory(CatalogHistory):
    def append(self, row):
        if row.get("workforce_kind"):
            require(row["before_config_sha256"] == digest(self.current), "PERSON_PREVIOUS_VIEW")
            config = self.current
            if row["workforce_kind"] == "PERSON_ARRIVE":
                config, _ = generate(config, row["payload"], row["sim_h"])
            require(digest(config) == row["config_sha256"], "PERSON_RECONSTRUCTION")
            require(row["event_id"] not in self.by_event, "PERSON_DUPLICATE_EVENT")
            self.generations.append(row)
            self.views[digest(config)] = config
            self.by_event[row["event_id"]] = row
            self.current = config
            return config
        return super().append(row)


def production_schema(kind):
    from .dynamic_orders import production_schema as order_schema

    value = order_schema(kind)
    for name, definition in value["$defs"].items():
        props = definition.get("properties", {})
        if "schema_version" in props:
            props["schema_version"] = {"enum": [VERSION]}
        if name == "Configuration":
            props["specification"] = {"enum": [SPECIFICATION]}
        if name == "WorldEvent":
            props["kind"]["enum"].extend((*KINDS, "PERSON_LEFT"))
    return value


def apply_status(state, kind, pid):
    old = status(state, pid)
    if kind == "PERSON_ARRIVE":
        target = "PRESENT"
    elif kind == "PERSON_DEPART":
        require(old == "PRESENT", "PERSON_STATE")
        target = "DEPARTURE_PENDING" if obligated(state, pid) else "DEPARTED"
    elif kind == "PERSON_ABSENT":
        require(old in ("PRESENT", "DEPARTURE_PENDING"), "PERSON_STATE")
        target = "ABSENT_HOLD" if obligated(state, pid) else "ABSENT"
    elif kind == "PERSON_RETURN":
        require(old in ("DEPARTED", "ABSENT", "ABSENT_HOLD"), "PERSON_STATE")
        target = "PRESENT"
    elif kind == "PERSON_LEFT":
        require(
            old == "DEPARTURE_PENDING" and not obligated(state, pid), "PERSON_NOT_SAFE_TO_LEAVE"
        )
        target = "DEPARTED"
    else:
        require(False, "PERSON_EVENT_KIND")
    flags = tuple(
        x
        for x in state.failed_resources
        if x
        not in {marker(k, pid) for k in ("ABSENT_HOLD", "ABSENT", "DEPARTURE_PENDING", "DEPARTED")}
    )
    return replace(
        state, failed_resources=flags + (() if target == "PRESENT" else (marker(target, pid),))
    )


def append_world(world, config, person):
    world.config, world.config_hash = config, digest(config)
    world.people = dict(world.people, **{person.id: person})
    world.s = replace(
        world.s,
        humans=world.s.humans
        + (m.HumanState(person.id, person.initial_f, 0, person.initial_f, 0),),
        positions=world.s.positions
        + (
            m.Position(
                person.id,
                config.person_positions[-1].location,
                config.person_positions[-1].location,
            ),
        ),
    )
