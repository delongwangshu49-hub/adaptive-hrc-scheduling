"""Declared F0 stays separate from the historical immutable S18 family."""

import sys
import unittest
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from build_simulation_production import configuration

from adaptive_hrc_scheduling.contracts.codec import ContractError, as_data
from adaptive_hrc_scheduling.contracts.production import dumps, loads, validate
from adaptive_hrc_scheduling.domain import production as m
from adaptive_hrc_scheduling.production_backend import ProductionBackend
from adaptive_hrc_scheduling.research_initial import ResearchOnlinePolicy
from adaptive_hrc_scheduling.research_initial import configuration as research


class InitialFatigueTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.base = configuration(products=2)

    def test_actual_initial_state_and_roundtrip(self):
        c = research(self.base, initial_f=0.60)
        self.assertEqual(as_data(loads(m.Configuration, dumps(c))), as_data(c))
        world = ProductionBackend(c)
        self.assertTrue(all(h.fatigue == 0.60 and h.exposure == 0 for h in world.s.humans))
        self.assertEqual(c.people[0].work_rate, self.base.people[0].work_rate)
        self.assertEqual(c.research.industrial_g2, "OPEN")

    def test_historical_override_still_rejected(self):
        people = tuple(replace(p, initial_f=0.60) for p in self.base.people)
        with self.assertRaisesRegex(ContractError, "SIM_PRESERVED_PARAMETER:people"):
            validate(replace(self.base, people=people))

    def test_other_people_changes_rejected(self):
        c = research(self.base, initial_f=0.60)
        for person in (
            replace(c.people[0], work_rate=0.01),
            replace(c.people[0], qualifications=()),
            replace(c.people[0], initial_f=0.9),
        ):
            with self.subTest(person=person), self.assertRaises(ContractError):
                validate(replace(c, people=(person, *c.people[1:])))

    def test_physical_and_approval_changes_rejected(self):
        c = research(self.base)
        for altered in (
            replace(c, cap=0.9),
            replace(c, setup_h=5),
            replace(c, research=replace(c.research, assumption_sha256="0" * 64)),
        ):
            with self.subTest(altered=altered.id), self.assertRaises(ContractError):
                validate(altered)

    def test_research_search_count_preserves_change_opportunities(self):
        from adaptive_hrc_scheduling.control.online import Limits
        from adaptive_hrc_scheduling.control.session_budget import BudgetAccount, Profile

        limits = Limits(decision_seconds=30, search_seconds=25, max_search_calls=4)
        profile = Profile("P053-TEST", limits, 900, 3)
        policy = ResearchOnlinePolicy(
            research(self.base), limits, end_h=720, budget_account=BudgetAccount(profile)
        )
        policy.calls = 4
        self.assertFalse(policy._search_allowed("PERIODIC"))
        self.assertTrue(policy._search_allowed("CATALOG_CHANGED"))
        policy.calls = 7
        self.assertFalse(policy._search_allowed("FEEDBACK"))

    def test_fixed_future_urgent_declaration_does_not_inject_a_scenario_event(self):
        from types import SimpleNamespace

        from adaptive_hrc_scheduling.control.production_loop import Scenario
        from adaptive_hrc_scheduling.control.session import Session

        session = SimpleNamespace(
            spec=dict(
                scenario="U",
                initial_orders=[dict(priority="NORMAL")],
                clock=dict(session_until_h=720),
            ),
            fixed_requests=[dict(kind="ORDER_CREATE", payload=dict(priority="URGENT"))],
        )
        self.assertEqual(Session.scenario(session), Scenario(id="U", until_h=720))
        session.fixed_requests = []
        with self.assertRaisesRegex(ContractError, "SCENARIO_FIXTURE_NOT_BOUND"):
            Session.scenario(session)


if __name__ == "__main__":
    unittest.main()
