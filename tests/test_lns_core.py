"""S17 constrained neighborhoods, budget/fallback and production commitment tests."""

import sys
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from adaptive_hrc_scheduling.algorithms.lns import Options, Repair, Verification, search
from adaptive_hrc_scheduling.algorithms.production_lns import ProductionProblem
from adaptive_hrc_scheduling.algorithms.static_lns import StaticProblem
from adaptive_hrc_scheduling.contracts.codec import ContractError
from adaptive_hrc_scheduling.control.production_decisions import record
from adaptive_hrc_scheduling.planning.production import planning_input
from adaptive_hrc_scheduling.production_backend import ProductionBackend
from adaptive_hrc_scheduling.reference.baselines import enumerate_independent
from adaptive_hrc_scheduling.reference.cases import buffer_case, tiny_cases
from adaptive_hrc_scheduling.reference.checker import check, check_hours, to_hours
from adaptive_hrc_scheduling.reference.cpsat import solve
from adaptive_hrc_scheduling.reference.domain import Alternative, Entry, Instance, Task

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from build_production_contracts import Builder


def fixed(instance):
    return {t.id: t.alternatives[0].id for t in instance.tasks}


def replay(result):
    return (
        result.termination,
        result.best,
        result.best_score,
        tuple(
            (
                h.removed,
                h.candidate,
                h.score,
                h.accepted,
                h.improved,
                h.reasons,
                h.trials,
                h.repair_termination,
            )
            for h in result.history
        ),
    )


class CoreTests(unittest.TestCase):
    def test_slot_neighborhood_improves_delayed_legal_initial(self):
        inst = tiny_cases()[0]
        initial = (Entry("A", "H", 1, 3), Entry("B", "H", 3, 4))
        result = search(
            StaticProblem(inst, fixed(inst), initial=initial), Options(iterations=4, stagnation=3)
        )
        self.assertEqual(result.initial_score, (4,))
        self.assertEqual(result.best_score, (3,))
        self.assertTrue(check(inst, result.best).valid)
        self.assertTrue(any(h.improved for h in result.history))

    def test_fixed_seed_iteration_budget_replays_all_search_decisions(self):
        inst = tiny_cases()[0]
        options = Options(seed=37, iterations=7, repair_trials=2, stagnation=10, wall_seconds=30)
        a = search(StaticProblem(inst, fixed(inst)), options)
        b = search(StaticProblem(inst, fixed(inst)), options)
        self.assertEqual(replay(a), replay(b))
        self.assertEqual(len(a.history), 7)
        self.assertEqual(a.termination, "ITERATION_BUDGET")

    def test_empty_neighborhood_preserves_all_committed_entries(self):
        inst = tiny_cases()[0]
        initial = (Entry("A", "H", 0, 2), Entry("B", "H", 2, 3))
        result = search(StaticProblem(inst, fixed(inst), initial=initial, committed=initial))
        self.assertEqual(result.best, initial)
        self.assertEqual(result.termination, "EMPTY_NEIGHBORHOOD")

    def test_running_commitment_not_destroyed(self):
        inst = tiny_cases()[0]
        initial = (Entry("A", "H", 0, 2), Entry("B", "H", 3, 4))
        result = search(StaticProblem(inst, fixed(inst), initial=initial, committed=initial[:1]))
        self.assertEqual(result.best[0], initial[0])
        self.assertTrue(all("A" not in h.removed for h in result.history))
        self.assertEqual(result.best_score, (3,))

    def test_single_feasible_schedule_stops_without_inventing_gain(self):
        inst = Instance("ONE", 1, (Task("A", (Alternative("H", 1),)),), ())
        result = search(StaticProblem(inst, fixed(inst)), Options(stagnation=2))
        self.assertEqual(result.termination, "NO_IMPROVEMENT")
        self.assertEqual(result.initial_score, result.best_score)
        self.assertFalse(any(h.improved for h in result.history))

    def test_zero_wall_budget_keeps_supplied_audited_initial(self):
        inst = tiny_cases()[0]
        initial = (Entry("A", "H", 0, 2), Entry("B", "H", 2, 3))
        result = search(StaticProblem(inst, fixed(inst), initial=initial), Options(wall_seconds=0))
        self.assertEqual(result.termination, "WALL_BUDGET")
        self.assertEqual(result.best, initial)
        self.assertEqual(result.history, ())

    def test_zero_iterations_returns_audited_baseline(self):
        inst = tiny_cases()[1]
        result = search(StaticProblem(inst, fixed(inst)), Options(iterations=0))
        self.assertEqual(result.best, result.initial)
        self.assertEqual(result.termination, "ITERATION_BUDGET")

    def test_no_legal_initial_is_wait_not_infeasibility_proof(self):
        inst = Instance("NO", 1, (Task("A", (Alternative("H", 2),)),), ())
        result = search(StaticProblem(inst, fixed(inst)))
        self.assertEqual(result.status, "WAIT")
        self.assertIsNone(result.best)
        self.assertIn("NO_PLAN_FOUND", result.initial_reasons)

    def test_invalid_initial_never_enters_feasible_cache(self):
        inst = tiny_cases()[0]
        bad = (Entry("A", "H", 0, 2), Entry("B", "H", 1, 2))
        result = search(StaticProblem(inst, fixed(inst), initial=bad))
        self.assertIsNone(result.best)
        self.assertTrue(any(r.startswith("CAPACITY") for r in result.initial_reasons))

    def test_fixed_modes_explicit_and_unchanged(self):
        inst = tiny_cases()[2]
        with self.assertRaises(ValueError):
            StaticProblem(inst, {})
        with self.assertRaises(ValueError):
            StaticProblem(inst, {"A": "HR", "B": "H"})
        problem = StaticProblem(inst, {"A": "SLOW", "B": "H"})
        result = search(problem)
        self.assertTrue(
            all(e.alternative_id == problem.fixed_modes[e.task_id] for e in result.best)
        )
        changed = (Entry("A", "FAST", 0, 1), Entry("B", "H", 1, 2))
        self.assertIn("FIXED_MODE_CHANGED", problem.verify(changed).reasons)

    def test_commitment_violation_is_rejected_even_when_physical_schedule_valid(self):
        inst = tiny_cases()[0]
        initial = (Entry("A", "H", 0, 2), Entry("B", "H", 2, 3))
        problem = StaticProblem(inst, fixed(inst), committed=initial[:1])
        alternative = (Entry("A", "H", 1, 3), Entry("B", "H", 0, 1))
        self.assertTrue(check(inst, alternative).valid)
        self.assertIn("COMMITMENT_CHANGED", problem.verify(alternative).reasons)

    def test_tiny_fixed_domain_scores_match_complete_oracle_and_cpsat(self):
        for inst in tiny_cases():
            with self.subTest(case=inst.id):
                problem = StaticProblem(inst, fixed(inst))
                oracle = enumerate_independent(problem.fixed_instance)
                exact = solve(problem.fixed_instance)
                result = search(problem, Options(iterations=8, destroy_size=3, repair_trials=1000))
                optimum = min(check(problem.fixed_instance, s).objective for s in oracle)
                self.assertEqual(exact.objective, optimum)
                self.assertEqual(exact.best_bound, optimum)
                self.assertGreaterEqual(result.best_score[0], optimum)
                self.assertIn(result.best, oracle)
                self.assertTrue(check_hours(inst, to_hours(inst, result.best)).valid)

    def test_buffer_backpressure_not_removed_by_slot_repair(self):
        inst = buffer_case()
        problem = StaticProblem(inst, fixed(inst))
        result = search(problem, Options(iterations=3, destroy_size=2, repair_trials=50))
        self.assertTrue(check(inst, result.best).valid)
        entries = {e.task_id: e for e in result.best}
        self.assertGreaterEqual(entries["STORE3"].start, entries["RECEIVE1"].end)

    def test_malformed_budgets_rejected(self):
        for fields in (
            {"seed": True},
            {"iterations": -1},
            {"repair_trials": 0},
            {"wall_seconds": float("nan")},
            {"destroy_size": 0},
            {"accept_equal": 1},
            {"stagnation": 0},
        ):
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                search(None, Options(**fields))


class Toy:
    def __init__(self, repaired, *, valid=True):
        self.repaired, self.valid = repaired, valid

    def initial(self, deadline):
        return Repair(2)

    def mutable(self, candidate):
        return ("slot",)

    def repair(self, candidate, removed, rng, trials, deadline):
        return self.repaired

    def verify(self, candidate):
        return Verification(
            self.valid or candidate == 2,
            (candidate,),
            ("INVALID",) if not self.valid and candidate != 2 else (),
        )


class CacheTests(unittest.TestCase):
    def test_late_better_candidate_discarded_and_valid_fallback_retained(self):
        elapsed = [0.0]

        class Slow(Toy):
            def repair(self, candidate, removed, rng, trials, deadline):
                elapsed[0] = 2.0
                return Repair(0, 1, (), "WALL_BUDGET")

        with patch(
            "adaptive_hrc_scheduling.algorithms.lns.perf_counter", side_effect=lambda: elapsed[0]
        ):
            result = search(Slow(Repair(0)), Options(wall_seconds=1))
        self.assertEqual(result.best, 2)
        self.assertEqual(result.termination, "WALL_BUDGET")
        self.assertIn("WALL_BUDGET_CANDIDATE_DISCARDED", result.history[0].reasons)
        self.assertFalse(result.history[0].improved)

    def test_unrepairable_neighborhood_keeps_legal_initial(self):
        result = search(Toy(Repair(None, 4, ("BLOCKED_SUPPLY",))), Options(stagnation=2))
        self.assertEqual(result.best, 2)
        self.assertTrue(
            all("REPAIR_FAILED_KEEP_LEGAL_INCUMBENT" in h.reasons for h in result.history)
        )
        self.assertEqual(result.termination, "NO_IMPROVEMENT")

    def test_illegal_better_score_never_cached(self):
        result = search(Toy(Repair(0), valid=False), Options(stagnation=1))
        self.assertEqual(result.best, 2)
        self.assertFalse(result.history[0].accepted)
        self.assertIn("INVALID", result.history[0].reasons)

    def test_worse_candidate_recorded_and_rejected(self):
        result = search(Toy(Repair(3)), Options(stagnation=1))
        self.assertEqual(result.best, 2)
        self.assertIn("WORSE_OR_EQUAL_REJECTED", result.history[0].reasons)

    def test_equal_acceptance_does_not_claim_improvement(self):
        yes = search(Toy(Repair(2)), Options(stagnation=1))
        no = search(Toy(Repair(2)), Options(stagnation=1, accept_equal=False))
        self.assertTrue(yes.history[0].accepted)
        self.assertFalse(yes.history[0].improved)
        self.assertFalse(no.history[0].accepted)

    def test_nan_objective_cannot_enter_cache(self):
        result = search(Toy(Repair(float("nan"))), Options(stagnation=1))
        self.assertEqual(result.best, 2)
        self.assertIn("INVALID_OBJECTIVE", result.history[0].reasons)


class ProductionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = Builder().configuration()

    def problem(self, world=None, decisions=()):
        world = world or ProductionBackend(self.config)
        obs = world.observe()
        world.deliver()
        return ProductionProblem(
            self.config,
            planning_input(self.config, obs, 10000),
            world.snapshot(),
            decisions=decisions,
        ), world

    def test_current_window_initial_and_fallback_are_s10_and_causally_checked(self):
        problem, world = self.problem()
        before = world.snapshot()
        result = search(problem, Options(iterations=1, repair_trials=2, wall_seconds=30))
        self.assertEqual(result.status, "FEASIBLE")
        self.assertTrue(problem.verify(result.best).valid)
        self.assertEqual(world.snapshot(), before)

    def test_zero_budget_returns_valid_production_baseline(self):
        problem, _ = self.problem()
        result = search(problem, Options(wall_seconds=0))
        self.assertEqual(result.termination, "WALL_BUDGET")
        self.assertTrue(problem.verify(result.best).valid)

    def test_future_or_stale_observation_rejected(self):
        world = ProductionBackend(self.config)
        obs = world.observe()
        for changed in (
            replace(obs, received_h=1),
            replace(obs, event_ids=("FUTURE",)),
            replace(obs, state=replace(obs.state, revision=1)),
        ):
            with self.subTest(obs=changed.id), self.assertRaises(ContractError):
                ProductionProblem(
                    self.config, planning_input(self.config, changed), world.snapshot()
                )

    def test_unobserved_material_cannot_be_started_or_teleported(self):
        problem, _ = self.problem()
        obs = problem.value.observation
        transfer = next(o for o in self.config.operations if o.action == "TRANSFER")
        from adaptive_hrc_scheduling.contracts.production import mode_for
        from adaptive_hrc_scheduling.domain import production as m

        cmd = m.DispatchCommand(
            "S15-PROD-1.0",
            self.config.id,
            obs.config_sha256,
            obs.run_id,
            obs.epoch,
            "ILLEGAL",
            transfer.product_id,
            transfer.activity_id,
            transfer.id,
            transfer.attempt_index,
            transfer.unit_index,
            mode_for(transfer),
            0,
            0,
            tuple(m.RoleBinding(r.id, r.id) for r in transfer.roles),
        )
        plan = m.Plan("S15-PROD-1.0", self.config.id, obs.id, (cmd,), "CANDIDATE", "TEST")
        checked = problem.verify(plan)
        self.assertFalse(checked.valid)
        self.assertTrue(checked.reasons)

    def test_wrong_mode_or_revision_rejected_before_cache(self):
        problem, _ = self.problem()
        plan = problem.initial(float("inf")).candidate
        self.assertTrue(plan.commands)
        for cmd in (
            replace(plan.commands[0], mode_id="HR"),
            replace(plan.commands[0], expected_revision=999),
        ):
            with self.subTest(cmd=cmd.id):
                self.assertFalse(problem.verify(replace(plan, commands=(cmd,))).valid)

    def test_running_transport_and_reservations_preserved_by_preview(self):
        problem, world = self.problem()
        plan = problem.initial(float("inf")).candidate
        obs = problem.value.observation
        receipt = world.dispatch(plan.commands[0])
        self.assertEqual(receipt.kind, "STARTED")
        decision = record(
            SimpleNamespace(observation=obs, plan=plan, rejected_parents=(), receipt_id=receipt.id)
        )
        newer, world = self.problem(world, (decision,))
        before = world.snapshot()
        result = search(newer, Options(iterations=1, repair_trials=1, wall_seconds=30))
        self.assertTrue(newer.verify(result.best).valid)
        self.assertEqual(world.snapshot(), before)
        self.assertEqual(world.s.running, before.state.running)
        self.assertEqual(world.s.owners, before.state.owners)
        self.assertEqual(world.s.reservations, before.state.reservations)

    def test_missing_decision_history_rejected(self):
        problem, world = self.problem()
        world.dispatch(problem.initial(float("inf")).candidate.commands[0])
        with self.assertRaisesRegex(ContractError, "INVALID_DECISION_PREFIX"):
            self.problem(world)

    def test_fabricated_stock_or_person_position_cannot_become_initial(self):
        world = ProductionBackend(self.config)
        for state in (
            replace(world.s, lots=(replace(world.s.lots[0], available=99),) + world.s.lots[1:]),
            replace(
                world.s,
                positions=tuple(
                    replace(p, location="FG1", support="FG1") if p.id == "P1" else p
                    for p in world.s.positions
                ),
            ),
        ):
            with self.subTest(state=state.revision):
                world.s = state
                obs = world.observe()
                with self.assertRaisesRegex(ContractError, "INVALID_S10_PREFIX"):
                    ProductionProblem(
                        self.config, planning_input(self.config, obs), world.snapshot()
                    )

    def test_current_wait_is_audited_and_does_not_forecast_arrival_or_receipt(self):
        from adaptive_hrc_scheduling.domain import production as m

        problem, _ = self.problem()
        obs = problem.value.observation
        wait = m.Plan(
            "S15-PROD-1.0",
            self.config.id,
            obs.id,
            (),
            "WAIT",
            "MATERIAL_NOT_DELIVERED;RECEIVE_PERMIT_MISSING",
        )
        self.assertTrue(problem.verify(wait).valid)
        self.assertEqual(problem.mutable(wait), ())
        with patch.object(problem, "initial", return_value=Repair(wait)):
            result = search(problem)
        self.assertEqual(result.termination, "EMPTY_NEIGHBORHOOD")
        self.assertEqual(result.best, wait)
        self.assertFalse(any(lot.arrived for lot in obs.state.lots))
        self.assertEqual(obs.state.receive_permits, ())


if __name__ == "__main__":
    unittest.main()
