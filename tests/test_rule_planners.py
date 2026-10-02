"""S11 algorithmic generation, bounded failures and independent trace mutations."""

import importlib.util
import json
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from adaptive_hrc_scheduling import checker
from adaptive_hrc_scheduling.building_backend import BuildingBackend
from adaptive_hrc_scheduling.contracts.codec import as_data
from adaptive_hrc_scheduling.domain import building as b
from adaptive_hrc_scheduling.planning.decoder import Options, generate_plan, legal_candidates
from adaptive_hrc_scheduling.planning.rules import Candidate, select

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "s11_generator", ROOT / "scripts/build_building_contracts.py"
)
generator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(generator)


def configuration(variant="SR-W1", products=1):
    return generator.synthetic_fixture(generator.build_configuration(variant, products=products))


def run(c, **kwargs):
    return generate_plan(c, BuildingBackend(c).observe()[0], Options(**kwargs))


class RulePlannerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.results = {
            (v, rule): run(configuration(v), rule=rule, synthetic_gate_assumptions=True)
            for v in ("SR-W1", "SR-W2")
            for rule in ("EDD", "SPT", "FASTEST_MODE")
        }
        cls.r = cls.results["SR-W1", "EDD"]

    def audit(self, *, plan=None, trace=None, observation=None):
        r = self.r
        return checker.check_run(
            r.configuration,
            trace or r.trace,
            plan=plan or r.plan,
            observation=observation or r.observation,
            candidate_trace=True,
        )

    def test_all_rules_both_complete_variants(self):
        for key, r in self.results.items():
            with self.subTest(key=key):
                self.assertEqual(r.status, "FEASIBLE", r.reason)
                self.assertTrue(r.plan.commands)
                self.assertEqual(r.report.status, "PASS", r.report.findings)
                self.assertEqual(len(r.report.reconstructed["attempts"]), 37)
                self.assertEqual(len(r.report.metrics["people"]), 15)
                self.assertEqual(r.report.metrics["ready_products"], 1)
                self.assertEqual(r.trace.products[0].state, "READY")
                self.assertEqual(r.trace.products[0].location, "OUT1")
                self.assertEqual(len(r.trace.quality), 7)
                self.assertEqual(r.trace.scenario.events, ())
                self.assertTrue(r.assumptions)

    def test_repeated_inputs_commands_and_trace_are_identical(self):
        r = run(configuration(), synthetic_gate_assumptions=True)
        self.assertEqual(self.r.plan, r.plan)
        self.assertEqual(self.r.trace, r.trace)
        self.assertEqual(self.r.waits, r.waits)

    def test_input_activity_order_is_not_manual_witness_order(self):
        c = configuration()
        c = replace(c, activities=tuple(reversed(c.activities)), edges=tuple(reversed(c.edges)))
        r = run(c, synthetic_gate_assumptions=True)
        self.assertEqual(r.status, "FEASIBLE", r.reason)
        self.assertEqual(r.plan.commands, self.r.plan.commands)
        codes = [
            next(a.code for a in c.activities if a.id == x.activity_id) for x in r.plan.commands
        ]
        self.assertLess(codes.index("MV-IN-T"), codes.index("W-B"))

    def test_rules_and_stable_ties(self):
        cmd = self.r.plan.commands[0]
        a = Candidate(cmd, "P1", 10, 3)
        c2 = replace(cmd, activity_id="OTHER", mode_id="M2")
        b2 = Candidate(c2, "P2", 5, 8)
        self.assertEqual(select((a, b2), "EDD"), b2)
        self.assertEqual(select((a, b2), "SPT"), a)
        fast = replace(a, command=replace(cmd, mode_id="FAST"), estimated_remaining_h=1)
        self.assertEqual(select((a, fast), "FASTEST_MODE"), fast)
        for rule in ("EDD", "SPT", "FASTEST_MODE"):
            tied = replace(b2, due_h=10, estimated_remaining_h=3)
            self.assertEqual(select((tied, a), rule), select((a, tied), rule))

    def test_legality_precedes_urgency(self):
        c = configuration(products=2)
        c = replace(
            c,
            products=(replace(c.products[0], due_h=1), c.products[1]),
            materials=tuple(
                replace(m, released=False) if m.product_id == "PRODUCT-1" else m
                for m in c.materials
            ),
        )
        r = run(c, synthetic_gate_assumptions=True, max_decisions=2)
        starts = [e for e in r.trace.events if e.kind == "UNIT_START"]
        # KIT may run without a downstream kit, CUT may not consume missing steel.
        self.assertTrue(all(e.entity_id.endswith("KIT") for e in starts))

    def test_edd_selects_earlier_due_visible_product(self):
        c = configuration(products=2)
        c = replace(c, products=(c.products[0], replace(c.products[1], due_h=10)))
        r = run(c, synthetic_gate_assumptions=True, max_decisions=1)
        self.assertEqual(
            next(e.entity_id for e in r.trace.events if e.kind == "UNIT_START"), "PRODUCT-2.KIT"
        )

    def test_probes_leave_world_unchanged_and_return_only_legal_bindings(self):
        w = BuildingBackend(configuration())
        before = w.snapshot
        candidates, _, exhausted = legal_candidates(w)
        self.assertFalse(exhausted)
        self.assertEqual(w.snapshot, before)
        self.assertEqual(len(candidates), 1)
        self.assertTrue(w.dispatch(candidates[0].command).accepted)

    def test_default_research_input_holds_and_hr_stays_disabled(self):
        c = generator.build_configuration()
        r = run(c)
        self.assertEqual(r.status, "NO_PLAN_FOUND")
        self.assertIsNone(r.plan)
        self.assertTrue(any(w.reason == "MODE_DISABLED_OR_UNQUALIFIED" for w in r.waits))
        for r in self.results.values():
            modes = {m.id: m for a in r.configuration.activities for m in a.modes}
            self.assertTrue(all(modes[x.mode_id].kind != "HR-seq" for x in r.plan.commands))

    def test_no_automatic_quality_fact_without_explicit_assumption(self):
        r = run(configuration())
        self.assertEqual(r.status, "NO_PLAN_FOUND")
        self.assertIsNone(r.plan)
        self.assertFalse(r.trace.quality)
        self.assertTrue(any(w.reason.startswith("QUALITY_HOLD:") for w in r.waits))

    def test_unknown_quality_qualification_never_promoted(self):
        c = configuration()
        gate = next(a.quality_evidence for a in c.activities if a.code == "Q-STR")
        c = replace(
            c,
            evidence=tuple(replace(e, status="UNKNOWN") if e.id == gate else e for e in c.evidence),
        )
        r = run(c, synthetic_gate_assumptions=True)
        self.assertEqual(r.status, "NO_PLAN_FOUND")
        self.assertFalse(r.trace.quality)

    def test_industrial_configuration_cannot_use_synthetic_assumption(self):
        r = run(generator.build_configuration(), synthetic_gate_assumptions=True)
        self.assertEqual(r.status, "INVALID_INPUT")

    def test_finite_output_never_implicitly_received_or_freed(self):
        r = run(configuration(products=2), synthetic_gate_assumptions=True)
        self.assertEqual(r.status, "NO_PLAN_FOUND", r.reason)
        self.assertIsNone(r.plan)
        self.assertEqual(sum(p.state == "READY" for p in r.trace.products), 1)
        self.assertTrue(any(w.reason == "DESTINATION_CAPACITY:OUT1" for w in r.waits))
        self.assertTrue(any(r.location == "OUT1" for r in r.trace.residencies))
        self.assertFalse(
            any(e.kind == "EXTERNAL" and '"RECEIVED"' in e.reason for e in r.trace.events)
        )
        self.assertEqual(checker.check_run(r.configuration, r.trace).status, "PASS")
        self.assertTrue(any(w.blockers for w in r.waits if w.reason.startswith("RESOURCE_BUSY:")))

    def test_shared_crane_intervals_do_not_overlap(self):
        r = run(configuration(products=2), synthetic_gate_assumptions=True)
        spans = [
            json.loads(e.reason)
            for e in r.trace.events
            if e.kind == "UNIT_START" and "CR1" in json.loads(e.reason)["equipment"]
        ]
        self.assertGreater(len(spans), 3)
        spans.sort(key=lambda x: x["start_h"])
        self.assertTrue(all(a["end_h"] <= z["start_h"] for a, z in zip(spans, spans[1:])))

    def test_all_crew_calendars_and_fatigue_are_respected(self):
        c = configuration()
        c = replace(
            c,
            people=tuple(
                replace(p, calendar=b.Calendar(24, (b.Window(0, 2), b.Window(5, 8))))
                if p.id == "Lsig"
                else p
                for p in c.people
            ),
        )
        r = run(c, synthetic_gate_assumptions=True)
        self.assertEqual(r.status, "FEASIBLE", r.reason)
        self.assertEqual(r.report.status, "PASS")
        self.assertTrue(
            any(w.reason == "CALENDAR_OR_QUALIFICATION" and "Lsig" in w.blockers for w in r.waits)
        )
        self.assertTrue(all(h.peak <= c.cap for h in r.trace.people))

    def test_overload_is_exact_fixed_model_infeasibility(self):
        c = configuration()
        c = replace(c, products=tuple(replace(p, mass_t=12) for p in c.products))
        r = run(c, synthetic_gate_assumptions=True)
        self.assertEqual(r.status, "INFEASIBLE")
        self.assertIn("12+1>12", r.reason)
        self.assertIsNone(r.plan)

    def test_budget_and_horizon_exhaustion_are_not_infeasibility(self):
        for opts in ({"max_decisions": 1}, {"horizon_h": 1}, {"max_bindings": 1}):
            r = run(configuration(), synthetic_gate_assumptions=True, **opts)
            self.assertEqual(r.status, "NO_PLAN_FOUND", r.reason)
            self.assertIn("EXHAUSTED", r.reason)
            self.assertIsNone(r.plan)

    def test_invalid_input_is_separate(self):
        c = configuration()
        r = generate_plan(replace(c, edges=()), self.r.observation)
        self.assertEqual(r.status, "INVALID_INPUT")

    def test_invalid_options_and_missing_initial_observation(self):
        for opts in ({"rule": "OTHER"}, {"horizon_h": float("nan")}, {"max_decisions": True}):
            self.assertEqual(run(configuration(), **opts).status, "INVALID_INPUT")
        obs = replace(self.r.observation, people=())
        self.assertEqual(generate_plan(self.r.configuration, obs).status, "INVALID_INPUT")

    def test_later_observation_is_explicitly_out_of_static_scope(self):
        w = BuildingBackend(configuration())
        w.advance(1)
        r = generate_plan(w.config, w.observe()[0])
        self.assertEqual(r.status, "INVALID_INPUT")

    def test_future_product_cannot_change_visible_schedule(self):
        c = configuration(products=2)
        c = replace(c, products=(c.products[0], replace(c.products[1], release_h=300, due_h=400)))
        r = run(c, synthetic_gate_assumptions=True)
        self.assertEqual(r.status, "FEASIBLE", r.reason)
        self.assertEqual(
            tuple(replace(x, config_id=self.r.configuration.id) for x in r.plan.commands),
            self.r.plan.commands,
        )
        self.assertEqual(len(r.configuration.products), 1)

    def test_future_required_order_member_is_not_silently_completed(self):
        c = configuration(products=2)
        c = replace(
            c,
            products=(
                c.products[0],
                replace(c.products[1], release_h=300, due_h=400, order_id=c.products[0].order_id),
            ),
        )
        r = run(c, synthetic_gate_assumptions=True)
        self.assertEqual(r.status, "NO_PLAN_FOUND")
        self.assertEqual(r.reason, "CURRENT_WINDOW_HAS_UNRELEASED_ORDER_MEMBERS")

    def test_rejected_independent_check_cannot_return_candidate(self):
        with patch(
            "adaptive_hrc_scheduling.planning.decoder.check_run",
            return_value=checker.Report("FAIL", [], {}, {}, {}),
        ):
            r = run(configuration(), synthetic_gate_assumptions=True)
        self.assertEqual(r.status, "NO_PLAN_FOUND")
        self.assertIsNone(r.plan)
        self.assertEqual(r.reason, "INDEPENDENT_CHECK_REJECTED")

    def test_unbound_legacy_plan_remains_incomplete(self):
        r = self.r
        report = checker.check_run(r.configuration, r.trace, plan=r.plan, observation=r.observation)
        self.assertEqual(report.status, "INCOMPLETE")

    def test_empty_candidate_is_not_pass_even_with_complete_trace(self):
        self.assertNotEqual(self.audit(plan=replace(self.r.plan, commands=())).status, "PASS")

    def test_predicted_ready_is_not_completion_evidence(self):
        w = BuildingBackend(self.r.configuration)
        self.assertNotEqual(self.audit(trace=w.snapshot).status, "PASS")
        plan = replace(self.r.plan, predicted_ready=(b.Prediction("PRODUCT-1", 1),))
        self.assertNotEqual(self.audit(plan=plan).status, "PASS")

    def test_each_command_field_bound_to_trace(self):
        command = self.r.plan.commands[0]
        changes = (
            {"expected_revision": 999},
            {"activity_id": "PRODUCT-1.CUT"},
            {"mode_id": "FAKE"},
            {"attempt": 1},
            {"unit_index": 1},
            {"issued_h": 0.1},
            {"roles": ()},
            {"id": "FAKE-ID"},
        )
        for fields in changes:
            with self.subTest(fields=fields):
                plan = replace(
                    self.r.plan, commands=(replace(command, **fields),) + self.r.plan.commands[1:]
                )
                self.assertNotEqual(self.audit(plan=plan).status, "PASS")

    def test_missing_extra_reordered_commands_rejected(self):
        commands = self.r.plan.commands
        for altered in (
            commands[1:],
            commands + (commands[0],),
            (commands[1], commands[0]) + commands[2:],
        ):
            self.assertNotEqual(
                self.audit(plan=replace(self.r.plan, commands=altered)).status, "PASS"
            )

    def test_missing_trace_and_forged_quality_never_pass(self):
        trace = self.r.trace
        self.assertNotEqual(
            self.audit(trace=replace(trace, events=trace.events[1:])).status, "PASS"
        )
        q = replace(trace.quality[0], result="FAIL")
        self.assertNotEqual(
            self.audit(trace=replace(trace, quality=(q,) + trace.quality[1:])).status, "PASS"
        )

    def test_frozen_requirements_cannot_be_removed_to_get_plan(self):
        c = configuration()
        c = replace(
            c,
            activities=tuple(
                replace(
                    a,
                    modes=tuple(
                        replace(m, units=tuple(replace(u, equipment=()) for u in m.units))
                        for m in a.modes
                    ),
                )
                if a.code == "CUT"
                else a
                for a in c.activities
            ),
        )
        r = generate_plan(c, self.r.observation, Options(synthetic_gate_assumptions=True))
        self.assertEqual(r.status, "INVALID_INPUT")
        self.assertIn("missing frozen equipment", r.reason)

    def test_json_serializable_diagnostics(self):
        json.dumps(as_data(self.r.trace), allow_nan=False)
        self.assertTrue(self.r.waits)

    def test_synthetic_fastest_mode_branch_only(self):
        c = generator.synthetic_fixture(generator.build_configuration(), hr=True)
        r = run(c, rule="FASTEST_MODE", synthetic_gate_assumptions=True)
        self.assertEqual(r.status, "FEASIBLE", r.reason)
        weld = [x for x in r.plan.commands if x.activity_id.endswith((".W-B", ".W-T"))]
        self.assertTrue(all(x.mode_id.endswith("HR-seq") for x in weld))

    def test_foreign_initial_people_and_revision_rejected_independently(self):
        obs = self.r.observation
        for altered in (
            replace(obs, state_revision=1),
            replace(obs, people=()),
            replace(obs, people=(replace(obs.people[0], fatigue=0.1),) + obs.people[1:]),
        ):
            self.assertNotEqual(self.audit(observation=altered).status, "PASS")

    def test_duplicate_role_person_never_admitted(self):
        c = configuration()
        c = replace(c, people=tuple(p for p in c.people if p.id != "AF2"))
        r = run(c, synthetic_gate_assumptions=True)
        self.assertEqual(r.status, "NO_PLAN_FOUND")
        self.assertTrue(any(w.reason == "NO_QUALIFIED_DISTINCT_BINDING" for w in r.waits))

    def test_j2_co_residency_and_fixture_exclusion_preserved(self):
        reservations = [
            json.loads(e.reason) for e in self.r.trace.events if e.kind == "MOVE_RESERVED"
        ]
        self.assertTrue(
            any(
                len({x["entity_id"] for x in d["residencies"] if x["location"] == "J2"}) == 2
                for d in reservations
            )
        )
        spans = [
            json.loads(e.reason)
            for e in self.r.trace.events
            if e.kind == "UNIT_START" and "FIX-J2" in json.loads(e.reason)["equipment"]
        ]
        self.assertTrue(all(a["end_h"] <= z["start_h"] for a, z in zip(spans, spans[1:])))


if __name__ == "__main__":
    unittest.main()
