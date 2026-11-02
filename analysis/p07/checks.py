"""Independent P07 arithmetic and cross-artifact consistency checks."""

import math
from collections import defaultdict

from adapters import fatigue_polyline, require


def equal(actual, expected, path="result"):
    if isinstance(expected, bool) or expected is None or isinstance(expected, str):
        require(actual == expected and type(actual) is type(expected), "VALUE:" + path)
    elif isinstance(expected, (int, float)):
        require(
            isinstance(actual, (int, float))
            and not isinstance(actual, bool)
            and math.isfinite(actual)
            and math.isclose(actual, expected, rel_tol=1e-9, abs_tol=1e-7),
            "NUMBER:" + path,
        )
    elif isinstance(expected, list):
        require(isinstance(actual, list) and len(actual) == len(expected), "LIST:" + path)
        for i, (a, b) in enumerate(zip(actual, expected)):
            equal(a, b, f"{path}[{i}]")
    elif isinstance(expected, dict):
        require(isinstance(actual, dict) and set(actual) == set(expected), "KEYS:" + path)
        for k, v in expected.items():
            equal(actual[k], v, path + "." + k)
    else:
        raise ValueError("UNSUPPORTED_EXPECTED_TYPE:" + path)


def people_oracle(config, state, changes=(), generations=(), rates=None):
    """Closed-form interval integrals and independent calendar/status sweep."""
    groups = defaultdict(list)
    for row in state["intervals"]:
        groups[row["person_id"]].append(row)
    humans = {h["person_id"]: h for h in state["humans"]}
    require(
        len(humans) == len(state["humans"]) and set(humans) == {p["id"] for p in config["people"]},
        "ORACLE_HISTORICAL_ID_SET",
    )
    arrivals = {
        g["target_id"]: g for g in generations if g.get("workforce_kind") == "PERSON_ARRIVE"
    }
    answer = {}
    for p in config["people"]:
        pid = p["id"]
        birth = arrivals[pid]["sim_h"] if pid in arrivals else 0
        t = birth
        f = p["initial_f"]
        total = 0.0
        peak = f
        for row in groups[pid]:
            equal(row["start_h"], t, "oracle.time")
            equal(row["start_f"], f, "oracle.start_F")
            dt = row["end_h"] - t
            k = row["rate"]
            require(dt >= 0 and k >= 0, "ORACLE_INTERVAL_DOMAIN")
            rest = row["phase"] in ("REST", "OFF_SHIFT")
            if rest and k and dt > f / k:
                area = f * f / (2 * k)
                end_f = 0
            else:
                slope = -k if rest else k
                area = f * dt + slope * dt * dt / 2
                end_f = f + slope * dt
            equal(row["exposure"], area, "oracle.interval_E")
            equal(row["end_f"], end_f, "oracle.end_F")
            total += area
            f = end_f
            peak = max(peak, f)
            t = row["end_h"]
        equal(t, state["time_h"], "oracle.end_time")
        for key, value in [("fatigue", f), ("exposure", total), ("peak", peak)]:
            equal(humans[pid][key], value, "oracle.human." + key)
        # The plotting function has a separate geometry-area assertion. Its
        # zero breakpoints are checked against these closed-form integrals.
        tx, fy = fatigue_polyline(groups[pid])
        equal(
            sum((b - a) * (x + y) / 2 for a, b, x, y in zip(tx, tx[1:], fy, fy[1:])),
            total,
            "oracle.polyline_E",
        )
        history = sorted(
            [x for x in changes if x["person_id"] == pid],
            key=lambda x: (x["time_h"], x.get("event_sequence", 0)),
        )
        T = state["time_h"]
        period = p["calendar"]["period_h"]
        require(period > 0, "ORACLE_CALENDAR_PERIOD")
        points = {birth, T, p["valid_until_h"]}
        points.update(x["time_h"] for x in history)
        for day in range(math.floor(birth / period), math.ceil(T / period) + 1):
            for w in p["calendar"]["windows"]:
                points.update([day * period + w["start_h"], day * period + w["end_h"]])
        points = sorted(x for x in points if birth <= x <= T)
        presence = availability = 0.0
        for a, b in zip(points, points[1:]):
            mid = (a + b) / 2
            status = "PRESENT"
            for change in history:
                if change["time_h"] <= mid:
                    status = change["status"]
            if status not in ("ABSENT", "DEPARTED"):
                presence += b - a
            if (
                status == "PRESENT"
                and mid < p["valid_until_h"]
                and any(w["start_h"] <= mid % period < w["end_h"] for w in p["calendar"]["windows"])
            ):
                availability += b - a
        tid = arrivals[pid]["payload"]["parameter_template_id"] if pid in arrivals else pid
        rate = rates[tid] if rates is not None else None
        answer[pid] = dict(
            exposure_F_h=total,
            fatigue=f,
            peak_f=peak,
            presence_h=presence,
            availability_h=availability,
            presence_labour_cost=presence * rate if rate is not None else None,
        )
    return answer


def fixed_oracle(cache, computed, policy):
    rates = (
        {r["template_id"]: r["rate_per_h"] for r in policy["cost"]["rates"]}
        if policy.get("cost")
        else None
    )
    people = people_oracle(cache["configuration"], cache["final_state"], rates=rates)
    actual = {p["person_id"]: p for p in computed["people"]}
    require(set(actual) == set(people), "FIXED_RESULT_HISTORICAL_PEOPLE")
    for pid, expected in people.items():
        for key, value in expected.items():
            equal(actual[pid][key], value, f"{cache['unit']}.{pid}.{key}")
    s = computed["summary"]
    for key, value in [
        ("lifecycle_sum_E", sum(p["exposure_F_h"] for p in people.values())),
        ("lifecycle_max_E", max(p["exposure_F_h"] for p in people.values())),
        ("available_person_h", sum(p["availability_h"] for p in people.values())),
        ("presence_person_h", sum(p["presence_h"] for p in people.values())),
    ]:
        equal(s[key], value, "summary." + key)
    common = {h["person_id"]: h for h in cache["analysis"]["common_horizon"]["humans"]}
    tail = max(0, 720 - cache["final_state"]["time_h"])
    for p in cache["configuration"]["people"]:
        h = people[p["id"]]
        k = p["recovery_rate"]
        duration = min(tail, h["fatigue"] / k) if k else tail
        expected = h["exposure_F_h"] + h["fatigue"] * duration - k * duration * duration / 2
        equal(common[p["id"]]["exposure"], expected, "common_tail.E")
        equal(actual[p["id"]]["common_exposure_F_h"], expected, "computed_common.E")
    equal(
        s["common_window_sum_E"],
        sum(h["exposure"] for h in common.values()),
        "summary.common_sum_E",
    )
    equal(
        s["common_window_max_E"],
        max(h["exposure"] for h in common.values()),
        "summary.common_max_E",
    )
    return dict(
        people=len(people),
        human_intervals=len(cache["final_state"]["intervals"]),
        independent_integrals=True,
        independent_denominator_sweep=True,
        polyline_area=True,
    )


def dynamic_oracle(cases):
    require(len(cases) == 2, "DYNAMIC_CASES")
    count = 0
    for c in cases:
        d = c["reproduction_input"]
        oracle = people_oracle(
            d["configuration"], d["state"], d["changes"], d["generations"], d["rates"]
        )
        actual = {p["person_id"]: p for p in c["people"]}
        require(len(actual) == len(c["people"]) == len(oracle) == 16, "DYNAMIC_ALL_PEOPLE")
        for pid, expected in oracle.items():
            for key, value in expected.items():
                equal(actual[pid][key], value, "dynamic." + pid + "." + key)
        equal(
            c["actual_available_person_h"],
            sum(p["availability_h"] for p in oracle.values()),
            "dynamic.total_available",
        )
        equal(
            c["presence_labour_cost"],
            sum(p["presence_labour_cost"] for p in oracle.values()),
            "dynamic.total_cost",
        )
        equal(
            c["total_exposure_F_h"],
            sum(p["exposure_F_h"] for p in oracle.values()),
            "dynamic.total_E",
        )
        equal(
            c["max_exposure_F_h"], max(p["exposure_F_h"] for p in oracle.values()), "dynamic.max_E"
        )
        equal(c["common_window_h"], [0, d["state"]["time_h"]], "dynamic.window")
        require(
            c["common_720h_status"] == "UNKNOWN_INCOMPLETE_LOCAL_CHECKPOINT_NO_TAIL",
            "DYNAMIC_NO_INVENTED_TAIL",
        )
        mapping = {
            "presence_h": "presence_h",
            "availability_h": "available_h",
            "fatigue": "fatigue",
            "exposure_F_h": "exposure",
            "peak_f": "peak",
            "presence_exposure_F_h": "presence_exposure",
            "presence_labour_cost": "labour_cost",
        }
        require(len(c["checks"]) == 112 and bool(c["return_checks"]), "DYNAMIC_CHECK_COVERAGE")
        for row in c["checks"]:
            equal(row["actual"], actual[row["person_id"]][row["metric"]], "dynamic.check_actual")
            equal(
                row["saved"],
                d["saved_statistics"]["people"][row["person_id"]][mapping[row["metric"]]],
                "dynamic.check_saved",
            )
            equal(row["actual"], row["saved"], "dynamic.saved_value")
        for row in c["return_checks"]:
            equal(row["previous"], row["returned"], "dynamic.return_continuity")
        count += len(c["checks"])
    return count


def e20_oracle(actual, reference):
    equal(actual, reference, "E20_SOURCE_BOUND_REFERENCE")
    require(len(actual["products"]) == 4 and len(actual["plan_changes"]) == 5, "E20_COVERAGE")
    T = 387.7324633333333
    for p in actual["products"]:
        for key in (
            "ready_h",
            "received_h",
            "accepted_sim_h",
            "registration_applied_h",
            "actual_arrival_h",
            "first_observed_decision_h",
            "first_adopted_arrangement_h",
            "first_actual_production_h",
        ):
            t = p[key]
            require(t is None or 0 <= t <= T + 1e-7, "E20_TIME_DOMAIN:" + key)
        if p["initial_or_new"] == "DYNAMIC_NEW":
            require(
                p["accepted_sim_h"]
                <= p["registration_applied_h"]
                <= p["first_actual_production_h"],
                "E20_CAUSAL_ORDER",
            )
    require(
        sum(p["received_h"] is not None for p in actual["products"]) == 1,
        "E20_ORIGINAL_ONE_RECEIVED",
    )
