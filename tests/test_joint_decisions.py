"""S18 program gates and conditional mechanisms, never acquired G2 evidence."""

import sys
import unittest
from dataclasses import replace
from pathlib import Path
from time import perf_counter
from unittest.mock import patch

from adaptive_hrc_scheduling.algorithms.joint_lns import (
    Action,
    Candidate,
    JointProblem,
    Switches,
    admission,
    joint_search,
)
from adaptive_hrc_scheduling.algorithms.lns import Options, fingerprint
from adaptive_hrc_scheduling.building_backend import BuildingBackend
from adaptive_hrc_scheduling.control.light_loop import capture
from adaptive_hrc_scheduling.domain import building as b

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from build_building_contracts import build_configuration, synthetic_fixture
from build_production_contracts import Builder
from run_building_witness import command, fact
from run_joint_mechanisms import first_mode, fixture, problem


def result(pr, *, iterations=0):
    return joint_search(
        pr, Options(seed=18, iterations=iterations, repair_trials=6, wall_seconds=30, stagnation=4)
    )


class JointTests(unittest.TestCase):
    def test_real_steel_gate_is_open_and_hr_disabled(self):
        c = build_configuration()
        gate = admission(c)
        self.assertEqual(gate.status, "BLOCKED")
        self.assertIn("G2_OPEN", gate.reasons)
        self.assertTrue(
            all(not m.enabled for a in c.activities for m in a.modes if m.kind == "HR-seq")
        )

    def test_current_production_contract_cannot_start_joint_research(self):
        gate = admission(Builder().configuration())
        self.assertEqual(gate.status, "BLOCKED")
        self.assertIn("S15_HR_SEQUENCE_MAPPING_ABSENT", gate.reasons)

    def test_synthetic_h_only_is_not_joint_qualification(self):
        c = synthetic_fixture(build_configuration())
        self.assertEqual(admission(c).status, "BLOCKED")
        with self.assertRaisesRegex(ValueError, "G2_OPEN"):
            JointProblem(capture(BuildingBackend(c)), (), ("PRODUCT-1.W-B",))

    def test_all_eight_g2_fields_must_pass(self):
        c = synthetic_fixture(build_configuration(), hr=True)
        for ident, _, _, _ in admission(c).references:
            with self.subTest(gate=ident):
                cc = replace(
                    c,
                    evidence=tuple(
                        replace(e, status="UNKNOWN") if e.id == ident else e for e in c.evidence
                    ),
                    activities=tuple(
                        replace(
                            a,
                            modes=tuple(
                                replace(m, enabled=False) if m.kind == "HR-seq" else m
                                for m in a.modes
                            ),
                        )
                        for a in c.activities
                    ),
                )
                self.assertEqual(admission(cc).status, "BLOCKED")

    def test_changed_qualification_revision_fails_closed(self):
        c = synthetic_fixture(build_configuration(), hr=True)
        c = replace(
            c,
            evidence=tuple(
                replace(e, revision="v2") if e.id == "G2-FIXTURE" else e for e in c.evidence
            ),
        )
        self.assertEqual(admission(c).status, "BLOCKED")

    def test_industrial_pass_labels_do_not_replace_scoped_dossier(self):
        c = synthetic_fixture(build_configuration(), hr=True)
        c = replace(
            c,
            purpose="RESEARCH_BLOCKED",
            evidence=tuple(replace(e, basis="INDUSTRIAL") for e in c.evidence),
        )
        gate = admission(c)
        self.assertEqual(gate.status, "BLOCKED")
        self.assertIn("REVIEWED_PRODUCT_JOINT_DOSSIER_REQUIRED", gate.reasons)

    def test_conditional_gate_explicitly_does_not_claim_research(self):
        c = synthetic_fixture(build_configuration(), hr=True)
        gate = admission(c)
        self.assertEqual(gate.status, "CONDITIONAL_BRANCH_ONLY")
        self.assertEqual(len(gate.references), 8)
        self.assertTrue(all(x[2] == "SYNTHETIC_TEST" for x in gate.references))

    def test_unsupported_domain_rejected(self):
        self.assertEqual(admission(object()).status, "BLOCKED")

    def test_complete_target_tail_independent_s10_and_common_window(self):
        w = fixture()
        before = w.snapshot
        pr = problem(w)
        r = result(pr)
        self.assertEqual(r.status, "FEASIBLE", r.initial_reasons)
        self.assertTrue(pr.verify(r.best).valid)
        trace = pr.preview(r.best)
        self.assertEqual(trace.time_h, w.time + 8)
        self.assertEqual(w.snapshot, before)
        self.assertTrue(
            any(a.activity_id.endswith("W-B") and a.state == "COMPLETED" for a in trace.attempts)
        )
        self.assertTrue(any(x.location == "J2" for x in trace.residencies))
        self.assertFalse(trace.quality)
        self.assertFalse(any(x.kind == "READY" for x in trace.events))

    def test_observed_failure_changes_mode_legally(self):
        a, z = fixture(), fixture(failure="R1")
        self.assertEqual(first_mode(result(problem(a)), a.config), "HR-seq")
        self.assertEqual(first_mode(result(problem(z)), z.config), "H")

    def test_irrelevant_observed_failure_keeps_choice(self):
        a, z = fixture(), fixture(failure="TEST1")
        ra, rz = result(problem(a)), result(problem(z))
        self.assertEqual(first_mode(ra, a.config), first_mode(rz, z.config))
        self.assertEqual(ra.best_score, rz.best_score)

    def test_same_visible_history_different_hidden_future_equal(self):
        a = fixture(future=(b.WorldEvent("HIDDEN-1", 100, "FAILURE", "R1", None, None),))
        z = fixture(future=(b.WorldEvent("HIDDEN-2", 200, "FAILURE", "WELD1", None, None),))
        pa, pz = problem(a), problem(z)
        self.assertEqual(pa.feedback, pz.feedback)
        ra, rz = result(pa, iterations=2), result(pz, iterations=2)
        self.assertEqual(ra.best, rz.best)
        self.assertEqual(ra.best_score, rz.best_score)
        self.assertEqual(
            [(x.removed, x.candidate_sha256, x.accepted, x.trials) for x in ra.history],
            [(x.removed, x.candidate_sha256, x.accepted, x.trials) for x in rz.history],
        )
        self.assertEqual(pa.preview(ra.best).scenario.events, ())

    def test_crew_ranking_changes_with_observed_fatigue(self):
        w = fixture(failure="R1", initial={"W1": 0.4, "W2": 0.05})
        pr = problem(w)
        no = problem(w, state=False)
        a, z = result(pr), result(no)
        ca = next(x.command for x in a.best.actions if x.command)
        cz = next(x.command for x in z.best.actions if x.command)
        self.assertEqual(ca.roles[0].person_id, "W2")
        self.assertEqual(cz.roles[0].person_id, "W1")
        self.assertTrue(pr.verify(a.best).valid and no.verify(z.best).valid)
        self.assertEqual(pr.world.config.cap, no.world.config.cap)
        self.assertEqual(pr.max_bindings, no.max_bindings)

    def test_fixed_modes_keep_same_rules_and_actual_window(self):
        w = fixture()
        for mode in ("H", "HR-seq"):
            pr = problem(w, fixed=mode)
            r = result(pr)
            self.assertEqual(r.status, "FEASIBLE", r.initial_reasons)
            self.assertEqual(first_mode(r, w.config), mode)
            self.assertEqual(pr.preview(r.best).time_h, w.time + 8)
            self.assertEqual(pr.world.config, capture(w).configuration)
            self.assertEqual(pr.world.s.locks, w.s.locks)

    def test_prepared_mode_cannot_be_changed(self):
        w = fixture()
        cmd = command(w, "PRODUCT-1.W-B", mode="PRODUCT-1.HR-seq")
        self.assertTrue(w.dispatch(cmd).accepted)
        w.advance(w.s.running[0].end_h)
        with self.assertRaisesRegex(ValueError, "FIXED_COMMITMENT_CHANGED"):
            problem(w, fixed="H")
        pr = problem(w, fixed="HR-seq")
        r = result(pr)
        self.assertEqual(r.status, "FEASIBLE", r.initial_reasons)
        self.assertTrue(
            all(x.command.mode_id.endswith("HR-seq") for x in r.best.actions if x.command)
        )
        self.assertEqual(pr.preview(r.best).events[: len(w.s.events)], w.s.events)

    def test_running_work_keeps_crew_and_materials(self):
        w = fixture()
        self.assertTrue(w.dispatch(command(w, "PRODUCT-1.W-B", mode="PRODUCT-1.HR-seq")).accepted)
        pr = problem(w)
        r = result(pr)
        self.assertEqual(r.status, "FEASIBLE", r.initial_reasons)
        trace = pr.preview(r.best)
        self.assertEqual(trace.events[: len(w.s.events)], w.s.events)
        consumed = {x.material_id: x.consumed_by for x in w.s.materials if x.consumed_by}
        self.assertTrue(
            all(
                consumed[x.material_id] == x.consumed_by
                for x in trace.materials
                if x.material_id in consumed
            )
        )

    def test_rest_of_committed_operator_rejected(self):
        w = fixture()
        w.dispatch(command(w, "PRODUCT-1.W-B", mode="PRODUCT-1.HR-seq"))
        pr = problem(w)
        forged = Candidate(
            pr.observation_hash, (Action("REST", people=("OP1",), until_h=w.time + 0.25),)
        )
        self.assertFalse(pr.verify(forged).valid)
        self.assertIn("REST_WHILE_COMMITTED", pr.verify(forged).reasons)

    def test_explicit_rest_and_start_delays_are_costed(self):
        w = fixture()
        pr = problem(w)
        action = Action("REST", people=("OP1",), until_h=w.time + 0.25)
        candidate = pr._rollout(
            (action, Action("ADVANCE", until_h=w.time + 0.25)), None, perf_counter() + 30
        ).candidate
        self.assertTrue(pr.verify(candidate).valid, pr.verify(candidate).reasons)
        trace = pr.preview(candidate)
        self.assertTrue(any(e.kind == "REST_START" for e in trace.events[len(w.s.events) :]))
        self.assertTrue(any(i.person_id == "OP1" and i.activity == "REST" for i in trace.intervals))
        self.assertGreater(pr.verify(candidate).score[0], result(pr).best_score[0])

    def test_bad_binding_cannot_enter_cache(self):
        w = fixture()
        pr = problem(w)
        r = result(pr)
        index = next(i for i, x in enumerate(r.best.actions) if x.command)
        actions = list(r.best.actions)
        cmd = actions[index].command
        actions[index] = replace(
            actions[index], command=replace(cmd, roles=(b.RoleBinding("OP1", "W1"),))
        )
        self.assertFalse(pr.verify(replace(r.best, actions=tuple(actions))).valid)

    def test_stale_command_and_changed_observation_rejected(self):
        w = fixture()
        pr = problem(w)
        r = result(pr)
        actions = list(r.best.actions)
        cmd = actions[0].command
        actions[0] = replace(actions[0], command=replace(cmd, expected_revision=999))
        self.assertFalse(pr.verify(replace(r.best, actions=tuple(actions))).valid)
        self.assertFalse(pr.verify(replace(r.best, observation_sha256="0" * 64)).valid)

    def test_deleted_proposed_completion_or_window_rejected(self):
        pr = problem(fixture())
        r = result(pr)
        self.assertFalse(pr.verify(replace(r.best, actions=())).valid)
        self.assertFalse(pr.verify(replace(r.best, actions=r.best.actions[:-1])).valid)

    def test_independent_s10_rejects_suffix_even_if_backend_admits(self):
        pr = problem(fixture())
        r = result(pr)
        report = type("Report", (), {"status": "INVALID", "findings": ()})()
        with patch("adaptive_hrc_scheduling.algorithms.joint_lns.check_run", return_value=report):
            self.assertFalse(pr.verify(r.best).valid)

    def test_forged_prefix_cannot_remove_j2_occupancy(self):
        w = fixture()
        f = capture(w)
        f = replace(f, state=replace(f.state, residencies=()))
        with self.assertRaises(ValueError):
            JointProblem(f, w.s.intervals, ("PRODUCT-1.W-B",))

    def test_future_event_and_missing_intervals_fail_closed(self):
        w = fixture()
        f = capture(w)
        future = replace(f.state.events[-1], time_h=w.time + 1)
        f2 = replace(f, state=replace(f.state, events=f.state.events[:-1] + (future,)))
        with self.assertRaises(ValueError):
            JointProblem(f2, w.s.intervals, ("PRODUCT-1.W-B",))
        with self.assertRaises(ValueError):
            JointProblem(f, (), ("PRODUCT-1.W-B",))

    def test_fixed_mode_coverage_and_invalid_controls_rejected(self):
        w = fixture()
        f = capture(w)
        for switches in (Switches((("PRODUCT-1.W-B", "PRODUCT-1.H"),)), Switches(state_ranking=1)):
            with self.assertRaises(ValueError):
                JointProblem(f, w.s.intervals, ("PRODUCT-1.W-B",), switches=switches)
        for bounds in ({"window_h": 0}, {"max_steps": True}, {"max_bindings": 0}):
            with self.assertRaises(ValueError):
                JointProblem(f, w.s.intervals, ("PRODUCT-1.W-B",), **bounds)

    def test_binding_exhaustion_is_wait_not_feasibility(self):
        w = fixture(failure="R1")
        pr = JointProblem(capture(w), w.s.intervals, ("PRODUCT-1.W-B",), max_bindings=1)
        r = result(pr)
        self.assertEqual(r.status, "WAIT")
        self.assertIn("BINDING_BUDGET_EXHAUSTED", r.initial_reasons)

    def test_missing_materials_no_implicit_supply(self):
        w = fixture()
        mid = w.activities["PRODUCT-1.W-B"].material_ids[0]
        fact(w, "INVALIDATE", "PRODUCT-1.W-B")
        # Configuration-level unreleased kit is a separate, genuine fixture.
        c = replace(
            w.config,
            materials=tuple(
                replace(m, released=False) if m.id == mid else m for m in w.config.materials
            ),
        )
        blocked = BuildingBackend(c)
        pr = JointProblem(capture(blocked), (), ("PRODUCT-1.W-B",), window_h=2)
        r = result(pr)
        self.assertEqual(r.status, "WAIT")
        self.assertFalse(blocked.s.quality)
        self.assertIsNone(r.best)

    def test_neighborhood_replay_is_seed_and_trial_reproducible(self):
        pr = problem(fixture())
        a = result(pr, iterations=3)
        z = result(pr, iterations=3)
        self.assertEqual(a.best, z.best)
        self.assertEqual(
            [(h.removed, h.candidate_sha256, h.reasons, h.trials) for h in a.history],
            [(h.removed, h.candidate_sha256, h.reasons, h.trials) for h in z.history],
        )
        self.assertEqual(fingerprint(a.best), fingerprint(z.best))

    def test_short_window_keeps_failure_without_infeasibility_claim(self):
        r = result(problem(fixture(), window=0.25))
        self.assertEqual(r.status, "WAIT")
        self.assertIn("VISIBLE_TAIL_NOT_COMPLETED", r.initial_reasons)

    def test_late_unload_erases_and_reverses_processing_advantage(self):
        w = fixture(late_unload=True)
        h = problem(w, fixed="H")
        hr = problem(w, fixed="HR-seq")
        rh, rhr = result(h), result(hr)
        self.assertTrue(h.verify(rh.best).valid and hr.verify(rhr.best).valid)
        self.assertGreater(rhr.best_score[0], rh.best_score[0])
        trace = hr.preview(rhr.best)
        starts = [
            e.time_h
            for e in trace.events
            if e.kind == "UNIT_START" and e.entity_id == "PRODUCT-1.W-B"
        ]
        self.assertEqual(starts[-1], 7)
        robot_end = next(
            e.time_h
            for e in trace.events
            if e.kind == "UNIT_COMPLETE"
            and e.entity_id == "PRODUCT-1.W-B"
            and '"unit_index": 1' in e.reason
        )
        self.assertLess(robot_end, 7)
        self.assertTrue(any(r.location == "J2" for r in trace.residencies))

    def test_normal_joint_has_no_gain_over_same_hr_choice(self):
        w = fixture()
        a = result(problem(w))
        z = result(problem(w, fixed="HR-seq"))
        self.assertEqual(a.best_score, z.best_score)

    def test_two_frame_sequence_can_change_without_deleting_residency(self):
        w = fixture(both_frames=True)
        pr = problem(w, targets=("PRODUCT-1.W-B", "PRODUCT-1.W-T"), window=24)
        menu, _ = pr._menu(pr.world)
        top = next(
            a
            for a in menu
            if a.command
            and a.command.activity_id == "PRODUCT-1.W-T"
            and a.command.mode_id.endswith("HR-seq")
        )
        repaired = pr._rollout((top,), None, perf_counter() + 30)
        self.assertIsNotNone(repaired.candidate, repaired.reasons)
        self.assertTrue(pr.verify(repaired.candidate).valid, pr.verify(repaired.candidate).reasons)
        starts = [a.command.activity_id for a in repaired.candidate.actions if a.command]
        self.assertEqual(starts[0], "PRODUCT-1.W-T")
        self.assertIn("PRODUCT-1.W-B", starts)
        self.assertTrue(any(r.location == "J2" for r in pr.preview(repaired.candidate).residencies))

    def test_robot_completion_keeps_cell_and_fixture_until_real_unload(self):
        w = fixture()
        for _ in range(2):
            cmd = command(w, "PRODUCT-1.W-B", mode="PRODUCT-1.HR-seq")
            self.assertTrue(w.dispatch(cmd).accepted)
            w.advance(w.s.running[0].end_h)
        self.assertTrue({"R1", "FIX-J2"} <= {r.resource_id for r in w.s.locks})
        before = w.snapshot
        pr = problem(w)
        r = result(pr)
        self.assertTrue(pr.verify(r.best).valid, r.initial_reasons)
        self.assertEqual(w.snapshot, before)
        wrong = command(pr.world, "PRODUCT-1.W-B", mode="PRODUCT-1.H")
        forged = Candidate(pr.observation_hash, (Action("DISPATCH", wrong),))
        self.assertFalse(pr.verify(forged).valid)

    def test_wall_zero_initial_failure_never_promotes_partial_tail(self):
        r = joint_search(problem(fixture()), Options(wall_seconds=0))
        self.assertEqual(r.status, "WAIT")
        self.assertIsNone(r.best)
        self.assertIn("WALL_BUDGET", r.initial_reasons)


if __name__ == "__main__":
    unittest.main()
