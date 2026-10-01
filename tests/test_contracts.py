"""S06 adversarial contract checks, not simulator or scheduler experiments."""

import copy
import importlib.util
import json
import unittest
from dataclasses import FrozenInstanceError, replace
from pathlib import Path

from adaptive_hrc_scheduling.contracts.codec import ContractError, as_data, dumps, loads, schema
from adaptive_hrc_scheduling.contracts.messages import (
    DispatchCommand,
    ExecutionEvent,
    HiddenScenario,
    OfflineEvaluation,
    Plan,
    PlanningInput,
    PlanningObservation,
    RunManifest,
    phase_execution_id,
)
from adaptive_hrc_scheduling.contracts.planning import planning_input
from adaptive_hrc_scheduling.contracts.validation import validate
from adaptive_hrc_scheduling.domain.models import Configuration
from adaptive_hrc_scheduling.domain.phases import resolve_process_phase
from adaptive_hrc_scheduling.domain.state import ExecutionSnapshot

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "examples/contracts"


class ContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw = json.loads((FIXTURES / "toy.json").read_text(encoding="utf-8"))
        cls.config = loads(Configuration, json.dumps(cls.raw))
        cls.large = loads(Configuration, (FIXTURES / "structural.json").read_text(encoding="utf-8"))

    def fixture(self, name):
        return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))

    def reject_config(self, mutation):
        data = copy.deepcopy(self.raw)
        mutation(data)
        with self.assertRaises(ContractError):
            loads(Configuration, json.dumps(data))

    def reject(self, cls, data):
        with self.assertRaises(ContractError):
            loads(cls, json.dumps(data), config=self.config)

    def assignment(self, phase="setup", mode="R"):
        q = next(q for q in self.raw["allocations"] if q["id"].startswith(f"q.CUT.{mode}"))
        return dict(
            operation_id="J1.C1",
            mode_id=f"mode.CUT.{mode}",
            group_id="J1.C1.process",
            phase_id=phase,
            allocation_id=q["id"],
            attempt=1,
            restore_sequence=1 if phase == "restore" else 0,
            planned_start_min=0,
            planned_end_min=1,
            reason_code="contract_test",
        )

    def running(self, phase="work"):
        data = self.fixture("execution_snapshot")
        a = self.assignment(phase)
        data["sim_time_min"] = 2
        data["bindings"] = [{k: a[k] for k in ("operation_id", "group_id", "allocation_id")}]
        data["preparations"][0].update(
            operation_id="J1.C1", group_id="J1.C1.process", station_id="CS1", valid=phase == "work"
        )
        data["phases"] = [
            {
                k: a[k]
                for k in (
                    "operation_id",
                    "mode_id",
                    "group_id",
                    "phase_id",
                    "attempt",
                    "restore_sequence",
                )
            }
            | dict(
                status="running",
                remaining_base_min=1,
                sampled_f=None,
                speed_multiplier=1,
                started_min=1,
                completed_min=None,
            )
        ]
        return data

    def test_roundtrip_all_documents_and_structural_scale(self):
        for config in (self.config, self.large):
            self.assertEqual(loads(Configuration, dumps(config)), config)
            self.assertEqual(dumps(loads(Configuration, dumps(config))), dumps(config))
        for cls, name in (
            (PlanningObservation, "planning_observation"),
            (PlanningInput, "planning_input"),
            (Plan, "plan"),
            (DispatchCommand, "dispatch"),
            (ExecutionSnapshot, "execution_snapshot"),
            (ExecutionEvent, "execution_event"),
            (HiddenScenario, "hidden_scenario"),
            (OfflineEvaluation, "offline_evaluation"),
            (RunManifest, "run_manifest"),
        ):
            with self.subTest(name=name):
                value = loads(cls, json.dumps(self.fixture(name)), config=self.config)
                self.assertEqual(
                    loads(cls, dumps(value, config=self.config), config=self.config), value
                )
        self.assertEqual(
            (
                len(self.large.orders),
                len(self.large.operations),
                sum(len(o.mode_ids) > 1 for o in self.large.operations),
            ),
            (12, 96, 52),
        )
        self.assertEqual(
            (
                sum(r.kind == "worker" for r in self.large.resources),
                sum(r.kind == "robot" for r in self.large.resources),
            ),
            (6, 3),
        )

    def test_toy_semantics_and_f3_transport(self):
        self.assertEqual((len(self.config.orders), len(self.config.operations)), (1, 6))
        self.assertEqual(
            [(o.release_min, o.due_min, o.weight) for o in self.config.orders], [(0, 32, 2)]
        )
        self.assertEqual(self.config.observation_window_min, 40)
        self.assertEqual({r.id for r in self.config.resources if r.kind == "worker"}, {"W1", "W2"})
        self.assertEqual(sum(r.kind == "robot" for r in self.config.resources), 1)
        joins = [o for o in self.large.operations if o.kind == "ASSEMBLE" and o.transfers]
        self.assertEqual(len(joins), 4)
        self.assertTrue(
            all(
                len(o.transfers) == 2
                and all(t.wait_for_reset and t.reserve_all_receiving_slots for t in o.transfers)
                for o in joins
            )
        )

    def test_unknown_missing_and_duplicate_json_members(self):
        self.reject_config(lambda d: d.update(hidden_future=[]))
        self.reject_config(lambda d: d.pop("units"))
        with self.assertRaises(ContractError):
            loads(Configuration, '{"kind":"configuration","kind":"configuration"}')

    def test_wrong_units_and_version(self):
        for key, value in (
            ("time", "s"),
            ("rate", "s^-1"),
            ("fatigue", "percent"),
            ("exposure", "s"),
            ("capacity", "kg"),
        ):
            with self.subTest(unit=key):
                self.reject_config(lambda d: d["units"].update({key: value}))
        self.reject_config(lambda d: d.update(schema_version="S05-0.4"))

    def test_strict_numbers_no_coercion(self):
        for value in (True, "1", -1, float("nan"), float("inf"), 10**1000):
            with self.subTest(value=str(value)[:20]):
                self.reject_config(lambda d: d.update(protective_rest_min=value))
        self.reject_config(lambda d: d["resources"][0].update(capacity=1.0))
        self.reject_config(lambda d: d["materials"][0].update(quantity=False))

    def test_ids_unique_and_stable(self):
        self.reject_config(lambda d: d["orders"][0].update(id="bad id"))
        self.reject_config(lambda d: d["resources"].append(d["resources"][0]))
        self.reject_config(lambda d: d["operations"][0].update(id=d["orders"][0]["id"]))
        a = phase_execution_id("J1.C1", "J1.C1.process", "work", 1)
        self.assertEqual(a, phase_execution_id("J1.C1", "J1.C1.process", "work", 1))
        self.assertNotEqual(a, phase_execution_id("J1.C1", "J1.C1.process", "work", 2))
        self.assertNotEqual(
            phase_execution_id("a:b", "c", "restore", 1, 1),
            phase_execution_id("a", "b:c", "restore", 1, 1),
        )
        self.assertNotEqual(
            phase_execution_id("a", "b", "restore", 1, 1),
            phase_execution_id("a", "b", "restore", 1, 2),
        )

    def test_invalid_references(self):
        mutations = [
            lambda d: d["operations"][0].update(order_id="missing"),
            lambda d: d["operations"][0].update(mode_ids=["missing"]),
            lambda d: d["materials"][0].update(producer_id="missing"),
            lambda d: d["modes"][0].update(allocation_ids=["missing"]),
            lambda d: d["allocations"][0].update(worker_id="missing"),
        ]
        for mutation in mutations:
            with self.subTest(mutation=mutations.index(mutation)):
                self.reject_config(mutation)

    def test_operation_and_phase_cycles(self):
        self.reject_config(
            lambda d: d["operations"][0].update(predecessors=[d["operations"][0]["id"]])
        )
        self.reject_config(lambda d: d["modes"][0]["phases"][0].update(predecessors=["work"]))

    def test_unqualified_worker_and_unreachable_robot(self):
        self.reject_config(lambda d: d["resources"][0].update(skills=[]))
        self.reject_config(
            lambda d: next(r for r in d["resources"] if r["kind"] == "robot").update(
                reachable_station_ids=[]
            )
        )
        self.reject_config(
            lambda d: next(q for q in d["allocations"] if q["skill"] == "WELD").update(
                worker_id="W1"
            )
        )

    def test_equipment_fixture_binding_and_resource_capacity(self):
        self.reject_config(
            lambda d: next(r for r in d["resources"] if r["kind"] == "fixture").update(
                station_id="CS1"
            )
        )
        self.reject_config(lambda d: d["resources"][0].update(capacity=2))
        self.reject_config(
            lambda d: next(r for r in d["resources"] if r["kind"] == "buffer").update(capacity=None)
        )
        self.reject_config(
            lambda d: next(q for q in d["allocations"] if q["skill"] == "WELD").update(
                equipment_id=None
            )
        )

    def test_mode_roles_cost_activity_and_cancellation(self):
        self.reject_config(lambda d: d["modes"][0].update(name="HR"))
        self.reject_config(lambda d: d["modes"][0]["phases"][0].update(base_min=0))
        self.reject_config(
            lambda d: next(m for m in d["modes"] if m["name"] == "HR")["phases"][-2].update(
                active_roles=["worker"]
            )
        )
        self.reject_config(lambda d: d["modes"][0]["phases"][1].update(cancel_boundary="clear"))
        self.reject_config(lambda d: d["modes"][0]["phases"][0].update(activity="rest"))
        self.reject_config(lambda d: d["modes"][0].update(held_roles=[]))

    def test_material_double_consumption_and_bad_release(self):
        self.reject_config(
            lambda d: d["operations"][1].update(input_ids=d["operations"][0]["input_ids"])
        )
        self.reject_config(lambda d: d["materials"][0].update(available_at="release"))
        self.reject_config(lambda d: d["materials"][0].update(movement="retained"))
        self.reject_config(
            lambda d: next(m for m in d["materials"] if m["kind"] == "pipe").update(
                storage_ids=["BRACKET_BUFFER"]
            )
        )

    def test_join_capacity_and_transport_cannot_be_omitted(self):
        data = as_data(self.large)
        next(r for r in data["resources"] if r["id"] == "AS1")["receiving_slots"] = 1
        with self.assertRaises(ContractError):
            loads(Configuration, json.dumps(data))
        self.reject_config(
            lambda d: next(o for o in d["operations"] if o["transfers"]).update(transfers=[])
        )
        data = as_data(self.large)
        next(o for o in data["operations"] if o["kind"] == "ASSEMBLE" and o["transfers"])[
            "transfers"
        ][0]["wait_for_reset"] = False
        with self.assertRaises(ContractError):
            loads(Configuration, json.dumps(data))

    def test_objects_immutable_and_dump_revalidates(self):
        with self.assertRaises(FrozenInstanceError):
            self.config.fatigue_cap = 0.5
        with self.assertRaises(ContractError):
            dumps(replace(self.config, protective_rest_min=-1))
        with self.assertRaises(ContractError):
            validate(replace(self.config, fatigue_cap=True))

    def test_future_observations_and_hidden_fields_rejected(self):
        for key in ("events", "true_fatigue", "evaluation_order_ids", "future_orders"):
            data = self.fixture("planning_observation")
            data[key] = []
            self.reject(PlanningObservation, data)
        data = self.fixture("planning_observation")
        data["known_orders"][0]["cancel_observed_min"] = 1
        self.reject(PlanningObservation, data)

    def test_planning_projection_excludes_unobserved_order_data(self):
        raw = self.fixture("planning_observation")
        raw["configuration_id"] = self.large.id
        raw["known_orders"][0]["order_id"] = "J01"
        observation = loads(PlanningObservation, json.dumps(raw), config=self.large)
        projected = planning_input(self.large, observation)
        self.assertEqual([o.id for o in projected.visible_configuration.orders], ["J01"])
        self.assertEqual(len(projected.visible_configuration.operations), 6)
        changed_future = replace(
            self.large,
            orders=tuple(
                replace(o, due_min=o.due_min + 100) if o.id != "J01" else o
                for o in self.large.orders
            ),
        )
        self.assertEqual(planning_input(changed_future, observation), projected)
        leaked = replace(projected, visible_configuration=self.large)
        with self.assertRaises(ContractError):
            dumps(leaked, config=self.large)
        empty = replace(observation, known_orders=())
        self.assertFalse(planning_input(self.large, empty).visible_configuration.orders)
        data = self.fixture("planning_observation")
        data["estimates"] = [
            dict(
                resource_id="W1",
                sampled_min=1,
                received_min=0,
                fatigue_estimate=0.1,
                exposure_estimate_min=0,
                available_estimate=True,
            )
        ]
        self.reject(PlanningObservation, data)

    def test_online_K_t_cannot_drop_order_or_invent_completion(self):
        data = self.fixture("plan")
        data["completions"] = []
        self.reject(Plan, data)
        data = self.fixture("plan")
        data["completions"][0]["actual_completion_min"] = 0
        self.reject(Plan, data)
        data = self.fixture("plan")
        data["status"] = "candidate"
        self.reject(Plan, data)

    def test_completed_online_order_uses_actual_C(self):
        data = self.fixture("plan")
        data["observation"]["as_of_min"] = 35
        data["observation"]["known_orders"][0].update(
            completion_observed_min=34, actual_completion_min=33
        )
        data["completions"][0]["actual_completion_min"] = 33
        value = loads(Plan, json.dumps(data), config=self.config)
        self.assertEqual(value.completions[0].actual_completion_min, 33)
        data["completions"][0]["predicted_completion_min"] = 36
        self.reject(Plan, data)

    def test_group_worker_identity_cannot_change_between_phases(self):
        data = self.fixture("plan")
        a, b = self.assignment(), self.assignment("work")
        b.update(
            allocation_id=b["allocation_id"].replace("W1", "W2"),
            planned_start_min=1,
            planned_end_min=4,
        )
        data["assignments"] = [a, b]
        self.reject(Plan, data)

    def test_assignment_Q_membership_and_negative_interval(self):
        data = self.fixture("plan")
        a = self.assignment()
        a["allocation_id"] = next(q["id"] for q in self.raw["allocations"] if q["skill"] == "WELD")
        data["assignments"] = [a]
        self.reject(Plan, data)
        data["assignments"] = [self.assignment() | {"planned_end_min": 0}]
        with self.assertRaisesRegex(ContractError, "planned interval"):
            loads(Plan, json.dumps(data), config=self.config)

    def test_selected_transport_and_process_must_share_destination(self):
        data = self.fixture("plan")
        data["observation"]["configuration_id"] = self.large.id
        data["observation"]["known_orders"][0]["order_id"] = "J01"
        data["completions"][0]["order_id"] = "J01"
        op = next(o for o in self.large.operations if o.id == "J01.W1")
        process = self.assignment() | dict(
            operation_id=op.id,
            mode_id="mode.WELD.R",
            group_id=op.process_group_id,
            allocation_id="q.WELD.R.WS1.H2.R1",
        )
        transport = process | dict(
            group_id=op.transfers[0].id,
            phase_id="preposition",
            allocation_id="q.transfer.AS1.WS2.H1",
        )
        data["assignments"] = [process, transport]
        with self.assertRaisesRegex(ContractError, "transport/process target mismatch"):
            loads(Plan, json.dumps(data), config=self.large)

    def test_restore_positive_origin_and_stable_resume(self):
        data = self.fixture("plan")
        data["assignments"] = [self.assignment("restore")]
        loads(Plan, json.dumps(data), config=self.config)
        data["assignments"][0]["restore_sequence"] = 0
        self.reject(Plan, data)
        data["assignments"] = [self.assignment("restore", mode="H")]
        self.reject(Plan, data)
        state = self.running("restore")
        self.reject(ExecutionSnapshot, state)
        original = state["phases"][0] | dict(
            phase_id="setup",
            restore_sequence=0,
            status="completed",
            remaining_base_min=0,
            started_min=0,
            completed_min=1,
        )
        state["phases"].append(original)
        loads(ExecutionSnapshot, json.dumps(state), config=self.config)
        state["phases"][0].update(status="paused", remaining_base_min=0.5)
        loads(ExecutionSnapshot, json.dumps(state), config=self.config)
        state["phases"][0]["attempt"] = 2
        self.reject(ExecutionSnapshot, state)

    def test_restore_inherits_positive_cost_activity_and_locks(self):
        for operation, mode, base, activity in (
            ("J1.C1", "mode.CUT.R", 1, "work"),
            ("J1.A1", "mode.ASSEMBLE.HR", 0.5, "supervise"),
            ("J1.W1", "mode.WELD.HR", 1, "work"),
        ):
            phase = resolve_process_phase(self.config, operation, mode, "restore")
            self.assertEqual(
                (phase.base_min, phase.activity, phase.interruption), (base, activity, "resume")
            )
            self.assertTrue({"worker", "robot"} <= set(phase.active_roles))
            self.assertFalse(phase.fatigue_sensitive)
        with self.assertRaises(ContractError):
            resolve_process_phase(self.config, "J1.C1", "mode.CUT.H", "restore")
        self.assertEqual(
            resolve_process_phase(self.large, "J03.A3", "mode.ASSEMBLE.HR", "work").base_min, 3
        )

    def test_failed_resource_invalidates_preparation(self):
        state = self.running()
        next(r for r in state["resources"] if r["resource_id"] == "CS1_M").update(
            failed=True, release_allowed=False
        )
        self.reject(ExecutionSnapshot, state)

    def test_restore_does_not_reset_work_attempt_or_speed_sample(self):
        state = self.running("restore")
        initial = state["phases"][0] | dict(
            phase_id="setup",
            restore_sequence=0,
            status="completed",
            remaining_base_min=0,
            started_min=0,
            completed_min=1,
        )
        state["phases"].append(initial)
        state["phases"][0]["speed_multiplier"] = 1.2
        self.reject(ExecutionSnapshot, state)
        state = self.running()
        state["phases"][0]["remaining_base_min"] = 4
        self.reject(ExecutionSnapshot, state)

    def test_work_requires_matching_valid_robot_preparation(self):
        data = self.running()
        loads(ExecutionSnapshot, json.dumps(data), config=self.config)
        data["preparations"][0]["valid"] = False
        self.reject(ExecutionSnapshot, data)
        data = self.running()
        data["preparations"][0]["station_id"] = "WS1"
        self.reject(ExecutionSnapshot, data)

    def test_state_cap_future_completion_and_quantity(self):
        data = self.fixture("execution_snapshot")
        data["workers"][0]["fatigue"] = 0.9
        self.reject(ExecutionSnapshot, data)
        data = self.fixture("execution_snapshot")
        data["orders"][0]["actual_completion_min"] = 1
        self.reject(ExecutionSnapshot, data)
        data = self.running()
        data["phases"][0].update(status="completed", completed_min=2, remaining_base_min=1)
        self.reject(ExecutionSnapshot, data)

    def test_inventory_and_reservations_count_together(self):
        data = self.fixture("execution_snapshot")
        a = self.assignment()
        data["bindings"] = [{k: a[k] for k in ("operation_id", "group_id", "allocation_id")}]
        data["materials"] = [
            dict(material_id="J1.C1_out", location_id="PIPE_BUFFER", status="stored", slot=None)
        ]
        data["reservations"] = [
            dict(
                material_id="J1.C1_out",
                location_id="PIPE_BUFFER",
                owner_group_id="J1.C1.process",
                slot=None,
            )
        ]
        self.reject(ExecutionSnapshot, data)

    def test_fixed_failure_requires_explicit_unlock_flag(self):
        data = self.fixture("hidden_scenario")
        event = dict(
            id="failure.1", sim_time_min=3, type="failure", entity_id="CS1_M", release_allowed=None
        )
        data["events"] = [event]
        self.reject(HiddenScenario, data)
        event["release_allowed"] = False
        loads(HiddenScenario, json.dumps(data), config=self.config)
        data["events"].append(event | {"id": "repair.1", "type": "repair", "release_allowed": None})
        self.reject(HiddenScenario, data)

    def test_offline_cancellation_window_is_method_independent(self):
        data = self.fixture("offline_evaluation")
        event = dict(
            id="cancel.1", sim_time_min=41, type="cancel", entity_id="J1", release_allowed=None
        )
        data["scenario"]["events"] = [event]
        loads(OfflineEvaluation, json.dumps(data), config=self.config)
        event["sim_time_min"] = 40
        self.reject(OfflineEvaluation, data)
        data["evaluation_order_ids"], data["completions"] = [], []
        loads(OfflineEvaluation, json.dumps(data), config=self.config)

    def test_dispatch_shape_and_minimum_duration(self):
        data = self.fixture("dispatch")
        data["duration_min"] = 0
        self.reject(DispatchCommand, data)
        data = self.fixture("dispatch")
        data["action"] = "start"
        self.reject(DispatchCommand, data)

    def test_D_budget_and_manifest_window(self):
        data = self.fixture("plan")
        data["budget_kind"], data["exposure_budget_min"] = "Dsum", 10
        self.reject(Plan, data)
        data = self.fixture("run_manifest")
        data["observation_window_min"] = 39
        self.reject(RunManifest, data)

    def test_manifest_accepts_numeric_git_hash_and_rejects_moving_ref(self):
        data = self.fixture("run_manifest")
        data["code_revision"] = "970192a797bae40299832d1b7c0c6e5415e069a5"
        loads(RunManifest, json.dumps(data), config=self.config)
        for revision in ("main", "970192a", "example.uncommitted"):
            data.update(code_revision=revision, status="completed", termination_reason="finished")
            with self.assertRaisesRegex(ContractError, "pinned full Git revision"):
                loads(RunManifest, json.dumps(data), config=self.config)
        data = self.fixture("run_manifest")
        data["status"] = "completed"
        self.reject(RunManifest, data)

    def test_schema_and_example_generation_is_current(self):
        spec = importlib.util.spec_from_file_location(
            "contract_examples", ROOT / "scripts/build_contract_examples.py"
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        for relative, content in module.artifacts().items():
            with self.subTest(path=relative):
                self.assertEqual((ROOT / relative).read_bytes(), content.encode("utf-8"))
        generated = schema(Configuration)
        self.assertFalse(generated["$defs"]["Configuration"]["additionalProperties"])
        self.assertEqual(generated["$defs"]["Units"]["properties"]["time"], {"enum": ["min"]})


if __name__ == "__main__":
    unittest.main()
