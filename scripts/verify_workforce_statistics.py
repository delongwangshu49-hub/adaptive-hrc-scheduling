"""Independent workforce intervals, rates, scene and return audit.

No Session, executor, metrics projector or workforce transition predicates.
"""

import math

from adaptive_hrc_scheduling.contracts.session import digest as sha


def verify_statistics(spec, saved, history, snapshot, check):
    stats = saved["workforce_statistics"]
    check(
        stats["identity"] == "P043-PRESENCE-LABOUR-r1"
        and stats["common_window_h"] == [0, snapshot.state.time_h]
        and stats["legacy_cost_policy"] == "UNCHANGED_FROZEN_RESOURCE_MODEL",
        "STATISTICS_WINDOW_AND_POLICY",
    )
    check(stats["run_spec_sha256"] == sha(spec), "STATISTICS_RUNSPEC")
    rates = {r["template_id"]: r["rate_per_h"] for r in spec["cost"]["rates"]}
    check(stats["policy_sha256"] == spec["cost"]["policy_sha256"], "STATISTICS_COST_POLICY")
    check(
        stats["legacy_resource_cost_source_sha256"] == spec["initial_config_sha256"],
        "FROZEN_RESOURCE_COST",
    )
    arrivals = {
        r["target_id"]: r
        for r in saved["generations"]
        if r.get("workforce_kind") == "PERSON_ARRIVE"
    }
    check(
        set(stats["people"]) == {p.id for p in history.current.people}, "STATISTICS_PERSON_COVERAGE"
    )
    total_available = total_cost = total_exposure = 0
    for p in history.current.people:
        g = arrivals.get(p.id)
        start = g["sim_h"] if g else 0
        tid = g["payload"]["parameter_template_id"] if g else p.id
        v = stats["people"][p.id]
        check(
            v["qualification_version"] == (1 if g else 0) and v["valid_until_h"] == p.valid_until_h,
            "PERSON_QUALIFICATION_VERSION:" + p.id,
        )
        check(
            v["defined_from_h"] == start and v["before_arrival"] == "NOT_IN_CATALOG",
            "PERSON_BASELINE:" + p.id,
        )
        check(
            tid in rates and v["template_id"] == tid and v["rate_per_h"] == rates[tid],
            "PERSON_RATE:" + p.id,
        )
        person_events = [
            e
            for e in snapshot.events
            if e.world and e.world.entity_id == p.id and e.world.kind.startswith("PERSON_")
        ]
        presence = []
        availability = []
        activity = []
        for row in snapshot.state.intervals:
            if row.person_id != p.id:
                continue
            check(row.start_h >= start, "NO_PREARRIVAL_HISTORY:" + p.id)
            last = next(
                (e for e in reversed(person_events) if e.occurred_sim_h <= row.start_h), None
            )
            flags = last.state.failed_resources if last else ()
            present = not any("P043." + k + "." + p.id in flags for k in ("ABSENT", "DEPARTED"))
            blocked = any(
                "P043." + k + "." + p.id in flags
                for k in ("ABSENT", "ABSENT_HOLD", "DEPARTED", "DEPARTURE_PENDING")
            )
            phase = row.start_h % p.calendar.period_h
            window = any(w.start_h <= phase < w.end_h for w in p.calendar.windows)
            available = not blocked and window and row.start_h < p.valid_until_h
            if present:
                presence.append([row.start_h, row.end_h])
            if present and available and min(row.end_h, p.valid_until_h) > row.start_h:
                availability.append([row.start_h, min(row.end_h, p.valid_until_h)])
            from dataclasses import asdict

            activity.append(dict(asdict(row), presence=present, availability=available))
        check(
            v["presence_intervals"] == presence
            and v["availability_intervals"] == availability
            and v["activity_intervals"] == activity,
            "PERSON_INTERVALS:" + p.id,
        )
        ph = sum(b - a for a, b in presence)
        ah = sum(b - a for a, b in availability)
        h = next(x for x in snapshot.state.humans if x.person_id == p.id)
        check(
            all(
                math.isclose(v[k], expected, abs_tol=1e-9)
                for k, expected in dict(
                    presence_h=ph,
                    available_h=ah,
                    labour_cost=ph * rates[tid],
                    fatigue=h.fatigue,
                    exposure=h.exposure,
                    peak=h.peak,
                    presence_exposure=sum(x["exposure"] for x in activity if x["presence"]),
                ).items()
            ),
            "PERSON_TOTALS:" + p.id,
        )
        if g:
            e = next(e for e in snapshot.events if e.id == g["event_id"])
            h0 = next(x for x in e.state.humans if x.person_id == p.id)
            check(
                h0.fatigue == p.initial_f and h0.exposure == 0 and h0.peak == p.initial_f,
                "TRUE_NEW_BASELINE:" + p.id,
            )
            check(
                all(
                    p.id not in {h.person_id for h in x.state.humans}
                    for x in snapshot.events[: e.sequence - 1]
                ),
                "TRUE_NEW_PERSON:" + p.id,
            )
            scene = next(
                (
                    s
                    for s in saved["scene_bindings"]
                    if s["event_id"] == e.id and s["domain_id"] == p.id
                ),
                None,
            )
            check(
                scene is not None
                and scene["scope"] == "P043_PERSON_ACTUAL_READBACK"
                and scene["ready"]
                and scene["actual_location"] == g["payload"]["arrival_location"]
                and scene["scene_entity_id"] == p.id,
                "PERSON_SCENE_READY:" + p.id,
            )
            check(
                scene["catalog_version"]
                == next(d["new_version"] for d in saved["deltas"] if d["commit_event_id"] == e.id),
                "PERSON_SCENE_VERSION:" + p.id,
            )
            if spec["backend"] == "ISAAC":
                check(
                    scene["source"] == "ISAAC_USD"
                    and scene["prim_path"] == g["payload"]["scene_reference"]["prim_path"]
                    and (scene["run_id"], scene["epoch"]) == (spec["run_id"], spec["epoch"]),
                    "PERSON_REAL_USD:" + p.id,
                )
            else:
                check(scene["prim_path"] == "CPU:N/A", "PERSON_CPU_SCENE:" + p.id)
        for e in person_events:
            if e.world.kind == "PERSON_RETURN":
                before = snapshot.events[e.sequence - 2].state
                old = next(x for x in before.humans if x.person_id == p.id)
                new = next(x for x in e.state.humans if x.person_id == p.id)
                check(old == new, "RETURN_CONTINUOUS_FE:" + e.id)
        total_available += ah
        total_cost += ph * rates[tid]
        total_exposure += h.exposure
    check(
        all(
            math.isclose(stats[k], value, abs_tol=1e-8)
            for k, value in dict(
                total_available_h=total_available,
                total_labour_cost=total_cost,
                common_window_exposure=total_exposure,
            ).items()
        ),
        "WORKFORCE_AGGREGATES",
    )
    expected = [
        (r["request_id"], r["target_id"], r["event_id"], r["sim_h"], r.get("automatic", False))
        for r in saved["generations"]
        if r.get("workforce_kind")
    ]
    actual = [
        (r["request_id"], r["person_id"], r["event_id"], r["sim_h"], r["automatic"])
        for r in saved["workforce_results"]
    ]
    check(actual == expected, "WORKFORCE_BUSINESS_RESULT_COVERAGE")
    for result in saved["workforce_results"]:
        event = next(e for e in snapshot.events if e.id == result["event_id"])
        pid = result["person_id"]
        expected_status = next(
            (
                k
                for k in ("DEPARTED", "DEPARTURE_PENDING", "ABSENT_HOLD", "ABSENT")
                if "P043." + k + "." + pid in event.state.failed_resources
            ),
            "PRESENT",
        )
        delta = next(d for d in saved["deltas"] if d["commit_event_id"] == event.id)
        check(
            result["status"] == expected_status
            and result["catalog_version"] == delta["new_version"],
            "WORKFORCE_BUSINESS_STATUS:" + event.id,
        )
    from verify_workforce_integrity import verify_integrity

    verify_integrity(spec, saved, history, snapshot, check)
