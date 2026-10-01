"""Deterministic S05-to-S06 example translation, not an experiment generator.

Run --check to compare checked-in fixtures and schemas without writing them.
The two S05 source examples are always read-only.
"""

import argparse
import hashlib
import json
from pathlib import Path

from adaptive_hrc_scheduling.contracts.codec import decode, dumps, schema
from adaptive_hrc_scheduling.contracts.messages import (
    DispatchCommand,
    ExecutionEvent,
    HiddenScenario,
    OfflineEvaluation,
    Plan,
    PlanningInput,
    PlanningObservation,
    RunManifest,
)
from adaptive_hrc_scheduling.contracts.planning import planning_input
from adaptive_hrc_scheduling.domain.models import (
    Allocation,
    Configuration,
    DurationOverride,
    Material,
    Mode,
    Operation,
    Order,
    Phase,
    Resource,
    Route,
    TransferGroup,
    Units,
    WorkerParameters,
)
from adaptive_hrc_scheduling.domain.state import ExecutionSnapshot

ROOT = Path(__file__).resolve().parents[1]
UNITS = Units("min", "min^-1", "dimensionless", "min", "count")


def build_configuration(toy_only=False):
    old = json.loads((ROOT / "examples/structural_instance.json").read_text(encoding="utf-8"))
    toy = json.loads((ROOT / "examples/toy_instance.json").read_text(encoding="utf-8"))
    rm, sp = old["resource_model"], old["state_parameters"]
    if toy_only:
        # T0 quantities/skills/times are retained; locations use S06 aliases.
        rm["workers"] = [
            {
                "id": wid,
                "skills": ["CUT", "BRACKET", "ASSEMBLE", "INSPECT", "TRANSFER"]
                + (["WELD"] if wid == "W2" else []),
                "state_profile": f"T0_{wid}",
            }
            for wid in ("W1", "W2")
        ]
        selected = {"CS1", "PS1", "AS1", "WS1", "IS1"}
        rm["stations"] = [s for s in rm["stations"] if s["id"] in selected]
        for s in rm["stations"]:
            s["module_receiving_slots"] = 0
        rm["robots"] = [{**rm["robots"][0], "reachable_stations": ["CS1", "AS1", "WS1"]}]
        rm["equipment"] = [r for r in rm["equipment"] if r["station"] in selected]
        rm["fixtures"] = [r for r in rm["fixtures"] if r["station"] in selected]
        rm["routes"] = [
            r
            for r in rm["routes"]
            if r["source"] in selected and r["target"] in selected | {"FINISHED", "SCRAP"}
        ]
        for buffer in rm["buffers"]:
            buffer["capacity"] = 1
        old["orders"] = [
            {
                **{k: toy["orders"][0][k] for k in ("id", "release_min", "due_min", "weight")},
                "family": "F1",
            }
        ]
        old["evaluation"]["observation_window_min"] = 40
    resources = []

    def resource(
        id, kind, capacity=1, skills=(), station=None, reach=(), accepted=(), slots=0, params=None
    ):
        resources.append(
            Resource(
                id,
                kind,
                capacity,
                tuple(skills),
                station,
                tuple(reach),
                tuple(accepted),
                slots,
                params,
            )
        )

    for w in rm["workers"]:
        profile = sp["profiles"][w["state_profile"]]
        rates = sp["activity_rates_per_min"]
        params = WorkerParameters(
            profile["F0"],
            profile["recovery_per_min"],
            sp["kappa"],
            *(rates[key] for key in ("work", "collaborate", "carry", "supervise", "wait")),
        )
        resource(w["id"], "worker", skills=w["skills"], params=params)
    for r in rm["robots"]:
        resource(r["id"], "robot", skills=r["capabilities"], reach=r["reachable_stations"])
    for s in rm["stations"]:
        resource(s["id"], "station", skills=(s["kind"],), slots=s["module_receiving_slots"])
    for name, kind in (("equipment", "equipment"), ("fixtures", "fixture")):
        for item in rm[name]:
            resource(item["id"], kind, station=item["station"])
    resource(rm["crane"]["id"], "crane")
    for item in rm["shared_spaces"]:
        resource(item["id"], "space")
    for item in rm["buffers"]:
        resource(item["id"], "buffer", capacity=item["capacity"], accepted=(item["kind"],))
    for item in rm["terminals"]:
        resource(item["id"], "terminal", capacity=None)
    routes = tuple(
        Route(
            f"route.{r['source']}.{r['target']}",
            r["source"],
            r["target"],
            r["resource"],
            "crane",
            1,
            1,
            2,
            1,
            1,
        )
        for r in rm["routes"]
    )
    allocations, modes = [], []
    stations = {s["id"]: s for s in rm["stations"]}
    for template in toy["operations"]:
        kind = template["id"].split(".")[-1]
        for name, stages in template["modes"].items():
            mid = f"mode.{kind}.{name}"
            qids = []
            if kind != "LIFT":
                for station in rm["stations"]:
                    if station["kind"] != kind:
                        continue
                    for worker in rm["workers"]:
                        if kind not in worker["skills"]:
                            continue
                        robots = (
                            [
                                r
                                for r in rm["robots"]
                                if kind in r["capabilities"]
                                and station["id"] in r["reachable_stations"]
                            ]
                            if name in {"R", "HR"}
                            else [None]
                        )
                        for robot in robots:
                            rid = robot["id"] if robot else None
                            qid = f"q.{kind}.{name}.{station['id']}.{worker['id']}.{rid or 'none'}"
                            allocations.append(
                                Allocation(
                                    qid,
                                    kind,
                                    worker["id"],
                                    rid,
                                    station["equipment"],
                                    station["id"],
                                    station["fixture"],
                                    None,
                                    None,
                                )
                            )
                            qids.append(qid)
            phases = []
            prep = ("align" if kind == "ASSEMBLE" else "setup") if name in {"R", "HR"} else None
            for stage in stages:
                if stage["id"] not in {"setup", "align", "work", "handoff"} or kind == "LIFT":
                    continue
                roles = []
                if stage["worker_role"]:
                    roles.append("worker")
                for rid in stage["active_resources"]:
                    if rid == "R1":
                        roles.append("robot")
                    elif rid.startswith("M_"):
                        roles.append("equipment")
                pid = stage["id"]
                phases.append(
                    Phase(
                        pid,
                        (() if not phases else (phases[-1].id,)),
                        stage["base_min"],
                        tuple(roles),
                        stage["activity"],
                        stage["fatigue_sensitive"],
                        stage["interruption"].lower(),
                        "handoff_then_clear" if pid == "work" and kind != "INSPECT" else "clear",
                        pid == prep,
                        pid == "work" and prep is not None,
                    )
                )
            switch = "setup" if kind in {"ASSEMBLE", "WELD"} else None
            freeze = (
                "preposition"
                if kind == "LIFT"
                else "align"
                if kind == "ASSEMBLE" and name == "HR"
                else "work"
                if switch
                else phases[0].id
            )
            held = (
                ()
                if kind == "LIFT"
                else ("station",)
                + (("fixture",) if kind in {"ASSEMBLE", "WELD", "INSPECT"} else ())
                + (("equipment",) if kind in {"CUT", "WELD"} else ())
            )
            modes.append(
                Mode(mid, kind, name, tuple(phases), tuple(qids), switch, freeze, prep, held)
            )
    for route in routes:
        station = stations.get(route.target_id)
        for w in rm["workers"]:
            if "TRANSFER" in w["skills"]:
                allocations.append(
                    Allocation(
                        f"q.transfer.{route.source_id}.{route.target_id}.{w['id']}",
                        "TRANSFER",
                        w["id"],
                        None,
                        None,
                        station["id"] if station else None,
                        station["fixture"] if station else None,
                        rm["crane"]["id"],
                        route.id,
                    )
                )
    qmap, rmap = {q.id: q for q in allocations}, {r.id: r for r in routes}
    orders, operations, materials = [], [], []
    for order in old["orders"]:
        family, oid = old["families"][order["family"]], order["id"]

        def qualify(key):
            return f"{oid}.{key}"

        nodes = family["nodes"]
        producer = {n["output"]["id"]: n for n in nodes}
        consumers = {i: n["id"] for n in nodes for i in n["inputs"]}
        orders.append(
            Order(
                oid,
                order["family"],
                order["release_min"],
                order["due_min"],
                order["weight"],
                tuple(qualify(i) for i in family["required_finished_outputs"]),
            )
        )
        for n in nodes:
            nid, kind = qualify(n["id"]), n["kind"]
            output = n["output"]
            storage = (
                ("PIPE_BUFFER",)
                if output["kind"] == "pipe"
                else ("BRACKET_BUFFER",)
                if output["kind"] == "bracket"
                else ("FINISHED",)
                if output["kind"] == "finished"
                else tuple(s["id"] for s in rm["stations"] if s["kind"] == kind)
            )
            materials.append(
                Material(
                    qualify(output["id"]),
                    oid,
                    output["kind"],
                    output["quantity"],
                    nid,
                    qualify(consumers[output["id"]]) if output["id"] in consumers else None,
                    storage,
                    {"pipe": "feed", "bracket": "feed", "module": "crane", "finished": "retained"}[
                        output["kind"]
                    ],
                    "work" if kind == "INSPECT" else "unload" if kind == "LIFT" else "handoff",
                )
            )
            inputs = tuple(qualify(i) for i in n["inputs"])
            if not inputs:
                rawid = nid + ".raw"
                materials.append(
                    Material(rawid, oid, "raw", 1, None, nid, ("RAW",), "raw_at_release", "release")
                )
                inputs = (rawid,)
            transfers = []
            for iid in n["inputs"]:
                source = producer[iid]
                if source["output"]["kind"] != "module":
                    continue
                sources = {s["id"] for s in rm["stations"] if s["kind"] == source["kind"]}
                targets = (
                    {"FINISHED"}
                    if kind == "LIFT"
                    else {s["id"] for s in rm["stations"] if s["kind"] == kind}
                )
                eligible = tuple(
                    q.id
                    for q in allocations
                    if q.skill == "TRANSFER"
                    and rmap[q.route_id].source_id in sources
                    and rmap[q.route_id].target_id in targets
                )
                transfers.append(
                    TransferGroup(
                        nid + ".in." + iid,
                        qualify(iid),
                        eligible,
                        kind == "ASSEMBLE",
                        kind == "ASSEMBLE",
                    )
                )
            modeids = tuple(f"mode.{kind}.{m}" for m in n["modes"])
            overrides = []
            if n["duration_profile"] in old["duration_profiles"]["overrides"]:
                change = old["duration_profiles"]["overrides"][n["duration_profile"]]
                for mid in modeids:
                    overrides.append(DurationOverride(mid, "setup", change["setup_min"]))
                    key = mid.split(".")[-1] + "_work_min"
                    if key in change:
                        overrides.append(DurationOverride(mid, "work", change[key]))
            feed = any(producer[i]["output"]["kind"] in {"pipe", "bracket"} for i in n["inputs"])
            operations.append(
                Operation(
                    nid,
                    oid,
                    kind,
                    tuple(qualify(producer[i]["id"]) for i in n["inputs"]),
                    modeids,
                    inputs,
                    qualify(output["id"]),
                    None if kind == "LIFT" else nid + ".process",
                    tuple(transfers),
                    tuple(overrides),
                    "FEED_ROUTE" if feed else None,
                )
            )
    assert qmap  # Q is explicitly enumerated; no runtime enlargement.
    return Configuration(
        "S06-1.0",
        "configuration",
        "toy.S06" if toy_only else "structural.S06",
        UNITS,
        "PROJECT_CHOICE_SYNTHETIC_UNCALIBRATED",
        sp["cap"],
        sp["minimum_protective_rest_min"],
        old["evaluation"]["observation_window_min"],
        1,
        tuple(resources),
        routes,
        tuple(allocations),
        tuple(modes),
        tuple(orders),
        tuple(operations),
        tuple(materials),
    )


def artifacts():
    config = build_configuration()
    result = {"examples/contracts/structural.json": dumps(config)}
    small = build_configuration(toy_only=True)
    result["examples/contracts/toy.json"] = dumps(small)
    types = (
        Configuration,
        PlanningObservation,
        PlanningInput,
        Plan,
        DispatchCommand,
        ExecutionSnapshot,
        ExecutionEvent,
        HiddenScenario,
        OfflineEvaluation,
        RunManifest,
    )
    for cls in types:
        result[f"schemas/{cls.__name__}.schema.json"] = (
            json.dumps(schema(cls), indent=2, sort_keys=True) + "\n"
        )
    units = {
        "time": "min",
        "rate": "min^-1",
        "fatigue": "dimensionless",
        "exposure": "min",
        "capacity": "count",
    }
    observation = {
        "schema_version": "S06-1.0",
        "kind": "planning_observation",
        "id": "obs.0",
        "run_id": "example.run",
        "configuration_id": small.id,
        "units": units,
        "as_of_min": 0,
        "known_orders": [
            {
                "order_id": "J1",
                "released_observed_min": 0,
                "cancel_observed_min": None,
                "completion_observed_min": None,
                "actual_completion_min": None,
            }
        ],
        "estimates": [],
        "observed_event_ids": [],
    }
    hidden = {
        "schema_version": "S06-1.0",
        "kind": "hidden_scenario",
        "configuration_id": small.id,
        "units": units,
        "scenario_seed": 0,
        "events": [],
    }
    examples = [(PlanningObservation, observation), (HiddenScenario, hidden)]
    plan = {
        "schema_version": "S06-1.0",
        "kind": "plan",
        "id": "plan.0",
        "observation": observation,
        "units": units,
        "status": "incomplete",
        "assignments": [],
        "completions": [
            {"order_id": "J1", "predicted_completion_min": None, "actual_completion_min": None}
        ],
        "exposure_estimates": [],
        "budget_kind": "D0",
        "exposure_budget_min": None,
        "reason_code": "contract_example_no_scheduler",
    }
    examples.append((Plan, plan))
    examples.append(
        (
            DispatchCommand,
            {
                "schema_version": "S06-1.0",
                "kind": "dispatch",
                "id": "command.wait",
                "run_id": "example.run",
                "configuration_id": small.id,
                "observation_id": "obs.0",
                "units": units,
                "issued_min": 0,
                "action": "wait",
                "assignment": None,
                "worker_id": None,
                "duration_min": 1,
                "cleanup_material_id": None,
            },
        )
    )
    snapshot = {
        "schema_version": "S06-1.0",
        "kind": "execution_snapshot",
        "run_id": "example.run",
        "configuration_id": small.id,
        "units": units,
        "sim_time_min": 0,
        "workers": [
            {
                "worker_id": r.id,
                "fatigue": r.worker_parameters.initial_f,
                "exposure_min": 0,
                "activity": "wait",
            }
            for r in small.resources
            if r.kind == "worker"
        ],
        "preparations": [
            {
                "robot_id": r.id,
                "operation_id": None,
                "group_id": None,
                "station_id": None,
                "valid": False,
            }
            for r in small.resources
            if r.kind == "robot"
        ],
        "bindings": [],
        "phases": [],
        "locks": [],
        "reservations": [],
        "materials": [
            {"material_id": m.id, "location_id": "RAW", "status": "stored", "slot": None}
            for m in small.materials
            if m.kind == "raw"
        ],
        "resources": [
            {"resource_id": r.id, "failed": False, "release_allowed": None} for r in small.resources
        ],
        "orders": [
            {"order_id": "J1", "released": True, "cancelled": False, "actual_completion_min": None}
        ],
    }
    examples.append((ExecutionSnapshot, snapshot))
    examples.append(
        (
            ExecutionEvent,
            {
                "schema_version": "S06-1.0",
                "kind": "execution_event",
                "run_id": "example.run",
                "configuration_id": small.id,
                "event_id": "example.release",
                "units": units,
                "sim_time_min": 0,
                "event_type": "released",
                "entity_id": "J1",
                "phase_execution_id": None,
                "old_state": "unreleased",
                "new_state": "released",
                "cause": "illustrative_not_executed",
            },
        )
    )
    hidden_text = dumps(decode(HiddenScenario, hidden), config=small)

    def digest(value):
        return hashlib.sha256(value).hexdigest()

    examples.append(
        (
            RunManifest,
            {
                "schema_version": "S06-1.0",
                "kind": "run_manifest",
                "run_id": "example.run",
                "configuration_id": small.id,
                "units": units,
                "configuration_sha256": digest(dumps(small).encode("utf-8")),
                "scenario_sha256": digest(hidden_text.encode("utf-8")),
                "dependency_lock_sha256": digest((ROOT / "uv.lock").read_bytes()),
                "code_revision": "example.uncommitted",
                "scenario_seed": 0,
                "decision_seed": 0,
                "algorithm_id": "not_implemented",
                "backend": "event",
                "decision_budget_ms": 1,
                "observation_window_min": 40,
                "fatigue_cap": 0.8,
                "status": "planned",
                "solver_pauses_simulation": True,
                "termination_reason": None,
            },
        )
    )
    # Deliberate truncated shape example, not a claim that a run took place.
    examples.append(
        (
            OfflineEvaluation,
            {
                "schema_version": "S06-1.0",
                "kind": "offline_evaluation",
                "run_id": "example.not_executed",
                "configuration_id": small.id,
                "units": units,
                "observation_window_min": 40,
                "scenario": hidden,
                "evaluation_order_ids": ["J1"],
                "completions": [{"order_id": "J1", "actual_completion_min": None}],
                "workers": [
                    {"worker_id": r.id, "actual_exposure_min": 0, "actual_peak": 0}
                    for r in small.resources
                    if r.kind == "worker"
                ],
                "drained_at_min": None,
                "truncated": True,
                "budget_violated": False,
            },
        )
    )
    for cls, data in examples:
        result[f"examples/contracts/{data['kind']}.json"] = dumps(decode(cls, data), config=small)
    result["examples/contracts/planning_input.json"] = dumps(
        planning_input(small, decode(PlanningObservation, observation)), config=small
    )
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    for relative, content in artifacts().items():
        path = ROOT / relative
        if args.check:
            if not path.exists() or path.read_bytes() != content.encode("utf-8"):
                raise SystemExit(f"Contract artifact differs: {relative}")
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8", newline="\n")
    print(
        "Contract examples and schemas match."
        if args.check
        else "Contract examples and schemas written."
    )


if __name__ == "__main__":
    main()
