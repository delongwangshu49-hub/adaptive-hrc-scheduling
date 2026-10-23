"""P043 single-writer personnel transactions used by every Session entry."""

from copy import deepcopy
from dataclasses import replace

from .building_human import calendar_state
from .contracts.codec import as_data, require
from .contracts.production import digest as config_digest
from .contracts.session import digest, validate_record
from .domain import production as m
from .dynamic_workforce import (
    SPECIFICATION,
    VERSION,
    append_world,
    generate,
    new_person,
    obligated,
    registry,
    status,
    template_hashes,
)


def configuration(config):
    from .contracts.production import validate

    result = replace(config, schema_version=VERSION, specification=SPECIFICATION)
    validate(result)
    return result


def make_spec(config, profile, *, rates, **kwargs):
    from .control.session import make_spec as shared_spec

    spec = shared_spec(config, profile, rates=rates, **kwargs)
    for key, p in registry().items():
        require(key in rates, "COST_RATE_REQUIRED")
        spec["cost"]["person_template_ids"].append(key)
        spec["cost"]["rates"].append(dict(template_id=key, rate_per_h=rates[key]))
    spec["cost"]["policy_sha256"] = digest(
        {k: v for k, v in spec["cost"].items() if k != "policy_sha256"}
    )
    return spec


def arrival_payload(config, pid, template_id="P043-W1-v1", *, location="F1", initial_f=0.1):
    base = registry()[template_id]
    return dict(
        person_id=pid,
        qualification_evidence_id=template_id + ".QUAL",
        qualifications=list(base.qualifications),
        valid_until_h=base.valid_until_h,
        parameter_template_id=template_id,
        parameter_template_sha256=template_hashes()[template_id],
        calendar_id=template_id + ".CAL",
        calendar_sha256=digest(as_data(base.calendar)),
        initial_f=initial_f,
        arrival_location=location,
        scene_reference=dict(
            domain_id=pid, scene_entity_id=pid, prim_path="CPU:N/A", template_revision="v1"
        ),
    )


def check_request(session, req, *, applying=False):
    require(session.workforce_enabled, "WORKFORCE_FAMILY_REQUIRED")
    world, p = session.world, req["payload"]
    pid, kind = req["target_id"], req["kind"]
    if kind == "PERSON_ARRIVE":
        require(applying or not session.closed, "INPUT_CLOSED")
        require(pid not in session.catalog["objects"], "PERSON_ID_USED")
        require(pid == p["person_id"], "TARGET_PAYLOAD_MISMATCH")
        require(len(world.config.people) < 18, "WORKFORCE_TESTED_LIMIT")
        person = new_person(world.config, p)
        rates = {r["template_id"]: r["rate_per_h"] for r in session.spec["cost"]["rates"]}
        require(p["parameter_template_id"] in rates, "COST_RATE_REQUIRED")
        ref = p["scene_reference"]
        require(
            ref["domain_id"] == ref["scene_entity_id"] == pid and ref["template_revision"] == "v1",
            "PERSON_SCENE_IDENTITY",
        )
        expected = "CPU:N/A" if session.spec["backend"] == "CPU" else "/World/P043/People/" + pid
        require(ref["prim_path"] == expected, "PERSON_SCENE_PATH")
        require(person.valid_until_h > world.s.time_h, "PERSON_QUALIFICATION_EXPIRED")
    else:
        require(
            pid in world.people and session.catalog["objects"].get(pid, {}).get("kind") == "person",
            "UNKNOWN_PERSON",
        )
        old = status(world.s, pid)
        if kind == "PERSON_DEPART":
            require(old == "PRESENT", "PERSON_STATE")
        elif kind == "PERSON_ABSENT":
            require(old in ("PRESENT", "DEPARTURE_PENDING"), "PERSON_STATE")
        elif kind == "PERSON_RETURN":
            require(old in ("ABSENT", "ABSENT_HOLD", "DEPARTED"), "PERSON_STATE")
            require(p["scene_entity_id"] == pid, "PERSON_SCENE_IDENTITY")
            require(
                p["arrival_location"] == world._position(pid).location, "PERSON_RETURN_LOCATION"
            )
            require(
                p["arrival_location"] in world.places
                or old == "ABSENT_HOLD"
                and p["arrival_location"] == "IN_TRANSIT",
                "PERSON_LOCATION",
            )
            require(
                world.people[pid].valid_until_h > world.s.time_h, "PERSON_QUALIFICATION_EXPIRED"
            )
            require(
                calendar_state(world.people[pid], world.s.time_h)[0] == "WAIT",
                "PERSON_RETURN_CALENDAR",
            )
            if old in ("DEPARTED", "ABSENT"):
                from .production_geometry import standing_point
                from .production_navigation import walk_blocker

                loc = p["arrival_location"]
                point = standing_point(world.config, pid, loc)
                require(
                    walk_blocker(world.config, world.s, pid, loc, loc, (point, point)) is None,
                    "PERSON_RETURN_OCCUPIED",
                )
                require(
                    loc != "J2"
                    or not any(
                        world.operations[r.command.operation_id].branch
                        and world.operations[r.command.operation_id].branch.phase == "ROBOT"
                        for r in world.s.running
                    ),
                    "PERSON_RETURN_ISOLATION",
                )


def apply_request(session, req, admission, *, automatic=False):
    if not automatic:
        check_request(session, req, applying=True)
    world, kind, pid = session.world, req["kind"], req["target_id"]
    before, revision = session.version, world.s.revision
    prior = config_digest(world.config)
    config = world.config
    scene_rows = []
    if kind == "PERSON_ARRIVE":
        config, person = generate(config, req["payload"], world.s.time_h)
        from .production_geometry import standing_point
        from .production_navigation import walk_blocker

        loc = req["payload"]["arrival_location"]
        point = standing_point(config, pid, loc)
        prepared_state = replace(
            world.s, positions=world.s.positions + (m.Position(pid, loc, loc),)
        )
        require(
            walk_blocker(config, prepared_state, pid, loc, loc, (point, point)) is None,
            "PERSON_ARRIVAL_OCCUPIED",
        )
        if session.spec["backend"] == "ISAAC":
            scene_rows = [
                session.backend.port.append_person(config, person, req["payload"], before + 1)
            ]
        else:
            scene_rows = [
                dict(
                    req["payload"]["scene_reference"],
                    catalog_version=before + 1,
                    actual_location=req["payload"]["arrival_location"],
                    ready=True,
                    source="CPU_LOCATION_EXECUTOR",
                )
            ]
        append_world(world, config, person)
    elif kind == "PERSON_RETURN":
        if session.spec["backend"] == "ISAAC":
            scene_rows = [
                session.backend.port.person_readback(
                    pid, req["payload"]["arrival_location"], before + 1
                )
            ]
        else:
            scene_rows = [
                dict(
                    domain_id=pid,
                    scene_entity_id=pid,
                    prim_path="CPU:N/A",
                    template_revision="v1",
                    catalog_version=before + 1,
                    actual_location=world._position(pid).location,
                    ready=True,
                    source="CPU_LOCATION_EXECUTOR",
                )
            ]
    # Absence first stops affected executions; ownership and physical payload stay held.
    if kind == "PERSON_ABSENT":
        affected_activities = {
            a.activity_id
            for a in world.s.mode_attempts
            if a.state != "COMPLETE" and any(r.person_id == pid for r in a.crew)
        }
        for run in tuple(world.s.running):
            if (
                any(r.person_id == pid for r in run.command.roles)
                or run.command.activity_id in affected_activities
            ) and run.status == "STARTED":
                if session.spec["backend"] == "ISAAC":
                    session.backend.port.hold_person(run.command.id)
                world.exception(run.command.id, "P043_PERSON_ABSENT:" + req["request_id"])
    event = session.backend.apply_world(
        m.WorldEvent(
            "REQUEST-" + req["request_id"] + ("-LEFT" if automatic else ""),
            world.run_id,
            world.epoch,
            world.s.time_h,
            kind,
            pid,
            config.products[0].id,
            0,
            "PASS",
            req["request_id"],
        )
    )
    row = dict(
        workforce_kind=kind,
        target_id=pid,
        payload=deepcopy(req["payload"]),
        sim_h=world.s.time_h,
        before_config_sha256=prior,
        config_sha256=config_digest(config),
        event_id=event.id,
        request_id=req["request_id"],
        automatic=automatic,
    )
    session.history.append(row)
    old = session.catalog["objects"].get(pid, dict(revision=-1))
    session.catalog["objects"][pid] = dict(
        revision=old["revision"] + 1,
        kind="person",
        available=status(world.s, pid) == "PRESENT",
        presence_status=status(world.s, pid),
        **(
            {
                k: v
                for k, v in old.items()
                if k in ("parameter_template_id", "qualification_version")
            }
        ),
    )
    if kind == "PERSON_ARRIVE":
        session.catalog["objects"][pid].update(
            parameter_template_id=req["payload"]["parameter_template_id"], qualification_version=1
        )
    payload = dict(
        delta_id=f"DELTA-{before + 1}",
        request_id=req["request_id"],
        request_digest=req["request_digest"],
        kind="PERSON_DEPART" if automatic else kind,
        accept_sequence=admission["sequence"],
        actual_sim_h=world.s.time_h,
        read_set_hash=admission["read_set_hash"],
        state_revision_before=revision,
        state_revision_after=world.s.revision,
        object_ids=[pid],
        generation_sha256=digest(row),
        commit_event_id=event.id,
    )
    h = digest(dict(previous_hash=session.versions[-1], version=before + 1, delta=payload))
    delta = dict(
        payload,
        old_version=before,
        new_version=before + 1,
        old_hash=session.versions[-1],
        new_hash=h,
        materialized_catalog_sha256=digest(session.catalog),
    )
    validate_record("CatalogDelta", delta)
    session.deltas.append(delta)
    session.versions.append(h)
    session.policy.config = config
    promises = digest(as_data(session.policy.committed))
    running = tuple(r.command for r in world.s.running)
    known = {
        c.id
        for c in session.policy.pending
        if c not in session.policy.committed and c not in running
    }
    invalid = session.policy.catalog_changed([pid], world.operations, [event.id], running)
    session.transitions.append(
        dict(
            old_catalog_version=before,
            new_catalog_version=session.version,
            affected_object_ids=[pid],
            invalidated_keys=invalid,
            known_uncommitted_keys=sorted(known),
            revalidated_keys=[],
            reused_keys=[],
            surviving_commands={c.id: as_data(c) for c in session.policy.pending if c.id in known},
            cache_sha256=session.policy.cache_hash,
            reuse_proofs=[],
            protected_before_hash=promises,
            protected_after_hash=digest(as_data(session.policy.committed)),
            reason_event_ids=[event.id],
            rebase_from_version=admission["accepted_version"],
            read_set_hash=admission["read_set_hash"],
        )
    )
    for x in scene_rows:
        session.scene_bindings.append(
            dict(x, event_id=event.id, scope="P043_PERSON_ACTUAL_READBACK")
        )
    if session.spec["backend"] == "ISAAC":
        session.backend.ledger.catalog, session.backend.ledger.config = session.history, config
        session.backend.port.config = config
    session.workforce_results.append(
        dict(
            request_id=req["request_id"],
            person_id=pid,
            event_id=event.id,
            catalog_version=session.version,
            sim_h=world.s.time_h,
            status=status(world.s, pid),
            automatic=automatic,
            committed_commands=as_data(session.policy.committed),
            blocked_commitments=[
                dict(
                    command_id=c.id,
                    command_sha256=config_digest(c),
                    reason_event_id=event.id,
                    status="COMMITMENT_BLOCKED",
                )
                for c in session.policy.committed
                if kind in ("PERSON_DEPART", "PERSON_ABSENT")
                and (
                    any(r.person_id == pid for r in c.roles)
                    or any(
                        a.activity_id == c.activity_id
                        and a.state != "COMPLETE"
                        and any(r.person_id == pid for r in a.crew)
                        for a in world.s.mode_attempts
                    )
                )
            ],
        )
    )
    if not automatic:
        session._receipt(
            req,
            "APPLIED",
            "PERSON_COMMITTED",
            sequence=admission["sequence"],
            event=event,
            before=before,
        )
    else:
        session.persist()


def settle_departures(session):
    for pid in session.world.people:
        if status(session.world.s, pid) == "DEPARTURE_PENDING" and not obligated(
            session.world.s, pid
        ):
            original = next(r for r in reversed(session.workforce_results) if r["person_id"] == pid)
            req = deepcopy(session.requests[original["request_id"]])
            req["kind"] = "PERSON_LEFT"
            apply_request(session, req, session.admissions[req["request_id"]], automatic=True)
