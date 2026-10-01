"""S06 r3 regressions for the seven reviewed contract defects."""

import copy
import json
import unittest
from pathlib import Path

from adaptive_hrc_scheduling.contracts.codec import ContractError, dumps, loads
from adaptive_hrc_scheduling.contracts.messages import Plan, PlanningObservation, RunManifest
from adaptive_hrc_scheduling.contracts.planning import planning_input
from adaptive_hrc_scheduling.domain.models import Configuration
from adaptive_hrc_scheduling.domain.state import ExecutionSnapshot

FIXTURES = Path(__file__).resolve().parents[1] / "examples/contracts"


def fixture(name):
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


def phase(op, mode, group, q, name, *, end=5):
    return dict(
        operation_id=op,
        mode_id=mode,
        group_id=group,
        allocation_id=q,
        phase_id=name,
        attempt=1,
        restore_sequence=0,
        status="completed",
        remaining_base_min=0,
        sampled_f=None,
        speed_multiplier=1,
        started_min=end - 1,
        completed_min=end,
    )


def observed(phases, bindings, time):
    return dict(
        sampled_min=time,
        received_min=time,
        phases=phases,
        bindings=bindings,
        locks=[],
        materials=[],
        reservations=[],
        preparations=[],
    )


class ContractRepairTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = loads(Configuration, json.dumps(fixture("toy")))

    def accept(self, kind, data, config=None):
        value = loads(kind, json.dumps(data), config=config or self.config)
        self.assertEqual(
            loads(kind, dumps(value, config=config or self.config), config=config or self.config),
            value,
        )
        return value

    def reject(self, kind, data, message=None):
        with self.assertRaisesRegex(ContractError, message or ".+"):
            loads(kind, json.dumps(data), config=None if kind is Configuration else self.config)

    def switch(self, kind, before, after):
        op = "J1.A1" if kind == "ASSEMBLE" else "J1.W1"
        site = "AS1" if kind == "ASSEMBLE" else "WS1"
        worker = "W1" if kind == "ASSEMBLE" else "W2"

        def q(mode):
            return f"q.{kind}.{mode}.{site}.{worker}" + (".R1" if mode != "H" else ".none")

        state = fixture("execution_snapshot")
        state["sim_time_min"] = 6.2
        state["bindings"] = [
            dict(operation_id=op, group_id=op + ".process", allocation_id=q(after))
        ]
        prefix = phase(op, f"mode.{kind}.{before}", op + ".process", q(before), "setup", end=6)
        name = "align" if kind == "ASSEMBLE" and after == "HR" else "work"
        suffix = phase(op, f"mode.{kind}.{after}", op + ".process", q(after), name, end=7)
        suffix.update(status="running", remaining_base_min=0.3, completed_min=None)
        if name == "work" and after != "R":
            suffix.update(sampled_f=0.1, speed_multiplier=1.1)
        state["phases"] = [prefix, suffix]
        if kind == "WELD":
            state["preparations"][0].update(
                operation_id=op, group_id=op + ".process", station_id=site, valid=True
            )
        return state

    def test_common_prefix_switches_preserve_actual_history(self):
        for kind, before, after in (
            ("ASSEMBLE", "H", "HR"),
            ("ASSEMBLE", "HR", "H"),
            ("WELD", "R", "HR"),
            ("WELD", "HR", "R"),
        ):
            with self.subTest(kind=kind, before=before):
                state = self.switch(kind, before, after)
                value = self.accept(ExecutionSnapshot, state)
                self.assertEqual(value.phases[0].mode_id, f"mode.{kind}.{before}")
                self.assertEqual(value.phases[0].allocation_id, state["phases"][0]["allocation_id"])

    def test_switch_rejects_worker_change_and_already_started_suffix(self):
        malformed = self.switch("ASSEMBLE", "H", "HR")
        malformed["phases"][0]["completed_min"] = None
        self.reject(ExecutionSnapshot, malformed, "completion status")
        early = self.switch("ASSEMBLE", "H", "HR")
        early["phases"][1]["started_min"] = 5.5
        self.reject(ExecutionSnapshot, early, "suffix started before")
        state = self.switch("ASSEMBLE", "H", "HR")
        state["phases"][0]["allocation_id"] = "q.ASSEMBLE.H.AS1.W2.none"
        self.reject(ExecutionSnapshot, state, "historical allocation")
        state = self.switch("ASSEMBLE", "HR", "H")
        state["phases"].append(
            phase(
                "J1.A1",
                "mode.ASSEMBLE.HR",
                "J1.A1.process",
                "q.ASSEMBLE.HR.AS1.W1.R1",
                "align",
                end=6,
            )
        )
        self.reject(ExecutionSnapshot, state)
        state = self.switch("ASSEMBLE", "H", "HR")
        state["phases"][0].update(status="paused", remaining_base_min=0.2, completed_min=None)
        self.reject(ExecutionSnapshot, state)

    def tail_plan(self, completed=False):
        plan = fixture("plan")
        time = 33 if completed else 5
        plan["observation"]["as_of_min"] = time
        known = plan["observation"]["known_orders"][0]
        if completed:
            known.update(completion_observed_min=33, actual_completion_min=33)
            plan["completions"][0]["actual_completion_min"] = 33
            prior = phase(
                "J1.L1",
                "mode.LIFT.H",
                "J1.L1.in.I1_out",
                "q.transfer.IS1.FINISHED.W1",
                "unload",
                end=33,
            )
            tail = "reset"
        else:
            known["cancel_observed_min"] = 5
            plan["completions"] = []
            prior = phase("J1.C1", "mode.CUT.R", "J1.C1.process", "q.CUT.R.CS1.W1.R1", "work")
            tail = "handoff"
        binding = {k: prior[k] for k in ("operation_id", "group_id", "allocation_id")}
        plan["observation"]["execution"] = observed([prior], [binding], time)
        assignment = {
            k: prior[k]
            for k in (
                "operation_id",
                "mode_id",
                "group_id",
                "allocation_id",
                "attempt",
                "restore_sequence",
            )
        }
        assignment.update(
            phase_id=tail,
            planned_start_min=time,
            planned_end_min=time + 1,
            reason_code="required_release",
        )
        plan["assignments"] = [assignment]
        return plan

    def test_required_tails_preserve_online_scoring_set(self):
        restarted = self.tail_plan()
        restarted["observation"]["execution"]["phases"][0]["attempt"] = 2
        self.accept(Plan, restarted)  # handoff attempt 1 follows successful work attempt 2
        restarted["observation"]["execution"]["phases"][0].update(
            status="paused", remaining_base_min=0.5, completed_min=None
        )
        self.accept(Plan, restarted)  # future handoff has its own phase attempt
        for completed in (False, True):
            with self.subTest(completed=completed):
                value = self.accept(Plan, self.tail_plan(completed))
                self.assertEqual(len(value.completions), int(completed))

    def test_required_tails_need_evidence_and_cannot_start_new_production(self):
        for completed in (False, True):
            plan = self.tail_plan(completed)
            plan["observation"]["execution"] = None
            self.reject(Plan, plan, "committed tail")
        plan = self.tail_plan()
        plan["assignments"][0]["phase_id"] = "setup"
        self.reject(Plan, plan, "committed tail")
        plan = self.tail_plan()
        plan["assignments"][0]["allocation_id"] = "q.CUT.R.CS1.W2.R1"
        self.reject(Plan, plan, "committed tail")
        plan = self.tail_plan(True)
        prior = plan["observation"]["execution"]["phases"][0]
        plan["observation"]["execution"]["phases"].append(prior | dict(phase_id="reset"))
        self.reject(Plan, plan, "committed tail")

    def test_cancelled_committed_transport_can_unload_and_reset(self):
        plan = self.tail_plan(True)
        known = plan["observation"]["known_orders"][0]
        known.update(
            completion_observed_min=None, actual_completion_min=None, cancel_observed_min=33
        )
        plan["completions"] = []
        plan["observation"]["execution"]["phases"][0]["phase_id"] = "rig"
        original = plan["assignments"][0]
        plan["assignments"] = [
            original | dict(phase_id=name, planned_start_min=33 + i, planned_end_min=34 + i)
            for i, name in enumerate(("move", "unload", "reset"))
        ]
        self.accept(Plan, plan)
        plan["assignments"][0]["phase_id"] = "preposition"
        self.reject(Plan, plan, "committed tail")

    def test_execution_observation_roundtrip_and_projection(self):
        observation = self.tail_plan()["observation"]
        observation["execution"]["locks"] = [
            dict(resource_id="CS1_M", owner_group_id="J1.C1.process", purpose="held")
        ]
        observation["execution"]["materials"] = [
            dict(material_id="J1.C1.raw", location_id="RAW", status="consumed", slot=None)
        ]
        observation["execution"]["reservations"] = [
            dict(
                material_id="J1.C1_out",
                location_id="PIPE_BUFFER",
                owner_group_id="J1.C1.process",
                slot=None,
            )
        ]
        observation["execution"]["preparations"] = [
            dict(
                robot_id="R1",
                operation_id="J1.C1",
                group_id="J1.C1.process",
                station_id="CS1",
                valid=True,
            )
        ]
        value = self.accept(PlanningObservation, observation)
        projected = planning_input(self.config, value)
        self.assertEqual(projected.observation.execution, value.execution)
        self.assertTrue(projected.visible_configuration.orders)  # cancelled cleanup stays visible

    def test_execution_observation_rejects_future_hidden_and_unobserved_data(self):
        observation = self.tail_plan()["observation"]
        for change in (dict(sampled_min=6), dict(received_min=6), dict(hidden_scenario={})):
            data = copy.deepcopy(observation)
            data["execution"].update(change)
            self.reject(PlanningObservation, data)
        data = copy.deepcopy(observation)
        data["known_orders"] = []
        self.reject(PlanningObservation, data, "unobserved execution order")
        data = copy.deepcopy(observation)
        data["execution"]["phases"][0]["completed_min"] = 6
        self.reject(PlanningObservation, data)

    def dedicated_join(self):
        data = fixture("structural")
        qs = {q["id"]: q for q in data["allocations"]}
        routes = {r["id"]: r for r in data["routes"]}
        modes = {m["id"]: m for m in data["modes"]}
        materials = {m["id"]: m for m in data["materials"]}
        for oid, station in (("J03.A1", "AS1"), ("J03.A2", "AS2"), ("J03.A3", "AS3")):
            op = next(o for o in data["operations"] if o["id"] == oid)
            remap = {}
            for mid in op["mode_ids"]:
                mode = copy.deepcopy(modes[mid])
                mode["id"] = mid + "." + oid
                mode["allocation_ids"] = [
                    q for q in mode["allocation_ids"] if qs[q]["station_id"] == station
                ]
                remap[mid] = mode["id"]
                data["modes"].append(mode)
            op["mode_ids"] = list(remap.values())
            for override in op["duration_overrides"]:
                override["mode_id"] = remap[override["mode_id"]]
            materials[op["output_id"]]["storage_ids"] = [station]
        for op in data["operations"]:
            for group in op["transfers"]:
                group["allocation_ids"] = [
                    q
                    for q in group["allocation_ids"]
                    if routes[qs[q]["route_id"]]["source_id"]
                    in materials[group["material_id"]]["storage_ids"]
                    and (op["id"] != "J03.A3" or routes[qs[q]["route_id"]]["target_id"] == "AS3")
                ]
        return data

    def test_F3_dedicated_sources_and_independent_receiver(self):
        data = self.dedicated_join()
        value = loads(Configuration, json.dumps(data))
        self.assertEqual(loads(Configuration, dumps(value)), value)

    def test_F3_rejects_two_inputs_with_same_only_source(self):
        data = self.dedicated_join()
        op = next(o for o in data["operations"] if o["id"] == "J03.A2")
        for mode in data["modes"]:
            if mode["id"] in op["mode_ids"]:
                original = next(m for m in data["modes"] if m["id"] == mode["id"].split(".J03")[0])
                qs = {q["id"]: q for q in data["allocations"]}
                mode["allocation_ids"] = [
                    qid for qid in original["allocation_ids"] if qs[qid]["station_id"] == "AS1"
                ]
        next(m for m in data["materials"] if m["id"] == op["output_id"])["storage_ids"] = ["AS1"]
        join = next(o for o in data["operations"] if o["id"] == "J03.A3")
        for group in join["transfers"]:
            group["allocation_ids"] = [q.replace("AS2", "AS1") for q in group["allocation_ids"]]
        self.reject(Configuration, data, "distinct sources")

    def test_intermediate_storage_cannot_use_terminals_or_wrong_buffer(self):
        for location in ("RAW", "FINISHED", "SCRAP", "BRACKET_BUFFER", "AS1"):
            with self.subTest(location=location):
                data = fixture("toy")
                next(m for m in data["materials"] if m["id"] == "J1.C1_out")["storage_ids"] = [
                    location
                ]
                self.reject(Configuration, data)
        data = fixture("toy")
        next(r for r in data["resources"] if r["id"] == "RAW")["accepted_materials"] = ["pipe"]
        self.reject(Configuration, data, "terminal purpose")

    def test_prefix_cost_mismatch_in_templates_and_effective_overrides(self):
        for override in (False, True):
            data = fixture("toy")
            if override:
                next(o for o in data["operations"] if o["id"] == "J1.A1")["duration_overrides"] = [
                    dict(mode_id="mode.ASSEMBLE.HR", phase_id="setup", base_min=100)
                ]
            else:
                next(m for m in data["modes"] if m["id"] == "mode.ASSEMBLE.HR")["phases"][0][
                    "base_min"
                ] = 100
            self.reject(Configuration, data, "incompatible common prefix")
        data = fixture("toy")
        next(o for o in data["operations"] if o["id"] == "J1.A1")["duration_overrides"] = [
            dict(mode_id=mid, phase_id="setup", base_min=2)
            for mid in ("mode.ASSEMBLE.H", "mode.ASSEMBLE.HR")
        ]
        loads(Configuration, json.dumps(data))

    def test_manifest_digest_matches_actual_configuration(self):
        data = fixture("run_manifest")
        self.accept(RunManifest, data)
        data["configuration_sha256"] = "0" * 64
        self.reject(RunManifest, data, "configuration digest mismatch")

    def test_old_contract_version_is_rejected_explicitly(self):
        data = fixture("planning_observation")
        data["schema_version"] = "S06-1.0"
        self.reject(PlanningObservation, data)
