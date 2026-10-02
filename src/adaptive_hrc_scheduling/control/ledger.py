"""S12 decision-prefix verification using S10's independent event reducer.

No controller, observation producer or backend admission methods are called.
A full S10 check of the final physical trace remains a separate prerequisite.
"""

import copy
import json
from dataclasses import fields, replace

from adaptive_hrc_scheduling.checker import _Audit, close
from adaptive_hrc_scheduling.domain import building as b

COMMITMENTS = {"UNIT_START", "READY", "COMPLETED", "REST_START", "CLEANUP_START"}


def audit_prefixes(config, trace, turns):
    """Return findings; old ledgers without actual boundary counts fail closed."""
    findings = []
    audit = _Audit(config, trace, trace.time_h)
    audit.released = {p.id for p in config.products if p.release_h == 0}
    scenario_ids = {e.id for e in trace.scenario.events}
    ticks = sorted({x.end_h for x in trace.intervals})
    versions = [0]
    for e in trace.events:
        manual_fact = e.kind == "EXTERNAL" and e.entity_id not in scenario_ids
        versions.append(versions[-1] + int(e.kind in COMMITMENTS or manual_fact))

    # Actual interval endpoints are independent evidence of the integration ticks.
    humans = {(0, p.id): (p.initial_f, 0, p.initial_f) for p in config.people}
    totals = {p.id: (0, p.initial_f) for p in config.people}
    for row in trace.intervals:
        exposure, peak = totals[row.person_id]
        exposure += row.exposure
        peak = max(peak, row.start_f, row.end_f)
        totals[row.person_id] = exposure, peak
        humans[row.end_h, row.person_id] = row.end_f, exposure, peak
    cursor = previous_end = 0
    previous_h = 0

    for turn in turns:
        f, d = turn.feedback, turn.decision
        o, state = f.observation, f.state

        def need(ok, code):
            if not ok:
                findings.append(f"{d.id}:{code}")
            return ok

        before, after = turn.before_event_count, turn.after_event_count
        if not need(
            type(before) is int
            and type(after) is int
            and previous_end <= before <= after <= len(trace.events),
            "INCOMPLETE:ACTUAL_BOUNDARIES_REQUIRED",
        ):
            return tuple(findings)
        need(d.time_h == previous_h, "OBSERVATION_AT_ACTUAL_RETURN")
        need(
            all(
                e.time_h == d.time_h and e.kind not in COMMITMENTS
                for e in trace.events[previous_end:before]
            ),
            "UNBOUND_BETWEEN_TURN_COMMITMENT",
        )
        need(
            tuple(e.id for e in trace.events[before:after]) == turn.actual_event_ids,
            "EXACT_ACTION_EVENT_RANGE",
        )
        need(all(e.time_h <= d.time_h for e in trace.events[:before]), "FUTURE_PREFIX")
        need(all(e.time_h >= turn.after_h for e in trace.events[after:]), "OMITTED_PAST_EVENT")
        while cursor < before:
            e = trace.events[cursor]
            audit.event = e
            audit.advance_area(e.time_h)
            audit.event_record(e)
            cursor += 1
        audit.event = None
        need(not audit.findings, "INVALID_ACTUAL_PREFIX")
        expected_revision = versions[before] + sum(t <= d.time_h for t in ticks)
        need(o.state_revision == d.revision == expected_revision, "ACTUAL_OBSERVATION_REVISION")
        need(
            turn.after_revision == versions[after] + sum(t <= turn.after_h for t in ticks),
            "ACTUAL_RETURN_REVISION",
        )
        visible = audit.released
        aids = {a.id for a in config.activities if a.product_id in visible}
        refs = (
            visible
            | aids
            | {x.id for x in config.components + config.materials if x.product_id in visible}
        )
        refs |= {x.id for x in config.people + config.resources}
        evidence = {"G1", "G2", "G4", "G5", "G6", "G7"}
        for a in config.activities:
            if a.id in aids:
                evidence.update((a.quality_evidence, a.release_evidence))
                for m in a.modes:
                    evidence.update(m.qualification_ids)
                    evidence.update(u.checkpoint_id for u in m.units)
        expected_config = replace(
            config,
            **{
                name: tuple(
                    x
                    for x in getattr(config, name)
                    if (x.id if name == "products" else x.product_id) in visible
                )
                for name in ("products", "activities", "components", "materials")
            },
            edges=tuple(e for e in config.edges if e.source in aids and e.target in aids),
            evidence=tuple(e for e in config.evidence if e.id in evidence),
        )
        need(f.configuration == expected_config, "EXACT_VISIBLE_CONFIGURATION")
        expected_events = tuple(
            e
            for e in trace.events[:before]
            if (
                json.loads(e.reason)["entity_id"] in refs
                if e.kind == "EXTERNAL"
                else e.entity_id in refs or e.kind in ("REST_START", "PROTECTIVE_REST")
            )
        )
        need(
            state.events == expected_events and o.event_ids == tuple(e.id for e in expected_events),
            "COMPLETE_VISIBLE_EVENT_PREFIX",
        )
        need(
            o.config_id == config.id and o.id == f"OBS-{expected_revision}-0",
            "ACTUAL_OBSERVATION_ID",
        )
        need(
            {p.product_id for p in o.products} == visible and len(o.products) == len(visible),
            "COMPLETE_RELEASED_PRODUCTS",
        )
        for p in o.products:
            completed = {
                aid
                for (aid, _), a in audit.attempt_history.items()
                if audit.a[aid].product_id == p.product_id and a.state == "COMPLETED"
            }
            need(
                p.state == audit.product_states.get(p.product_id)
                and p.location == audit.locations.get(p.product_id)
                and p.cancelled == (p.product_id in audit.cancelled)
                and set(p.completed_activity_ids) == completed
                and len(p.completed_activity_ids) == len(completed),
                "OBSERVED_PRODUCT_STATE",
            )
        unavailable = audit.failed | {rid for rid in audit.locks if rid in audit.resources}
        need(tuple(sorted(unavailable)) == o.unavailable_resources, "OBSERVED_UNAVAILABLE")
        released = {aid for aid, a in audit.attempts.items() if aid in aids and a.released}
        need(
            set(state.released_processes) == released
            and len(state.released_processes) == len(released),
            "OBSERVED_PROCESS_RELEASE",
        )
        need(
            {h.person_id for h in o.people} == set(audit.people)
            and len(o.people) == len(audit.people),
            "OBSERVED_PEOPLE_COVERAGE",
        )
        for h in o.people:
            values = humans.get((d.time_h, h.person_id))
            rest_until = max([0, *(end for _, end, pid in audit.rests if pid == h.person_id)])
            need(
                values is not None
                and all(close(x, y) for x, y in zip((h.fatigue, h.exposure, h.peak), values))
                and h.rest_until_h == rest_until,
                "OBSERVED_HUMAN_STATE",
            )

        # Compare only released entities, while locks/failures remain factory-wide.
        view = copy.copy(audit)
        view.findings = []
        view.window = view.t = d.time_h
        view.s = replace(
            trace,
            **{x.name: getattr(state, x.name) for x in fields(state)},
            time_h=d.time_h,
            people=o.people,
            scenario=b.HiddenScenario("C04-1.0", config.id, 0, ()),
        )
        view.p = {k: v for k, v in audit.p.items() if k in visible}
        for name in ("components", "materials"):
            setattr(view, name, {k: v for k, v in getattr(audit, name).items() if k in refs})
        view.running = {k: v for k, v in audit.running.items() if k in aids}
        view.attempt_history = {k: v for k, v in audit.attempt_history.items() if k[0] in aids}
        view.quality = {k: v for k, v in audit.quality.items() if k[0] in aids}
        view.services = {k: v for k, v in audit.services.items() if v["product_id"] in visible}
        view.residencies = {x for x in audit.residencies if x[2] in visible}
        view.compare_snapshot()
        findings.extend(f"{d.id}:OBSERVED_STATE:{x.code}" for x in view.findings)
        previous_end, previous_h = after, turn.after_h
    if previous_end != len(trace.events) or previous_h != trace.time_h:
        findings.append("INCOMPLETE:FINAL_ACTUAL_BOUNDARY")
    if trace.revision != versions[-1] + len(ticks):
        findings.append("FINAL_ACTUAL_REVISION")
    return tuple(findings)
