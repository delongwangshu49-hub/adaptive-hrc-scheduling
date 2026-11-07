"""W2a regressions for exact-task promotion, retained rows and safe STOP."""

import sys
import tempfile
import time
import unittest
from concurrent.futures import Future
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "desktop/p051/src"), str(ROOT / "desktop/s19b/src")]

from p051_desktop.gantt import ScheduleReader  # noqa: E402
from p051_desktop.planning import PlanningFeedback  # noqa: E402
from p051_desktop.stop_feedback import StopFeedback  # noqa: E402
from s19b_desktop.control import Controller, command  # noqa: E402
from s19b_desktop.model import atomic_json  # noqa: E402


class FeedbackTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.launch = dict(run_id="RUN", request_id="LAUNCH", session=dict(spec=dict(epoch=0)))
        self.base = dict(run_id="RUN", epoch=0, request_id="LAUNCH")
        self.now = time.monotonic() - 20
        self.versions = {1: "a" * 64, 2: "b" * 64, 3: "c" * 64}

    def stage(self, task, phase, version=None, **changes):
        version = version or task
        planning = phase == "PLANNING"
        row = dict(
            **self.base,
            format="P051-PLANNING-1",
            phase=phase,
            task=task,
            sequence=2 * task - planning,
            version=version,
            artifact_sha256=self.versions[version] if phase == "AWAITING_VERIFICATION" else None,
            started_monotonic_s=self.now + 2 * task,
            changed_monotonic_s=self.now + 2 * task + (not planning),
        )
        atomic_json(self.root / "p051-planning.json", dict(row, **changes))

    def view(self, version=None, *, task=None, observation=1, **changes):
        ref = (
            dict(
                version=version,
                task=task or version,
                artifact_sha256=self.versions[version],
                sampled_monotonic_s=self.now,
                sampled_sim_h=4,
            )
            if version
            else None
        )
        result = dict(
            envelope=dict(run_id="RUN", epoch=0),
            verified_full_schedule=ref,
            full_schedule=(
                dict(
                    version=version,
                    solve_calls=task or version,
                    artifact_sha256=self.versions[version],
                )
                if version
                else None
            ),
            status="VERIFIED",
            rows=[
                dict(row_kind="FACT_PREFIX", row_id=f"fact:{observation}"),
                *([dict(row_kind="FULL_PLAN", plan_version=version)] if version else []),
            ],
        )
        return dict(result, **changes)

    def test_live_cpu_and_kit_only_promote_current_exact_task(self):
        for backend in ("light", "isaac"):
            with self.subTest(backend=backend):
                feed = PlanningFeedback(dict(self.launch, backend=backend))
                self.assertEqual(feed.status({})["phase"], "WAITING")
                self.stage(1, "PLANNING")
                feed.refresh(self.root)
                self.assertIsNone(feed.project(self.view(1), {})["verified_full_schedule"])
                self.assertEqual(feed.status({})["phase"], "PLANNING")
                self.stage(1, "AWAITING_VERIFICATION")
                feed.refresh(self.root)
                self.assertEqual(feed.status({})["phase"], "AWAITING_VERIFICATION")
                first = feed.project(self.view(1), {})
                self.assertEqual(feed.status(first)["phase"], "AVAILABLE")
                self.stage(2, "PLANNING")
                feed.refresh(self.root)
                retained = feed.project(self.view(2, observation=7), first)
                self.assertEqual(retained["rows"][0]["row_id"], "fact:7")
                self.assertEqual(retained["rows"][1]["plan_version"], 1)
                status = feed.status(retained)
                self.assertEqual((status["shown_version"], status["candidate_version"]), (1, 2))
                self.assertGreater(status["plan_age_s"], 19)
                self.stage(2, "AWAITING_VERIFICATION")
                feed.refresh(self.root)
                self.assertEqual(
                    feed.project(self.view(2, task=1), first)["rows"][-1]["plan_version"], 1
                )
                self.assertEqual(feed.project(self.view(2), first)["rows"][-1]["plan_version"], 2)
                other = self.view(2)
                other["envelope"]["run_id"] = "OTHER"
                self.assertEqual(feed.project(other, first)["rows"][-1]["plan_version"], 1)

    def test_duplicates_cross_run_and_terminal_cannot_move_display(self):
        feed = PlanningFeedback(self.launch)
        self.stage(1, "AWAITING_VERIFICATION")
        feed.refresh(self.root)
        first = feed.project(self.view(1), {})
        self.stage(2, "PLANNING", run_id="OTHER")
        feed.refresh(self.root)
        self.stage(2, "PLANNING", epoch=False)
        feed.refresh(self.root)
        self.stage(2, "PLANNING", request_id="OLD")
        feed.refresh(self.root)
        self.stage(1, "FAILED")
        feed.refresh(self.root)
        self.assertEqual(feed.latest["phase"], "AWAITING_VERIFICATION")
        self.stage(2, "AWAITING_VERIFICATION")
        feed.refresh(self.root)
        self.assertEqual(
            feed.project(self.view(2), first, hold=True)["rows"][-1]["plan_version"], 1
        )
        feed.refresh(self.root, terminal=True)
        self.stage(3, "AWAITING_VERIFICATION")
        feed.refresh(self.root)
        self.assertEqual(feed.latest["task"], 2)
        self.assertEqual(feed.project(self.view(2), first)["rows"][-1]["plan_version"], 1)
        self.assertEqual(feed.status(first)["phase"], "HELD")

    def test_failure_then_same_candidate_version_on_new_task(self):
        feed = PlanningFeedback(self.launch)
        self.stage(1, "AWAITING_VERIFICATION")
        feed.refresh(self.root)
        first = feed.project(self.view(1), {})
        self.stage(2, "FAILED")
        feed.refresh(self.root)
        self.assertEqual(feed.status(first)["phase"], "FAILED")
        self.stage(3, "AWAITING_VERIFICATION", version=2)
        feed.refresh(self.root)
        self.assertEqual(feed.project(self.view(2), first)["rows"][-1]["plan_version"], 1)
        self.assertEqual(feed.project(self.view(2, task=3), first)["rows"][-1]["plan_version"], 2)
        failed = self.view(
            1,
            full_schedule=dict(artifact_sha256=self.versions[2], version=2, solve_calls=3),
            full_schedule_audit_error="BAD",
        )
        self.assertEqual(feed.status(failed)["phase"], "FAILED")
        self.assertIsNone(feed.status(failed)["wait_s"])

    def test_new_timeline_task_cannot_promote_a_late_older_audit(self):
        feed = PlanningFeedback(self.launch)
        self.stage(1, "AWAITING_VERIFICATION")
        feed.refresh(self.root)
        mixed = self.view(1, full_schedule=self.view(2)["full_schedule"])
        self.assertIsNone(feed.project(mixed, {})["verified_full_schedule"])
        self.assertEqual(feed.status(mixed)["phase"], "UNAVAILABLE")

    def test_missing_stage_distinguishes_legacy_and_managed_sessions(self):
        legacy = PlanningFeedback(self.launch, require_stage=False)
        managed = PlanningFeedback(self.launch)
        first = self.view(1)
        self.assertEqual(legacy.project(first, {})["verified_full_schedule"]["version"], 1)
        self.assertEqual(legacy.status(first)["phase"], "AVAILABLE")
        self.assertIsNone(managed.project(first, {})["verified_full_schedule"])
        self.assertEqual(managed.status(first)["phase"], "UNAVAILABLE")
        self.stage(1, "AWAITING_VERIFICATION")
        managed.refresh(self.root)
        prior = managed.project(first, {})
        (self.root / "p051-planning.json").write_text("{", encoding="utf8")
        managed.refresh_stage(self.root)
        self.assertEqual(managed.status(prior)["phase"], "UNAVAILABLE")
        (self.root / "p051-planning.json").unlink()
        managed.refresh_stage(self.root)
        retained = managed.project(self.view(2), prior)
        self.assertEqual(retained["verified_full_schedule"]["version"], 1)
        self.assertEqual(managed.status(retained)["phase"], "UNAVAILABLE")

    def test_attached_standalone_terminal_rejects_late_audit(self):
        feed = PlanningFeedback(spec=dict(run_id="RUN", epoch=0))
        first = feed.project(self.view(1), {})
        self.assertEqual(first["verified_full_schedule"]["version"], 1)
        feed.refresh(self.root, terminal=True)
        late = feed.project(self.view(2, observation=7), first)
        self.assertEqual(late["verified_full_schedule"]["version"], 1)
        self.assertEqual(late["rows"][0]["row_id"], "fact:7")

    def test_heartbeat_has_own_clock_and_no_plan_or_observation_effect(self):
        feed = PlanningFeedback(self.launch)
        self.stage(1, "PLANNING")
        pulse = dict(**self.base, sequence=4, published_monotonic_s=self.now)
        atomic_json(self.root / "live.json", pulse)
        feed.refresh(self.root)
        self.assertEqual(feed.status({})["phase"], "PLANNING")
        atomic_json(self.root / "live.json", dict(pulse, published_monotonic_s=self.now + 10))
        feed.refresh(self.root)
        self.assertGreater(feed.status({})["heartbeat_age_s"], 19)
        self.assertEqual(feed.status({})["sequence"], 1)
        atomic_json(
            self.root / "live.json", dict(pulse, sequence=5, published_monotonic_s=self.now + 10)
        )
        feed.refresh(self.root, terminal=True)
        self.assertLess(feed.status({})["heartbeat_age_s"], 11)
        atomic_json(
            self.root / "live.json", dict(pulse, sequence=6, published_monotonic_s=self.now + 15)
        )
        feed.refresh(self.root, terminal=True, exited=True)
        self.assertEqual(feed.heartbeat["sequence"], 5)
        saved = PlanningFeedback()
        archive = self.view(1)
        self.assertEqual(saved.project(archive, {}), archive)
        self.assertIsNone(saved.status(archive)["plan_age_s"])

    def test_reader_retains_approved_rows_during_audit_and_after_failed_candidate(self):
        reader = ScheduleReader()
        self.addCleanup(reader.close)
        ref = dict(
            version=1,
            solve_calls=1,
            plan_id="RUN:FULL",
            anchor_events=0,
            artifact_sha256=self.versions[1],
        )
        client = SimpleNamespace(
            directory=self.root,
            consumer=SimpleNamespace(
                basis=dict(configuration={}),
                events=[],
                envelope=dict(run_id="RUN", sampled_monotonic_s=self.now, sampled_sim_h=0),
            ),
        )
        one, two = Future(), Future()
        interval = dict(
            command=dict(mode_id="H", attempt=1, service=None),
            start_h=1,
            end_h=2,
            command_id="C",
            operation_id="O",
            activity_id="A",
            product_id="P",
            roles=[],
        )
        with patch.object(reader.executor, "submit", side_effect=(one, two)):
            self.assertEqual(reader.read_full(client, ref), [])
            one.set_result(dict(version=1, plan_id="RUN:FULL", intervals=[interval]))
            reader.drain()
            self.assertEqual(reader.read_full(client, ref)[0]["plan_version"], 1)
            new = dict(ref, version=2, solve_calls=2, artifact_sha256=self.versions[2])
            self.assertEqual(reader.read_full(client, new)[0]["plan_version"], 1)
            two.set_exception(ValueError("PROOF_REJECTED"))
            reader.drain()
            self.assertEqual(reader.read_full(client, new)[0]["plan_version"], 1)
            self.assertEqual(reader.full_failures[self.versions[2]], "PROOF_REJECTED")

    def test_stop_submission_unknown_durable_receipt_save_and_real_exit(self):
        launch = dict(self.launch, backend="light")
        control = Controller(self.root, launch)
        control.accept(command(launch, "start", 1))
        control.initialized()
        stop = StopFeedback()
        envelope = command(launch, "stop", 2)
        original = stop.send(self.root, envelope)
        self.assertEqual(stop.status(self.root, launch, None)["acceptance"], "PENDING")
        with patch("p051_desktop.stop_feedback.time.monotonic", return_value=stop.submitted_at + 3):
            self.assertEqual(stop.status(self.root, launch, None)["acceptance"], "UNKNOWN")
        self.assertEqual(stop.send(self.root, command(launch, "stop", 3)), original)
        self.assertEqual(len(list((self.root / "control-inbox").glob("*.json"))), 1)
        control.accept(envelope)
        accepted = stop.status(self.root, launch, None)
        self.assertEqual(
            (accepted["acceptance"], accepted["save"], accepted["worker_exit"]),
            ("ACCEPTED", "PENDING", None),
        )
        control.finish("STOPPED", {})
        final = dict(
            run_id="RUN", epoch=0, phase="STOPPED", save_status="COMPLETE", audit_status="PASS"
        )
        (self.root / "session").mkdir()
        atomic_json(self.root / "session/final-commit.json", dict(final=final))
        atomic_json(
            self.root / "report.json",
            dict(self.base, status="PASS", closed=True, session_final=final),
        )
        self.assertEqual(stop.status(self.root, launch, None)["save"], "SAVED")
        self.assertEqual(stop.status(self.root, launch, 0)["worker_exit"], 0)
        self.assertIsNone(StopFeedback().status(self.root, launch, None))

    def test_missing_stop_recovery_requires_original_envelope_and_authority(self):
        launch = dict(self.launch, backend="light")
        control = Controller(self.root, launch)
        control.accept(command(launch, "start", 1))
        control.initialized()
        stop = StopFeedback()
        envelope = command(launch, "stop", 2)
        request_id, key = stop.send(self.root, envelope)
        path = self.root / "control-inbox" / (key + ".json")
        original = path.read_bytes()
        with patch("p051_desktop.stop_feedback.time.monotonic", return_value=stop.submitted_at + 3):
            self.assertFalse(stop.status(self.root, launch, None)["recoverable"])
            path.unlink()
            status = stop.status(self.root, launch, None)
            self.assertEqual((status["request_id"], status["acceptance"]), (request_id, "UNKNOWN"))
            self.assertTrue(status["recoverable"])
            self.assertFalse(stop.restore_missing(self.root, launch, command(launch, "stop", 2)))
            self.assertFalse(
                stop.restore_missing(self.root, dict(launch, run_id="OTHER"), envelope)
            )
            self.assertTrue(stop.restore_missing(self.root, launch, envelope))
            self.assertEqual(path.read_bytes(), original)
            self.assertFalse(stop.restore_missing(self.root, launch, envelope))
        self.assertTrue(control.poll())
        self.assertEqual(control.state["stop"], request_id)
        self.assertEqual(len(control.state["commands"]), 2)


if __name__ == "__main__":
    unittest.main()
