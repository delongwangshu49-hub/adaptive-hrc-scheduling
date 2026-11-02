"""Independent arithmetic for compact P07 evidence; no execution or solving."""

import math
from collections import defaultdict


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def union(intervals):
    result = []
    for start, end in sorted(intervals):
        require(
            math.isfinite(start) and math.isfinite(end) and 0 <= start <= end, "INVALID_INTERVAL"
        )
        if not result or start > result[-1][1]:
            result.append([start, end])
        else:
            result[-1][1] = max(result[-1][1], end)
    return result


def hours(intervals):
    return sum(b - a for a, b in union(intervals))


def calendar_intersection(start, end, person):
    end = min(end, person["valid_until_h"])
    if end <= start:
        return []
    cal = person["calendar"]
    period = cal["period_h"]
    require(period > 0, "CALENDAR_PERIOD")
    pieces = []
    for day in range(math.floor(start / period), math.floor(end / period) + 1):
        for window in cal["windows"]:
            a = max(start, day * period + window["start_h"])
            b = min(end, day * period + window["end_h"])
            if b > a:
                pieces.append([a, b])
    return union(pieces)


def check_human_interval(row, tolerance=1e-8):
    dt, f, rate = row["end_h"] - row["start_h"], row["start_f"], row["rate"]
    require(dt >= 0 and f >= 0 and rate >= 0, "HUMAN_INTERVAL_DOMAIN")
    if row["phase"] in ("REST", "OFF_SHIFT"):
        active = min(dt, f / rate) if rate else dt
        final = max(0, f - dt * rate)
        active_final = max(0, f - active * rate)
        exposure = active * (f + active_final) / 2
    else:
        final = f + dt * rate
        exposure = dt * (f + final) / 2
    require(
        math.isclose(final, row["end_f"], rel_tol=1e-8, abs_tol=tolerance), "HUMAN_INTERVAL_FATIGUE"
    )
    require(
        math.isclose(exposure, row["exposure"], rel_tol=1e-8, abs_tol=tolerance),
        "HUMAN_INTERVAL_EXPOSURE",
    )


def fatigue_polyline(intervals):
    """Exact piecewise-linear F(t), including the recovery clamp at zero."""
    times, values = [], []
    for row in intervals:
        check_human_interval(row)
        start, end, f, rate = (row[k] for k in ("start_h", "end_h", "start_f", "rate"))
        if not times:
            times.append(start)
            values.append(f)
        else:
            require(
                math.isclose(times[-1], start, abs_tol=1e-7)
                and math.isclose(values[-1], f, abs_tol=1e-7),
                "PLOT_HISTORY_GAP_OR_RESET",
            )
        if row["phase"] in ("REST", "OFF_SHIFT") and rate > 0 and 0 < f / rate < end - start:
            times.append(start + f / rate)
            values.append(0.0)
        times.append(end)
        values.append(row["end_f"])
    area = math.fsum(
        (b - a) * (x + y) / 2 for a, b, x, y in zip(times, times[1:], values, values[1:])
    )
    require(
        math.isclose(area, math.fsum(r["exposure"] for r in intervals), rel_tol=1e-8, abs_tol=1e-7),
        "PLOT_AREA_MUST_MATCH_RECORDED_EXPOSURE",
    )
    return times, values


def people_metrics(config, state, changes=(), generations=(), rates=None):
    persons = {p["id"]: p for p in config["people"]}
    humans = {h["person_id"]: h for h in state["humans"]}
    require(set(persons) == set(humans), "ALL_HISTORICAL_PEOPLE_REQUIRED")
    arrivals = {
        g["target_id"]: g for g in generations if g.get("workforce_kind") == "PERSON_ARRIVE"
    }
    by_person, by_change = defaultdict(list), defaultdict(list)
    for row in state["intervals"]:
        require(row["person_id"] in persons, "UNKNOWN_INTERVAL_PERSON")
        check_human_interval(row)
        by_person[row["person_id"]].append(row)
    for row in changes:
        by_change[row["person_id"]].append(row)
    output, phases, intervals = [], [], []
    for pid, p in persons.items():
        h = humans[pid]
        defined = arrivals[pid]["sim_h"] if pid in arrivals else 0
        rows = sorted(by_person[pid], key=lambda r: (r["start_h"], r["end_h"]))
        cursor, fatigue = defined, p["initial_f"]
        presence, availability, activity = [], [], defaultdict(lambda: [0.0, 0.0])
        for row in rows:
            require(
                math.isclose(row["start_h"], cursor, abs_tol=1e-7), "PERSON_HISTORY_GAP_OR_OVERLAP"
            )
            require(
                math.isclose(row["start_f"], fatigue, abs_tol=1e-7), "PERSON_FATIGUE_DISCONTINUITY"
            )
            cursor, fatigue = row["end_h"], row["end_f"]
            status = next(
                (x["status"] for x in reversed(by_change[pid]) if x["time_h"] <= row["start_h"]),
                "PRESENT",
            )
            present = status not in ("ABSENT", "DEPARTED")
            if present:
                presence.append([row["start_h"], row["end_h"]])
            allowed = (
                calendar_intersection(row["start_h"], row["end_h"], p)
                if status == "PRESENT"
                else []
            )
            availability.extend(allowed)
            activity[row["phase"]][0] += row["end_h"] - row["start_h"]
            activity[row["phase"]][1] += row["exposure"]
            intervals.append(dict(row, presence=present, availability_h=hours(allowed)))
        require(math.isclose(cursor, state["time_h"], abs_tol=1e-7), "PERSON_FINAL_WINDOW_GAP")
        exposure = sum(r["exposure"] for r in rows)
        require(
            math.isclose(exposure, h["exposure"], rel_tol=1e-8, abs_tol=1e-7),
            "PERSON_EXPOSURE_TOTAL",
        )
        require(math.isclose(fatigue, h["fatigue"], abs_tol=1e-7), "PERSON_FINAL_FATIGUE")
        peak = max([p["initial_f"]] + [max(r["start_f"], r["end_f"]) for r in rows])
        require(math.isclose(peak, h["peak"], abs_tol=1e-7), "PERSON_PEAK_HISTORY")
        tid = arrivals[pid]["payload"]["parameter_template_id"] if pid in arrivals else pid
        rate = rates.get(tid) if rates else None
        if rates is not None:
            require(rate is not None, "LABOUR_RATE_REQUIRED")
        output.append(
            dict(
                person_id=pid,
                defined_from_h=defined,
                before_arrival="NOT_IN_CATALOG",
                lifecycle_end_h=state["time_h"],
                fatigue=h["fatigue"],
                peak_f=h["peak"],
                exposure_F_h=h["exposure"],
                presence_h=hours(presence),
                availability_h=hours(availability),
                presence_exposure_F_h=sum(
                    r["exposure"] for r in intervals if r["person_id"] == pid and r["presence"]
                ),
                rate_per_h=rate,
                presence_labour_cost=rate * hours(presence) if rate is not None else None,
                rate_status="RECORDED_MODEL_RATE"
                if rate is not None
                else "UNKNOWN_NOT_DECLARED_IN_FIXED_CONFIGURATION",
            )
        )
        phases.extend(
            dict(person_id=pid, phase=k, duration_h=v[0], exposure_F_h=v[1])
            for k, v in sorted(activity.items())
        )
    return output, phases, intervals


def product_metrics(products, outcomes, window_h):
    require(window_h >= 0, "ORDER_WINDOW")
    states = {p["product_id"]: p for p in outcomes}
    require(set(states) == {p["id"] for p in products}, "PRODUCT_CATALOG_COVERAGE")
    rows = []
    for p in products:
        s = states[p["id"]]
        released = bool(s["released"])
        cancel = bool(s["cancelled"])
        ready, received, due = s["ready_h"], s["received_h"], p["due_h"]
        require(
            all(t is None or 0 <= t <= window_h + 1e-8 for t in (ready, received)),
            "PRODUCT_FUTURE_RESULT",
        )
        rows.append(
            dict(
                product_id=p["id"],
                order_id=p["order_id"],
                due_h=due,
                release_h=p["release_h"],
                released=released,
                cancelled=cancel,
                ready_h=ready,
                received_h=received,
                ready_tardiness_h=max(0, ready - due) if ready is not None and not cancel else None,
                received_tardiness_h=max(0, received - due)
                if received is not None and not cancel
                else None,
                ready_delay_lower_bound_h=max(0, (ready if ready is not None else window_h) - due)
                if not cancel
                else None,
                received_delay_lower_bound_h=max(
                    0, (received if received is not None else window_h) - due
                )
                if not cancel
                else None,
                incomplete=released and not cancel and received is None,
                on_time_ready=not cancel and ready is not None and ready <= due,
                on_time_received=not cancel and received is not None and received <= due,
                status="CANCELLED_WITH_HISTORY"
                if cancel
                else "RECEIVED"
                if received is not None
                else "RIGHT_CENSORED",
            )
        )
    return rows


def pair_values(rows, metric):
    index = {}
    for r in rows:
        key = (r["scenario"], r["method"])
        require(key not in index, "DUPLICATE_PAIR_SIDE")
        index[key] = r
    result = []
    for scenario in sorted({r["scenario"] for r in rows}):
        a, b = index.get((scenario, "ADAPTIVE")), index.get((scenario, "EDD"))
        require(a is not None and b is not None, "PAIR_SIDE_REQUIRED")
        require(
            a["source_family"] == b["source_family"]
            and a["evaluation_window_h"] == b["evaluation_window_h"]
            and a["input_configuration_sha256"] == b["input_configuration_sha256"],
            "PAIR_SCOPE_MISMATCH",
        )
        av, bv = a.get(metric), b.get(metric)
        result.append(
            dict(
                scenario=scenario,
                metric=metric,
                adaptive=av,
                edd=bv,
                delta_adaptive_minus_edd=av - bv if av is not None and bv is not None else None,
                status="EVALUABLE"
                if av is not None and bv is not None
                else "UNKNOWN_METRIC_SOURCE",
            )
        )
    return result
