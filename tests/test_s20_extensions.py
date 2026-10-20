"""S20 objective/tail hand checks and independent observation/shield audits."""

import copy
import json
import math
import sys
import unittest
from dataclasses import replace
from pathlib import Path
from time import perf_counter
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from build_simulation_production import configuration  # noqa: E402
from s20_design import keyed_uniform  # noqa: E402

from adaptive_hrc_scheduling.algorithms.lns import fingerprint  # noqa: E402
from adaptive_hrc_scheduling.algorithms.simulation_joint import (  # noqa: E402
    SimulationJointProblem,
    terminal,
)
from adaptive_hrc_scheduling.contracts.codec import ContractError, as_data  # noqa: E402
from adaptive_hrc_scheduling.control.production_decisions import record  # noqa: E402
from adaptive_hrc_scheduling.control.production_loop import Scenario, run  # noqa: E402
from adaptive_hrc_scheduling.control.research_projection import (  # noqa: E402
    ObservationSettings,
    ProjectedPolicy,
    audit_projection_history,
    audit_saved_projection,
    check_frame,
    export_projection,
    uniform,
)
from adaptive_hrc_scheduling.control.simulation_joint_policy import Budget  # noqa: E402
from adaptive_hrc_scheduling.domain import production as m  # noqa: E402
from adaptive_hrc_scheduling.planning.production import planning_input  # noqa: E402
from adaptive_hrc_scheduling.production_backend import ProductionBackend  # noqa: E402
from adaptive_hrc_scheduling.production_checker import check_run  # noqa: E402
from adaptive_hrc_scheduling.research_objective import WeightedObjective  # noqa: E402
from adaptive_hrc_scheduling.research_tail import (  # noqa: E402
    check_common_horizon,
    common_horizon,
    rest_tail,
)


def allowance():
    return Budget(2, 2, 4, 60, 1, 1, 30, (0, 0.5), 1)


class ObjectiveAndTailTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = configuration()

    def test_weighted_formula_and_extremes(self):
        c = self.config
        n = len(c.core_activities)
        exposure = len(c.people) * c.cap * 720 / 4
        self.assertAlmostEqual(
            WeightedObjective(0.5).score(c, n // 2, exposure, 2, "0" * 64)[0],
            0.5 * (1 - (n // 2) / n) + 0.125,
        )
        self.assertEqual(WeightedObjective(0).score(c, 0, exposure, 2, "0" * 64)[0], 0.25)
        self.assertEqual(WeightedObjective(1).score(c, n, exposure, 2, "0" * 64)[0], 0)

    def test_equal_score_uses_full_stable_fingerprint(self):
        a = WeightedObjective(0.5).score(self.config, 0, 1, 1, "0" * 64)
        b = WeightedObjective(0.5).score(self.config, 0, 1, 1, "f" * 64)
        self.assertLess(a, b)
        self.assertEqual(b[-1], int("f" * 64, 16))

    def test_invalid_objective_and_measurement(self):
        for w in (True, -1, 1.1, math.nan, math.inf):
            with self.assertRaises(ContractError):
                WeightedObjective(w).validate()
        for horizon in (0, -1, True, math.inf):
            with self.assertRaises(ContractError):
                WeightedObjective(0.5, horizon).validate()
        with self.assertRaisesRegex(ContractError, "D_EXPOSURE"):
            WeightedObjective(0.5).score(self.config, 0, -1, 0, "0" * 64)

    def test_real_problem_legacy_and_weighted_verification(self):
        c = self.config
        w = ProductionBackend(c)
        legacy = SimulationJointProblem(c, w.observe(), w.snapshot(), end_h=0.5)
        schedule = legacy.initial(perf_counter() + 30).candidate
        self.assertIsNotNone(schedule)
        score = legacy.verify(schedule)
        self.assertTrue(score.valid)
        weighted = SimulationJointProblem(
            c, w.observe(), w.snapshot(), end_h=0.5, objective=WeightedObjective(0.5)
        )
        result = weighted.verify(schedule)
        self.assertTrue(result.valid)
        self.assertEqual(
            result.score,
            WeightedObjective(0.5).score(
                c, -score.score[0], score.score[1], score.score[2], fingerprint(schedule)
            ),
        )

    def test_rest_crosses_shift_and_preserves_old_exposure(self):
        c = self.config
        humans = tuple(replace(h, exposure=2) for h in ProductionBackend(c).s.humans)
        result, rows = rest_tail(c, humans, 3.5, 5)
        self.assertTrue(all(abs(h.exposure - 2.1) < 1e-12 and h.fatigue == 0 for h in result))
        self.assertEqual(len(rows), 45)
        self.assertTrue(all(r["activity"] == "REST" for r in rows))
        self.assertEqual(tuple(h.peak for h in result), tuple(h.peak for h in humans))

    def test_off_shift_and_zero_tail(self):
        c = self.config
        humans = ProductionBackend(c).s.humans
        result, rows = rest_tail(c, humans, 9, 10)
        self.assertTrue(all(r["activity"] == "OFF_SHIFT" for r in rows))
        self.assertTrue(all(abs(h.exposure - 0.1) < 1e-12 for h in result))
        self.assertEqual(rest_tail(c, humans, 9, 9), (humans, ()))

    def test_incomplete_source_not_extended_and_tamper_rejected(self):
        c = self.config
        w = ProductionBackend(c)
        rows = (record(terminal(c, w.observe())),)
        ledger = common_horizon(c, w.snapshot(), rows, 1)
        self.assertEqual(ledger["status"], "INCOMPLETE_SOURCE_NO_TAIL")
        self.assertEqual(check_common_horizon(c, w.snapshot(), rows, ledger), "PASS")
        ledger["common_humans"] = as_data(w.s.humans)
        self.assertEqual(check_common_horizon(c, w.snapshot(), rows, ledger), "INVALID")

    def test_exact_end_source_and_wrong_source_or_causal_rejected(self):
        c = self.config
        w = ProductionBackend(c)
        rows = (record(terminal(c, w.observe())),)
        ledger = common_horizon(c, w.snapshot(), rows, 0)
        self.assertEqual(ledger["intervals"], [])
        self.assertEqual(check_common_horizon(c, w.snapshot(), rows, ledger), "PASS")
        ledger["source_sha256"] = "0" * 64
        self.assertEqual(check_common_horizon(c, w.snapshot(), rows, ledger), "INVALID")
        with self.assertRaisesRegex(ContractError, "TAIL_INVALID_CAUSAL"):
            common_horizon(c, w.snapshot(), (), 1)


class ObservationProjectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = configuration()
        cls.results = {}
        settings = ObservationSettings(delay_h=0.25, fatigue_noise=0.02)
        for method in ("ADAPTIVE_JOINT", "FIXED_H", "FIXED_HR", "NO_OBSERVATION_UPDATE"):
            policy = ProjectedPolicy(
                cls.config, allowance(), end_h=1, settings=settings, method=method
            )
            result = run(ProductionBackend(cls.config), Scenario(until_h=1), joint_policy=policy)
            cls.results[method] = policy, result, tuple(record(d) for d in result.decisions)

    def test_four_methods_real_and_model_audits(self):
        for policy, result, rows in self.results.values():
            with self.subTest(method=policy.method):
                self.assertEqual(
                    (result.audit.status, result.decision_audit.status), ("PASS", "PASS")
                )
                self.assertEqual(
                    audit_projection_history(self.config, result.snapshot, rows, policy)["status"],
                    "PASS",
                )
                self.assertEqual(policy.budget.calls, 2)
                self.assertGreater(len(policy.candidates), 0)
                self.assertTrue(all(r["within_budget"] for r in policy.budget.records))

    def test_keyed_stream_matches_candidate_and_ignores_call_order(self):
        self.assertEqual(
            uniform("B-TEST-00", "noise", "W1", 5), keyed_uniform("B-TEST-00", "noise", "W1", 5)
        )
        a = uniform("B-DEV", "missing", "snapshot", 6)
        uniform("B-DEV", "noise", "W2", 999)
        self.assertEqual(a, uniform("B-DEV", "missing", "snapshot", 6))
        self.assertNotEqual(a, uniform("B-DEV", "noise", "snapshot", 6))

    def test_future_delivery_wrong_run_and_changed_mask_rejected(self):
        policy, _, _ = self.results["ADAPTIVE_JOINT"]
        f = policy.frames[0]
        with self.assertRaisesRegex(ContractError, "FUTURE_OR_UNDELIVERED"):
            check_frame(self.config, f, policy.settings, 0)
        with self.assertRaisesRegex(ContractError, "DROP_MASK"):
            check_frame(self.config, replace(f, dropped=not f.dropped), policy.settings, 1)
        with self.assertRaisesRegex(ContractError, "SAMPLE_CLOCK"):
            check_frame(self.config, replace(f, received_h=0), policy.settings, 1)
        wrong_run = replace(f, snapshot=replace(f.snapshot, run_id="OTHER-RUN"))
        with self.assertRaisesRegex(ContractError, "SOURCE_EXECUTION"):
            check_frame(self.config, wrong_run, policy.settings, 1)

    def test_model_never_certifies_as_actual_and_history_has_no_raw_fatigue(self):
        policy, _, _ = self.results["ADAPTIVE_JOINT"]
        anchor, problem, candidate = policy.candidate_proofs[0]
        nominal, _ = problem.preview(candidate)
        self.assertNotEqual(check_run(self.config, nominal).status, "PASS")
        self.assertTrue(all(not e.state.humans for e in anchor.snapshot.events[:-1]))
        self.assertEqual(
            anchor.audit_candidate(problem, candidate)["scope"],
            "HYPOTHETICAL_SUFFIX_NOT_ACTUAL_EXECUTION",
        )

    def test_no_update_keeps_first_delivered_anchor(self):
        policy, _, _ = self.results["NO_OBSERVATION_UPDATE"]
        ids = {e["frame_id"] for e in policy.trace if e["frame_id"] is not None}
        self.assertEqual(len(ids), 1)
        self.assertGreater(len(policy.frames), 1)

    def test_all_missing_stays_unknown_no_zero_filled_search(self):
        c = self.config
        p = ProjectedPolicy(
            c, allowance(), end_h=1, settings=ObservationSettings(missing_probability=1)
        )
        r = run(ProductionBackend(c), Scenario(until_h=1), joint_policy=p)
        self.assertEqual(p.budget.calls, 0)
        self.assertTrue(all(e["result"] == "WAIT_UNKNOWN" for e in p.trace))
        self.assertEqual(
            audit_projection_history(c, r.snapshot, tuple(record(d) for d in r.decisions), p)[
                "status"
            ],
            "PASS",
        )

    def test_actual_plan_and_candidate_proof_tamper_rejected(self):
        p, r, rows = self.results["ADAPTIVE_JOINT"]
        e = next(e for e in p.trace if "actual_plan" in e)
        old = copy.deepcopy(e)
        try:
            e["actual_plan"]["reason"] = "FORGED"
            with self.assertRaisesRegex(ContractError, "ACTUAL_PLAN_BINDING"):
                audit_projection_history(self.config, r.snapshot, rows, p)
        finally:
            e.clear()
            e.update(old)
        anchor = p.candidate_proofs[0][0]
        old = copy.deepcopy(anchor.proof)
        try:
            anchor.proof["noise"][0]["measured"] = 0.99
            with self.assertRaisesRegex(ContractError, "MODEL_PROOF_MUTATION"):
                audit_projection_history(self.config, r.snapshot, rows, p)
        finally:
            anchor.proof = old

    def test_hidden_current_failure_cannot_change_same_delivered_proposal(self):
        c = self.config
        journals = []
        for failed in (False, True):
            w = ProductionBackend(c)
            p = ProjectedPolicy(c, allowance(), end_h=1, settings=ObservationSettings(delay_h=0.25))
            obs = w.observe()
            plan = p.decide(planning_input(c, obs, 10000), w.snapshot(), (), sequence=0)
            old_row = record(
                SimpleNamespace(observation=obs, plan=plan, rejected_parents=(), receipt_id=None)
            )
            w.advance(0.25)
            if failed:
                w.apply_world(
                    m.WorldEvent(
                        "HIDDEN",
                        w.run_id,
                        w.epoch,
                        0.25,
                        "FAILURE",
                        "R1",
                        "PRODUCT-1",
                        0,
                        "UNKNOWN",
                        "ML-METHOD",
                    )
                )
            p.decide(planning_input(c, w.observe(), 10000), w.snapshot(), (old_row,), sequence=1)
            journals.append(p.inner.journal[0]["schedule_sha256"])
        self.assertIsNotNone(journals[0])
        self.assertEqual(*journals)

    def test_invalid_settings_are_not_accepted(self):
        for settings in (
            ObservationSettings(delay_h=-1),
            ObservationSettings(fatigue_noise=0.1),
            ObservationSettings(missing_probability=math.nan),
            ObservationSettings(period_h=0.1),
        ):
            with self.assertRaises(ContractError):
                settings.validate()

    def test_saved_projection_round_trip_without_search(self):
        p, r, rows = self.results["ADAPTIVE_JOINT"]
        data = json.loads(json.dumps(export_projection(p)))
        result = audit_saved_projection(self.config, r.snapshot, rows, data, expected=p.contract)
        self.assertEqual(result["status"], "PASS")
        data["candidates"][0]["proof"]["noise"][0]["epsilon"] = 0.99
        with self.assertRaisesRegex(ContractError, "SAVED_PROOF"):
            audit_saved_projection(self.config, r.snapshot, rows, data, expected=p.contract)

    def test_missing_decision_or_candidate_proof_rejected(self):
        p, r, rows = self.results["ADAPTIVE_JOINT"]
        entry = p.trace.pop()
        try:
            with self.assertRaisesRegex(ContractError, "MISSING_OR_DUPLICATE_DECISION_PROOF"):
                audit_projection_history(self.config, r.snapshot, rows, p)
        finally:
            p.trace.append(entry)
        proof = p.candidate_proofs.pop()
        try:
            with self.assertRaisesRegex(ContractError, "MISSING_CANDIDATE_PROOF"):
                audit_projection_history(self.config, r.snapshot, rows, p)
        finally:
            p.candidate_proofs.append(proof)


if __name__ == "__main__":
    unittest.main()
