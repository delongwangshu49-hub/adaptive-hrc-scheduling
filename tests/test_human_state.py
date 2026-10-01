"""S07 analytic and S05 witness checks; no simulated production claims."""

import json
import math
import random
import unittest
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

from adaptive_hrc_scheduling.contracts.codec import ContractError, loads
from adaptive_hrc_scheduling.domain.models import Configuration
from adaptive_hrc_scheduling.domain.phases import resolve_process_phase
from adaptive_hrc_scheduling.domain.state import PhaseState, WorkerState
from adaptive_hrc_scheduling.human_state import (
    ActivityInterval,
    FatigueLimitError,
    evaluate_window,
    evolve,
    process_start_allowed,
    protective_rest,
    remaining_duration,
    sample_phase,
    time_to_cap,
)

ROOT = Path(__file__).resolve().parents[1]


class HumanStateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = loads(
            Configuration, (ROOT / "examples/contracts/toy.json").read_text(encoding="utf-8")
        )
        cls.parameters = next(r.worker_parameters for r in cls.config.resources if r.id == "W1")
        cls.witness = json.loads((ROOT / "examples/toy_instance.json").read_text(encoding="utf-8"))[
            "witness"
        ]

    def state(self, f=0.1, exposure=0.0):
        return WorkerState("W1", f, exposure, "wait")

    def phase(self, kind="ASSEMBLE", mode="HR", phase="work"):
        operation = next(o for o in self.config.operations if o.kind == kind)
        return resolve_process_phase(self.config, operation.id, f"mode.{kind}.{mode}", phase)

    def progress(self, phase=None, sample=0.2, remaining=1.0):
        phase = phase or self.phase()
        mode = next(m for m in self.config.modes if m.id == "mode.ASSEMBLE.HR")
        q = next(
            q
            for q in self.config.allocations
            if q.id in mode.allocation_ids and q.worker_id == "W1"
        )
        timing = sample_phase(phase, self.parameters, sample, 0.8)
        return PhaseState(
            "J1.A1",
            "mode.ASSEMBLE.HR",
            q.id,
            "J1.A1.process",
            phase.id,
            1,
            0,
            "paused",
            remaining,
            timing.sampled_f,
            timing.speed_multiplier,
            0,
            None,
        )

    def timelines(self):
        return {
            worker: tuple(
                ActivityInterval(s["start_min"], s["end_min"], s["activity"]) for s in seq
            )
            for worker, seq in self.witness["worker_timeline"].items()
        }

    def test_all_nonrest_activities_and_cumulative_exposure(self):
        for activity, rate in (
            ("work", 0.02),
            ("collaborate", 0.01),
            ("carry", 0.03),
            ("supervise", 0.005),
            ("wait", 0.002),
        ):
            with self.subTest(activity=activity):
                result = evolve(self.state(exposure=4), self.parameters, activity, 2, 0.8)
                self.assertAlmostEqual(result.state.fatigue, 0.1 + 2 * rate)
                self.assertAlmostEqual(result.exposure_increment_min, 0.2 + 2 * rate)
                self.assertAlmostEqual(result.state.exposure_min, 4.2 + 2 * rate)
                self.assertEqual(result.state.activity, activity)
                self.assertEqual(result.peak_f, result.state.fatigue)

    def test_rest_before_at_and_after_zero(self):
        for duration, final, area in ((2, 0.05, 0.15), (4, 0, 0.2), (10, 0, 0.2)):
            with self.subTest(duration=duration):
                result = evolve(self.state(), self.parameters, "rest", duration, 0.8)
                self.assertAlmostEqual(result.state.fatigue, final)
                self.assertAlmostEqual(result.exposure_increment_min, area)
                self.assertEqual(result.peak_f, 0.1)
        self.assertEqual(evolve(self.state(0), self.parameters, "rest", 20, 0.8).state.fatigue, 0)

    def test_zero_duration_is_identity_and_input_immutable(self):
        state = self.state(exposure=9)
        result = evolve(state, self.parameters, "rest", 0, 0.8)
        self.assertEqual(result.state, state)
        self.assertEqual(result.exposure_increment_min, 0)
        with self.assertRaises(FatigueLimitError):
            evolve(state, self.parameters, "carry", 100, 0.8)
        self.assertEqual(state, self.state(exposure=9))

    def test_strict_cap_including_one_float_above(self):
        p = replace(self.parameters, work_per_min=0.125)
        result = evolve(self.state(0.5), p, "work", 2, 0.75)
        self.assertEqual(result.state.fatigue, 0.75)
        with self.assertRaises(FatigueLimitError):
            evolve(self.state(0.5), p, "work", math.nextafter(2.0, math.inf), 0.75)
        for activity in ("rest", "wait"):
            with self.assertRaises(ContractError):
                evolve(self.state(math.nextafter(0.8, math.inf)), p, activity, 1, 0.8)

    def test_invalid_scalars_and_parameters(self):
        for bad in (True, "1", float("nan"), float("inf"), -1, 10**400):
            with self.subTest(bad=repr(bad)):
                with self.assertRaises(ContractError):
                    evolve(self.state(), self.parameters, "work", bad, 0.8)
        for cap in (0, 1, -0.1, True):
            with self.assertRaises(ContractError):
                evolve(self.state(), self.parameters, "work", 1, cap)
        for changes in (
            {"recovery_per_min": 0},
            {"wait_per_min": 0},
            {"work_per_min": -0.1},
            {"speed_kappa": -1},
            {"initial_f": 0.9},
        ):
            with self.assertRaises(ContractError):
                evolve(self.state(), replace(self.parameters, **changes), "work", 1, 0.8)
        with self.assertRaises(ContractError):
            evolve(self.state(), self.parameters, "idle", 1, 0.8)
        with self.assertRaises(ContractError):
            evolve(self.state(exposure=-1), self.parameters, "rest", 1, 0.8)

    def test_overflow_is_not_a_valid_state(self):
        p = replace(self.parameters, work_per_min=0)
        with self.assertRaises(ContractError):
            evolve(self.state(0.7, 1.7e308), p, "work", 1.7e308, 0.8)
        with self.assertRaises(ContractError):
            sample_phase(replace(self.phase(), base_min=1.7e308), p, 0.7, 0.8)

    def test_zero_rate_and_heterogeneous_recovery(self):
        p = replace(self.parameters, work_per_min=0)
        result = evolve(self.state(), p, "work", 10, 0.8)
        self.assertEqual(result.state.fatigue, 0.1)
        self.assertEqual(result.exposure_increment_min, 1)
        p2 = replace(p, recovery_per_min=0.02)
        self.assertAlmostEqual(evolve(self.state(), p2, "rest", 2, 0.8).state.fatigue, 0.06)

    def test_partition_invariance_with_zero_crossing(self):
        for activity in ("work", "rest", "wait"):
            state = self.state(exposure=3)
            whole = evolve(state, self.parameters, activity, 8, 0.8)
            peak = state.fatigue
            for duration in (1, 2, 3, 2):
                part = evolve(state, self.parameters, activity, duration, 0.8)
                state = part.state
                peak = max(peak, part.peak_f)
            self.assertAlmostEqual(state.fatigue, whole.state.fatigue)
            self.assertAlmostEqual(state.exposure_min, whole.state.exposure_min)
            self.assertAlmostEqual(peak, whole.peak_f)

    def test_decimal_analytic_oracle(self):
        rng = random.Random(7)
        for _ in range(100):
            f, rate, duration = (
                Decimal(rng.randrange(1, 30)) / 100,
                Decimal(rng.randrange(1, 10)) / 1000,
                Decimal(rng.randrange(1, 20)) / 2,
            )
            for activity in ("work", "rest"):
                p = replace(self.parameters, work_per_min=float(rate), recovery_per_min=float(rate))
                if activity == "work":
                    end = f + rate * duration
                    area = f * duration + rate * duration**2 / 2
                else:
                    active = min(duration, f / rate)
                    end = max(Decimal(0), f - rate * duration)
                    area = f * active - rate * active**2 / 2
                result = evolve(self.state(float(f)), p, activity, float(duration), 0.8)
                self.assertAlmostEqual(result.state.fatigue, float(end), delta=1e-14)
                self.assertAlmostEqual(result.exposure_increment_min, float(area), delta=1e-14)

    def test_wait_horizon_and_positive_protective_rest(self):
        self.assertAlmostEqual(time_to_cap(0.79, self.parameters, "wait", 0.8), 5)
        self.assertEqual(time_to_cap(0.8, self.parameters, "wait", 0.8), 0)
        self.assertIsNone(time_to_cap(0.2, self.parameters, "rest", 0.8))
        self.assertIsNone(time_to_cap(0.2, replace(self.parameters, work_per_min=0), "work", 0.8))
        state = self.state(0.8, 6)
        result = protective_rest(state, self.parameters, 0.8, 1)
        self.assertAlmostEqual(result.state.fatigue, 0.775)
        self.assertGreater(result.state.exposure_min, 6)
        with self.assertRaises(ContractError):
            protective_rest(state, self.parameters, 0.8, 0)

    def test_phase_start_sampling_and_hr_single_duration(self):
        timing = sample_phase(self.phase(), self.parameters, 0.1885, 0.8)
        self.assertAlmostEqual(timing.duration_min, 2.377)
        self.assertEqual(timing.sampled_f, 0.1885)
        self.assertEqual(
            sample_phase(
                self.phase(), replace(self.parameters, speed_kappa=0), 0.7, 0.8
            ).duration_min,
            2,
        )
        for phase in (
            self.phase("CUT", "R"),
            self.phase(phase="align"),
            self.phase(phase="restore"),
        ):
            result = sample_phase(phase, self.parameters, 0.7, 0.8)
            self.assertEqual(result.duration_min, phase.base_min)
            self.assertEqual(result.speed_multiplier, 1)
            self.assertIsNone(result.sampled_f)

    def test_resume_preserves_sample_restart_takes_new_sample(self):
        phase = self.phase()
        progress = self.progress(phase)
        self.assertEqual(remaining_duration(phase, self.parameters, progress, 0.8), 1.2)
        after = protective_rest(self.state(0.5, 4), self.parameters, 0.8, 4).state
        after = evolve(after, self.parameters, "supervise", 0.5, 0.8).state
        self.assertEqual(remaining_duration(phase, self.parameters, progress, 0.8), 1.2)
        restart = sample_phase(phase, self.parameters, after.fatigue, 0.8)
        self.assertAlmostEqual(restart.duration_min, 2 * (1 + 0.4025))
        self.assertGreater(after.exposure_min, 4)
        self.assertEqual(progress.attempt, 1)

    def test_invalid_progress_samples_and_remaining_work(self):
        progress = self.progress()
        for changes in (
            {"remaining_base_min": 3},
            {"remaining_base_min": 0},
            {"sampled_f": None},
            {"sampled_f": 0.9},
            {"speed_multiplier": 1.7},
            {"status": "failed"},
            {"status": "completed"},
            {"completed_min": 2},
            {"phase_id": "setup"},
        ):
            with self.subTest(changes=changes), self.assertRaises(ContractError):
                remaining_duration(self.phase(), self.parameters, replace(progress, **changes), 0.8)
        phase = self.phase(phase="align")
        with self.assertRaises(ContractError):
            remaining_duration(
                phase,
                self.parameters,
                replace(progress, phase_id="align", remaining_base_min=0.25),
                0.8,
            )

    def test_duration_override_and_restore_cost(self):
        config = loads(
            Configuration, (ROOT / "examples/contracts/structural.json").read_text(encoding="utf-8")
        )
        operation = next(o for o in config.operations if o.duration_overrides)
        override = operation.duration_overrides[0]
        phase = resolve_process_phase(config, operation.id, override.mode_id, override.phase_id)
        self.assertEqual(phase.base_min, override.base_min)
        restore = self.phase("CUT", "R", "restore")
        self.assertEqual(
            (restore.base_min, restore.activity, restore.interruption), (1, "work", "resume")
        )
        result = evolve(self.state(), self.parameters, restore.activity, restore.base_min, 0.8)
        self.assertAlmostEqual(result.state.fatigue, 0.12)

    def test_handoff_is_automatically_included_in_protection(self):
        # CUT.R work: wait +.006 is feasible; necessary carry handoff +.03 is not.
        result = process_start_allowed(self.config, "J1.C1", "mode.CUT.R", "work", self.state(0.77))
        self.assertFalse(result.allowed)
        self.assertEqual(result.reason, "FATIGUE_PROTECTION")
        self.assertTrue(
            process_start_allowed(
                self.config, "J1.C1", "mode.CUT.R", "work", self.state(0.7)
            ).allowed
        )

    def test_restore_cost_included_and_refusal_does_not_reveal_state(self):
        args = (self.config, "J1.C1", "mode.CUT.R", "work", self.state(0.75))
        self.assertTrue(process_start_allowed(*args).allowed)
        refusal = process_start_allowed(*args, restore_required=True)
        self.assertFalse(refusal.allowed)
        self.assertEqual(set(vars(refusal)), {"allowed", "reason"})
        other = process_start_allowed(self.config, "J1.C1", "mode.CUT.R", "work", self.state(0.79))
        self.assertEqual(refusal, other)
        with self.assertRaises(ContractError):
            process_start_allowed(
                self.config, "J1.I1", "mode.INSPECT.H", "work", self.state(), restore_required=True
            )

    def test_resume_protection_after_restore_and_new_attempt_sampling(self):
        progress = self.progress(remaining=1)
        # Resume: .779 + .0025 restore + .012 work + .005 handoff = .7985.
        # Fresh full work samples .7815 and exceeds cap.
        args = (self.config, "J1.A1", "mode.ASSEMBLE.HR", "work", self.state(0.779))
        self.assertTrue(
            process_start_allowed(*args, progress=progress, restore_required=True).allowed
        )
        self.assertFalse(process_start_allowed(*args, restore_required=True).allowed)
        with self.assertRaises(ContractError):
            process_start_allowed(*args, progress=replace(progress, group_id="wrong"))

    def test_protective_rest_requires_rechecking_and_may_be_insufficient(self):
        state = protective_rest(self.state(0.8), self.parameters, 0.8, 1).state
        args = (self.config, "J1.C1", "mode.CUT.R", "work")
        self.assertFalse(process_start_allowed(*args, state).allowed)
        state = protective_rest(state, self.parameters, 0.8, 1).state
        self.assertTrue(process_start_allowed(*args, state).allowed)

    def test_s05_entire_trajectory_and_metrics(self):
        result = evaluate_window(self.config, self.timelines(), drained_min=33.604108)
        metrics = self.witness["metrics"]
        for trajectory in result.trajectories:
            expected = self.witness["worker_timeline"][trajectory.worker_id]
            for calculated, segment in zip(trajectory.results, expected, strict=True):
                self.assertAlmostEqual(calculated.state.fatigue, segment["F_end"], delta=1e-10)
                self.assertAlmostEqual(
                    calculated.exposure_increment_min, segment["exposure_min"], delta=1e-10
                )
            self.assertAlmostEqual(
                trajectory.peak_f, metrics["worker"][trajectory.worker_id]["peak_F"], delta=1e-10
            )
            self.assertAlmostEqual(
                trajectory.results[-1].state.exposure_min,
                metrics["worker"][trajectory.worker_id]["exposure_min"],
                delta=1e-10,
            )
        self.assertAlmostEqual(result.total_min, metrics["E_total_min"], delta=1e-10)
        self.assertAlmostEqual(result.max_individual_min, metrics["E_max_min"], delta=1e-10)
        self.assertAlmostEqual(result.peak_f, metrics["F_peak"], delta=1e-10)
        self.assertFalse(result.censored)

    def test_window_rejects_missing_worker_gap_overlap_or_tail(self):
        original = self.timelines()
        variants = [{"W1": original["W1"]}]
        for intervals in (
            original["W1"][:-1],
            original["W1"][1:],
            (ActivityInterval(0, 2, "wait"),) + original["W1"][1:],
        ):
            variants.append(original | {"W1": intervals})
        variants.append(original | {"W1": (ActivityInterval(0, 41, "rest"),)})
        for timelines in variants:
            with self.assertRaises(ContractError):
                evaluate_window(self.config, timelines, drained_min=33.604108)

    def test_window_requires_explicit_rest_after_drain(self):
        timelines = self.timelines()
        timelines["W1"] = timelines["W1"][:-1] + (ActivityInterval(33.604108, 40, "wait"),)
        with self.assertRaises(ContractError):
            evaluate_window(self.config, timelines, drained_min=33.604108)
        result = evaluate_window(self.config, timelines, drained_min=None)
        self.assertTrue(result.censored)
        self.assertGreater(result.total_min, self.witness["metrics"]["E_total_min"])

    def test_window_cannot_hide_intermediate_violation_with_later_rest(self):
        timelines = {
            w: (ActivityInterval(0, 30, "carry"), ActivityInterval(30, 40, "rest"))
            for w in ("W1", "W2")
        }
        with self.assertRaises(FatigueLimitError):
            evaluate_window(self.config, timelines, drained_min=30)

    def test_common_cap_and_horizon_validation(self):
        for drain in (-1, 41, True, float("nan")):
            with self.assertRaises(ContractError):
                evaluate_window(self.config, self.timelines(), drained_min=drain)
        with self.assertRaises(ContractError):
            evaluate_window(
                replace(self.config, fatigue_cap=0.15), self.timelines(), drained_min=None
            )

    def test_cap_horizon_is_safe_to_integrate(self):
        for f in (0.0, 0.1, 0.79, math.nextafter(0.8, 0)):
            horizon = time_to_cap(f, self.parameters, "wait", 0.8)
            result = evolve(self.state(f), self.parameters, "wait", horizon, 0.8)
            self.assertLessEqual(result.state.fatigue, 0.8)
            with self.assertRaises(FatigueLimitError):
                evolve(
                    self.state(f), self.parameters, "wait", math.nextafter(horizon, math.inf), 0.8
                )
        with self.assertRaises(ContractError):
            time_to_cap(0, replace(self.parameters, wait_per_min=5e-324), "wait", 0.8)

    def test_restore_precedes_fresh_work_sample_at_protection_boundary(self):
        # Sampling before restore would wrongly admit this borderline case.
        result = process_start_allowed(
            self.config,
            "J1.A1",
            "mode.ASSEMBLE.HR",
            "work",
            self.state(0.75733),
            restore_required=True,
        )
        self.assertFalse(result.allowed)

    def test_full_rest_window_reaches_zero_without_discarding_exposure(self):
        timelines = {w: (ActivityInterval(0, 40, "rest"),) for w in ("W1", "W2")}
        result = evaluate_window(self.config, timelines, drained_min=0)
        self.assertAlmostEqual(result.total_min, 0.2 + 1)
        self.assertAlmostEqual(result.max_individual_min, 1)
        self.assertEqual(result.peak_f, 0.2)
        self.assertTrue(all(t.results[-1].state.fatigue == 0 for t in result.trajectories))


if __name__ == "__main__":
    unittest.main()
