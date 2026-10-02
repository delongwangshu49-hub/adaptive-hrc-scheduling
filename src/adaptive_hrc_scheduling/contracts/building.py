"""C04 building semantic boundary; no pipe-to-building coercion."""

import hashlib
import json

from adaptive_hrc_scheduling.contracts.codec import (
    ContractError,
    _pairs,
    as_data,
    decode,
    require,
)
from adaptive_hrc_scheduling.domain import building as b

TOP_LEVEL = (
    b.Configuration,
    b.PlanningInput,
    b.PlanningObservation,
    b.Plan,
    b.DispatchCommand,
    b.ExecutionEvent,
    b.ExecutionSnapshot,
    b.HiddenScenario,
    b.OfflineEvaluation,
    b.RunManifest,
)


def indexed(items, path):
    result = {x.id: x for x in items}
    require(len(result) == len(items), f"{path}: duplicate ID")
    return result


def evidence_pass(config, ids):
    evidence = {e.id: e for e in config.evidence}
    return all(
        i in evidence
        and evidence[i].status == "PASS"
        and (
            evidence[i].basis == "INDUSTRIAL"
            or config.purpose == "SYNTHETIC_TEST_ONLY"
            and evidence[i].basis == "SYNTHETIC_TEST"
        )
        for i in ids
    )


def validate(record, *, config=None):
    require(type(record) in TOP_LEVEL, "message: unsupported building type")
    record = decode(type(record), as_data(record))
    if isinstance(record, b.Configuration):
        c = record
        people = indexed(c.people, "people")
        resources = indexed(c.resources, "resources")
        products = indexed(c.products, "products")
        components = indexed(c.components, "components")
        materials = indexed(c.materials, "materials")
        activities = indexed(c.activities, "activities")
        evidence = indexed(c.evidence, "evidence")
        indexed(c.parameters, "parameters")
        all_ids = (
            list(people)
            + list(resources)
            + list(products)
            + list(components)
            + list(materials)
            + list(activities)
            + list(evidence)
        )
        require(len(set(all_ids)) == len(all_ids), "configuration: globally duplicate ID")
        require(c.cap > 0 and c.people and c.products and c.activities, "configuration: empty/cap")
        for e in c.evidence:
            require(
                e.status != "PASS" or e.basis != "UNRESOLVED", f"evidence.{e.id}: unresolved PASS"
            )
            require(e.status != "PASS" or bool(e.reference), f"evidence.{e.id}: missing source")
            require(
                e.basis != "SYNTHETIC_TEST" or c.purpose == "SYNTHETIC_TEST_ONLY",
                f"evidence.{e.id}: synthetic provenance",
            )
        for p in c.people:
            require(p.initial_f <= c.cap, f"people.{p.id}: cap")
            require(
                p.qualifications and len(set(p.qualifications)) == len(p.qualifications),
                f"people.{p.id}: qualifications",
            )
            last = 0
            for w in p.calendar.windows:
                require(
                    last <= w.start_h < w.end_h <= p.calendar.period_h,
                    f"people.{p.id}.calendar: overlap/window",
                )
                last = w.end_h
            require(p.calendar.windows, f"people.{p.id}.calendar: empty")
        for p in c.products:
            require(p.due_h >= p.release_h, f"products.{p.id}: due")
            bom = indexed(p.bom, f"products.{p.id}.bom")
            require(
                {"B-ST", "B-FL", "B-EN", "B-WT", "B-ME", "B-FI", "B-PR"} <= set(bom),
                f"products.{p.id}: incomplete BOM",
            )
            if p.variant == "SR-W2":
                require(
                    "B-BRANCH" in bom and "B-EXTRA-BASIN" in bom and "B-EXTRA-SOCKET" in bom,
                    f"products.{p.id}: variant BOM",
                )
            cc = [x for x in c.components if x.product_id == p.id]
            require(
                sorted((x.kind, x.quantity) for x in cc)
                == [("BOTTOM", 1), ("COLUMNS", 4), ("TOP", 1)],
                f"products.{p.id}: components",
            )
            aa = [x for x in c.activities if x.product_id == p.id]
            require(
                len({x.code for x in aa}) == len(aa), f"products.{p.id}: duplicate activity code"
            )
            require(len(aa) == 37, f"products.{p.id}: expected complete 37-activity graph")
            if p.variant == "SR-W2":
                bycode = {x.code: x for x in aa}
                require(
                    len(bycode["MEP-P"].modes[0].units) == 4
                    and len(bycode["Q-FIN"].modes[0].units) == 3,
                    f"products.{p.id}: variant work units",
                )
        for x in c.components:
            require(
                x.product_id in products and x.initial_location in resources,
                f"components.{x.id}: reference",
            )
        for x in c.materials:
            require(
                x.product_id in products and x.activity_id in activities,
                f"materials.{x.id}: reference",
            )
            require(
                activities[x.activity_id].product_id == x.product_id,
                f"materials.{x.id}: foreign product",
            )
            require(
                not x.released or x.arrived and x.identified,
                f"materials.{x.id}: release before identity/arrival",
            )
            require(
                set(x.bom_ids) <= {z.id for z in products[x.product_id].bom},
                f"materials.{x.id}: BOM reference",
            )
        for a in c.activities:
            path = f"activities.{a.id}"
            require(
                a.product_id in products and a.location in resources, path + ": location/product"
            )
            require(a.modes, path + ": no modes")
            indexed(a.modes, path + ".modes")
            quality_codes = {
                source for source, _, relation in b.STEEL_EDGES if relation == "quality"
            }
            wait_codes = {
                source for source, _, relation in b.STEEL_EDGES if relation == "wait_release"
            }
            move_codes = {"MV-IN-B", "MV-IN-T", "MV-B", "MV-T", "JOIN-IN", "MOVE-F", "MOVE-OUT"}
            require(
                (a.quality_evidence is not None) == (a.code in quality_codes),
                path + ": frozen quality gate",
            )
            require(
                (a.release_evidence is not None) == (a.code in wait_codes),
                path + ": frozen release gate",
            )
            require((a.wait_h > 0) == (a.code in wait_codes), path + ": frozen positive wait")
            require((a.move is not None) == (a.code in move_codes), path + ": frozen move")
            kinds = (
                {"H", "HR-seq"}
                if a.code in ("W-B", "W-T")
                else {"MOVE"}
                if a.move
                else {"WAIT"}
                if a.code in wait_codes
                else {"GATE"}
                if a.code == "READY"
                else {"H-team"}
            )
            require(
                {m.kind for m in a.modes} == kinds and len(a.modes) == len(kinds),
                path + ": frozen mode kinds",
            )
            for gate in (a.release_evidence, a.quality_evidence):
                require(gate is None or gate in evidence, path + ": gate reference")
            for mid in a.material_ids:
                require(
                    mid in materials
                    and materials[mid].activity_id == a.id
                    and materials[mid].product_id == a.product_id,
                    path + ": illegal material kit",
                )
            require(len(set(a.material_ids)) == len(a.material_ids), path + ": duplicate kit")
            for mode in a.modes:
                require(
                    mode.output_revision == products[a.product_id].revision,
                    path + ": output revision",
                )
                require(
                    set(mode.qualification_ids) <= set(evidence), path + ": qualification reference"
                )
                require(
                    len(mode.qualification_ids) == len(mode.qualification_revisions),
                    path + ": qualification revision coverage",
                )
                require(
                    all(
                        evidence[i].revision == v
                        for i, v in zip(
                            mode.qualification_ids, mode.qualification_revisions, strict=True
                        )
                    ),
                    path + ": changed qualification revision",
                )
                if mode.kind == "HR-seq":
                    required = {
                        "G2-JOINT",
                        "G2-WPS",
                        "G2-PROGRAM",
                        "G2-FIXTURE",
                        "G2-PEOPLE",
                        "G2-ISOLATION",
                        "G2-INSPECTION",
                        "G2-OUTPUT",
                    }
                    require(
                        required <= set(mode.qualification_ids), path + ": incomplete G2 coverage"
                    )
                    require(
                        not mode.enabled or evidence_pass(c, mode.qualification_ids),
                        path + ": HR unqualified",
                    )
                passive = {"WAIT-W", "WAIT-TEST", "WAIT-TILE", "WAIT-PAINT", "READY"}
                require(bool(mode.units) == (a.code not in passive), path + ": frozen work units")
                required_equipment = (
                    {"R1", "FIX-J2"}
                    if mode.kind == "HR-seq"
                    else {"WELD1", "FIX-J2"}
                    if a.code in ("W-B", "W-T")
                    else {"WELD1", "FIX-J3"}
                    if a.code == "W-3D"
                    else {"CUT1"}
                    if a.code == "CUT"
                    else {"HST1"}
                    if a.code.startswith("MV-")
                    else {"CR1"}
                    if a.code in ("JOIN-IN", "MOVE-F", "MOVE-OUT")
                    else {"TEST1"}
                    if a.code in ("Q-MEP", "TEST-SET", "Q-POND", "Q-EXT", "Q-FIN")
                    else set()
                )
                indexed(mode.units, path + ".units")
                for u in mode.units:
                    require(u.checkpoint_id in evidence, path + ": checkpoint reference")
                    indexed(u.roles, path + ".roles")
                    role_sets = {
                        "W-3D": {"W1", "W2"},
                        "JOIN-IN": {"Lop", "Lrig", "Lsig"},
                        "MOVE-F": {"Lop", "Lrig", "Lsig"},
                        "MOVE-OUT": {"Lop", "Lrig", "Lsig"},
                        "FLOOR": {"AF1", "AF2"},
                        "MEP-E": {"E1"},
                        "MEP-P": {"PL1"},
                        "Q-MEP": {"QA1", "E1", "PL1"},
                        "LINING": {"AF1", "AF2"},
                        "Q-POND": {"QA1", "T1"},
                        "TILE": {"T1", "T2"},
                        "FIT": {"AF1", "E1", "PL1"},
                        "Q-FIN": {"QA1", "E1", "PL1"},
                        "Q-STR": {"QA1", "W2"},
                    }
                    if a.code in role_sets:
                        require(
                            {r.id for r in u.roles} == role_sets[a.code],
                            path + ": missing frozen role",
                        )
                    require(set(u.equipment) <= set(resources), path + ": equipment reference")
                    require(
                        required_equipment <= set(u.equipment), path + ": missing frozen equipment"
                    )
                    for role in u.roles:
                        require(
                            any(role.qualification in p.qualifications for p in c.people),
                            path + ": missing qualified role " + role.id,
                        )
                    require(bool(u.roles) or u.phase == "ROBOT", path + ": missing roles")
                    require(
                        u.phase != "ROBOT" or mode.kind == "HR-seq" and not u.roles,
                        path + ": robot isolation",
                    )
            if a.move:
                move = a.move
                require(
                    all(
                        x in resources
                        for x in (move.source, move.target, move.route, move.equipment)
                    ),
                    path + ": move reference",
                )
                require(set(move.qualification_ids) <= set(evidence), path + ": move qualification")
                require(
                    len(move.qualification_ids) == len(move.qualification_revisions),
                    path + ": move qualification revision coverage",
                )
                require(
                    all(
                        evidence[i].revision == v
                        for i, v in zip(
                            move.qualification_ids, move.qualification_revisions, strict=True
                        )
                    ),
                    path + ": move qualification revision",
                )
                require(move.source != move.target and move.landing_h, path + ": move boundaries")
                require(
                    len(move.entity_ids) == len(set(move.entity_ids)) == len(move.landing_h),
                    path + ": move entity/landing coverage",
                )
                require(
                    all(
                        len(m.units) == 1
                        and m.units[0].base_h == move.landing_h[-1]
                        and move.equipment in m.units[0].equipment
                        for m in a.modes
                    ),
                    path + ": move work/equipment boundaries",
                )
                require(
                    list(move.landing_h) == sorted(set(move.landing_h)), path + ": landing order"
                )
                require(
                    set(move.entity_ids)
                    <= {a.product_id}
                    | {x.id for x in c.components if x.product_id == a.product_id},
                    path + ": foreign entity",
                )
                require(all(m.kind == "MOVE" for m in a.modes), path + ": move mode")
        require(len(set((e.source, e.target) for e in c.edges)) == len(c.edges), "edges: duplicate")
        for edge in c.edges:
            require(
                edge.source in activities and edge.target in activities, "edges: dangling reference"
            )
            require(
                activities[edge.source].product_id == activities[edge.target].product_id,
                "edges: foreign product",
            )
        pending = set(activities)
        while pending:
            ready = {
                x
                for x in pending
                if not any(e.target == x and e.source in pending for e in c.edges)
            }
            require(ready, "edges: cycle")
            pending -= ready
        expected_codes = {x for source, target, _ in b.STEEL_EDGES for x in (source, target)}
        for product in c.products:
            actual_codes = {a.code for a in c.activities if a.product_id == product.id}
            require(actual_codes == expected_codes, "activities: frozen steel codes")
            actual_edges = {
                (activities[e.source].code, activities[e.target].code, e.relation)
                for e in c.edges
                if activities[e.source].product_id == product.id
            }
            require(actual_edges == set(b.STEEL_EDGES), "edges: frozen steel DAG")
        for pair in c.face_pairs:
            require(
                pair.qualification_id in evidence and pair.first != pair.second,
                "face_pairs: qualification/pair",
            )
        return
    require(
        config is not None and record.config_id == config.id,
        "config_id: missing/mismatched configuration",
    )
    aa = {x.id: x for x in config.activities}
    pp = {x.id: x for x in config.products}
    hh = {x.id: x for x in config.people}
    rr = {x.id: x for x in config.resources}
    if isinstance(record, b.DispatchCommand):
        require(record.activity_id in aa, "dispatch.activity_id: unknown")
        a = aa[record.activity_id]
        modes = {m.id: m for m in a.modes}
        require(record.mode_id in modes, "dispatch.mode_id: unknown")
        m = modes[record.mode_id]
        require(
            m.enabled and (m.kind != "HR-seq" or evidence_pass(config, m.qualification_ids)),
            "dispatch.mode_id: disabled/unqualified",
        )
        require(record.attempt <= 1, "dispatch.attempt: repair limit")
        require(record.unit_index < max(1, len(m.units)), "dispatch.unit_index: range")
        expected = m.units[record.unit_index].roles if m.units else ()
        require(
            {r.role_id for r in record.roles} == {r.id for r in expected}
            and len(record.roles) == len(expected),
            "dispatch.roles: missing/duplicate role",
        )
        require(
            len({r.person_id for r in record.roles}) == len(record.roles),
            "dispatch.roles: independent roles require distinct people",
        )
        for r in record.roles:
            required = next(x.qualification for x in expected if x.id == r.role_id)
            require(
                r.person_id in hh and required in hh[r.person_id].qualifications,
                "dispatch.roles: qualification",
            )
            require(record.issued_h < hh[r.person_id].valid_until_h, "dispatch.roles: expired")
    elif isinstance(record, b.PlanningObservation):
        require(
            record.sampled_h <= record.received_h <= record.observed_h,
            "observation: time authorization",
        )
        require(
            len({p.product_id for p in record.products}) == len(record.products),
            "observation.products: duplicate",
        )
        for p in record.products:
            require(
                p.product_id in pp and pp[p.product_id].release_h <= record.sampled_h,
                "observation.products: future/unknown product",
            )
            require(
                all(a in aa and aa[a].product_id == p.product_id for a in p.completed_activity_ids),
                "observation.products: foreign progress",
            )
        require(all(h.person_id in hh for h in record.people), "observation.people: reference")
        require(set(record.unavailable_resources) <= set(rr), "observation.resources: reference")
    elif isinstance(record, b.PlanningInput):
        validate(record.observation, config=config)
        visible = {p.product_id for p in record.observation.products}
        require({p.id for p in record.products} == visible, "planning.products: unauthorized view")
        require(
            all(a.product_id in visible and a in config.activities for a in record.activities),
            "planning.activities: unauthorized view",
        )
        require(
            all(p == pp[p.id] for p in record.products), "planning.products: changed static data"
        )
    elif isinstance(record, b.HiddenScenario):
        indexed(record.events, "scenario.events")
        seen = {}
        for e in record.events:
            kind = e.kind
            refs = (
                {m.id for m in config.materials}
                if kind.startswith("MATERIAL_")
                else set(rr)
                if kind in ("FAILURE", "REPAIR")
                else set(aa)
                if kind in ("PROCESS_RELEASE", "QUALITY_RESULT", "INVALIDATE")
                else set(pp)
            )
            require(e.entity_id in refs, "scenario.events: entity reference")
            if kind in ("FAILURE", "REPAIR"):
                key = (e.entity_id, e.time_h)
                require(
                    key not in seen or seen[key] == kind,
                    "scenario.events: conflicting failure/repair",
                )
                seen[key] = kind
            require(
                kind != "QUALITY_RESULT" or e.value is not None and e.attempt is not None,
                "scenario.events: missing result identity",
            )
    elif isinstance(record, b.ExecutionSnapshot):
        require(record.config_sha256 == digest(config), "snapshot: configuration digest")
        require(
            {p.product_id for p in record.products} == set(pp) and len(record.products) == len(pp),
            "snapshot.products: coverage",
        )
        require(
            {h.person_id for h in record.people} == set(hh) and len(record.people) == len(hh),
            "snapshot.people: coverage",
        )
        require(
            all(h.fatigue <= config.cap and h.peak <= config.cap for h in record.people),
            "snapshot.people: cap",
        )
        require(
            len(set(record.consumed_commands)) == len(record.consumed_commands),
            "snapshot.commands: duplicate",
        )
        require(
            len({(a.activity_id, a.number) for a in record.attempts}) == len(record.attempts),
            "snapshot.attempts: duplicate",
        )
        require(
            all(a.activity_id in aa and a.number <= 1 for a in record.attempts),
            "snapshot.attempts: reference/repair limit",
        )
        require(
            all(
                r.activity_id in aa and r.start_h <= record.time_h and r.start_h <= r.end_h
                for r in record.running
            ),
            "snapshot.running: time/reference",
        )
        for p in record.products:
            if p.location == "UNASSEMBLED":
                require(
                    not any(x.entity_id == p.product_id for x in record.residencies),
                    "snapshot: logical product cannot occupy a bay",
                )
        require(
            len({(r.entity_id, r.location, r.reserved) for r in record.residencies})
            == len(record.residencies),
            "snapshot.residencies: duplicate",
        )
        for r in record.residencies:
            require(r.location in rr, "snapshot.residencies: location")
        for rid, res in rr.items():
            owners = {r.owner for r in record.residencies if r.location == rid}
            require(len(owners) <= res.capacity, "snapshot.residencies: capacity " + rid)
        require(
            len({x.resource_id for x in record.locks}) == len(record.locks),
            "snapshot.locks: duplicate resource",
        )
        require(
            all(x.resource_id in rr or x.resource_id in hh for x in record.locks),
            "snapshot.locks: reference",
        )
        validate(record.scenario, config=config)
        require(record.event_cursor <= len(record.scenario.events), "snapshot.event_cursor: range")
        component_ids = {x.id for x in config.components}
        material_ids = {x.id for x in config.materials}
        require(
            {x.component_id for x in record.components} == component_ids
            and len(record.components) == len(component_ids),
            "snapshot.components: coverage",
        )
        require(
            {x.material_id for x in record.materials} == material_ids
            and len(record.materials) == len(material_ids),
            "snapshot.materials: coverage",
        )
        for material in record.materials:
            require(
                not material.released or material.arrived and material.identified,
                "snapshot.materials: release",
            )
        attempts = {(a.activity_id, a.number): a for a in record.attempts}
        for attempt in record.attempts:
            modes = {m.id: m for m in aa[attempt.activity_id].modes}
            require(attempt.mode_id in modes, "snapshot.attempts: mode reference")
            require(
                attempt.completed_units <= len(modes[attempt.mode_id].units),
                "snapshot.attempts: progress",
            )
        require(
            len({r.activity_id for r in record.running}) == len(record.running),
            "snapshot.running: duplicate",
        )
        for run in record.running:
            require((run.activity_id, run.attempt) in attempts, "snapshot.running: missing attempt")
            attempt = attempts[(run.activity_id, run.attempt)]
            require(
                attempt.state == "RUNNING"
                and attempt.completed_units == run.unit_index
                and attempt.mode_id == run.mode_id,
                "snapshot.running: attempt mismatch",
            )
            mode = next(m for m in aa[run.activity_id].modes if m.id == run.mode_id)
            require(run.unit_index < len(mode.units), "snapshot.running: unit range")
            unit = mode.units[run.unit_index]
            require(
                run.multiplier == 1 + unit.kappa * run.sampled_max_f
                and run.end_h == run.start_h + unit.base_h * run.multiplier,
                "snapshot.running: anchor/multiplier",
            )
            require(run.equipment == unit.equipment, "snapshot.running: equipment mismatch")
            require(
                {x.role_id for x in run.roles} == {r.id for r in unit.roles}
                and len({x.person_id for x in run.roles}) == len(unit.roles),
                "snapshot.running: roles",
            )
            for binding in run.roles:
                require(binding.person_id in hh, "snapshot.running: person")
                role = next(r for r in unit.roles if r.id == binding.role_id)
                require(
                    role.qualification in hh[binding.person_id].qualifications,
                    "snapshot.running: qualification",
                )
            for rid in tuple(x.person_id for x in run.roles) + run.equipment:
                require(
                    any(
                        lock.resource_id == rid and lock.owner == run.activity_id
                        for lock in record.locks
                    ),
                    "snapshot.running: missing lock",
                )
        for service in record.services:
            require(
                service.product_id in pp and service.start_h <= record.time_h <= service.end_h,
                "snapshot.services: reference/time",
            )
            require(
                len(service.people) == len(set(service.people)) and set(service.people) <= set(hh),
                "snapshot.services: people",
            )
            require(
                all(
                    any(
                        lock.resource_id == pid and lock.owner == service.id
                        for lock in record.locks
                    )
                    for pid in service.people
                ),
                "snapshot.services: missing lock",
            )
        require(record.random_cursor == 0, "snapshot.random_cursor: no stochastic draws in C05")
        require(
            list(record.scenario.events)
            == sorted(record.scenario.events, key=lambda e: (e.time_h, e.id)),
            "snapshot.scenario: order",
        )
        require(
            all(e.time_h <= record.time_h for e in record.scenario.events[: record.event_cursor]),
            "snapshot.event_cursor: future consumed",
        )
        require(
            all(e.time_h > record.time_h for e in record.scenario.events[record.event_cursor :]),
            "snapshot.event_cursor: missed event",
        )
        validate_residencies(record, config)
        for obs in record.observation_queue:
            validate(obs, config=config)
    elif isinstance(record, b.Plan):
        for cmd in record.commands:
            validate(cmd, config=config)
        require(
            all(p.product_id in pp for p in record.predicted_ready), "plan.predictions: reference"
        )
    elif isinstance(record, b.RunManifest):
        require(record.configuration_sha256 == digest(config), "manifest: configuration digest")
        import re

        require(
            bool(re.fullmatch("[0-9a-f]{40}", record.code_revision))
            or record.status == "PLANNED"
            and record.code_revision == "example.uncommitted",
            "manifest: code revision",
        )
    elif isinstance(record, b.OfflineEvaluation):
        require({p.product_id for p in record.products} == set(pp), "evaluation.products: coverage")
        require({p.person_id for p in record.people} == set(hh), "evaluation.people: coverage")


def validate_residencies(state, config):
    """Check both directions of the physical location/reservation ledger on recovery."""
    resources = {r.id: r for r in config.resources}
    components = {c.id: c for c in config.components}
    activities = {a.id: a for a in config.activities}
    # entity -> (held source, reserved destination, current physical location)
    transfers = {}
    for run in state.running:
        move = activities[run.activity_id].move
        if move is None:
            continue
        require(state.time_h < run.end_h, "snapshot.physical: expired movement")
        done = sum(run.start_h + t * run.multiplier <= state.time_h for t in move.landing_h)
        require(done == run.landings_done, "snapshot.physical: landing progress")
        for index, entity in enumerate(move.entity_ids):
            if index < done:
                continue
            require(entity not in transfers, "snapshot.physical: duplicate movement")
            source = (
                "PRE"
                if entity in components
                and components[entity].kind == "COLUMNS"
                and activities[run.activity_id].code == "JOIN-IN"
                else move.source
            )
            previous = move.landing_h[index - 1] if index else 0
            lift = (
                run.start_h + (previous + (move.landing_h[index] - previous) * 0.4) * run.multiplier
            )
            transfers[entity] = (
                source,
                move.target,
                "IN_TRANSIT" if state.time_h >= lift else source,
            )
    for service in state.services:
        if service.kind != "CLEANUP":
            continue
        require(service.product_id not in transfers, "snapshot.physical: duplicate cleanup")
        require(state.time_h < service.end_h, "snapshot.physical: expired cleanup")
        transfers[service.product_id] = (
            service.source,
            service.target,
            "IN_TRANSIT" if state.time_h >= service.start_h + 0.4 else service.source,
        )
    expected = set()

    def add(entity, product, location, reserved):
        require(
            location in resources and resources[location].kind in ("BAY", "BUFFER"),
            "snapshot.residencies: physical location",
        )
        # A product may hold both of its frames in J2; BUF counts individual frames.
        owner = entity if location == "BUF" else product
        expected.add((entity, location, owner, reserved))

    physical = [(p.product_id, p.product_id, p.location) for p in state.products]
    physical += [
        (c.component_id, components[c.component_id].product_id, c.location)
        for c in state.components
    ]
    entities = {entity for entity, _, _ in physical}
    require(set(transfers) <= entities, "snapshot.physical: unknown moving entity")
    for entity, product, location in physical:
        if entity in transfers:
            source, target, actual = transfers[entity]
            require(location == actual, "snapshot.physical: movement location")
            add(entity, product, source, False)
            add(entity, product, target, True)
        elif location not in ("UNASSEMBLED", "UNFABRICATED", "INCORPORATED", "EXTERNAL"):
            add(entity, product, location, False)
        else:
            if entity in components:
                component = next(c for c in state.components if c.component_id == entity)
                require(
                    location in ("UNFABRICATED", "INCORPORATED")
                    and component.incorporated == (location == "INCORPORATED"),
                    "snapshot.physical: component location",
                )
            else:
                product_state = next(p for p in state.products if p.product_id == entity)
                require(
                    location in ("UNASSEMBLED", "EXTERNAL")
                    and (location != "EXTERNAL" or product_state.state == "RECEIVED"),
                    "snapshot.physical: product location",
                )
    for product in config.products:
        kit_started = any(
            activities[a.activity_id].product_id == product.id
            and activities[a.activity_id].code == "KIT"
            for a in state.attempts
        )
        unfabricated = all(
            c.location == "UNFABRICATED"
            for c in state.components
            if components[c.component_id].product_id == product.id
        )
        if kit_started and unfabricated:
            add(product.id + ".RAW", product.id, "PRE", False)
    actual = {(r.entity_id, r.location, r.owner, r.reserved) for r in state.residencies}
    require(actual == expected, "snapshot.residencies: physical ledger mismatch")


def loads(kind, text, *, config=None):
    try:
        data = json.loads(text, object_pairs_hook=_pairs)
    except (ValueError, UnicodeError) as error:
        raise ContractError(str(error)) from error
    record = decode(kind, data)
    validate(record, config=config)
    return record


def dumps(record, *, config=None):
    checked = decode(type(record), as_data(record))
    validate(checked, config=config)
    return (
        json.dumps(as_data(checked), ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
        + "\n"
    )


def digest(config):
    return hashlib.sha256(dumps(config).encode("utf-8")).hexdigest()


def planning_input(config, observation, budget_ms=100.0):
    validate(observation, config=config)
    visible = {p.product_id for p in observation.products}
    out = b.PlanningInput(
        "C04-1.0",
        config.id,
        observation,
        tuple(p for p in config.products if p.id in visible),
        tuple(a for a in config.activities if a.product_id in visible),
        budget_ms,
    )
    validate(out, config=config)
    return out
