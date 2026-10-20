"""S20 post-production evaluation ledger; never modifies execution snapshots."""

import math
from dataclasses import replace

from adaptive_hrc_scheduling.building_human import calendar_state, integrate
from adaptive_hrc_scheduling.contracts.codec import as_data, require
from adaptive_hrc_scheduling.contracts.production import digest
from adaptive_hrc_scheduling.control.production_decisions import check_decisions, fingerprint
from adaptive_hrc_scheduling.production_checker import check_run


def rest_tail(config, humans, start_h, end_h):
    require(
        math.isfinite(start_h) and math.isfinite(end_h) and 0 <= start_h <= end_h, "TAIL_WINDOW"
    )
    require({h.person_id for h in humans} == {p.id for p in config.people}, "TAIL_PEOPLE")
    current = {h.person_id: h for h in humans}
    intervals = []
    t = start_h
    while t < end_h:
        bound = min(end_h, *(calendar_state(p, t)[1] for p in config.people))
        require(bound > t, "TAIL_CALENDAR_PROGRESS")
        for person in config.people:
            activity = "OFF_SHIFT" if calendar_state(person, t)[0] == "OFF_SHIFT" else "REST"
            new, interval = integrate(person, current[person.id], activity, t, bound, config.cap)
            current[person.id] = new
            intervals.append(as_data(interval))
        t = bound
    return tuple(current[p.id] for p in config.people), tuple(intervals)


def common_horizon(config, snapshot, decisions, end_h):
    require(check_run(config, snapshot).status == "PASS", "TAIL_INVALID_EXECUTION")
    require(check_decisions(config, snapshot, decisions).status == "PASS", "TAIL_INVALID_CAUSAL")
    require(
        type(end_h) in (int, float) and math.isfinite(end_h) and end_h >= snapshot.state.time_h,
        "TAIL_WINDOW",
    )
    state = snapshot.state
    result = dict(
        version="S20-REST-TAIL-r1",
        config_sha256=digest(config),
        source_sha256=digest(snapshot),
        decisions_sha256=fingerprint(tuple(decisions)),
        source_end_h=state.time_h,
        end_h=end_h,
        policy="POST_RECEIPT_REST_ON_DUTY_OFF_SHIFT_OTHERWISE",
        lifecycle_humans=as_data(state.humans),
        source_scope="AUDITED_EXECUTION_THEN_DERIVED_EVALUATION_NOT_EXECUTION_EVENTS",
    )
    if state.time_h < end_h and (
        any(p.received_h is None for p in state.products)
        or state.running
        or state.owners
        or state.reservations
    ):
        return dict(result, status="INCOMPLETE_SOURCE_NO_TAIL", common_humans=None, intervals=[])
    humans, intervals = rest_tail(config, state.humans, state.time_h, end_h)
    return dict(result, status="PASS", common_humans=as_data(humans), intervals=list(intervals))


def check_common_horizon(config, snapshot, decisions, ledger):
    """Recompute the declared REST ledger with a separate closed-form integral."""
    try:
        require(check_run(config, snapshot).status == "PASS", "TAIL_INVALID_EXECUTION")
        require(
            check_decisions(config, snapshot, decisions).status == "PASS", "TAIL_INVALID_CAUSAL"
        )
        require(
            ledger["version"] == "S20-REST-TAIL-r1"
            and ledger["source_sha256"] == digest(snapshot)
            and ledger["config_sha256"] == digest(config)
            and ledger["decisions_sha256"] == fingerprint(tuple(decisions))
            and ledger["source_end_h"] == snapshot.state.time_h
            and ledger["policy"] == "POST_RECEIPT_REST_ON_DUTY_OFF_SHIFT_OTHERWISE"
            and ledger["source_scope"]
            == "AUDITED_EXECUTION_THEN_DERIVED_EVALUATION_NOT_EXECUTION_EVENTS"
            and ledger["lifecycle_humans"] == as_data(snapshot.state.humans),
            "TAIL_SOURCE",
        )
        end = ledger["end_h"]
        require(
            type(end) in (int, float) and math.isfinite(end) and end >= snapshot.state.time_h,
            "TAIL_WINDOW",
        )
        complete = all(p.received_h is not None for p in snapshot.state.products)
        incomplete = snapshot.state.time_h < end and (
            not complete
            or snapshot.state.running
            or snapshot.state.owners
            or snapshot.state.reservations
        )
        if incomplete:
            require(
                ledger["status"] == "INCOMPLETE_SOURCE_NO_TAIL"
                and ledger["common_humans"] is None
                and ledger["intervals"] == [],
                "TAIL_FABRICATED",
            )
            return "PASS"
        require(ledger["status"] == "PASS", "TAIL_STATUS")
        expected = {h.person_id: h for h in snapshot.state.humans}
        intervals = []
        t = snapshot.state.time_h
        while t < end:
            # Derive calendar boundaries directly, without calling rest_tail/integrate.
            boundaries = []
            kinds = {}
            for person in config.people:
                phase = t % person.calendar.period_h
                edges = [x for w in person.calendar.windows for x in (w.start_h, w.end_h)]
                following = [x for x in edges if x > phase]
                boundaries.append(
                    t - phase + (min(following) if following else person.calendar.period_h)
                )
                kinds[person.id] = (
                    "OFF_SHIFT"
                    if phase < person.calendar.windows[0].start_h
                    or phase >= person.calendar.windows[-1].end_h
                    else "REST"
                )
            bound = min(end, *boundaries)
            require(bound > t, "TAIL_CALENDAR_PROGRESS")
            for person in config.people:
                old = expected[person.id]
                dt, rate = bound - t, person.recovery_rate
                active = min(dt, old.fatigue / rate) if rate else dt
                final = max(0, old.fatigue - rate * dt)
                area = active * (old.fatigue + final) / 2
                expected[person.id] = replace(old, fatigue=final, exposure=old.exposure + area)
                intervals.append(
                    dict(
                        person_id=person.id,
                        start_h=t,
                        end_h=bound,
                        activity=kinds[person.id],
                        rate=rate,
                        start_f=old.fatigue,
                        end_f=final,
                        exposure=area,
                    )
                )
            t = bound
        require(len(intervals) == len(ledger["intervals"]), "TAIL_INTERVAL_COUNT")
        for a, b in zip(intervals, ledger["intervals"]):
            require(a.keys() == b.keys(), "TAIL_INTERVAL_FIELDS")
            require(
                all(
                    math.isclose(v, b[k], abs_tol=1e-10, rel_tol=1e-12)
                    if type(v) in (int, float)
                    else v == b[k]
                    for k, v in a.items()
                ),
                "TAIL_INTEGRAL",
            )
        actual = ledger["common_humans"]
        require(len(actual) == len(expected), "TAIL_PEOPLE")
        for person, row in zip(config.people, actual):
            old = as_data(expected[person.id])
            require(
                old.keys() == row.keys()
                and all(
                    math.isclose(v, row[k], abs_tol=1e-10, rel_tol=1e-12)
                    if type(v) in (int, float)
                    else v == row[k]
                    for k, v in old.items()
                ),
                "TAIL_HUMAN_RESULT",
            )
        return "PASS"
    except (ValueError, KeyError, TypeError, AttributeError, ZeroDivisionError):
        return "INVALID"
