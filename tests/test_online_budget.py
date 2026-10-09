"""S19 deadlines, current-state gates and preservation on real executed prefixes."""

import json
import sys
import unittest
from dataclasses import replace
from pathlib import Path
from time import perf_counter
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from build_simulation_production import configuration

from adaptive_hrc_scheduling.algorithms.lns import Repair
from adaptive_hrc_scheduling.algorithms.simulation_joint import SimulationJointProblem
from adaptive_hrc_scheduling.contracts.codec import ContractError, as_data, decode
from adaptive_hrc_scheduling.control.online import (
    Interrupted,
    Limits,
    OnlinePolicy,
    plan_change,
    plan_rows,
    protected,
    version,
)
from adaptive_hrc_scheduling.control.production_decisions import record
from adaptive_hrc_scheduling.control.production_loop import Scenario, run
from adaptive_hrc_scheduling.domain import production as m
from adaptive_hrc_scheduling.planning.production import planning_input
from adaptive_hrc_scheduling.production_backend import ProductionBackend


class LimitAndChangeTests(unittest.TestCase):
    def test_initial_audit_anchor_preserves_saved_number_representation(self):
        from audit_online import initial_state_from_wire

        from adaptive_hrc_scheduling.algorithms.lns import fingerprint

        config = configuration(products=3, rework=True)
        wire = json.loads(json.dumps(as_data(config)))
        restored = initial_state_from_wire(decode(m.Configuration, wire), wire)
        actual = ProductionBackend(config).observe().state
        self.assertEqual(fingerprint(protected(restored)), fingerprint(protected(actual)))
        self.assertEqual(as_data(restored), as_data(actual))

    def test_invalid_limits(self):
        for data in (
            dict(decision_seconds=-1),
            dict(decision_seconds=float("nan")),
            dict(search_seconds=float("inf")),
            dict(period_h=0),
            dict(horizon_h=0),
            dict(search_seconds=2),
            dict(iterations=True),
            dict(max_search_calls=-1),
            dict(repair_trials=1.5),
            dict(future_commitment_h=-1),
            dict(future_commitment_h=3),
            dict(future_commitment_h=float("nan")),
        ):
            with self.subTest(data=data), self.assertRaises(ContractError):
                replace(Limits(), **data).validate()

    def test_zero_budget_allowed(self):
        Limits(decision_seconds=0, search_seconds=0).validate()

    def test_changes_do_not_count_index_shift_as_reordering(self):
        a = dict(operation="a", attempt=0, mode="H", roles=[], start_h=1)
        b = dict(a, operation="b")
        c = dict(a, operation="c")
        result = plan_change([a, b], [c, a, b])
        self.assertEqual(result["added"], 1)
        self.assertEqual(result["order_inversions"], 0)
        self.assertEqual(result["comparable"], 2)

    def test_changes_count_reorder_mode_crew_and_start(self):
        a = dict(operation="a", attempt=0, mode="H", roles=[], start_h=1)
        b = dict(a, operation="b")
        result = plan_change([a, b], [b, dict(a, mode="HR", roles=["p"], start_h=3)])
        self.assertEqual(result["order_inversions"], 1)
        self.assertEqual(result["mode_changes"], 1)
        self.assertEqual(result["crew_changes"], 1)
        self.assertEqual(result["start_changes"], 1)
        self.assertEqual(result["total_start_shift_h"], 2)

    def test_duplicate_plan_key_rejected(self):
        a = dict(operation="a", attempt=0, mode="H", roles=[], start_h=1)
        with self.assertRaises(ContractError):
            plan_change([a, a], [])


class OnlineExecutedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = configuration()
        cls.warmup = run(
            ProductionBackend(cls.config),
            Scenario(until_h=720),
            warmup_only=True,
            stop_condition=lambda w: (
                not w.s.running
                and any(p.id == "PRODUCT-1.BOTTOM" and p.location == "J2" for p in w.s.positions)
            ),
        )
        assert cls.warmup.audit.status == cls.warmup.decision_audit.status == "PASS"
        cls.prefix = cls.warmup.snapshot
        cls.rows = tuple(record(d) for d in cls.warmup.decisions)
        w = ProductionBackend(cls.config, run_id=cls.prefix.run_id, epoch=cls.prefix.epoch)
        w.s, w.events = cls.prefix.state, list(cls.prefix.events)
        cls.problem = SimulationJointProblem(
            cls.config,
            w.observe(),
            cls.prefix,
            decisions=cls.rows,
            end_h=w.s.time_h + 0.5,
        )
        cls.candidate = cls.problem.initial(perf_counter() + 90).candidate
        assert cls.candidate is not None
        report = cls.problem.verify(cls.candidate)
        assert report.valid, report.reasons

    def setUp(self):
        self.world = self.problem.world()
        self.obs = self.world.observe()
        self.value = planning_input(self.config, self.obs, 10000)

    def policy(self, **limits):
        return OnlinePolicy(
            self.config,
            replace(Limits(decision_seconds=30, search_seconds=0, horizon_h=0.5), **limits),
            end_h=self.obs.sampled_h + 2,
        )

    def decide(self, p):
        return p.decide(self.value, self.prefix, self.rows, sequence=500)

    def test_zero_budget_wait_does_not_touch_execution(self):
        before = self.world.snapshot()
        p = self.policy(decision_seconds=0)
        plan = self.decide(p)
        self.assertFalse(plan.commands)
        self.assertIn("DEADLINE", plan.reason)
        self.assertEqual(self.world.snapshot(), before)
        self.assertEqual(p.calls, 0)

    def test_full_audits_accept_stream_without_slicing_and_reject_tampering(self):
        from adaptive_hrc_scheduling.control.production_decisions import check_decisions
        from adaptive_hrc_scheduling.production_checker import check_run

        class EventStream:
            def __init__(self, events):
                self.events = events
                self.last = None

            def __iter__(self):
                for event in self.events:
                    self.last = event
                    yield event

            def __bool__(self):
                return self.last is not None

            def __getitem__(self, index):
                if index != -1 or self.last is None:
                    raise IndexError(index)
                return self.last

        for audit in (
            lambda snapshot: check_run(self.config, snapshot),
            lambda snapshot: check_decisions(self.config, snapshot, self.rows),
        ):
            expected = audit(self.prefix)
            self.assertEqual(expected.status, "PASS")
            streamed = replace(self.prefix, events=EventStream(self.prefix.events))
            self.assertEqual(audit(streamed), expected)
            bad = (replace(self.prefix.events[0], sequence=99),) + self.prefix.events[1:]
            self.assertNotEqual(audit(replace(self.prefix, events=EventStream(bad))).status, "PASS")

    def test_incremental_audit_matches_full_and_rejects_altered_history(self):
        from adaptive_hrc_scheduling.control.audit_cache import ExecutionCheckpoint
        from adaptive_hrc_scheduling.production_checker import check_run

        checkpoint = ExecutionCheckpoint()
        size = len(self.prefix.events)
        for count in sorted({1, size // 3, 2 * size // 3, size}):
            events = self.prefix.events[:count]
            state = replace(
                events[-1].state,
                intervals=tuple(
                    x for x in self.prefix.state.intervals if x.end_h <= events[-1].occurred_sim_h
                ),
            )
            snapshot = replace(self.prefix, events=events, state=state)
            full = check_run(self.config, snapshot)
            cached = checkpoint.verify(self.config, snapshot)
            self.assertEqual(full.status, "PASS", full.findings)
            self.assertEqual(cached, full)
        count, _ = checkpoint.restore(self.config, self.prefix)
        self.assertEqual(count, size)
        event = replace(self.prefix.events[0], sequence=99)
        altered = replace(self.prefix, events=(event,) + self.prefix.events[1:])
        self.assertNotEqual(checkpoint.verify(self.config, altered).status, "PASS")
        self.assertEqual(
            checkpoint.verify(self.config, self.prefix), check_run(self.config, self.prefix)
        )
        foreign = replace(self.prefix, epoch=self.prefix.epoch + 1)
        self.assertNotEqual(checkpoint.verify(self.config, foreign).status, "PASS")

    def test_incremental_causal_audit_replaces_terminal_without_trusting_changed_rows(self):
        from copy import deepcopy

        from adaptive_hrc_scheduling.control.audit_cache import DecisionCheckpoint
        from adaptive_hrc_scheduling.control.production_decisions import check_decisions

        checkpoint = DecisionCheckpoint()
        full = check_decisions(self.config, self.prefix, self.rows)
        self.assertEqual(full.status, "PASS")
        self.assertEqual(checkpoint.verify(self.config, self.prefix, self.rows), full)
        snapshot, rows = self.problem.preview(self.candidate)
        self.assertEqual(
            checkpoint.fork().verify(self.config, snapshot, rows),
            check_decisions(self.config, snapshot, rows),
        )
        changed = deepcopy(rows)
        changed[0]["state_sha256"] = "0" * 64
        cached = checkpoint.verify(self.config, snapshot, changed)
        self.assertNotEqual(cached.status, "PASS")
        self.assertEqual(cached, check_decisions(self.config, snapshot, changed))
        self.assertEqual(checkpoint.verify(self.config, self.prefix, self.rows).status, "PASS")

    def test_certified_interval_and_export_mutation_are_not_trusted(self):
        from adaptive_hrc_scheduling.control.audit_cache import ExecutionCheckpoint
        from adaptive_hrc_scheduling.production_checker import check_run

        checkpoint = ExecutionCheckpoint()
        self.assertEqual(checkpoint.verify(self.config, self.prefix).status, "PASS")
        first = self.prefix.state.intervals[0]
        changed = replace(
            self.prefix,
            state=replace(
                self.prefix.state,
                intervals=(replace(first, end_h=first.end_h + 0.01),)
                + self.prefix.state.intervals[1:],
            ),
        )
        self.assertEqual(checkpoint.interval_prefix(self.config, changed), 0)
        self.assertEqual(checkpoint.verify(self.config, changed), check_run(self.config, changed))
        self.assertNotEqual(checkpoint.verify(self.config, changed).status, "PASS")
        exported = self.problem.decisions
        exported[0]["state_sha256"] = "0" * 64
        self.assertTrue(self.problem.verify(self.candidate).valid)

    def test_conservative_seed_checks_entire_window_and_rejects_hold_tamper(self):
        problem = SimulationJointProblem(
            self.config,
            self.obs,
            self.prefix,
            decisions=self.rows,
            end_h=self.obs.sampled_h + 0.5,
            initial_action_only=True,
        )
        candidate = problem.initial(perf_counter() + 90).candidate
        self.assertIsNotNone(candidate)
        self.assertTrue(problem.verify(candidate).valid)
        self.assertEqual(sum(bool(s.plan.commands) for s in candidate.steps), 1)
        snapshot, _ = problem.preview(candidate)
        self.assertEqual(snapshot.state.time_h, candidate.end_h)
        self.assertFalse(problem.verify(replace(candidate, steps=candidate.steps[:-1])).valid)
        hold = candidate.steps[-1]
        bad = replace(hold, plan=replace(hold.plan, reason="FABRICATED_HOLD"))
        self.assertFalse(
            problem.verify(replace(candidate, steps=candidate.steps[:-1] + (bad,))).valid
        )

    def test_actual_recovery_precedes_unstarted_future_promise(self):
        world = ProductionBackend(self.config)
        prefix = run(
            world,
            Scenario(loaded_failure=True),
            stop_condition=lambda w: any(r.status == "EXCEPTION" for r in w.s.running),
        )
        held = next(r.command.id for r in world.s.running if r.status == "EXCEPTION")
        for index, resource in enumerate(world.s.failed_resources):
            world.apply_world(
                m.WorldEvent(
                    f"S19-RECOVERY-{index}",
                    world.run_id,
                    world.epoch,
                    world.s.time_h,
                    "REPAIR",
                    resource,
                    "PRODUCT-1",
                    0,
                    "PASS",
                    "S19-TEST",
                )
            )
        policy = OnlinePolicy(
            self.config, Limits(decision_seconds=30, search_seconds=0), end_h=world.s.time_h + 1
        )
        started = set(world.s.completed) | {r.command.operation_id for r in world.s.running}
        promise, reason = next(
            (c, s.plan.reason)
            for s in self.candidate.steps
            for c in s.plan.commands
            if c.operation_id not in started
        )
        policy.committed = (promise,)
        policy.commitment_reasons[(promise.operation_id, promise.attempt)] = reason
        obs = world.observe()
        plan = policy.decide(
            planning_input(self.config, obs),
            world.snapshot(),
            tuple(record(d) for d in prefix.decisions),
        )
        self.assertTrue(plan.commands, plan.reason)
        self.assertEqual(plan.commands[0].resume_of, held)
        self.assertEqual(policy.committed, (promise,))
        self.assertEqual(world.dispatch(plan.commands[0]).kind, "STARTED")

    def test_nonzero_future_commitment_survives_interrupted_replanning(self):
        p = self.policy(
            decision_seconds=120, search_seconds=110, iterations=0, future_commitment_h=0.5
        )
        plan = self.decide(p)
        self.assertTrue(p.committed)
        self.assertTrue(p.candidates)
        self.assertEqual(p.journal[-1]["commitments_after"], plan_rows(p.committed))
        promised = p.committed
        p._force_trigger = "RESUME"
        with patch.object(SimulationJointProblem, "initial", side_effect=RuntimeError("interrupt")):
            next_plan = self.decide(p)
        self.assertEqual(p.committed, promised)
        self.assertEqual(next_plan.commands[0].operation_id, plan.commands[0].operation_id)
        receipt = self.world.dispatch(next_plan.commands[0])
        p.end_cycle(next_plan, receipt)
        self.assertEqual(receipt.kind, "STARTED")
        self.assertEqual(p.journal[-1]["actual_start"]["delay_h"], 0)

    def test_commitment_blocks_fallback_when_current_admission_fails(self):
        p = self.policy(
            decision_seconds=120, search_seconds=110, iterations=0, future_commitment_h=0.5
        )
        self.decide(p)
        promised = p.committed
        self.assertTrue(promised)
        with patch.object(p, "_admit", side_effect=ContractError("RESOURCE_FAILED")):
            plan = self.decide(p)
        self.assertFalse(plan.commands)
        self.assertIn("COMMITMENT_BLOCKED", plan.reason)
        self.assertEqual(p.committed, promised)

    def test_replanning_candidate_replays_locked_commands_and_checks_metadata(self):
        commands = tuple((c, s.plan.reason) for s in self.candidate.steps for c in s.plan.commands)
        self.assertTrue(commands)
        problem = SimulationJointProblem(
            self.config,
            self.obs,
            self.prefix,
            decisions=self.rows,
            end_h=self.obs.sampled_h + 0.5,
            committed=commands[:1],
        )
        candidate = problem.initial(perf_counter() + 30).candidate
        self.assertIsNotNone(candidate)
        self.assertTrue(problem.verify(candidate).valid)
        first = next(s for s in candidate.steps if s.plan.commands)
        changed = replace(first, plan=replace(first.plan, reason="ALTERED_PROMISE"))
        bad = replace(candidate, steps=tuple(changed if s is first else s for s in candidate.steps))
        self.assertFalse(problem.verify(bad).valid)

    def test_short_search_falls_back_to_legal_rule(self):
        p = self.policy(search_seconds=1e-9)
        plan = self.decide(p)
        self.assertTrue(plan.commands, plan.reason)
        self.assertEqual(self.world.dispatch(plan.commands[0]).kind, "STARTED")
        self.assertEqual(p.journal[-1]["termination"], "SEARCH_DEADLINE")

    def test_rule_has_current_revision_and_run_binding(self):
        p = self.policy()
        plan = self.decide(p)
        self.assertEqual(plan.commands[0].expected_revision, self.obs.state.revision)
        self.assertEqual(plan.commands[0].run_id, self.obs.run_id)
        self.assertEqual(plan.commands[0].epoch, self.obs.epoch)

    def test_rule_retry_is_not_reported_as_verified_candidate_cache(self):
        p = self.policy()
        first = self.decide(p)
        self.assertTrue(first.commands)
        second = self.decide(p)
        self.assertEqual(second.commands[0].operation_id, first.commands[0].operation_id)
        self.assertEqual(second.reason, first.reason)
        self.assertEqual(p.journal[-1]["selected_source"], "RULE_RETRY")
        self.assertIsNone(p.journal[-1]["cache_sha256"])
        self.assertFalse(p.candidates)
        self.assertEqual(second.commands, first.commands)
        self.assertEqual(self.world.dispatch(second.commands[0]).kind, "STARTED")

    def test_verified_cache_and_rule_share_actual_dispatch_identity(self):
        from adaptive_hrc_scheduling.algorithms.lns import fingerprint

        rule_policy = self.policy()
        cached_policy = self.policy(decision_seconds=120, search_seconds=110, iterations=0)
        rule = self.decide(rule_policy)
        with patch.object(
            SimulationJointProblem, "initial", return_value=Repair(self.candidate, 1)
        ):
            cached = self.decide(cached_policy)
        self.assertEqual(rule_policy.journal[-1]["selected_source"], "RULE")
        self.assertEqual(cached_policy.journal[-1]["selected_source"], "VERIFIED_CACHE")
        self.assertEqual(cached_policy.cache_hash, fingerprint(self.candidate))
        self.assertEqual(cached.commands, rule.commands)
        self.assertEqual(cached.reason, rule.reason)
        for plan in (rule, cached):
            world = self.problem.world()
            receipt = world.dispatch(plan.commands[0])
            self.assertEqual(receipt.kind, "STARTED")
            self.assertEqual(receipt.command_id, rule.commands[0].id)

    def test_version_detects_epoch_time_state_and_event_changes(self):
        for obs in (
            replace(self.obs, epoch=self.obs.epoch + 1),
            replace(self.obs, sampled_h=self.obs.sampled_h + 1),
            replace(self.obs, event_ids=self.obs.event_ids + ("new",)),
            replace(self.obs, state=replace(self.obs.state, failed_resources=("R1",))),
        ):
            self.assertNotEqual(version(obs), version(self.obs))

    def test_feedback_between_solve_and_dispatch_is_rejected(self):
        p = self.policy()
        plan = self.decide(p)
        self.world.apply_world(
            m.WorldEvent(
                "S19-FAILURE",
                self.world.run_id,
                self.world.epoch,
                self.world.s.time_h,
                "FAILURE",
                "R1",
                "PRODUCT-1",
                0,
                "PASS",
                "S19-TEST",
            )
        )
        result = p.guard(plan, self.world.observe())
        self.assertFalse(result.commands)
        self.assertIn("STALE_OBSERVATION", result.reason)
        self.assertTrue(p.journal[-1]["stale_dispatch_rejected"])

    def test_completed_dispatch_cannot_be_sent_twice(self):
        p = self.policy()
        plan = self.decide(p)
        self.assertEqual(self.world.dispatch(plan.commands[0]).kind, "STARTED")
        self.assertFalse(p.guard(plan, self.world.observe()).commands)

    def test_current_revision_cannot_hide_illegal_command(self):
        p = self.policy()
        plan = self.decide(p)
        bad = replace(plan, commands=(replace(plan.commands[0], expected_revision=0),))
        self.assertFalse(p.guard(bad, self.obs).commands)

    def test_foreign_run_command_rejected_before_dispatch(self):
        p = self.policy()
        plan = self.decide(p)
        bad = replace(plan, commands=(replace(plan.commands[0], run_id="OTHER-RUN"),))
        self.assertIn("STALE_COMMAND_IDENTITY", p.guard(bad, self.obs).reason)

    def test_multiple_dispatch_commands_are_rejected(self):
        p = self.policy()
        plan = self.decide(p)
        self.assertIn(
            "SINGLE_DISPATCH", p.guard(replace(plan, commands=plan.commands * 2), self.obs).reason
        )

    def test_timing_probe_observes_actual_events_and_restores_methods(self):
        from adaptive_hrc_scheduling.control.online_timing import OnlineTiming

        p = self.policy()
        original = self.world.dispatch
        probe = OnlineTiming(self.world, p)
        self.assertEqual(probe.report()["initial_event_count"], len(self.prefix.events))
        result = run(
            self.world,
            Scenario(until_h=self.obs.sampled_h + 0.1),
            joint_policy=p,
            continuation=True,
            prefix_decisions=self.warmup.decisions,
        )
        self.assertEqual(result.audit.status, "PASS")
        self.assertTrue(probe.feedback)
        self.assertGreater(
            probe.report()["exclusive_categories"]["scheduler_exclusive"]["total_s"], 0
        )
        self.assertFalse(probe.stack)
        self.assertTrue(all(r["decision_latency_s"] >= 0 for r in probe.feedback))
        probe.close()
        self.assertEqual(self.world.dispatch, original)
        control = run(
            self.problem.world(),
            Scenario(until_h=self.obs.sampled_h + 0.1),
            joint_policy=self.policy(),
            continuation=True,
            prefix_decisions=self.warmup.decisions,
        )
        self.assertEqual(result.snapshot, control.snapshot)
        self.assertEqual(result.decisions, control.decisions)

    def test_pause_preserves_all_physical_and_reservation_facts(self):
        p = self.policy()
        plan = self.decide(p)
        self.assertEqual(self.world.dispatch(plan.commands[0]).kind, "STARTED")
        before = protected(self.world.s)
        p.pause()
        obs = self.world.observe()
        result = p.decide(planning_input(self.config, obs), self.world.snapshot(), self.rows)
        self.assertIn("PAUSED", result.reason)
        self.assertFalse(result.commands)
        self.assertEqual(protected(self.world.s), before)
        p.resume()
        self.assertFalse(p.paused)
        self.assertFalse(p.cancelled)
        # Resuming never resets the world or the identity of running work.
        self.assertEqual(protected(self.world.s), before)

    def test_interrupted_search_retains_previously_verified_best(self):
        p = self.policy(decision_seconds=120, search_seconds=110, iterations=1)
        original = SimulationJointProblem.repair

        def stop(problem, *args):
            problem.search_iterations += 1
            problem.search_trials += 1
            raise Interrupted("TEST_REPAIR_INTERRUPT")

        with patch.object(SimulationJointProblem, "repair", stop):
            self.decide(p)
        self.assertEqual(p.journal[-1]["termination"], "TEST_REPAIR_INTERRUPT")
        self.assertEqual(p.journal[-1]["iterations"], 1)
        self.assertEqual(p.journal[-1]["trials"], 2)
        self.assertTrue(p.candidates)
        self.assertIsNotNone(original)

    def test_search_fault_retains_best_and_charges_verification(self):
        p = self.policy(decision_seconds=120, search_seconds=110, iterations=1)
        with patch.object(SimulationJointProblem, "repair", side_effect=RuntimeError("fault")):
            plan = self.decide(p)
        self.assertTrue(plan.commands)
        self.assertTrue(p.candidates)
        self.assertEqual(p.journal[-1]["termination"], "SEARCH_ERROR")
        self.assertGreater(p.journal[-1]["verification_seconds"], 0)
        self.assertEqual(p.journal[-1]["selected_source"], "VERIFIED_CACHE")
        original_reason = next(
            s.plan.reason
            for s in p.candidates[-1][1].steps
            for c in s.plan.commands
            if c.operation_id == plan.commands[0].operation_id
        )
        self.assertEqual(plan.reason, original_reason)

    def test_cancel_checkpoint_interrupts_real_rollout(self):
        calls = 0

        def stop():
            nonlocal calls
            calls += 1
            if calls == 2:
                raise Interrupted("USER_CANCEL")

        p = self.problem
        with patch.object(p, "checkpoint", stop), self.assertRaises(Interrupted):
            p.rollout(self.candidate.genes, perf_counter() + 90)
        self.assertEqual(calls, 2)

    def test_cancel_checkpoint_interrupts_candidate_replay(self):
        with patch.object(self.problem, "checkpoint", side_effect=Interrupted("STOP")):
            with self.assertRaises(Interrupted):
                self.problem.verify(self.candidate)

    def test_invalid_candidate_is_not_cached(self):
        p = self.policy(decision_seconds=120, search_seconds=110, iterations=0)
        bad = replace(self.candidate, anchor_sha256="0" * 64)
        with patch.object(SimulationJointProblem, "initial", return_value=Repair(bad, 1)):
            plan = self.decide(p)
        self.assertFalse(p.candidates)
        self.assertTrue(plan.commands)  # independently checked rule fallback

    def test_verified_candidate_identity_survives_current_head_rejection(self):
        from adaptive_hrc_scheduling.algorithms.lns import fingerprint

        policy = self.policy(decision_seconds=120, search_seconds=110, iterations=0)
        with patch.object(policy, "_admit", side_effect=ContractError("CURRENT_HEAD_REJECTED")):
            self.decide(policy)
        self.assertTrue(policy.candidates)
        self.assertIsNone(policy.journal[-1]["cache_sha256"])
        self.assertEqual(
            policy.journal[-1]["verified_candidate_sha256"], fingerprint(policy.candidates[-1][1])
        )

    def test_cancellation_during_verification_discards_candidate(self):
        p = self.policy(decision_seconds=120, search_seconds=110, iterations=0)
        original = SimulationJointProblem.verify

        def cancel_after_validation(problem, candidate):
            result = original(problem, candidate)
            p.interrupt()
            return result

        with patch.object(SimulationJointProblem, "verify", cancel_after_validation):
            plan = self.decide(p)
        self.assertFalse(p.candidates)
        self.assertFalse(plan.commands)

    def test_late_verified_candidate_is_discarded(self):
        p = self.policy(decision_seconds=120, search_seconds=110, iterations=0)
        original = SimulationJointProblem.verify
        late = False

        def late_validation(problem, candidate):
            nonlocal late
            result = original(problem, candidate)
            late = True
            return result

        def clock():
            return perf_counter() + (1000 if late else 0)

        with (
            patch("adaptive_hrc_scheduling.control.online.perf_counter", clock),
            patch.object(SimulationJointProblem, "verify", late_validation),
        ):
            plan = self.decide(p)
        self.assertFalse(p.candidates)
        self.assertFalse(plan.commands)
        self.assertEqual(p.journal[-1]["termination"], "SEARCH_DEADLINE")
        self.assertTrue(p.journal[-1]["budget_exceeded"])

    def test_cache_invalidated_by_continuous_feedback(self):
        p = self.policy()
        self.decide(p)
        p.pending = tuple(c for step in self.candidate.steps for c in step.plan.commands)
        self.assertTrue(p.pending)
        for index, kind in enumerate(("FAILURE", "REPAIR", "FAILURE")):
            self.world.apply_world(
                m.WorldEvent(
                    f"S19-F{index}",
                    self.world.run_id,
                    self.world.epoch,
                    self.world.s.time_h,
                    kind,
                    "R1",
                    "PRODUCT-1",
                    0,
                    "PASS",
                    "S19-TEST",
                )
            )
            obs = self.world.observe()
            p.decide(planning_input(self.config, obs), self.world.snapshot(), self.rows)
            self.assertEqual(p.journal[-1]["trigger"], "FEEDBACK")
        self.assertTrue(any(r["cache_invalidated"] for r in p.journal))

    def test_no_current_budget_means_no_rule_work(self):
        p = self.policy(decision_seconds=0)
        with patch("adaptive_hrc_scheduling.control.online.choose") as rule:
            self.decide(p)
        rule.assert_not_called()

    def test_input_construction_charged_to_budget(self):
        p = self.policy()
        p._cycle_start = perf_counter() - 31
        plan = self.decide(p)
        self.assertFalse(plan.commands)
        self.assertGreater(p.journal[-1]["decision_seconds"], 30)
        self.assertTrue(p.journal[-1]["budget_exceeded"])

    def test_plan_change_is_recomputable(self):
        p = self.policy()
        self.decide(p)
        r = p.journal[-1]
        self.assertEqual(r["change"], plan_change(r["before"], r["after"]))
        self.assertEqual(r["after"], plan_rows(p.pending))

    def test_mismatched_delivered_prefix_rejected(self):
        p = self.policy()
        with self.assertRaises(ContractError):
            p.decide(self.value, replace(self.prefix, epoch=self.prefix.epoch + 1), self.rows)

    def test_full_loop_fallback_continuation_has_both_independent_audits(self):
        p = self.policy()
        result = run(
            self.world,
            Scenario(until_h=self.obs.sampled_h + 1),
            joint_policy=p,
            continuation=True,
            prefix_decisions=self.warmup.decisions,
        )
        self.assertEqual(result.audit.status, "PASS")
        self.assertEqual(result.decision_audit.status, "PASS")
        self.assertTrue(p.journal)
        self.assertTrue(all("cycle_seconds" in r for r in p.journal))
        self.assertGreater(p.report()["cycle_seconds"], 0)

    def test_pause_and_resume_loaded_exception_preserves_batch_and_holds(self):
        world = ProductionBackend(self.config)
        prefix = run(
            world,
            Scenario(loaded_failure=True),
            stop_condition=lambda w: any(r.status == "EXCEPTION" for r in w.s.running),
        )
        self.assertEqual(prefix.audit.status, "PASS")
        self.assertEqual(prefix.decision_audit.status, "PASS")
        self.assertTrue(any(0 < r.progress < 1 for r in world.s.motions))
        self.assertTrue(world.s.owners)
        p = OnlinePolicy(
            self.config, Limits(decision_seconds=30, search_seconds=0), end_h=world.s.time_h + 1
        )
        before = world.snapshot()
        p.pause()
        obs = world.observe()
        plan = p.decide(
            planning_input(self.config, obs), before, tuple(record(d) for d in prefix.decisions)
        )
        self.assertFalse(plan.commands)
        self.assertEqual(world.snapshot(), before)
        p.resume()
        self.assertEqual(world.snapshot(), before)
        # Controller resume alone cannot clear an execution failure or unload material.
        plan = p.decide(
            planning_input(self.config, obs), before, tuple(record(d) for d in prefix.decisions)
        )
        if plan.commands:
            held = next(r.command.id for r in world.s.running if r.status == "EXCEPTION")
            self.assertNotEqual(plan.commands[0].resume_of, held)
        self.assertEqual(world.snapshot(), before)


if __name__ == "__main__":
    unittest.main()
