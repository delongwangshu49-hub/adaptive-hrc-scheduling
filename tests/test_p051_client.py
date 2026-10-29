"""UI adapters exercised against actual P04 Session/TimelinePublisher output."""

import json
import sys
import tempfile
import time
import unittest
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [
    str(ROOT / "desktop/p051/src"),
    str(ROOT / "desktop/s19b/src"),
    str(ROOT / "scripts"),
]

from build_simulation_production import configuration as base  # noqa: E402
from p051_desktop.client import Client, prepare_launch  # noqa: E402
from p051_desktop.projection import WorkColors  # noqa: E402

from adaptive_hrc_scheduling.contracts.session import digest  # noqa: E402
from adaptive_hrc_scheduling.control.online import Limits  # noqa: E402
from adaptive_hrc_scheduling.control.session import Session  # noqa: E402
from adaptive_hrc_scheduling.control.session_budget import Profile  # noqa: E402
from adaptive_hrc_scheduling.control.session_lifecycle import enable  # noqa: E402
from adaptive_hrc_scheduling.dynamic_workforce import registry  # noqa: E402
from adaptive_hrc_scheduling.production_backend import ProductionBackend  # noqa: E402
from adaptive_hrc_scheduling.workforce_session import configuration, make_spec  # noqa: E402


class AdapterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "session"
        c = configuration(base())
        p = Profile(
            "P051-TEST",
            Limits(decision_seconds=5, search_seconds=1),
            100,
            2,
            "P042_URGENCY_DUE_PROGRESS_EXPOSURE-r1",
        )
        spec = enable(
            make_spec(
                c,
                p,
                run_id="P051-TEST",
                method="EDD",
                until_h=1,
                rates={k: 10 for k in [*[x.id for x in c.people], *registry()]},
            )
        )
        self.session = Session(spec, ProductionBackend(c, run_id=spec["run_id"]), p, self.path)
        self.session.projection.publish(self.session.world.observe())
        self.client = Client(self.path, writable=True)
        self.client.poll()

    def tearDown(self):
        self.temp.cleanup()

    def form(self, **changes):
        return dict(
            kind="ORDER_CREATE",
            target_id="NEW-ORDER",
            payload=dict(template_id="SR-W1", quantity=1, due_sim_h=10, priority="NORMAL"),
            **changes,
        )

    def test_real_projection_verified_and_never_plans_as_actual(self):
        view = self.client.snapshot()
        self.assertEqual(view["status"], "VERIFIED")
        self.assertTrue(view["writable"])
        self.assertTrue(view["rows"])
        self.assertTrue(all(r["schedule_state"] == "UNSCHEDULED" for r in view["rows"]))

    def test_exact_order_preview_and_single_publication(self):
        r = self.client.build_request(self.form())
        self.assertEqual(r["payload"]["order_id"], "NEW-ORDER")
        self.client.submit(r)
        self.assertEqual(len(list((self.path / "p051-confirmations/inbox").glob("*.json"))), 1)
        with self.assertRaisesRegex(ValueError, "DO_NOT_RESUBMIT"):
            self.client.submit(r)
        restored = Client(self.path, writable=True)
        self.assertEqual(restored.journal["sequence"], 1)
        self.assertEqual(restored.journal["requests"][r["request_id"]], r)

    def test_shared_writer_admission_and_receipt_are_not_business_completion(self):
        r = self.client.build_request(self.form())
        self.client.submit(r)
        receipt = self.session.receive(r)
        self.assertEqual(receipt["status"], "ACCEPTED")
        self.session.projection.publish(self.session.world.observe())
        view = self.client.poll()
        self.assertEqual(view["receipts"][-1]["status"], "ACCEPTED")
        self.assertEqual(view["business_results"], [])

    def test_corrupt_packet_freezes_last_rows_and_disables_writes(self):
        old = deepcopy(self.client.consumer.rows)
        packet = json.loads((self.path / "timeline.jsonl").read_text().splitlines()[0])
        packet["sequence"] = 2
        with (self.path / "timeline.jsonl").open("a") as stream:
            stream.write(json.dumps(packet) + "\n")
        view = self.client.poll()
        self.assertEqual(view["status"], "STALE_CORRUPT")
        self.assertEqual(self.client.consumer.rows, old)
        self.assertFalse(view["writable"])
        with self.assertRaisesRegex(ValueError, "STALE"):
            self.client.build_request(self.form())

    def test_partial_line_not_consumed_and_truncation_fails_closed(self):
        offset = self.client.offset
        with (self.path / "timeline.jsonl").open("ab") as stream:
            stream.write(b'{"partial":')
        self.client.poll()
        self.assertEqual(self.client.offset, offset)
        (self.path / "timeline.jsonl").write_bytes(b"{}")
        self.assertEqual(self.client.poll()["status"], "STALE_CORRUPT")

    def test_archived_or_old_frame_cannot_become_fresh_by_replay(self):
        self.client.consumer.envelope["sampled_monotonic_s"] = time.monotonic() - 6
        self.assertFalse(self.client.snapshot()["writable"])
        self.assertEqual(self.client.snapshot()["status"], "STALE")
        readonly = Client(self.path, writable=False)
        self.assertFalse(readonly.poll()["writable"])

    def test_return_has_no_initial_f_and_arrival_uses_registered_qualification(self):
        arrived = self.client.build_request(
            dict(
                kind="PERSON_ARRIVE",
                target_id="W3",
                payload=dict(initial_f=0.2, arrival_location="F1"),
            )
        )
        self.assertEqual(arrived["payload"]["initial_f"], 0.2)
        self.assertIn("calendar_sha256", arrived["payload"])
        returned = self.client.build_request(
            dict(
                kind="PERSON_RETURN",
                target_id="W1",
                payload=dict(arrival_location="F1", scene_entity_id="W1"),
            )
        )
        self.assertNotIn("initial_f", returned["payload"])

    def test_launch_binds_shared_worker_start_envelope_and_rate(self):
        directory, request = prepare_launch(
            ROOT, self.path / "runs", dict(backend="light", method="EDD", simulation_rate=0.1)
        )
        self.assertTrue((directory / "start-command.json").is_file())
        self.assertEqual(request["session"]["spec"]["clock"]["simulation_rate"], 0.1)
        self.assertEqual(request["session"]["spec"]["schema_version"], "P04.4-SESSION-r1")

    def test_work_identity_survives_new_keys_and_current_conflicts_clear(self):
        c = WorkColors("R", 0)

        def v(rows):
            return dict(envelope=dict(run_id="R", epoch=0), rows=rows)

        rows = [
            dict(
                row_id="a",
                product_id="P",
                activity_id="A",
                start_h=0,
                end_h=1,
                resource_id="X",
                schedule_state="ACTUAL",
            )
        ]
        first = c.project(v(rows), dict(operations=[]))["rows"][0]
        rows.append(
            dict(
                row_id="b",
                product_id="P",
                activity_id="0",
                start_h=0,
                end_h=1,
                resource_id="X",
                schedule_state="ACTUAL",
            )
        )
        after = c.project(v(rows), dict(operations=[]))["rows"][0]
        self.assertEqual(
            (first["work_number"], first["color"]), (after["work_number"], after["color"])
        )
        a, b = [r["work_key"] for r in c.project(v(rows), dict(operations=[]))["rows"]]
        c.cache[b] = c.cache[a]
        self.assertEqual(
            c.project(v(rows), dict(operations=[]))["color_collision_pairs"],
            [tuple(sorted((a, b)))],
        )
        rows[1]["start_h"] = 2
        rows[1]["end_h"] = 3
        self.assertEqual(c.project(v(rows), dict(operations=[]))["color_collision_pairs"], [])

    def test_idle_person_interval_with_null_command_uses_stable_service_identity(self):
        c = WorkColors("R", 0)
        row = dict(
            row_id="person:0",
            person_id="W1",
            command_id=None,
            start_h=0,
            end_h=1,
            schedule_state="ACTUAL",
        )
        result = c.project(
            dict(envelope=dict(run_id="R", epoch=0), rows=[row]), dict(operations=[])
        )
        self.assertTrue(result["rows"][0]["work_key"].endswith("service:W1"))

    def test_cached_event_prefix_hashes_match_full_digest_and_failed_packet_does_not_commit(self):
        self.session.world.advance(0.01)
        self.session.projection.publish(self.session.world.observe())
        packet = json.loads((self.path / "timeline.jsonl").read_text().splitlines()[-1])
        damaged = deepcopy(packet)
        damaged["envelope"]["event_prefix_hash"] = "f" * 64
        damaged["packet_sha256"] = digest(
            {k: v for k, v in damaged.items() if k != "packet_sha256"}
        )
        prior = self.client.consumer.sequence
        with self.assertRaises(ValueError):
            self.client.consumer.consume(damaged)
        self.assertEqual(self.client.consumer.sequence, prior)
        self.client.consumer.consume(packet)
        for n, value in self.client.consumer._prefix_hashes.items():
            self.assertEqual(value, digest(self.client.consumer.events[:n]))


if __name__ == "__main__":
    unittest.main()
