"""S17 F1/F2/C1 regressions: real commitments, rejection provenance and safe cache."""

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

from adaptive_hrc_scheduling.algorithms.lns import Options, Repair, Verification, search
from adaptive_hrc_scheduling.algorithms.production_lns import ProductionProblem, parent
from adaptive_hrc_scheduling.algorithms.static_lns import StaticProblem
from adaptive_hrc_scheduling.contracts.codec import ContractError
from adaptive_hrc_scheduling.control.production_decisions import check_decisions, record
from adaptive_hrc_scheduling.planning.production import choose, planning_input
from adaptive_hrc_scheduling.production_backend import ProductionBackend
from adaptive_hrc_scheduling.production_checker import check_run
from adaptive_hrc_scheduling.reference.baselines import enumerate_independent
from adaptive_hrc_scheduling.reference.cases import buffer_case, tiny_cases
from adaptive_hrc_scheduling.reference.checker import check
from adaptive_hrc_scheduling.reference.domain import Alternative, Entry, Instance, Resource, Task

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from build_production_contracts import Builder


def fixed(instance):
    return {t.id: t.alternatives[0].id for t in instance.tasks}


class CommittedInitialTests(unittest.TestCase):
    def test_audit_counterexample_generates_legal_committed_completion(self):
        instance = tiny_cases()[0]
        lock = Entry("A", "H", 1, 3)
        result = search(
            StaticProblem(instance, fixed(instance), committed=(lock,)),
            Options(iterations=0, wall_seconds=30),
        )
        self.assertEqual(result.status, "FEASIBLE")
        self.assertEqual(result.best[0], lock)
        self.assertTrue(check(instance, result.best).valid)

    def test_future_committed_resource_slot_is_reserved_during_completion(self):
        instance = Instance(
            "FUTURE_LOCK",
            5,
            (
                Task("A", (Alternative("H", 3, (("M", 1),)),)),
                Task("C", (Alternative("H", 1, (("M", 1),)),)),
            ),
            (Resource("M"),),
        )
        lock = Entry("C", "H", 1, 2)
        result = search(
            StaticProblem(instance, fixed(instance), committed=(lock,)), Options(iterations=0)
        )
        self.assertEqual(result.status, "FEASIBLE")
        self.assertEqual(result.best, (Entry("A", "H", 2, 5), lock))
        self.assertTrue(check(instance, result.best).valid)

    def test_committed_descendant_can_wait_for_unassigned_ancestors(self):
        instance = Instance(
            "DESCENDANT",
            5,
            (
                Task("A", (Alternative("H", 1, (("M", 1),)),)),
                Task("B", (Alternative("H", 1, (("M", 1),)),), ("A",)),
                Task("C", (Alternative("H", 1, (("M", 1),)),), ("B",)),
            ),
            (Resource("M"),),
        )
        lock = Entry("C", "H", 4, 5)
        result = search(
            StaticProblem(instance, fixed(instance), committed=(lock,)), Options(iterations=0)
        )
        self.assertEqual(result.status, "FEASIBLE")
        self.assertEqual(result.best[-1], lock)
        self.assertTrue(check(instance, result.best).valid)

    def test_commitment_completion_keeps_buffer_residency_and_backpressure(self):
        instance = buffer_case()
        lock = Entry("READY1", "H", 0, 1)
        result = search(
            StaticProblem(instance, fixed(instance), committed=(lock,)),
            Options(iterations=0, wall_seconds=30),
        )
        self.assertEqual(result.status, "FEASIBLE")
        self.assertTrue(check(instance, result.best).valid)
        entries = {e.task_id: e for e in result.best}
        self.assertEqual(entries["READY1"], lock)
        self.assertGreaterEqual(entries["STORE3"].start, entries["RECEIVE1"].end)

    def test_inconsistent_locked_entries_are_diagnosed_before_search(self):
        instance = tiny_cases()[0]
        locks = (Entry("A", "H", 0, 2), Entry("B", "H", 1, 2))
        result = search(StaticProblem(instance, fixed(instance), committed=locks))
        self.assertEqual(result.status, "WAIT")
        self.assertIsNone(result.best)
        self.assertIn("INVALID_COMMITMENT", result.initial_reasons)

    def test_bad_commit_mode_duration_or_time_is_rejected(self):
        instance = tiny_cases()[0]
        for lock in (Entry("A", "UNKNOWN", 0, 2), Entry("A", "H", 0, 1), Entry("A", "H", True, 3)):
            with self.subTest(lock=lock):
                result = search(StaticProblem(instance, fixed(instance), committed=(lock,)))
                self.assertEqual(result.status, "WAIT")
                self.assertIn("INVALID_COMMITMENT", result.initial_reasons)

    def test_valid_lock_with_no_legal_completion_is_search_failure(self):
        instance = Instance(
            "NO_COMPLETION",
            4,
            (
                Task("A", (Alternative("H", 2, (("M", 1),)),)),
                Task("C", (Alternative("H", 3, (("M", 1),)),)),
            ),
            (Resource("M"),),
        )
        lock = Entry("C", "H", 1, 4)
        self.assertFalse(any(lock in s for s in enumerate_independent(instance)))
        result = search(StaticProblem(instance, fixed(instance), committed=(lock,)))
        self.assertEqual(result.status, "WAIT")
        self.assertIn("NO_PLAN_FOUND", result.initial_reasons)

    def test_initial_trial_budget_exhaustion_is_explicit(self):
        instance = Instance(
            "TRIAL_LIMIT",
            5,
            (
                Task("A", (Alternative("H", 3, (("M", 1),)),)),
                Task("C", (Alternative("H", 1, (("M", 1),)),)),
            ),
            (Resource("M"),),
        )
        result = search(
            StaticProblem(
                instance, fixed(instance), committed=(Entry("C", "H", 1, 2),), initial_trials=1
            )
        )
        self.assertEqual(result.status, "WAIT")
        self.assertIn("INITIAL_TRIAL_BUDGET", result.initial_reasons)
        self.assertNotIn("INFEASIBLE", result.initial_reasons)

    def test_zero_budget_waits_for_incomplete_locks_but_keeps_complete_locks(self):
        instance = tiny_cases()[0]
        complete = (Entry("A", "H", 1, 3), Entry("B", "H", 0, 1))
        incomplete = search(
            StaticProblem(instance, fixed(instance), committed=complete[:1]),
            Options(wall_seconds=0),
        )
        self.assertEqual(incomplete.status, "WAIT")
        self.assertIn("WALL_BUDGET", incomplete.initial_reasons)
        frozen = search(
            StaticProblem(instance, fixed(instance), committed=complete), Options(wall_seconds=0)
        )
        self.assertEqual(frozen.status, "FEASIBLE")
        self.assertEqual(frozen.best, complete)

    def test_committed_initial_replays_with_fixed_budgets(self):
        instance = tiny_cases()[0]
        lock = Entry("A", "H", 1, 3)
        options = Options(seed=17, iterations=3, wall_seconds=30)
        a = search(StaticProblem(instance, fixed(instance), committed=(lock,)), options)
        b = search(StaticProblem(instance, fixed(instance), committed=(lock,)), options)
        self.assertEqual(a.best, b.best)
        self.assertEqual(
            [(h.removed, h.candidate, h.score, h.reasons, h.trials) for h in a.history],
            [(h.removed, h.candidate, h.score, h.reasons, h.trials) for h in b.history],
        )

    def test_initial_trial_budget_shape_is_validated(self):
        instance = tiny_cases()[0]
        for budget in (0, -1, True, 1.5):
            with self.subTest(budget=budget), self.assertRaises(ValueError):
                StaticProblem(instance, fixed(instance), initial_trials=budget)


class RejectedInitialTests(unittest.TestCase):
    def fixture(self, products=1):
        config = Builder(products=products).configuration()
        world = ProductionBackend(config)
        obs = world.observe()
        world.deliver()
        plan = choose(config, planning_input(config, obs, 10000))
        self.assertTrue(plan.reason.startswith("PREPARE:"))

        def blocked(command):
            raise ContractError("PATH_BLOCKED")

        receipt = world.dispatch(plan.commands[0], preflight=blocked)
        self.assertEqual(receipt.kind, "DEFERRED")
        past = record(
            SimpleNamespace(observation=obs, plan=plan, rejected_parents=(), receipt_id=receipt.id)
        )
        newer = world.observe()
        world.deliver()
        rejected = (parent(plan),)
        problem = ProductionProblem(
            config,
            planning_input(config, newer, 10000),
            world.snapshot(),
            decisions=(past,),
            sequence=1,
            rejected=rejected,
        )
        return problem, world, past, newer, rejected

    def test_single_product_observed_rejection_returns_audited_wait(self):
        problem, world, *_ = self.fixture()
        before = world.snapshot()
        result = search(problem, Options(iterations=0, wall_seconds=30))
        self.assertEqual(result.status, "FEASIBLE")
        self.assertEqual(result.best.status, "WAIT")
        self.assertTrue(problem.verify(result.best).valid)
        self.assertEqual(world.snapshot(), before)

    def test_two_product_observed_rejection_chooses_and_starts_alternative(self):
        problem, world, past, obs, rejected = self.fixture(2)
        result = search(problem, Options(iterations=1, repair_trials=1, wall_seconds=30))
        self.assertEqual(result.status, "FEASIBLE")
        self.assertTrue(result.best.commands)
        self.assertEqual(result.best.commands[0].product_id, "PRODUCT-2")
        self.assertNotIn(parent(result.best), rejected)
        receipt = world.dispatch(result.best.commands[0])
        self.assertEqual(receipt.kind, "STARTED")
        final = world.observe()
        world.deliver()
        actual = record(
            SimpleNamespace(
                observation=obs, plan=result.best, rejected_parents=rejected, receipt_id=receipt.id
            )
        )
        self.assertEqual(check_run(problem.config, world.snapshot()).status, "PASS")
        self.assertEqual(
            check_decisions(
                problem.config,
                world.snapshot(),
                (past, actual, record(ProductionProblem._terminal(final))),
            ).status,
            "PASS",
        )

    def test_zero_search_budget_keeps_filtered_legal_alternative(self):
        problem, world, *_ = self.fixture(2)
        before = world.snapshot()
        result = search(problem, Options(wall_seconds=0))
        self.assertEqual(result.status, "FEASIBLE")
        self.assertEqual(result.termination, "WALL_BUDGET")
        self.assertEqual(result.best.commands[0].product_id, "PRODUCT-2")
        self.assertTrue(problem.verify(result.best).valid)
        self.assertEqual(world.snapshot(), before)

    def test_fabricated_rejection_provenance_never_enters_legal_cache(self):
        problem, world, past, obs, _ = self.fixture(2)
        forged = ProductionProblem(
            problem.config,
            problem.value,
            world.snapshot(),
            decisions=(past,),
            sequence=1,
            rejected=("PRODUCT-2.KIT.U1",),
        )
        result = search(forged, Options(iterations=0))
        self.assertEqual(result.status, "WAIT")
        self.assertIsNone(result.best)
        self.assertTrue(any("UNOBSERVED_REJECTION_FILTER" in r for r in result.initial_reasons))


class DimensionTests(unittest.TestCase):
    class Problem:
        def __init__(self, changed=True):
            self.changed = changed

        def initial(self, deadline):
            return Repair(2)

        def mutable(self, candidate):
            return ("NEXT",)

        def repair(self, candidate, removed, rng, trials, deadline):
            return Repair(1)

        def verify(self, candidate):
            return Verification(True, (2,) if candidate == 2 else (1, 1) if self.changed else (1,))

    def test_dimension_change_rejects_candidate_and_returns_legal_cache(self):
        result = search(self.Problem(), Options(iterations=1))
        self.assertEqual(result.best, 2)
        self.assertFalse(result.history[0].accepted)
        self.assertIn("OBJECTIVE_DIMENSION_CHANGED", result.history[0].reasons)

    def test_same_dimension_improvement_still_accepted(self):
        result = search(self.Problem(changed=False), Options(iterations=1))
        self.assertEqual(result.best, 1)
        self.assertTrue(result.history[0].improved)

    def test_final_cache_dimension_drift_fails_closed(self):
        class Drifting(self.Problem):
            def __init__(self):
                self.calls = 0

            def verify(self, candidate):
                self.calls += 1
                return Verification(True, (2,) if self.calls == 1 else (2, 2))

        with self.assertRaisesRegex(RuntimeError, "final independent verification"):
            search(Drifting(), Options(iterations=0))


if __name__ == "__main__":
    unittest.main()
