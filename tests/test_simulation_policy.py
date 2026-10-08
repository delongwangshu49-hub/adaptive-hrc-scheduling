"""Predeclared budgets and no-update proposal isolation in the production domain."""

import sys
import unittest
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from build_simulation_production import configuration

from adaptive_hrc_scheduling.control.simulation_joint_policy import (
    Budget,
    BudgetLedger,
    SimulationJointPolicy,
)
from adaptive_hrc_scheduling.domain import production as m
from adaptive_hrc_scheduling.planning.production import planning_input
from adaptive_hrc_scheduling.production_backend import ProductionBackend


class SimulationBudgetTests(unittest.TestCase):
    def budget(self):
        return Budget(2, 2, 4, 60, 1, 1, 30, (0, 0.5), 1)

    def test_cumulative_limits_are_allocated_before_search(self):
        ledger = BudgetLedger(self.budget())
        first = ledger.allocation()
        self.assertEqual((first.iterations, first.repair_trials), (1, 1))
        self.assertTrue(ledger.consume(None, 1, None))
        self.assertTrue(ledger.consume(None, 1, None))
        self.assertIsNone(ledger.allocation())
        report = ledger.report()
        self.assertEqual(report["used_calls"], 2)
        self.assertEqual(report["used_repair_trials"], 2)
        self.assertEqual(report["declared"]["max_calls"], 2)

    def test_no_update_proposal_remains_nominal_after_new_failure(self):
        c = configuration()
        w = ProductionBackend(c)
        policy = SimulationJointPolicy(c, self.budget(), method="NO_OBSERVATION_UPDATE", end_h=1)
        value = planning_input(c, w.observe(), 10000)
        plan = policy.decide(value, w.snapshot(), (), sequence=0)
        self.assertEqual(policy.budget.calls, 1)
        schedule = policy.schedule
        self.assertIsNotNone(schedule)
        before = schedule.genes
        # Only a delivered fact enters the actual safety shield. There is no
        # extra opportunity at this clock and therefore no feedback-driven search.
        w.apply_world(
            m.WorldEvent(
                "FAIL-R1", w.run_id, 0, 0, "FAILURE", "R1", "PRODUCT-1", 0, "UNKNOWN", "ML-METHOD"
            )
        )
        policy.decide(planning_input(c, w.observe(), 10000), w.snapshot(), (), sequence=1)
        self.assertEqual(policy.budget.calls, 1)
        self.assertEqual(policy.schedule.genes, before)
        self.assertIn(plan.status, ("CANDIDATE", "WAIT"))

    def test_current_template_numerical_and_route_drift_rejected(self):
        from adaptive_hrc_scheduling.contracts.codec import ContractError
        from adaptive_hrc_scheduling.contracts.production import validate

        c = configuration(products=2)
        for bad in (
            replace(c, cap=0.9),
            replace(c, routes=(replace(c.routes[0], speed_m_s=0.75), *c.routes[1:])),
            replace(c, people=(replace(c.people[0], work_rate=0.001), *c.people[1:])),
        ):
            with self.assertRaisesRegex(ContractError, "SIM_PRESERVED"):
                validate(bad)

    def test_nonweld_roles_can_bind_different_qualified_people_before_commitment(self):
        from adaptive_hrc_scheduling.contracts.production import digest, validate

        c = configuration()
        w = ProductionBackend(c)
        op = next(o for o in c.operations if o.id == "PRODUCT-1.FLOOR.U1")
        command = m.DispatchCommand(
            c.schema_version,
            c.id,
            digest(c),
            w.run_id,
            0,
            "CREW-TEST",
            op.product_id,
            op.activity_id,
            op.id,
            0,
            op.unit_index,
            op.production_mode,
            0,
            0,
            (m.RoleBinding("AF1", "AF2"), m.RoleBinding("AF2", "AF1")),
            research=c.research,
        )
        validate(command, config=c)
        self.assertNotEqual(command.roles[0].role_id, command.roles[0].person_id)
        w.s = replace(
            w.s,
            activity_crews=(
                m.ActivityCrew(
                    op.activity_id, (m.RoleBinding("AF1", "AF1"), m.RoleBinding("AF2", "AF2"))
                ),
            ),
        )
        self.assertEqual(w.dispatch(command).reason, "SIM_ACTIVITY_CREW_COMMITMENT")
