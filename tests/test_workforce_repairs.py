"""P04.3 R01-R05 regression and independent corruption rejection."""

import copy
import json
import unittest
from dataclasses import replace
from unittest.mock import patch

import test_dynamic_workforce as fixtures
import test_simulation_production as phases
from verify_workforce_session import verify

from adaptive_hrc_scheduling.contracts.production import digest
from adaptive_hrc_scheduling.dynamic_orders import template_registry
from adaptive_hrc_scheduling.dynamic_workforce import status
from adaptive_hrc_scheduling.production_checker import check_run
from adaptive_hrc_scheduling.workforce_session import arrival_payload


class WorkforceRepairTests(unittest.TestCase):
    def setUp(self):
        self.x = fixtures.WorkforceTests()
        self.x.setUp()
        self.addCleanup(self.x.doCleanups)

    def robot_boundary(self):
        x = self.x
        f = phases.SimulationPhaseTests()
        f.setUp()
        f.config, f.world = x.c, x.w
        x.w.s = replace(
            x.w.s,
            completed=f.hr[0].prerequisites,
            positions=tuple(
                replace(p, location="J2", support="J2")
                if p.id in ("OP1", "PRODUCT-1.BOTTOM")
                else p
                for p in x.w.s.positions
            ),
        )
        f.complete(f.hr[0])
        f.exit_seed()
        return f

    def order(self, quantity=1):
        return self.x.req(
            "ORDER_CREATE",
            "NEW-2",
            dict(
                order_id="NEW-2",
                template_id="SR-W1",
                template_revision="v1",
                template_sha256=template_registry()["SR-W1"],
                quantity=quantity,
                due_sim_h=300,
                priority="NORMAL",
                material_plan_id="TEMPLATE-JIT-v1",
                arrival_rule="REQUEST_EFFECTIVE_TIME",
            ),
        )

    def saved(self):
        self.x.s.persist()
        return json.loads((self.x.s.output / "session-state.json").read_text())

    def rejects_damage(self, mutate, reason):
        original = self.saved()
        bad = copy.deepcopy(original)
        mutate(bad)
        path = self.x.s.output / "session-state.json"
        path.write_text(json.dumps(bad))
        with self.assertRaisesRegex(ValueError, reason):
            verify(self.x.s.output, require_decisions=False)
        path.write_text(json.dumps(original))

    def test_R01_gap_absence_blocks_roleless_robot_and_preserves_owners(self):
        x, f = self.x, self.robot_boundary()
        owners = x.w.s.owners
        self.assertEqual(x.apply(x.req("PERSON_ABSENT", "OP1"))["status"], "APPLIED")
        self.assertEqual(status(x.w.s, "OP1"), "ABSENT_HOLD")
        r = x.w.dispatch(f.command(f.hr[1]))
        self.assertEqual(r.reason, "PERSON_ATTEMPT_DISPATCH_DISABLED")
        self.assertEqual(x.w.s.owners, owners)
        self.assertNotIn(f.hr[1].id, x.w.s.completed)

    def test_R01_gap_return_allows_legally_unstarted_robot(self):
        x, f = self.x, self.robot_boundary()
        x.apply(x.req("PERSON_ABSENT", "OP1"))
        x.apply(x.req("PERSON_RETURN", "OP1"))
        self.assertEqual(x.w.dispatch(f.command(f.hr[1])).kind, "STARTED")

    def test_R01_pending_departure_blocks_new_robot(self):
        x, f = self.x, self.robot_boundary()
        x.apply(x.req("PERSON_DEPART", "OP1"))
        self.assertEqual(status(x.w.s, "OP1"), "DEPARTURE_PENDING")
        self.assertEqual(
            x.w.dispatch(f.command(f.hr[1])).reason, "PERSON_ATTEMPT_DISPATCH_DISABLED"
        )

    def test_R01_running_absence_keeps_original_exception(self):
        x, f = self.x, self.robot_boundary()
        x.w.dispatch(f.command(f.hr[1]))
        x.apply(x.req("PERSON_ABSENT", "OP1"))
        self.assertEqual(x.w.s.running[0].status, "EXCEPTION")
        self.assertEqual(x.w.s.mode_attempts[0].state, "HOLD")

    def test_R01_independent_checker_rejects_bypassed_gate(self):
        x, f = self.x, self.robot_boundary()
        x.apply(x.req("PERSON_ABSENT", "OP1"))
        with patch("adaptive_hrc_scheduling.dynamic_workforce.eligible", return_value=True):
            self.assertEqual(x.w.dispatch(f.command(f.hr[1])).kind, "STARTED")
        audit = check_run(x.w.config, x.w.snapshot(), catalog=x.s.history)
        self.assertIn("PERSON_ATTEMPT_DISPATCH_DISABLED", [r.reason for r in audit.findings])

    def test_R02_return_collision_rejected_atomically(self):
        x = self.x
        x.apply(x.req("PERSON_DEPART", "W1"))
        self.assertEqual(
            x.apply(x.req(payload=arrival_payload(x.c, "W3", location="CONTROL-W1")))["status"],
            "APPLIED",
        )
        before = x.w.snapshot()
        self.assertEqual(x.apply(x.req("PERSON_RETURN", "W1"))["reason"], "PERSON_RETURN_OCCUPIED")
        self.assertEqual(x.w.snapshot(), before)
        x.audit()

    def test_R02_return_after_occupant_leaves(self):
        x = self.x
        x.apply(x.req("PERSON_DEPART", "W1"))
        x.apply(x.req(payload=arrival_payload(x.c, "W3", location="CONTROL-W1")))
        x.apply(x.req("PERSON_DEPART", "W3"))
        self.assertEqual(x.apply(x.req("PERSON_RETURN", "W1"))["status"], "APPLIED")
        x.audit()

    def test_R02_future_return_rechecks_new_occupancy(self):
        x = self.x
        x.apply(x.req("PERSON_DEPART", "W1"))
        r = x.req("PERSON_RETURN", "W1", time_rule="AT_SIM_H", requested_sim_h=0.1)
        x.apply(r)
        x.apply(x.req(payload=arrival_payload(x.c, "W3", location="CONTROL-W1")))
        x.w.advance(0.1)
        x.s.boundary()
        self.assertEqual(x.s.receipts[-1]["reason"], "PERSON_RETURN_OCCUPIED")
        x.audit()

    def test_R02_checker_rejects_released_position_overlap(self):
        x = self.x
        x.apply(x.req("PERSON_DEPART", "W1"))
        x.apply(x.req(payload=arrival_payload(x.c, "W3", location="CONTROL-W1")))
        with patch("adaptive_hrc_scheduling.production_navigation.walk_blocker", return_value=None):
            self.assertEqual(x.apply(x.req("PERSON_RETURN", "W1"))["status"], "APPLIED")
        audit = check_run(x.w.config, x.w.snapshot(), catalog=x.s.history)
        self.assertTrue(any(r.reason.startswith("PERSON_RETURN_OCCUPIED") for r in audit.findings))

    def test_R03_new_order_without_person_changes_passes(self):
        self.assertEqual(self.x.apply(self.order())["status"], "APPLIED")
        self.x.audit()

    def test_R03_person_then_two_product_order_passes(self):
        self.x.apply(self.x.req())
        self.assertEqual(self.x.apply(self.order(2))["status"], "APPLIED")
        self.x.audit()

    def test_R03_order_then_person_and_return_passes(self):
        x = self.x
        x.apply(self.order())
        x.apply(x.req())
        x.apply(x.req("PERSON_DEPART"))
        x.apply(x.req("PERSON_RETURN"))
        x.audit()

    def test_R03_forged_order_arrival_is_rejected(self):
        x = self.x
        x.apply(self.order())
        self.rejects_damage(
            lambda d: next(
                e
                for e in d["execution"]["events"]
                if e["world"] and e["world"]["kind"] == "ORDER_ARRIVAL"
            )["world"].update(entity_id="WRONG"),
            "ORDER_TRANSACTION_END",
        )

    def test_R04_qualification_and_window_fields_checked(self):
        x = self.x
        x.apply(x.req())
        for field, value in (("qualification_version", 999), ("valid_until_h", 0)):
            with self.subTest(field=field):
                self.rejects_damage(
                    lambda d: d["workforce_statistics"]["people"]["W3"].update({field: value}),
                    "PERSON_QUALIFICATION_VERSION",
                )
        self.rejects_damage(
            lambda d: d["workforce_statistics"].update(common_window_h=[999, 1000]),
            "STATISTICS_WINDOW",
        )

    def test_R04_cpu_return_scene_required_and_bound(self):
        x = self.x
        x.apply(x.req("PERSON_DEPART", "W1"))
        x.apply(x.req("PERSON_RETURN", "W1"))
        x.audit()
        self.rejects_damage(lambda d: d.update(scene_bindings=[]), "PERSON_SCENE_EXACT_COVERAGE")
        for field, value in (
            ("ready", False),
            ("actual_location", "WRONG"),
            ("catalog_version", 999),
        ):
            with self.subTest(field=field):
                self.rejects_damage(
                    lambda d: d["scene_bindings"][0].update({field: value}),
                    "PERSON_SCENE_EVENT_BINDING",
                )

    def test_R04_nonempty_commitments_preserved_and_blocked(self):
        x = self.x
        cmd = fixtures.service_command(x.w, "W1", rest=True)
        x.s.policy.committed = (cmd,)
        x.apply(x.req("PERSON_DEPART", "W1"))
        self.assertEqual(
            x.s.workforce_results[-1]["blocked_commitments"][0]["command_sha256"], digest(cmd)
        )
        self.assertEqual(x.s.policy.committed, (cmd,))
        x.audit()
        self.rejects_damage(
            lambda d: d["workforce_results"][0].update(blocked_commitments=[]),
            "COMMITMENT_BLOCKED_COVERAGE",
        )
        self.rejects_damage(
            lambda d: d["workforce_results"][0].update(committed_commands=[]),
            "COMMITMENT_SNAPSHOT_BINDING",
        )

    def test_R04_unrelated_commitment_is_not_blocked(self):
        x = self.x
        x.s.policy.committed = (fixtures.service_command(x.w, "W2", rest=True),)
        x.apply(x.req("PERSON_DEPART", "W1"))
        self.assertEqual(x.s.workforce_results[-1]["blocked_commitments"], [])
        x.audit()

    def test_R04_fabricated_blocked_fact_rejected(self):
        x = self.x
        x.apply(x.req())
        self.rejects_damage(
            lambda d: d["workforce_results"][0].update(
                blocked_commitments=[dict(command_id="FAKE", status="COMMITMENT_BLOCKED")]
            ),
            "COMMITMENT_BLOCKED_COVERAGE",
        )

    def test_R05_future_operation_id_collision_is_atomic(self):
        x = self.x
        x.apply(x.req(pid="PRODUCT-2.CUT.U1"))
        before = x.w.snapshot()
        self.assertEqual(x.apply(self.order())["reason"], "GENERATION_PERSON_ID_COLLISION")
        self.assertEqual(x.w.snapshot(), before)
        x.audit()

    def test_R05_later_product_collision_rejects_entire_batch(self):
        x = self.x
        x.apply(x.req(pid="PRODUCT-3.CUT.U1"))
        before = x.w.snapshot()
        self.assertEqual(x.apply(self.order(2))["reason"], "GENERATION_PERSON_ID_COLLISION")
        self.assertEqual(x.w.snapshot(), before)
        self.assertEqual(len(x.w.config.products), 1)
        x.audit()

    def test_R05_existing_operation_id_still_rejected(self):
        x = self.x
        x.apply(self.order())
        self.assertEqual(x.apply(x.req(pid="PRODUCT-2.CUT.U1"))["reason"], "PERSON_ID_USED")
        x.audit()


if __name__ == "__main__":
    unittest.main()
