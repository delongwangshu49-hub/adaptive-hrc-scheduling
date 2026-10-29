"""Distinct replacement crews after real personnel transactions (P052 r6)."""

import unittest
from dataclasses import replace

import test_dynamic_workforce as fixtures

from adaptive_hrc_scheduling.domain import production as m
from adaptive_hrc_scheduling.dynamic_workforce import marker, status
from adaptive_hrc_scheduling.planning.production import _static_bindings, choose, planning_input
from adaptive_hrc_scheduling.workforce_session import arrival_payload


class StaticCrewRepairTests(unittest.TestCase):
    def setUp(self):
        self.x = fixtures.WorkforceTests()
        self.x.setUp()
        self.addCleanup(self.x.doCleanups)
        self.op = next(
            op
            for op in self.x.c.operations
            if not op.branch and {r.id for r in op.roles} == {"W1", "W2"}
        )

    def arrive(self, pid="W3", template="P043-W2-v1"):
        payload = arrival_payload(self.x.w.config, pid, template, initial_f=0.2)
        self.assertEqual(self.x.apply(self.x.req(pid=pid, payload=payload))["status"], "APPLIED")

    def depart(self, pid):
        self.assertEqual(self.x.apply(self.x.req("PERSON_DEPART", pid))["status"], "APPLIED")
        self.assertEqual(status(self.x.w.s, pid), "DEPARTED")

    def bindings(self, *, crews=None, config=None, state=None, operation=None):
        result = _static_bindings(
            config or self.x.w.config,
            state or self.x.w.s,
            operation or self.op,
            crews or {},
            set(),
        )
        return {r.role_id: r.person_id for r in result}

    def test_departed_w2_replaced_by_higher_fatigue_w3_without_reusing_w1(self):
        self.depart("W2")
        self.arrive()
        self.assertEqual(self.bindings(), {"W1": "W1", "W2": "W3"})

    def test_replacement_reserves_later_nominal_role(self):
        self.depart("W1")
        self.arrive(template="P043-W1-v1")
        self.assertEqual(self.bindings(), {"W1": "W3", "W2": "W2"})

    def test_no_replacement_keeps_unavailable_nominal_without_duplicate(self):
        self.depart("W2")
        self.assertEqual(self.bindings(), {"W1": "W1", "W2": "W2"})

    def test_eligible_originals_are_preserved(self):
        self.arrive()
        self.assertEqual(self.bindings(), {"W1": "W1", "W2": "W2"})

    def ready_weld(self):
        self.depart("W2")
        self.arrive()
        locations = {p.entity_id: p.place_id for p in self.op.component_input_places}
        locations["W1"] = "J3"
        self.x.w.s = replace(
            self.x.w.s,
            completed=self.op.prerequisites,
            positions=tuple(
                replace(p, location=locations[p.id], support=locations[p.id])
                if p.id in locations
                else p
                for p in self.x.w.s.positions
            ),
        )

    def next_weld_command(self):
        w = self.x.w
        obs = w.observe()
        w.deliver()
        value = replace(planning_input(w.config, obs), operations=(self.op,))
        return choose(w.config, value)

    def execute_service(self, command):
        w = self.x.w
        receipt = w.dispatch(command)
        self.assertEqual(receipt.kind, "STARTED", receipt.reason)
        end = next(r.earliest_end_h for r in w.s.running if r.command.id == command.id)
        w.advance(end)

    def test_idle_blocker_walks_then_replacement_walks_then_real_work_starts(self):
        self.ready_weld()
        plan = self.next_weld_command()
        self.assertTrue(plan.commands, plan.reason)
        clearance = plan.commands[0]
        self.assertEqual(clearance.service.operation.entity_id, "Lop")
        self.assertEqual(clearance.service.operation.target, "CONTROL-W2")
        self.execute_service(clearance)
        # Reusing a vacated place never weakens the original return gate.
        receipt = self.x.apply(self.x.req("PERSON_RETURN", "W2"))
        self.assertEqual(receipt["status"], "REJECTED")
        self.assertEqual(receipt["reason"], "PERSON_RETURN_OCCUPIED")
        self.assertEqual(status(self.x.w.s, "W2"), "DEPARTED")
        plan = self.next_weld_command()
        self.assertTrue(plan.commands, plan.reason)
        walking = plan.commands[0]
        self.assertEqual(walking.service.operation.entity_id, "W3")
        self.assertEqual(walking.service.operation.target, "J3")
        self.execute_service(walking)
        plan = self.next_weld_command()
        self.assertTrue(plan.commands, plan.reason)
        command = plan.commands[0]
        self.assertEqual(command.operation_id, self.op.id)
        self.assertEqual({r.person_id for r in command.roles}, {"W1", "W3"})
        receipt = self.x.w.dispatch(command)
        self.assertEqual(receipt.kind, "STARTED", receipt.reason)

    def test_busy_blocker_is_not_moved(self):
        self.ready_weld()
        rest = fixtures.service_command(self.x.w, "Lop", rest=True)
        self.assertEqual(self.x.w.dispatch(rest).kind, "STARTED")
        plan = self.next_weld_command()
        self.assertFalse(plan.commands, plan)
        self.assertIn("NO_LEGAL_PERSON_ACCESS", plan.reason)

    def test_newcomer_first_frees_the_only_vacated_parking_place(self):
        self.ready_weld()
        w = self.x.w
        w.s = replace(
            w.s,
            positions=tuple(
                replace(p, location="CONTROL-W2", support="CONTROL-W2") if p.id == "W3" else p
                for p in w.s.positions
            ),
        )
        expected = [("W3", "CONTROL-W1"), ("Lop", "CONTROL-W2"), ("W3", "J3")]
        for person, destination in expected:
            plan = self.next_weld_command()
            self.assertTrue(plan.commands, plan.reason)
            command = plan.commands[0]
            self.assertEqual(command.service.operation.entity_id, person)
            self.assertEqual(command.service.operation.target, destination)
            self.execute_service(command)
        plan = self.next_weld_command()
        self.assertEqual(plan.commands[0].operation_id, self.op.id)
        self.assertEqual(w.dispatch(plan.commands[0]).kind, "STARTED")

    def test_uncommitted_core_prefers_reachable_worker_over_lower_fatigue(self):
        self.depart("W2")
        self.arrive()
        w = self.x.w
        op = next(
            o
            for o in w.config.operations
            if o.activity_id == "PRODUCT-1.W-B" and o.production_mode == "H" and o.unit_index == 0
        )
        w.s = replace(
            w.s,
            completed=op.prerequisites,
            humans=tuple(replace(h, fatigue=0.3) if h.person_id == "W1" else h for h in w.s.humans),
            positions=tuple(
                replace(p, location="J2", support="J2") if p.id == "PRODUCT-1.BOTTOM" else p
                for p in w.s.positions
            ),
        )
        obs = w.observe()
        w.deliver()
        plan = choose(w.config, replace(planning_input(w.config, obs), operations=(op,)))
        self.assertTrue(plan.commands, plan.reason)
        command = plan.commands[0]
        self.assertEqual(command.service.operation.entity_id, "W1")
        self.assertEqual(command.service.operation.target, "J2")
        self.assertEqual(w.dispatch(command).kind, "STARTED")

    def test_explicit_research_assignment_is_reserved(self):
        self.depart("W2")
        self.arrive()
        config = replace(self.x.w.config, research=True)
        self.assertEqual(
            self.bindings(config=config, crews={self.op.activity_id + ":W1": "W3"}),
            {"W1": "W3", "W2": "W1"},
        )

    def test_overlapping_qualifications_backtrack_for_distinct_complete_crew(self):
        # A finite matching counterexample: the first flexible candidate is the
        # only candidate for the second role. Greedy exclusion alone fails.
        config = self.x.w.config
        people = tuple(
            replace(p, qualifications=("QA", "QB") if p.id == "W1" else ("QA",))
            for p in config.people
            if p.id in ("W1", "W2")
        )
        config = replace(config, people=people)
        state = replace(
            self.x.w.s, failed_resources=(marker("DEPARTED", "OLD-A"), marker("DEPARTED", "OLD-B"))
        )
        state = replace(
            state,
            humans=tuple(
                replace(h, fatigue=0 if h.person_id == "W1" else 0.2) for h in state.humans
            ),
        )
        operation = replace(self.op, roles=(m.Role("OLD-A", "QA"), m.Role("OLD-B", "QB")))
        self.assertEqual(
            self.bindings(config=config, state=state, operation=operation),
            {"OLD-A": "W2", "OLD-B": "W1"},
        )


if __name__ == "__main__":
    unittest.main()
