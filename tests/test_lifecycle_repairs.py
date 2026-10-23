"""R01-R06 regressions through production entries and re-signed saved evidence."""

import copy
import gzip
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from dataclasses import asdict
from pathlib import Path

from run_lifecycle_witness import execute
from test_session_lifecycle import request, setup_session
from verify_lifecycle_session import verify

from adaptive_hrc_scheduling.contracts.session import digest, validate_bundle
from adaptive_hrc_scheduling.control.production_decisions import record
from adaptive_hrc_scheduling.control.production_loop import run
from adaptive_hrc_scheduling.control.session import submit_file
from adaptive_hrc_scheduling.dynamic_orders import template_registry
from adaptive_hrc_scheduling.timeline import TimelineConsumer


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def write(path, value):
    path.write_text(json.dumps(value) + "\n", encoding="utf-8")


def persist(s, result):
    root = s.output
    write(root / "configuration.json", asdict(s.history.initial))
    write(root / "report.json", result.manifest)
    write(root / "online-journal.json", s.policy.journal)
    write(
        root / "audits.json",
        dict(execution=asdict(result.audit), decisions=asdict(result.decision_audit)),
    )
    for name, data in (
        ("events", [asdict(e) for e in result.snapshot.events]),
        ("decisions", [record(d) for d in result.decisions]),
    ):
        with gzip.open(root / (name + ".jsonl.gz"), "wt", encoding="utf-8") as f:
            for row in data:
                f.write(json.dumps(row) + "\n")


def resign(root, state, commit, packets):
    write(root / "session-state.json", state)
    commit["final"] = copy.deepcopy(state["lifecycle"]["final"])
    commit["session_state_sha256"] = hashlib.sha256(
        (root / "session-state.json").read_bytes()
    ).hexdigest()
    previous, rows = "0" * 64, {}
    for p in packets:
        p["previous_packet_sha256"] = previous
        p["packet_sha256"] = digest({k: v for k, v in p.items() if k != "packet_sha256"})
        previous = p["packet_sha256"]
        rows.update({r["row_id"]: r for r in p["upserts"]})
        for key in p["removed"]:
            rows.pop(key, None)
    (root / "timeline.jsonl").write_text(
        "".join(json.dumps(p) + "\n" for p in packets), encoding="utf-8"
    )
    latest = read(root / "timeline-latest.json")
    latest.update(
        rows=list(rows.values()), packet_sha256=previous, envelope=packets[-1]["envelope"]
    )
    write(root / "timeline-latest.json", latest)
    commit["projection_files"] = {
        name: hashlib.sha256((root / name).read_bytes()).hexdigest()
        for name in ("timeline.jsonl", "timeline-latest.json")
    }
    write(root / "final-commit.json", commit)


class LifecycleRepairTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.tmp.cleanup)
        cls.root = Path(cls.tmp.name)
        seed = setup_session(cls.root / "seed")
        _, cls.active, ok = execute(
            seed.backend, seed.account.profile, cls.root / "active", case="active-drain"
        )
        assert ok
        cls.packets = [
            json.loads(x) for x in (cls.active.output / "timeline.jsonl").read_text().splitlines()
        ]

    def consumer(self):
        return TimelineConsumer(self.active.spec["run_id"], 0, digest(self.active.spec))

    def mutate(self, name, change, *, consumer=False):
        target = self.root / name
        shutil.copytree(self.active.output, target)
        state, commit = read(target / "session-state.json"), read(target / "final-commit.json")
        packets = copy.deepcopy(self.packets)
        change(state, commit, packets)
        resign(target, state, commit, packets)
        with self.assertRaises((ValueError, KeyError)):
            verify(target)
        if consumer:
            c = self.consumer()
            with self.assertRaises((ValueError, KeyError)):
                for packet in packets:
                    c.consume(packet)
            self.assertEqual(c.status, "STALE_CORRUPT")

    def test_valid_saved_and_consumer(self):
        self.assertEqual(verify(self.active.output)["status"], "PASS")
        c = self.consumer()
        for p in self.packets:
            c.consume(p)
        self.assertEqual(c.status, "VERIFIED")

    def test_completed_open_commitment(self):
        def change(s, c, p):
            c["obligations"]["commitments"] = ["UNFINISHED"]
            s["lifecycle"]["final"]["open_obligations"] += 1

        self.mutate("commitment", change)

    def test_invalid_terminal_phase(self):
        self.mutate("phase", lambda s, c, p: s["lifecycle"]["final"].update(phase="RUNNING_OPEN"))

    def test_false_window_terminal(self):
        def change(s, c, p):
            s["lifecycle"]["phase"] = s["lifecycle"]["final"]["phase"] = "WINDOW_CENSORED"
            s["lifecycle"]["transitions"][-1].update(
                phase="WINDOW_CENSORED", reason="WINDOW_CENSORED"
            )
            c["reason"] = "WINDOW_CENSORED"

        self.mutate("window", change)

    def test_missing_projection_commit(self):
        target = self.root / "missing-commit"
        shutil.copytree(self.active.output, target)
        commit = read(target / "final-commit.json")
        commit["projection_files"] = {}
        write(target / "final-commit.json", commit)
        with self.assertRaisesRegex(ValueError, "REQUIRED_PROJECTION_COMMIT"):
            verify(target)

    def rows(self, packets, kind):
        return [r for p in packets for r in p["upserts"] if r["row_kind"] == kind]

    def test_wrong_fact_product_operation(self):
        self.mutate(
            "fact-identity",
            lambda s, c, p: [
                r.update(product_id="FOREIGN", operation_id="FOREIGN", order_id="FOREIGN")
                for r in self.rows(p, "FACT_PREFIX")
            ],
            consumer=True,
        )

    def test_completed_fact_downgraded_open(self):
        def change(s, c, p):
            for r in self.rows(p, "FACT_PREFIX"):
                if r["end_status"] == "CLOSED":
                    r["end_status"] = "OPEN"
                    for k in ("end_h", "end_event_id", "readback_id"):
                        r.pop(k, None)

        self.mutate("closure", change, consumer=True)

    def test_false_envelope_identity(self):
        self.mutate(
            "envelope",
            lambda s, c, p: [
                x["envelope"].update(
                    catalog_version=999,
                    catalog_hash="f" * 64,
                    state_revision=999,
                    observation_id="FALSE",
                    initial_config_sha256="e" * 64,
                )
                for x in p
            ],
            consumer=True,
        )

    def test_missing_person_cost(self):
        self.mutate(
            "missing-cost",
            lambda s, c, p: [
                r.pop(k)
                for r in self.rows(p, "PERSON_INTERVAL")
                for k in ("presence", "availability", "labour_cost")
            ],
            consumer=True,
        )

    def test_false_person_cost(self):
        self.mutate(
            "false-cost",
            lambda s, c, p: [
                r.update(labour_cost=r["labour_cost"] + 100)
                for r in self.rows(p, "PERSON_INTERVAL")
            ],
            consumer=True,
        )

    def test_false_resource_start(self):
        self.mutate(
            "resource",
            lambda s, c, p: [
                r.update(start_h=r["start_h"] + 1) for r in self.rows(p, "RESOURCE_FACT")
            ],
            consumer=True,
        )

    def test_false_order_due(self):
        self.mutate(
            "order-due",
            lambda s, c, p: [x["orders"][0].update(due_h=99999) for x in p],
            consumer=True,
        )

    def test_false_priority(self):
        self.mutate(
            "priority",
            lambda s, c, p: [x["orders"][0].update(priority="URGENT") for x in p],
            consumer=True,
        )

    def test_false_plan_version(self):
        self.mutate(
            "plan-version",
            lambda s, c, p: [x["envelope"].update(plan_version=999) for x in p],
            consumer=True,
        )

    def test_false_source_interval(self):
        def change(s, c, packets):
            for p in packets:
                if p["source"]["intervals"]:
                    p["source"]["intervals"][0]["end_h"] += 0.1

        self.mutate("source-interval", change, consumer=True)

    def test_corruption_retains_last_trusted_view(self):
        c = self.consumer()
        c.consume(self.packets[0])
        before = copy.deepcopy((c.rows, c.envelope, c.orders, c.basis))
        p = copy.deepcopy(self.packets[1])
        p["orders"][0]["due_h"] = 99999
        p["packet_sha256"] = digest({k: v for k, v in p.items() if k != "packet_sha256"})
        with self.assertRaises(ValueError):
            c.consume(p)
        self.assertEqual((c.rows, c.envelope, c.orders, c.basis), before)

    def test_zero_event_callback_and_forged_boundaries(self):
        s = setup_session(self.root / "callback")
        result = run(
            s.backend, s.scenario(), session=s, joint_policy=s.policy, orderly_stop=lambda w: True
        )
        persist(s, result)
        self.assertEqual(verify(s.output)["status"], "PASS")
        for key, value in (
            ("accepted_revision", 1),
            ("accepted_h", 0.1),
            ("event_count_at_boundary", -1),
            ("event_count_at_boundary", 1),
        ):
            with self.subTest(key=key, value=value):
                target = self.root / ("callback-bad-" + key + str(value))
                shutil.copytree(s.output, target)
                state, commit = (
                    read(target / "session-state.json"),
                    read(target / "final-commit.json"),
                )
                state["lifecycle"]["stop_control"][key] = value
                packets = [
                    json.loads(x) for x in (target / "timeline.jsonl").read_text().splitlines()
                ]
                resign(target, state, commit, packets)
                with self.assertRaises(ValueError):
                    verify(target)

    def retry(self, file=False):
        s = setup_session(self.root / ("stop-file" if file else "stop-queue"))
        holder = {}

        def hook(backend, phase):
            if phase == "after_dispatch" and s.world.s.running and not holder:
                holder["request"] = request(s, 100, "STOP_REQUEST", s.spec["run_id"])
                s.submit(holder["request"])
            if phase == "before_stop_advance" and not holder.get("retry"):
                (submit_file(s.output, holder["request"]) if file else s.submit(holder["request"]))
                s.submit(
                    request(
                        s,
                        101,
                        "DEVICE_FAIL",
                        next(iter(s.world.devices)),
                        dict(reason="STOP_FENCE"),
                    )
                )
                holder["retry"] = True

        r = run(s.backend, s.scenario(), session=s, joint_policy=s.policy, execution_hook=hook)
        self.assertEqual(s.lifecycle.final["phase"], "STOPPED")
        self.assertEqual(r.audit.status, "PASS")
        self.assertFalse(s.world.s.running)
        self.assertEqual(s.queue.qsize(), 0)
        self.assertEqual(
            next(x for x in s.receipts if x["request_id"] == "R101")["reason"], "SESSION_STOPPED"
        )
        self.assertEqual(sum(e.kind == "STARTED" for e in s.world.events), 1)

    def test_stop_queue_retry(self):
        self.retry()

    def test_stop_file_retry(self):
        self.retry(file=True)

    def test_replay_bundle_cli(self):
        s = setup_session(self.root / "replay-seed")
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
        source = dict(requests=[cancel, close], received_sim_h={"R1": 0, "R2": 0.02})
        spec = dict(s.spec, mode="INTERACTIVE_REPLAY", replay_source_sha256=digest(source))
        bundle = dict(
            spec=spec, profile=asdict(s.account.profile), fixed_requests=[], replay_source=source
        )
        self.assertEqual(validate_bundle(bundle), bundle)
        write(self.root / "bundle.json", bundle)
        write(self.root / "config.json", asdict(s.history.initial))
        output = self.root / "replay-cli"
        p = subprocess.run(
            [
                sys.executable,
                str(Path(__file__).resolve().parents[1] / "scripts/run_session.py"),
                "--configuration",
                str(self.root / "config.json"),
                "--bundle",
                str(self.root / "bundle.json"),
                "--output",
                str(output),
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(verify(output)["status"], "PASS")
        saved = read(output / "session-state.json")
        self.assertEqual(
            next(r for r in saved["receipts"] if r["request_id"] == "R2")["sim_h"], 0.02
        )

    def test_priority_visible_only_after_application(self):
        published = []
        for priority in ("NORMAL", "URGENT"):
            s = setup_session(self.root / priority)
            payload = dict(
                order_id="NEW",
                template_id="SR-W1",
                template_revision="v1",
                template_sha256=template_registry()["SR-W1"],
                quantity=1,
                due_sim_h=100,
                priority=priority,
                material_plan_id="TEMPLATE-DELAY-1H-v1",
                arrival_rule="REQUEST_EFFECTIVE_TIME",
            )
            s.receive(
                request(
                    s, 1, "ORDER_CREATE", "NEW", payload, time_rule="AT_SIM_H", requested_sim_h=0.01
                )
            )
            for at in (0, 0.01):
                if at:
                    s.world.advance(at)
                s.boundary()
                obs = s.world.observe()
                s.world.deliver()
                s.bind_observation(obs)
                s.projection.publish(obs)
            packets = [
                json.loads(x) for x in (s.output / "timeline.jsonl").read_text().splitlines()
            ]
            self.assertFalse(any(x["order_id"] == "NEW" for x in packets[0]["orders"]))
            self.assertFalse(packets[0]["source"]["generations"])
            order = next(x for x in packets[-1]["orders"] if x["order_id"] == "NEW")
            self.assertEqual(order["priority"], priority)
            published.append(order)
            consumer = TimelineConsumer(s.spec["run_id"], 0, digest(s.spec))
            for p in packets:
                consumer.consume(p)
        self.assertEqual(published[0]["due_h"], published[1]["due_h"])

    def test_valid_censor_reasons(self):
        for name, kwargs in (
            ("window", {}),
            ("turn", dict(max_turns=1)),
            ("checkpoint", dict(stop_condition=lambda w: True)),
        ):
            with self.subTest(reason=name):
                s = setup_session(self.root / ("censor-" + name), until=0.01)
                if name == "window":
                    for n, order in enumerate(s.order_products, 1):
                        s.submit(request(s, n, "ORDER_CANCEL", order, dict(reason="CENSOR")))
                result = run(s.backend, s.scenario(), session=s, joint_policy=s.policy, **kwargs)
                persist(s, result)
                self.assertEqual(verify(s.output)["phase"], "WINDOW_CENSORED")

    def test_initial_urgent_priority(self):
        from adaptive_hrc_scheduling.control.session import Session
        from adaptive_hrc_scheduling.production_backend import ProductionBackend

        seed = setup_session(self.root / "initial-urgent-seed")
        spec = copy.deepcopy(seed.spec)
        spec["initial_orders"][0]["priority"] = "URGENT"
        s = Session(
            spec,
            ProductionBackend(seed.history.initial, run_id=spec["run_id"]),
            seed.account.profile,
            self.root / "initial-urgent",
        )
        obs = s.world.observe()
        s.world.deliver()
        s.bind_observation(obs)
        s.projection.publish(obs)
        p = json.loads((s.output / "timeline.jsonl").read_text().splitlines()[0])
        c = TimelineConsumer(spec["run_id"], 0, digest(spec))
        c.consume(p)
        self.assertEqual(c.view()["orders"][0]["priority"], "URGENT")

    def test_unscheduled_rows_stable_across_same_observation(self):
        s = setup_session(self.root / "stable-unscheduled")
        obs = s.world.observe()
        s.world.deliver()
        s.bind_observation(obs)
        for _ in range(3):
            s.projection.publish(obs)
        packets = [json.loads(x) for x in (s.output / "timeline.jsonl").read_text().splitlines()]
        self.assertTrue(packets[0]["upserts"])
        self.assertTrue(all(not p["upserts"] and not p["removed"] for p in packets[1:]))
        c = TimelineConsumer(s.spec["run_id"], 0, digest(s.spec))
        for p in packets:
            c.consume(p)


if __name__ == "__main__":
    unittest.main()
