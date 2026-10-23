"""P044 lifetime boundaries exercised against the real production writer."""

import copy
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path

from build_simulation_production import configuration as base

from adaptive_hrc_scheduling.contracts.session import digest, request_digest
from adaptive_hrc_scheduling.control.online import Limits
from adaptive_hrc_scheduling.control.production_loop import run
from adaptive_hrc_scheduling.control.session import Session, submit_file
from adaptive_hrc_scheduling.control.session_budget import Profile
from adaptive_hrc_scheduling.control.session_lifecycle import enable
from adaptive_hrc_scheduling.dynamic_workforce import registry
from adaptive_hrc_scheduling.production_backend import ProductionBackend
from adaptive_hrc_scheduling.timeline import TimelineConsumer, compare_envelopes
from adaptive_hrc_scheduling.workforce_session import arrival_payload, configuration, make_spec


def setup_session(path, *, run_id="P044-TEST", until=0.04, **clock):
    c = configuration(base())
    p = Profile(
        "P044-TEST",
        Limits(decision_seconds=5, search_seconds=1),
        100,
        2,
        "P042_URGENCY_DUE_PROGRESS_EXPOSURE-r1",
    )
    spec = enable(
        make_spec(
            c,
            p,
            run_id=run_id,
            method="EDD",
            until_h=until,
            rates={k: 10 for k in [*[x.id for x in c.people], *registry()]},
        ),
        simulation_rate=1,
        idle_step_h=0.01,
        boundary_poll_wall_s=0.01,
        **clock,
    )
    return Session(spec, ProductionBackend(c, run_id=run_id), p, path)


def request(s, n, kind, target, payload=None, **changes):
    r = dict(
        run_id=s.spec["run_id"],
        epoch=0,
        request_id=f"R{n}",
        producer_id="TEST",
        client_sequence=n,
        source="CLI",
        kind=kind,
        target_id=target,
        payload=payload or {},
        expected_catalog_version=s.version,
        expected_state_revision=s.world.s.revision,
        expected_target_revision=s.catalog["objects"].get(target, {}).get("revision", 0),
        time_rule="IMMEDIATE",
        expires_sim_h=10,
        submitted_at_utc="2026-10-23T07:00:00+00:00",
    )
    r.update(changes)
    r["request_digest"] = request_digest(r)
    return r


class LifetimeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.s = setup_session(Path(self.tmp.name) / "run")

    def cancel(self):
        for n, order in enumerate(self.s.order_products, 1):
            self.s.submit(request(self.s, n, "ORDER_CANCEL", order, dict(reason="TEST")))

    def execute(self, hook=None):
        s = self.s
        return run(s.backend, s.scenario(), session=s, joint_policy=s.policy, execution_hook=hook)

    def test_empty_open_wait_is_metered_censored_and_continuous(self):
        self.cancel()
        result = self.execute()
        self.assertEqual(result.manifest["termination"], "WINDOW_CENSORED")
        life = self.s.lifecycle
        self.assertTrue(any(x["phase"] == "WAITING_INPUT" for x in life.transitions))
        self.assertAlmostEqual(sum(x["end_h"] - x["start_h"] for x in life.meter), 0.04)
        self.assertGreater(self.s.world.s.humans[0].exposure, 0)
        self.assertEqual(life.final["save_status"], "COMPLETE")
        self.assertNotIn("process_exit_code", life.final)

    def test_close_empty_completes_and_terminal_rejects_mutation(self):
        self.cancel()
        self.s.submit(request(self.s, 10, "CLOSE_INPUT", self.s.spec["run_id"]))
        result = self.execute()
        self.assertEqual(result.manifest["session_final"]["phase"], "COMPLETED")
        r = request(
            self.s, 11, "DEVICE_FAIL", next(iter(self.s.world.devices)), dict(reason="TEST")
        )
        self.assertEqual(self.s.receive(r)["reason"], "SESSION_TERMINAL")

    def test_future_person_survives_close_fence_and_applies(self):
        self.cancel()
        s = self.s
        s.submit(
            request(
                s,
                10,
                "PERSON_ARRIVE",
                "W3",
                arrival_payload(s.world.config, "W3"),
                time_rule="AT_SIM_H",
                requested_sim_h=0.02,
            )
        )
        s.submit(request(s, 11, "CLOSE_INPUT", s.spec["run_id"]))
        result = self.execute()
        self.assertEqual(result.manifest["session_final"]["phase"], "COMPLETED")
        self.assertIn("W3", s.world.people)
        self.assertEqual(
            next(r for r in s.receipts if r["request_id"] == "R10" and r["status"] == "APPLIED")[
                "sim_h"
            ],
            0.02,
        )

    def test_new_arrival_after_close_rejected(self):
        s = self.s
        s.receive(request(s, 1, "CLOSE_INPUT", s.spec["run_id"]))
        s.boundary()
        r = request(s, 2, "PERSON_ARRIVE", "W3", arrival_payload(s.world.config, "W3"))
        self.assertEqual(s.receive(r)["reason"], "INPUT_CLOSED")

    def test_stop_empty_is_not_complete(self):
        self.cancel()
        self.s.submit(request(self.s, 10, "STOP_REQUEST", self.s.spec["run_id"]))
        result = self.execute()
        self.assertEqual(result.manifest["session_final"]["phase"], "STOPPED")

    def test_external_stop_interrupts_empty_wait(self):
        self.cancel()
        s = self.s
        result = run(
            s.backend,
            s.scenario(),
            session=s,
            joint_policy=s.policy,
            orderly_stop=lambda world: True,
        )
        self.assertEqual(result.manifest["session_final"]["phase"], "STOPPED")

    def test_wall_budget_is_distinct(self):
        self.cancel()
        self.s.lifecycle.started -= 4000
        self.assertEqual(self.execute().manifest["session_final"]["phase"], "WALL_CENSORED")

    def test_real_thread_file_arrival_after_waiting(self):
        self.cancel()
        s = self.s
        # Producer reads the last durable observation, then atomically publishes.
        sent = []

        def producer():
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                if s.lifecycle.phase == "WAITING_INPUT":
                    r = request(s, 10, "CLOSE_INPUT", s.spec["run_id"])
                    submit_file(s.output, r)
                    sent.append(r)
                    return
                time.sleep(0.002)

        thread = threading.Thread(target=producer)
        thread.start()
        result = self.execute()
        thread.join(2)
        self.assertEqual(len(sent), 1)
        self.assertEqual(result.manifest["session_final"]["phase"], "COMPLETED")

    def test_projection_replay_gap_wrong_run_and_no_mutating_filters(self):
        self.cancel()
        self.execute()
        s = self.s
        packets = [json.loads(x) for x in (s.output / "timeline.jsonl").read_text().splitlines()]
        c = TimelineConsumer(s.spec["run_id"], 0, digest(s.spec))
        for packet in packets:
            c.consume(packet)
        original = copy.deepcopy(c.rows)
        c.view(product_id="MISSING")
        self.assertEqual(c.rows, original)
        self.assertEqual(compare_envelopes(c.envelope, c.envelope), "SAME_OBSERVATION")
        bad = copy.deepcopy(packets[-1])
        bad["sequence"] += 2
        bad["packet_sha256"] = digest({k: v for k, v in bad.items() if k != "packet_sha256"})
        with self.assertRaises(ValueError):
            c.consume(bad)
        self.assertEqual(c.rows, original)
        self.assertEqual(c.status, "STALE_CORRUPT")
        wrong = TimelineConsumer("OTHER", 0, digest(s.spec))
        with self.assertRaises(ValueError):
            wrong.consume(packets[0])

    def test_holds_prevent_completion(self):
        from dataclasses import replace

        from adaptive_hrc_scheduling.domain.production import Ownership

        self.cancel()
        self.s.boundary()
        self.s.world.s = replace(self.s.world.s, owners=(Ownership("FORK-01", "ORPHAN"),))
        self.assertFalse(self.s.lifecycle.clear())

    def test_wait_cap_protection_never_clips_fatigue(self):
        from dataclasses import replace

        self.cancel()
        self.s.boundary()
        w = self.s.world
        human = w.s.humans[0]
        w.s = replace(w.s, humans=(replace(human, fatigue=w.config.cap), *w.s.humans[1:]))
        self.assertEqual(self.s.lifecycle.advance(1, idle=True), "DRAIN_BLOCKED")
        self.assertEqual(w.s.time_h, 0)

    def test_future_order_before_close_is_not_discarded(self):
        from adaptive_hrc_scheduling.dynamic_orders import template_registry

        s = self.s
        payload = dict(
            order_id="NEW",
            template_id="SR-W1",
            template_revision="v1",
            template_sha256=template_registry()["SR-W1"],
            quantity=1,
            due_sim_h=100,
            priority="NORMAL",
            material_plan_id="TEMPLATE-DELAY-1H-v1",
            arrival_rule="REQUEST_EFFECTIVE_TIME",
        )
        s.receive(
            request(
                s, 1, "ORDER_CREATE", "NEW", payload, time_rule="AT_SIM_H", requested_sim_h=0.01
            )
        )
        s.receive(request(s, 2, "CLOSE_INPUT", s.spec["run_id"]))
        s.boundary()
        self.assertFalse(s.lifecycle.clear())
        s.world.advance(0.01)
        s.boundary()
        self.assertIn("NEW", s.order_products)
        self.assertFalse(s.lifecycle.clear())
        self.assertEqual(
            next(r for r in reversed(s.receipts) if r["request_id"] == "R1")["status"], "APPLIED"
        )

    def test_close_drains_started_command_before_completion(self):
        from run_lifecycle_witness import execute

        s = self.s
        result, active, success = execute(
            s.backend, s.account.profile, Path(self.tmp.name) / "active-drain", case="active-drain"
        )
        self.assertTrue(success)
        close = next(
            r for r in active.receipts if r["request_id"] == "LIVE-11" and r["status"] == "APPLIED"
        )
        state = next(
            e.state for e in result.snapshot.events if e.state.revision == close["state_revision"]
        )
        self.assertTrue(state.running)
        self.assertFalse(result.snapshot.state.running)
        self.assertEqual(active.lifecycle.final["phase"], "COMPLETED")

    def test_failure_preserves_failed_final_not_completed(self):
        def hook(backend, phase):
            raise RuntimeError("WITNESS_FAILURE")

        with self.assertRaisesRegex(RuntimeError, "WITNESS_FAILURE"):
            self.execute(hook)
        self.assertEqual(self.s.lifecycle.final["phase"], "FAILED")
        self.assertTrue((self.s.output / "final-commit.json").exists())

    def test_terminal_queries_preserve_committed_state(self):
        self.cancel()
        s = self.s
        s.submit(request(s, 10, "CLOSE_INPUT", s.spec["run_id"]))
        self.execute()
        before = (s.output / "session-state.json").read_bytes()
        r = request(s, 11, "STOP_REQUEST", s.spec["run_id"])
        self.assertEqual(s.receive(r), s.receive(r))
        self.assertEqual((s.output / "session-state.json").read_bytes(), before)

    def test_same_tick_stop_prevents_other_application(self):
        s = self.s
        s.submit(request(s, 1, "STOP_REQUEST", s.spec["run_id"]))
        s.submit(request(s, 2, "PERSON_ARRIVE", "W3", arrival_payload(s.world.config, "W3")))
        s.boundary()
        self.assertNotIn("W3", s.world.people)
        self.assertEqual(s.receipts[-1]["reason"], "SESSION_STOPPED")

    def test_received_future_rechecked_and_expired(self):
        s = self.s
        r = request(
            s,
            1,
            "PERSON_ARRIVE",
            "W3",
            arrival_payload(s.world.config, "W3"),
            time_rule="AT_SIM_H",
            requested_sim_h=0.01,
            expires_sim_h=0.01,
        )
        s.receive(r)
        s.world.advance(0.02)
        s.boundary()
        self.assertEqual(s.receipts[-1]["reason"], "EXPIRED")

    def test_fixed_mode_keeps_empty_completion_semantics(self):
        s = self.s
        # Bound fixed manifest is prepared before constructing its writer.
        changes = [
            request(
                s,
                1,
                "ORDER_CANCEL",
                next(iter(s.order_products)),
                dict(reason="FIXED"),
                source="FIXED_MANIFEST",
            )
        ]
        spec = copy.deepcopy(s.spec)
        spec.update(
            mode="FIXED_PROTOCOL", scenario="C", fixed_event_manifest_sha256=digest(changes)
        )
        self.s = Session(
            spec,
            ProductionBackend(s.world.config, run_id=s.world.run_id),
            s.account.profile,
            Path(self.tmp.name) / "fixed",
            fixed_requests=changes,
        )
        self.s.submit(changes[0])
        result = self.execute()
        self.assertEqual(result.manifest["session_final"]["phase"], "COMPLETED")
        self.assertFalse(self.s.closed)

    def test_replay_uses_recorded_reception_time(self):
        s = self.s
        cancel = request(
            s,
            1,
            "ORDER_CANCEL",
            next(iter(s.order_products)),
            dict(reason="REPLAY"),
            source="REPLAY",
        )
        close = request(
            s,
            2,
            "CLOSE_INPUT",
            s.spec["run_id"],
            source="REPLAY",
            expected_catalog_version=1,
            expected_state_revision=3,
        )
        replay = dict(requests=[cancel, close], received_sim_h={"R1": 0, "R2": 0.02})
        spec = copy.deepcopy(s.spec)
        spec.update(mode="INTERACTIVE_REPLAY", replay_source_sha256=digest(replay))
        self.s = Session(
            spec,
            ProductionBackend(s.world.config, run_id=s.world.run_id),
            s.account.profile,
            Path(self.tmp.name) / "replay",
            replay_source=replay,
        )
        self.execute()
        self.assertEqual(next(r for r in self.s.receipts if r["request_id"] == "R2")["sim_h"], 0.02)

    def test_projection_rejects_resigned_candidate_as_actual(self):
        self.cancel()
        self.execute()
        s = self.s
        p = json.loads((s.output / "timeline.jsonl").read_text().splitlines()[0])
        p["upserts"].append(dict(row_id="FALSE", row_kind="PLAN", schedule_state="ACTUAL"))
        p["packet_sha256"] = digest({k: v for k, v in p.items() if k != "packet_sha256"})
        c = TimelineConsumer(s.spec["run_id"], 0, digest(s.spec))
        with self.assertRaisesRegex(ValueError, "TIMELINE_PLAN_AS_FACT"):
            c.consume(p)
        self.assertFalse(c.rows)


if __name__ == "__main__":
    unittest.main()
