"""Typed cancellation material and command-linked sunk-resource accounts."""

import argparse
from collections import defaultdict
from pathlib import Path

from adapters import require
from load import P053, ROOT, csv_write, pin, read, write
from portable_metrics import transport


def compute(case, cache):
    state, definitions = case["state"], {x["id"]: x for x in case["lots"]}
    require(
        case["run_id"] == cache["run_id"] and state["time_h"] == cache["final_state"]["time_h"],
        "CANCEL_SOURCE_IDENTITY",
    )
    cancelled = [p["product_id"] for p in state["products"] if p["cancelled"]]
    accounts, lots, materials = [], [], []
    for pid in cancelled:
        records = [x for x in state["lots"] if definitions[x["id"]]["product_id"] == pid]
        grouped = defaultdict(lambda: defaultdict(float))
        for row in records:
            definition = definitions[row["id"]]
            values = {
                k: row[k] for k in ("available", "consumed", "converted", "scrapped", "returned")
            }
            require(all(v >= 0 for v in values.values()), "CANCEL_NEGATIVE_QUANTITY")
            expected = definition["quantity"] if row["arrived"] else 0
            require(abs(sum(values.values()) - expected) < 1e-7, "CANCEL_LOT_MATERIAL_BALANCE")
            lots.append(
                dict(
                    unit=cache["unit"],
                    product_id=pid,
                    lot_id=row["id"],
                    material=definition["material"],
                    quantity_unit=definition["unit"],
                    definition_quantity=definition["quantity"],
                    arrived=row["arrived"],
                    location=row["location"],
                    **values,
                )
            )
            for key, value in values.items():
                grouped[(definition["material"], definition["unit"])][key] += value
        for (material, unit), values in sorted(grouped.items()):
            materials.append(
                dict(
                    unit=cache["unit"],
                    product_id=pid,
                    material=material,
                    quantity_unit=unit,
                    **values,
                )
            )
        commands = {k: v for k, v in cache["commands"].items() if v["product_id"] == pid}
        events = []
        for e in cache["events"]:
            if (
                e["command_id"] in commands
                or e.get("readback")
                and e["readback"]["command_id"] in commands
            ):
                events.append(dict(e, command=cache["commands"].get(e["command_id"])))
        routed = transport(cache["configuration"], events)
        intervals = [x for x in cache["final_state"]["intervals"] if x["command_id"] in commands]
        phase_hours = defaultdict(float)
        for row in intervals:
            phase_hours[row["phase"]] += row["end_h"] - row["start_h"]
        installed = [x for x in state["masses"] if x["entity_id"].startswith(pid + ".")]
        holders = [x for x in state["owners"] if x["command_id"] in commands]
        reservations = [x for x in state["reservations"] if x["product_id"] == pid]
        running = [
            x for x in state["running"] if x.get("product_id") == pid or x.get("id") in commands
        ]
        marks = [
            m for m in cache["milestones"] if m["kind"] == "CANCEL" and m.get("product_id") == pid
        ]
        require(len(marks) == 1, "CANCEL_ACTUAL_EVENT_REQUIRED")
        accounts.append(
            dict(
                unit=cache["unit"],
                run_id=cache["run_id"],
                epoch=cache["epoch"],
                product_id=pid,
                cancelled_at_h=marks[0]["time_h"],
                observed_end_h=state["time_h"],
                final_product_status="CANCELLED_WITH_HISTORY",
                original_termination="WINDOW_CENSORED",
                material_lot_records=len(records),
                returned_lots=sum(x["returned"] > 0 for x in records),
                residual_available_lots=sum(x["available"] > 0 for x in records),
                installed_mass_t=sum(x["installed_t"] for x in installed),
                active_resource_holders=len(holders),
                running_commands=len(running),
                material_reservations=len(reservations),
                command_linked_person_h=sum(phase_hours.values()),
                command_linked_phase_h=dict(phase_hours),
                command_linked_exposure_F_h=sum(x["exposure"] for x in intervals),
                actual_transport_m=routed["total_m"],
                actual_empty_return_m=routed["empty_m"],
                actual_walk_m=routed["walk_m"],
                presence_labour_cost=None,
                monetary_status="UNKNOWN_NO_DECLARED_COST_POLICY_FOR_THIS_DIRECT_LOOP",
                attribution="RECORDED_COMMAND_LINKED_PERSON_INTERVALS_AND_ROUTE_CHAINS; UNASSIGNED_WAIT_REST_OFF_SHIFT_NOT_ALLOCATED",
                cleanup_time_h=None,
                cleanup_time_status="FINAL_STATE_CHECKED; LAST_COMMAND_COMPLETION_IS_NOT_A_CLEANUP_TIMESTAMP",
                observed_cleanup_status="NO_RECORDED_MATERIAL_OR_INSTALLED_RESIDUE"
                if not any(x["available"] > 0 for x in records)
                and not any(x["installed_t"] > 0 for x in installed)
                and not holders
                and not running
                and not reservations
                else "RECORDED_RESIDUE_OR_ACTIVE_HOLD_REMAINS",
            )
        )
    return dict(accounts=accounts, lots=lots, materials=materials)


def extract(destination):
    cases = []
    for method in ("EDD", "ADAPTIVE"):
        unit = f"C-STOCK-CPU-{method}-r4"
        folder = ROOT / P053 / "runs" / unit
        config = read(folder / "configuration.json")
        state = read(folder / "state.json", 16_000_000)
        cache = read(ROOT / "results/p07/cache/runs" / f"{unit}.json", 180_000_000)
        cases.append(
            dict(
                unit=unit,
                run_id=cache["run_id"],
                lots=config["lots"],
                state={
                    k: state[k]
                    for k in (
                        "time_h",
                        "products",
                        "lots",
                        "masses",
                        "positions",
                        "owners",
                        "running",
                        "reservations",
                    )
                },
                sources=[pin(folder / "configuration.json"), pin(folder / "state.json")],
                reason="Targeted existing final-state fields missing from original compact extraction; no new execution",
            )
        )
    write(destination, cases)


def build(inputs, cache_dir, data):
    combined = {k: [] for k in ("accounts", "lots", "materials")}
    for case in read(inputs):
        cp = cache_dir / f"{case['unit']}.json"
        if not cp.exists():
            cp = cp.with_suffix(".json.gz")
        result = compute(case, read(cp, 180_000_000))
        for key in combined:
            combined[key].extend(result[key])
    write(
        data / "cancellation.json",
        dict(format="P07-CANCELLATION-ACCOUNTS-r3", input=pin(inputs), **combined),
    )
    for key in combined:
        csv_write(data / f"cancellation_{key}.csv", combined[key])
    print(
        dict(
            status="CANCELLATION_ACCOUNTS_BUILT",
            accounts=len(combined["accounts"]),
            lots=len(combined["lots"]),
        )
    )


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--extract", action="store_true")
    p.add_argument("--inputs", type=Path, default=ROOT / "results/p07/r3/cancellation_inputs.json")
    p.add_argument("--cache", type=Path, default=ROOT / "results/p07/cache/runs")
    p.add_argument("--data", type=Path, default=ROOT / "results/p07/r3")
    a = p.parse_args()
    if a.extract:
        extract(a.inputs)
    build(a.inputs, a.cache, a.data)


if __name__ == "__main__":
    main()
