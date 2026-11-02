"""Question-led tables from the frozen P07 numerical results.

No production, optimization or private archives are read here. Calendar capacity,
actual activity, right-censoring and historical run identities remain distinct.
"""

import csv
import json
import math
from bisect import bisect_right
from collections import defaultdict
from pathlib import Path

from adapters import require
from load import pin, read, write


def csv_rows(source, name):
    with (source / (name + ".csv")).open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def percent(value, reference):
    return value / reference * 100


def clipped_exposure(row, start, end):
    """Integrate the recorded model, including recovery's zero crossing."""
    a, b = max(start, row["start_h"]), min(end, row["end_h"])
    if b <= a:
        return 0.0
    rate = -row["rate"] if row["phase"] in ("REST", "OFF_SHIFT") else row["rate"]
    fatigue = max(0.0, row["start_f"] + rate * (a - row["start_h"]))
    duration = b - a
    if rate < 0 and fatigue + rate * duration < 0:
        duration = max(0.0, -fatigue / rate)
    return max(0.0, fatigue * duration + 0.5 * rate * duration * duration)


def derive(source):
    summary = read(source / "summary.json")
    index = {(r["scenario"], r["method"]): r for r in summary if r["scenario"] != "MECHANISM"}
    costs = {r["unit"]: r for r in read(source / "costs.json")}
    tables = {}
    tradeoff = []
    for scenario in ("N", "H", "F", "U", "C"):
        edd, adaptive = index[scenario, "EDD"], index[scenario, "ADAPTIVE"]
        ce, ca = costs[edd["unit"]], costs[adaptive["unit"]]
        starts = ca["cached_plan_dispatches"] + ca["fallback_dispatches"]
        tradeoff.append(
            dict(
                scenario=scenario,
                received=adaptive["received_products"],
                released=adaptive["released_products"],
                cancelled=adaptive["cancelled_products"],
                delta_receipt_h=adaptive["last_received_h"] - edd["last_received_h"],
                delta_E_F_h=adaptive["common_window_sum_E"] - edd["common_window_sum_E"],
                delta_E_percent=percent(
                    adaptive["common_window_sum_E"] - edd["common_window_sum_E"],
                    edd["common_window_sum_E"],
                ),
                edd_wall_s=ce["original_runtime_elapsed_s"],
                adaptive_wall_s=ca["original_runtime_elapsed_s"],
                recorded_wall_change_percent=percent(
                    ca["original_runtime_elapsed_s"] - ce["original_runtime_elapsed_s"],
                    ce["original_runtime_elapsed_s"],
                ),
                cached_started=ca["cached_plan_dispatches"],
                all_classified_started=starts,
                cached_started_percent=percent(ca["cached_plan_dispatches"], starts),
            )
        )
    tables["method_tradeoff"] = tradeoff
    mechanism = {r["mechanism"]: r for r in read(source / "mechanisms.json")}
    contrasts = []
    for condition in ("N", "H"):
        human, hr = mechanism["M-H-" + condition], mechanism["M-HR-" + condition]
        contrasts.append(
            dict(
                initial_condition=condition,
                initial_f=0.2 if condition == "N" else 0.6,
                human_source=human["original_unit"],
                hr_source=hr["original_unit"],
                human_branch_person_h=human["branch_labour_h"],
                hr_branch_person_h=hr["branch_labour_h"],
                branch_person_h_change_percent=percent(
                    hr["branch_labour_h"] - human["branch_labour_h"], human["branch_labour_h"]
                ),
                human_branch_E=human["branch_exposure_F_h"],
                hr_branch_E=hr["branch_exposure_F_h"],
                human_all_person_E=human["common_window_sum_E"],
                hr_all_person_E=hr["common_window_sum_E"],
                all_person_E_change_percent=percent(
                    hr["common_window_sum_E"] - human["common_window_sum_E"],
                    human["common_window_sum_E"],
                ),
                human_receipt_h=human["last_received_h"],
                hr_receipt_h=hr["last_received_h"],
                receipt_change_h=hr["last_received_h"] - human["last_received_h"],
                hr_is_reused_fixed_run=True,
            )
        )
    tables["mechanism_contrasts"] = contrasts
    products = csv_rows(source, "products")
    tables["delivery_lateness"] = [
        dict(
            scenario=s,
            product_id=r["product_id"],
            order_id=r["order_id"],
            due_h=float(r["due_h"]),
            received_h=float(r["received_h"]) if r["received_h"] else None,
            tardiness_h=float(r["received_tardiness_h"]) if r["received_tardiness_h"] else None,
            cancelled=r["cancelled"] == "True",
        )
        for s in ("N", "H", "F", "U", "C")
        for r in products
        if r["unit"] == index[s, "EDD"]["unit"]
    ]
    end = read(source / "e20.json")["r14_final"]["final_sim_h"]
    response = []
    for r in csv_rows(source, "e20_orders"):

        def number(key):
            return float(r[key]) if r[key] else None

        registration, planned, started, ready, received, due = [
            number(k)
            for k in (
                "registration_applied_h",
                "first_adopted_arrangement_h",
                "first_actual_production_h",
                "ready_h",
                "received_h",
                "due_h",
            )
        ]
        response.append(
            dict(
                product_id=r["product_id"],
                order_id=r["order_id"],
                registration_h=registration,
                first_adopted_plan_h=planned,
                first_nonservice_started_h=started,
                ready_h=ready,
                received_h=received,
                due_h=due,
                wait_to_first_nonservice_started_h=started - registration
                if started is not None
                else None,
                observation_end_h=end,
                status=r["status"],
                receipt_tardiness_or_lower_bound_h=max(
                    0.0, (received if received is not None else end) - due
                ),
                tardiness_status="ACTUAL"
                if received is not None
                else ("LOWER_BOUND_RIGHT_CENSORED" if end > due else "DUE_AFTER_OBSERVATION"),
            )
        )
    tables["e20_response"] = response
    activities = csv_rows(source, "activity")
    activity_rows = []
    window_values = {}
    first_day_traces = {}
    first_day_knots = {0.0, 24.0}
    for unit in ("N-CPU-EDD", "H-CPU-EDD"):
        computed = read(source / "computed" / (unit + ".json"), limit=80_000_000)
        traces = defaultdict(list)
        for interval in computed["human_intervals"]:
            traces[interval["person_id"]].append(interval)
            if interval["start_h"] <= 24:
                first_day_knots.add(max(0.0, interval["start_h"]))
                first_day_knots.add(min(24.0, interval["end_h"]))
                if interval["phase"] in ("REST", "OFF_SHIFT") and interval["rate"]:
                    zero = interval["start_h"] + interval["start_f"] / interval["rate"]
                    if interval["start_h"] < zero < min(24.0, interval["end_h"]):
                        first_day_knots.add(zero)
        first_day_traces[unit] = {
            person: (
                sorted(rr, key=lambda row: row["start_h"]),
                sorted(row["start_h"] for row in rr),
            )
            for person, rr in traces.items()
        }
        eligible = defaultdict(float)
        early = 0.0
        total = 0.0
        for interval in computed["human_intervals"]:
            eligible[interval["phase"]] += interval["availability_h"]
            measured = clipped_exposure(interval, interval["start_h"], interval["end_h"])
            require(
                math.isclose(measured, interval["exposure"], rel_tol=1e-10, abs_tol=1e-8),
                "PRESENTATION_INTERVAL_EXPOSURE",
            )
            early += clipped_exposure(interval, 0, 24)
            total += measured
        original = computed["summary"]
        require(
            math.isclose(total, original["lifecycle_sum_E"], abs_tol=1e-7),
            "PRESENTATION_WHOLE_EXPOSURE",
        )
        window_values[unit] = dict(
            first=early, later=total - early, total=total, end=original["actual_lifecycle_end_h"]
        )
        require(
            math.isclose(sum(eligible.values()), original["available_person_h"], abs_tol=1e-7),
            "PRESENTATION_CALENDAR_DENOMINATOR",
        )
        for phase in sorted({r["phase"] for r in activities if r["unit"] == unit}):
            rr = [r for r in activities if r["unit"] == unit and r["phase"] == phase]
            duration = sum(float(r["duration_h"]) for r in rr)
            exposure = sum(float(r["exposure_F_h"]) for r in rr)
            activity_rows.append(
                dict(
                    unit=unit,
                    phase=phase,
                    actual_person_h=duration,
                    calendar_eligible_person_h=eligible[phase],
                    calendar_person_h_denominator=original["available_person_h"],
                    actual_exposure_denominator=original["lifecycle_sum_E"],
                    actual_window_end_h=original["actual_lifecycle_end_h"],
                    eligible_share_percent=percent(eligible[phase], original["available_person_h"]),
                    actual_exposure_F_h=exposure,
                    exposure_share_percent=percent(exposure, original["lifecycle_sum_E"]),
                )
            )
    tables["activity_decomposition"] = activity_rows
    n, h = window_values["N-CPU-EDD"], window_values["H-CPU-EDD"]
    total_difference = h["total"] - n["total"]
    tables["fatigue_windows"] = [
        dict(
            window=key,
            start_h=0 if key == "first" else 24,
            end_h=24 if key == "first" else n["end"],
            normal_E=n[key],
            higher_initial_E=h[key],
            delta_E=h[key] - n[key],
            delta_share_percent=percent(h[key] - n[key], total_difference),
            whole_actual_delta_E=total_difference,
        )
        for key in ("first", "later")
    ]

    def mean_fatigue(unit, time):
        values = []
        for intervals, starts in first_day_traces[unit].values():
            interval = intervals[bisect_right(starts, time) - 1]
            rate = (
                -interval["rate"]
                if interval["phase"] in ("REST", "OFF_SHIFT")
                else interval["rate"]
            )
            values.append(max(0.0, interval["start_f"] + rate * (time - interval["start_h"])))
        require(len(values) == 15, "PRESENTATION_FIXED_COHORT")
        return sum(values) / len(values)

    tables["fatigue_first_day"] = [
        dict(
            time_h=time,
            normal_mean_F=mean_fatigue("N-CPU-EDD", time),
            higher_mean_F=mean_fatigue("H-CPU-EDD", time),
        )
        for time in sorted(first_day_knots)
    ]
    for field, unit in (("normal_mean_F", "N-CPU-EDD"), ("higher_mean_F", "H-CPU-EDD")):
        curve = tables["fatigue_first_day"]
        area = (
            sum(
                (b["time_h"] - a["time_h"]) * (a[field] + b[field]) / 2
                for a, b in zip(curve, curve[1:])
            )
            * 15
        )
        require(
            math.isclose(area, window_values[unit]["first"], abs_tol=1e-7),
            "PRESENTATION_MEAN_CURVE_AREA",
        )
    group_rows = []
    for case in read(source / "dynamic_people.json", limit=40_000_000):
        groups = defaultdict(list)
        for person in case["people"]:
            groups[tuple(round(person[k], 10) for k in ("presence_h", "availability_h"))].append(
                person["person_id"]
            )
        for (presence, available), ids in sorted(
            groups.items(), key=lambda item: (-len(item[1]), sorted(item[1]))
        ):
            group_rows.append(
                dict(
                    case=case["case"],
                    observation_end_h=case["common_window_h"][1],
                    people_count=len(ids),
                    people=";".join(sorted(ids)),
                    presence_h_per_person=presence,
                    availability_h_per_person=available,
                    presence_minus_available_h=presence - available,
                )
            )
    tables["dynamic_denominators"] = group_rows
    accounts = csv_rows(source, "cancellation_accounts")
    comparable = [k for k in accounts[0] if k not in ("unit", "run_id")]
    require(
        all(accounts[0][k] == accounts[1][k] for k in comparable),
        "PRESENTATION_CANCEL_ACCOUNTS_DIFFER",
    )
    account = accounts[0]
    phases = json.loads(account["command_linked_phase_h"])
    material = csv_rows(source, "cancellation_materials")
    steel = next(r for r in material if r["unit"] == account["unit"] and r["material"] == "STEEL")
    tables["cancellation_resources"] = [
        dict(
            item="returned_steel",
            value=float(steel["returned"]),
            unit=steel["quantity_unit"],
            relation="per run; 28 returned lots",
        ),
        dict(
            item="command_linked_labour",
            value=float(account["command_linked_person_h"]),
            unit="person h",
            relation="total WORK+DRIVE+WALK",
        ),
        *[
            dict(
                item="labour_" + key,
                value=value,
                unit="person h",
                relation="component; do not add again",
            )
            for key, value in sorted(phases.items())
        ],
        dict(
            item="transport",
            value=float(account["actual_transport_m"]),
            unit="m",
            relation="per run",
        ),
        dict(
            item="empty_return",
            value=float(account["actual_empty_return_m"]),
            unit="m",
            relation="subset of transport",
        ),
        dict(
            item="walking",
            value=float(account["actual_walk_m"]),
            unit="m",
            relation="separate from transport",
        ),
    ]
    return tables


def validate_tables(actual, source):
    expected = derive(source)

    def compare(a, b, path):
        require(type(a) is type(b), "PRESENTATION_TYPE:" + path)
        if isinstance(a, dict):
            require(a.keys() == b.keys(), "PRESENTATION_FIELDS:" + path)
            for key in a:
                compare(a[key], b[key], path + "/" + key)
        elif isinstance(a, list):
            require(len(a) == len(b), "PRESENTATION_ROWS:" + path)
            for i, (x, y) in enumerate(zip(a, b)):
                compare(x, y, path + "/" + str(i))
        elif isinstance(a, float):
            require(
                math.isfinite(a) and math.isclose(a, b, rel_tol=1e-10, abs_tol=1e-8),
                "PRESENTATION_NUMBER:" + path,
            )
        else:
            require(a == b, "PRESENTATION_VALUE:" + path)

    compare(actual, expected, "")
    return dict(
        status="PASS",
        tables=len(actual),
        rows=sum(len(r) for r in actual.values()),
        source_semantics="NO_NEW_EXECUTION; FIXED_CASES_NOT_RANDOM_REPLICATES; TIMING_AND_EXPOSURE_WINDOWS_DISTINCT",
    )


def build_tables(source, output):
    output.mkdir(parents=True, exist_ok=True)
    tables = derive(source)
    result = validate_tables(tables, source)
    write(output / "tables.json", tables)
    files = [pin(output / "tables.json")]
    for name, records in tables.items():
        path = output / (name + ".csv")
        with path.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(records[0]))
            writer.writeheader()
            writer.writerows(records)
        files.append(pin(path))
    sources = [
        "summary.json",
        "costs.json",
        "mechanisms.json",
        "products.csv",
        "activity.csv",
        "e20.json",
        "e20_orders.csv",
        "dynamic_people.json",
        "cancellation_accounts.csv",
        "cancellation_materials.csv",
        "computed/N-CPU-EDD.json",
        "computed/H-CPU-EDD.json",
    ]
    result["source_data"] = [pin(source / name) for name in sources]
    result["script"] = pin(Path(__file__))
    write(output / "validation.json", result)
    write(
        output / "manifest.json",
        dict(
            format="P07-PRESENTATION-DATA-1",
            artifacts=files,
            validation=pin(output / "validation.json"),
            source_numerical_validation=pin(source / "validation.json"),
            private_original_archives_required=False,
        ),
    )
    return tables
