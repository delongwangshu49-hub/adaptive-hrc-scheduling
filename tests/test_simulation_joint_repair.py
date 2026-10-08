"""F1/F2 regressions using public configuration and an actually executed prefix."""

import random
import sys
import unittest
from dataclasses import replace
from pathlib import Path
from time import perf_counter
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from build_simulation_production import configuration

from adaptive_hrc_scheduling.algorithms.lns import Options, Repair, search
from adaptive_hrc_scheduling.algorithms.simulation_joint import SimulationJointProblem, terminal
from adaptive_hrc_scheduling.control.production_decisions import record
from adaptive_hrc_scheduling.control.production_loop import Scenario, run
from adaptive_hrc_scheduling.control.simulation_joint_policy import Budget, BudgetLedger
from adaptive_hrc_scheduling.production_backend import ProductionBackend


class RepairFailureTests(unittest.TestCase):
    def setUp(self):
        c = configuration()
        w = ProductionBackend(c)
        self.problem = SimulationJointProblem(c, w.observe(), w.snapshot(), end_h=0.5)
        self.candidate = self.problem.initial(perf_counter() + 30).candidate

    def test_crew_repair_uses_retained_mode_over_many_seeds(self):
        p = self.problem
        for mode in ("H", "HR-seq"):
            original = replace(
                self.candidate,
                genes=replace(
                    self.candidate.genes,
                    modes=tuple((a, mode) for a in p.scope),
                    crews=tuple(
                        (a, ("OP1" if mode == "HR-seq" else "W1") if a in p.scope else who)
                        for a, who in self.candidate.genes.crews
                    ),
                ),
            )
            for seed in range(20):
                with (
                    self.subTest(mode=mode, seed=seed),
                    patch.object(
                        p, "rollout", side_effect=lambda g, _: Repair(replace(original, genes=g), 1)
                    ),
                ):
                    result = p.repair(
                        original, ("CREW",), random.Random(seed), 1, perf_counter() + 30
                    )
                    self.assertEqual(result.candidate.genes.modes, original.genes.modes)
                    for aid, who in result.candidate.genes.crews:
                        if aid in p.scope:
                            self.assertIn(who, ("OP1",) if mode == "HR-seq" else ("W1", "W2"))

    def test_mode_only_repair_preserves_unrelated_crews(self):
        p = self.problem
        with patch.object(
            p, "rollout", side_effect=lambda g, _: Repair(replace(self.candidate, genes=g), 1)
        ):
            result = p.repair(self.candidate, ("MODE",), random.Random(3), 1, perf_counter() + 30)
        old = dict(self.candidate.genes.crews)
        modes = dict(result.candidate.genes.modes)
        for key, who in result.candidate.genes.crews:
            if key not in p.scope or modes[key] == dict(self.candidate.genes.modes)[key]:
                self.assertEqual(who, old[key])
            else:
                self.assertIn(who, ("W1", "W2") if modes[key] == "H" else ("OP1",))

    def test_failed_trial_is_local_and_next_trial_can_succeed(self):
        p = self.problem
        with patch.object(
            p, "rollout", side_effect=[ValueError("local failure"), Repair(self.candidate, 1)]
        ):
            result = p.repair(self.candidate, ("CREW",), random.Random(1), 2, perf_counter() + 30)
        self.assertIs(result.candidate, self.candidate)
        self.assertEqual(result.trials, 2)
        self.assertIn("REPAIR_REJECTED:ValueError:local failure", result.reasons)

    def test_failed_repair_keeps_incumbent_and_consumes_each_trial(self):
        p = self.problem
        original = p.rollout
        calls = 0

        def fail_repairs(genes, deadline):
            nonlocal calls
            calls += 1
            if calls == 1:
                return original(genes, deadline)
            raise ValueError("forced local failure")

        # Use a fresh counter baseline for this search.
        p.search_trials = p.search_iterations = 0
        with patch.object(p, "rollout", side_effect=fail_repairs):
            result = search(p, Options(seed=2, iterations=1, repair_trials=2, wall_seconds=30))
        self.assertEqual(result.status, "FEASIBLE")
        self.assertEqual(result.best, result.initial)
        self.assertEqual(result.history[0].trials, 2)
        self.assertIn("REPAIR_FAILED_KEEP_LEGAL_INCUMBENT", result.history[0].reasons)
        ledger = BudgetLedger(Budget(2, 2, 6, 60, 1, 2, 30, (0, 0.5), 1))
        self.assertTrue(ledger.consume(result, 1, p))
        self.assertEqual((ledger.iterations, ledger.trials), (1, 3))
        self.assertEqual(ledger.allocation().iterations, 1)
        self.assertTrue(
            ledger.consume(None, 1, SimpleNamespace(search_iterations=1, search_trials=3))
        )
        self.assertEqual((ledger.iterations, ledger.trials), (2, 6))
        self.assertIsNone(ledger.allocation())

    def test_unexpected_search_exit_still_charges_started_work(self):
        ledger = BudgetLedger(Budget(2, 2, 4, 60, 1, 1, 30, (0, 0.5), 1))
        ledger.consume(None, 1, SimpleNamespace(search_iterations=1, search_trials=2))
        self.assertEqual((ledger.iterations, ledger.trials), (1, 2))

    def test_nonfinite_slots_and_duplicate_rest_rejected(self):
        for value in (float("inf"), float("nan")):
            bad = replace(
                self.candidate,
                genes=replace(
                    self.candidate.genes,
                    slots=tuple((a, value) for a, _ in self.candidate.genes.slots),
                ),
            )
            self.assertIn("CANDIDATE_GENE_SLOTS", self.problem.verify(bad).reasons)
        bad = replace(self.candidate, genes=replace(self.candidate.genes, rests=("W1", "W1")))
        self.assertIn("CANDIDATE_GENE_REST", self.problem.verify(bad).reasons)


class ExecutedPrefixBindingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = configuration()
        warmup = run(
            ProductionBackend(cls.config),
            Scenario(until_h=720),
            warmup_only=True,
            stop_condition=lambda w: any(
                p.id == "PRODUCT-1.BOTTOM" and p.location == "J2" for p in w.s.positions
            ),
        )
        assert warmup.manifest["termination"] == "DECLARED_CHECKPOINT"
        assert warmup.audit.status == warmup.decision_audit.status == "PASS"
        cls.prefix = warmup.snapshot
        cls.rows = tuple(record(d) for d in warmup.decisions)
        w = ProductionBackend(cls.config, run_id=cls.prefix.run_id)
        w.s, w.events = cls.prefix.state, list(cls.prefix.events)
        cls.observation = w.observe()
        cls.problem = SimulationJointProblem(
            cls.config,
            cls.observation,
            cls.prefix,
            decisions=cls.rows,
            end_h=cls.prefix.state.time_h + 2,
            fixed_mode="H",
        )
        result = cls.problem.initial(perf_counter() + 120)
        assert result.candidate is not None, result.reasons
        cls.candidate = result.candidate
        assert any(c.branch and c.roles for s in cls.candidate.steps for c in s.plan.commands)

    def test_original_candidate_passes(self):
        checked = self.problem.verify(self.candidate)
        self.assertTrue(checked.valid, checked.reasons)

    def test_slots_cannot_claim_later_than_actual_core_commands(self):
        bad = replace(
            self.candidate,
            genes=replace(
                self.candidate.genes,
                slots=tuple((a, self.candidate.end_h + 100) for a, _ in self.candidate.genes.slots),
            ),
        )
        checked = self.problem.verify(bad)
        self.assertFalse(checked.valid)
        self.assertTrue(any("METADATA" in x for x in checked.reasons), checked.reasons)

    def test_eligible_but_different_declared_welder_rejected(self):
        bad = replace(
            self.candidate,
            genes=replace(
                self.candidate.genes,
                crews=tuple(
                    (a, "W2" if a in self.problem.scope else who)
                    for a, who in self.candidate.genes.crews
                ),
            ),
        )
        checked = self.problem.verify(bad)
        self.assertFalse(checked.valid)
        self.assertTrue(any("METADATA" in x for x in checked.reasons), checked.reasons)

    def test_rest_request_must_match_dispatch_decisions(self):
        bad = replace(self.candidate, genes=replace(self.candidate.genes, rests=("W2",)))
        self.assertIn("CANDIDATE_DISPATCH_METADATA", self.problem.verify(bad).reasons)

    def test_order_is_priority_and_equivalent_ranking_is_allowed(self):
        # Positive scaling preserves priorities, including the implicit zero for logistics.
        same = replace(
            self.candidate,
            genes=replace(
                self.candidate.genes,
                order=tuple((a, v * 2) for a, v in self.candidate.genes.order),
            ),
        )
        checked = self.problem.verify(same)
        self.assertTrue(checked.valid, checked.reasons)

    def test_multiple_commands_cannot_hide_unexecuted_tail(self):
        idx = next(i for i, s in enumerate(self.candidate.steps) if s.plan.commands)
        step = self.candidate.steps[idx]
        changed = replace(step, plan=replace(step.plan, commands=step.plan.commands * 2))
        bad = replace(
            self.candidate,
            steps=(*self.candidate.steps[:idx], changed, *self.candidate.steps[idx + 1 :]),
        )
        self.assertIn("SCHEDULE_COMMAND_COUNT", self.problem.verify(bad).reasons)

    @classmethod
    def stopped_problem(cls):
        if hasattr(cls, "_stopped_problem"):
            return cls._stopped_problem
        world = cls.problem.world()
        rows = list(cls.problem.decisions)
        for step in cls.candidate.steps:
            obs = world.observe()
            receipt = world.dispatch(step.plan.commands[0]) if step.plan.commands else None
            rows.append(
                record(
                    SimpleNamespace(
                        observation=obs,
                        plan=step.plan,
                        rejected_parents=(),
                        receipt_id=receipt.id if receipt else None,
                    )
                )
            )
            if step.advance_to_h is not None:
                world.advance(step.advance_to_h)
            if any(
                a.completed_units
                and a.state == "COMMITTED"
                and not any(r.command.activity_id == a.activity_id for r in world.s.running)
                for a in world.s.mode_attempts
            ):
                rows.append(record(terminal(cls.config, world.observe())))
                cls._stopped_problem = SimulationJointProblem(
                    cls.config,
                    world.observe(),
                    world.snapshot(),
                    decisions=rows,
                    end_h=world.s.time_h + 2,
                    fixed_mode="H",
                )
                return cls._stopped_problem
        raise AssertionError("No actual legal model stop reached")

    def test_legal_handover_matches_declared_incoming_welder(self):
        p = self.stopped_problem()
        genes = p.genes()
        aid = next(
            a.activity_id for a in p.observation.state.mode_attempts if a.state == "COMMITTED"
        )
        genes = replace(
            genes, crews=tuple((a, "W2" if a == aid else who) for a, who in genes.crews)
        )
        result = p.rollout(genes, perf_counter() + 120)
        self.assertIsNotNone(result.candidate, result.reasons)
        changes = [
            cmd.service.operation.handover
            for step in result.candidate.steps
            for cmd in step.plan.commands
            if cmd.service and cmd.service.operation.handover
        ]
        self.assertEqual([x.phase for x in changes], ["HANDOVER", "RESTORE"])
        checked = p.verify(result.candidate)
        self.assertTrue(checked.valid, checked.reasons)
        bad = replace(
            result.candidate,
            genes=replace(
                genes, crews=tuple((a, "W1" if a == aid else who) for a, who in genes.crews)
            ),
        )
        self.assertFalse(p.verify(bad).valid)

    def test_committed_mode_cannot_change_even_if_no_new_weld(self):
        p = self.stopped_problem()
        result = p.initial(perf_counter() + 120)
        self.assertIsNotNone(result.candidate, result.reasons)
        aid = p.observation.state.mode_attempts[0].activity_id
        bad = replace(
            result.candidate,
            genes=replace(
                result.candidate.genes,
                modes=tuple(
                    (a, "HR-seq" if a == aid else m) for a, m in result.candidate.genes.modes
                ),
                crews=tuple(
                    (a, "OP1" if a == aid else who) for a, who in result.candidate.genes.crews
                ),
            ),
        )
        self.assertIn("CANDIDATE_COMMITTED_MODE", p.verify(bad).reasons)

    def test_order_change_that_changes_dispatch_is_rejected(self):
        bad = replace(
            self.candidate,
            genes=replace(
                self.candidate.genes,
                order=tuple(
                    (a, 1000 if a in self.problem.scope else v)
                    for a, v in self.candidate.genes.order
                ),
            ),
        )
        self.assertIn("CANDIDATE_DISPATCH_METADATA", self.problem.verify(bad).reasons)
