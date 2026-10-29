"""Owner horizontal layout and cached/uncached semantic equivalence."""

import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "desktop/p051/src"))
import test_p051_client as fixtures
from p051_desktop.geometry import plan

from adaptive_hrc_scheduling.contracts.session import digest
from adaptive_hrc_scheduling.timeline_validation import validate


class LayoutTests(unittest.TestCase):
    def test_reviewed_sizes_keep_equal_panels_without_blank_native_gutter(self):
        for width, height in [(1280, 720), (1366, 768), (1920, 1080)]:
            for form in [False, True]:
                p = plan(width, height, form_open=form)
                a, b = p.plots
                self.assertTrue(p.geometry_admissible)
                self.assertEqual(p.orientation, "horizontal")
                self.assertEqual((a.y, a.width, a.height), (b.y, b.width + p.label_width, b.height))
                self.assertLess(a.x + a.width, b.x)
                self.assertGreaterEqual(a.width, 500)
                self.assertGreaterEqual(a.height, 160)


class CacheTests(unittest.TestCase):
    setUp = fixtures.AdapterTests.setUp
    tearDown = fixtures.AdapterTests.tearDown

    def test_cache_matches_uncached_oracle_and_corruption_does_not_commit(self):
        self.session.world.advance(0.01)
        self.session.projection.publish(self.session.world.observe())
        self.client.poll()
        c = self.client.consumer
        packet = copy.deepcopy(self.client.packet)
        validate(packet, c.events, c.rows, c.basis, prefix_hashes=c._prefix_hashes)
        self.assertIsNotNone(c._validation_cache["initial"])
        previous = dict(c._validation_cache)
        self.session.world.advance(0.02)
        self.session.projection.publish(self.session.world.observe())
        import json

        packet = json.loads((self.path / "timeline.jsonl").read_text().splitlines()[-1])
        packet["workforce_statistics"]["people"]["W1"]["fatigue"] = 0.9
        packet["packet_sha256"] = digest({k: v for k, v in packet.items() if k != "packet_sha256"})
        with self.assertRaises(ValueError):
            c.consume(packet)
        self.assertEqual(c._validation_cache, previous)

    def test_dynamic_order_resets_catalog_checkpoint_then_reuses_exact_new_history(self):
        request = self.client.build_request(
            dict(
                kind="ORDER_CREATE",
                target_id="P051-NEW",
                payload=dict(template_id="SR-W1", quantity=1, due_sim_h=10, priority="URGENT"),
            )
        )
        self.session.receive(request)
        self.session.boundary()
        self.session.projection.publish(self.session.world.observe())
        self.client.poll()
        self.assertEqual(self.client.receipts[request["request_id"]]["status"], "APPLIED")
        for time_h in [0.01, 0.02]:
            self.session.world.advance(time_h)
            self.session.projection.publish(self.session.world.observe())
            self.client.poll()
            c = self.client.consumer
            validate(self.client.packet, c.events, c.rows, c.basis, prefix_hashes=c._prefix_hashes)

    def test_confirmation_binds_current_verified_revision_without_changing_business_payload(self):
        r = self.client.build_request(
            dict(
                kind="ORDER_CREATE",
                target_id="CONFIRMED",
                payload=dict(template_id="SR-W1", quantity=1, due_sim_h=10, priority="NORMAL"),
            )
        )
        self.session.world.advance(0.01)
        self.session.projection.publish(self.session.world.observe())
        self.client.poll()
        self.client.submit(r)
        sent = self.client.journal["requests"][r["request_id"]]
        self.assertEqual(sent["payload"], r["payload"])
        self.assertEqual(sent["request_id"], r["request_id"])
        self.assertEqual(sent["expected_state_revision"], self.session.world.s.revision)
        self.assertEqual(self.session.receive(sent)["status"], "ACCEPTED")


class ConfirmationTests(unittest.TestCase):
    setUp = fixtures.AdapterTests.setUp
    tearDown = fixtures.AdapterTests.tearDown

    def request(self):
        return self.client.build_request(
            dict(
                kind="ORDER_CREATE",
                target_id="BOUND-NEW",
                payload=dict(template_id="SR-W1", quantity=1, due_sim_h=10, priority="URGENT"),
            )
        )

    def test_boundary_binds_once_then_original_session_applies_unchanged_payload(self):
        from adaptive_hrc_scheduling.control.gui_confirmation import bind_pending

        r = self.request()
        self.client.submit(r)
        self.session.world.advance(0.01)
        bound = bind_pending(self.session)
        self.assertEqual(bound["status"], "BOUND")
        self.assertEqual(bound["request"]["payload"], r["payload"])
        self.assertNotEqual(
            bound["request"]["expected_state_revision"], r["expected_state_revision"]
        )
        self.session.boundary()
        self.assertEqual(self.session.receipts[-1]["status"], "APPLIED")
        self.assertIsNone(bind_pending(self.session))
        self.assertEqual(len(list((self.path / "inbox").glob("*.json"))), 1)
        self.session.projection.publish(self.session.world.observe())
        v = self.client.poll()
        self.assertEqual(v["receipts"][-1]["status"], "APPLIED")
        self.assertEqual(v["submitted"][-1], bound["request"])

    def test_changed_target_is_rejected_and_never_published_or_retried(self):
        from adaptive_hrc_scheduling.control.gui_confirmation import bind_pending

        r = self.request()
        self.client.submit(r)
        self.session.catalog["objects"][r["target_id"]] = {"kind": "order", "revision": 1}
        result = bind_pending(self.session)
        self.assertEqual(result["status"], "REJECTED")
        self.assertIn("TARGET_CHANGED", result["reason"])
        self.assertFalse(list((self.path / "inbox").glob("*.json")))
        self.assertIsNone(bind_pending(self.session))
        self.assertEqual(self.client.poll()["receipts"][-1]["status"], "REJECTED")

    def test_tampered_final_bound_payload_fails_closed(self):
        from adaptive_hrc_scheduling.contracts.session import canonical, request_digest
        from adaptive_hrc_scheduling.control.gui_confirmation import bind_pending

        r = self.request()
        self.client.submit(r)
        v = bind_pending(self.session)
        v["request"]["payload"]["quantity"] = 2
        v["request"]["request_digest"] = request_digest(v["request"])
        p = self.path / "p051-confirmations/results" / (r["request_id"] + ".json")
        p.write_bytes(canonical(v))
        self.assertFalse(self.client.poll()["writable"])
        self.assertEqual(self.client.consumer.status, "STALE_CORRUPT")


class DeltaTests(unittest.TestCase):
    def test_incremental_display_reconstructs_full_rows_and_conflicts_then_resets_identity(self):
        from p051_desktop.delta import ProjectionDelta

        delta = ProjectionDelta()
        rows = {}
        for view in [
            dict(
                envelope=dict(run_id="A", epoch=0),
                rows=[dict(row_id="a", color_collision=False), dict(row_id="b")],
            ),
            dict(
                envelope=dict(run_id="A", epoch=0),
                rows=[dict(row_id="a", color_collision=True), dict(row_id="c")],
            ),
            dict(envelope=dict(run_id="B", epoch=0), rows=[dict(row_id="d")]),
        ]:
            wire = delta.encode(view)
            if wire["rows_mode"] == "replace":
                rows = {}
            for key in wire["row_deletes"]:
                rows.pop(key, None)
            rows.update({r["row_id"]: r for r in wire["rows"]})
            self.assertEqual(rows, {r["row_id"]: r for r in view["rows"]})
        self.assertEqual(delta.encode(view)["rows"], [])


class PersonResultTests(unittest.TestCase):
    setUp = fixtures.AdapterTests.setUp
    tearDown = fixtures.AdapterTests.tearDown

    def test_departure_business_result_requires_actual_verified_event(self):
        from adaptive_hrc_scheduling.control.gui_confirmation import bind_pending

        r = self.client.build_request(
            dict(
                kind="PERSON_DEPART",
                target_id="W2",
                payload=dict(reason="UI_TEST", handover_policy="SAFE_POINT_OR_VERIFIED_HANDOVER"),
            )
        )
        self.client.submit(r)
        self.assertFalse(self.client.snapshot()["business_results"])
        bind_pending(self.session)
        self.session.boundary()
        self.session.projection.publish(self.session.world.observe())
        v = self.client.poll()
        result = next(x for x in v["business_results"] if x["request_id"] == r["request_id"])
        self.assertEqual(result["status"], "DEPARTED")
        self.assertTrue(result["event_id"])

    def test_occupancy_and_person_segment_share_the_actual_work_identity_and_color(self):
        from p051_desktop.projection import WorkColors

        v = dict(
            envelope=dict(run_id="R", epoch=0),
            rows=[
                dict(
                    row_id="a",
                    row_kind="FACT_PREFIX",
                    command_id="CMD",
                    product_id="P",
                    activity_id="A",
                    operation_id="OP",
                    start_h=0,
                    end_h=1,
                ),
                dict(
                    row_id="b",
                    row_kind="RESOURCE_FACT",
                    command_id="CMD",
                    resource_id="D",
                    start_h=0,
                    end_h=1,
                ),
                dict(
                    row_id="c",
                    row_kind="PERSON_INTERVAL",
                    command_id="CMD",
                    person_id="W",
                    start_h=0,
                    end_h=1,
                ),
            ],
        )
        rows = WorkColors("R", 0).project(v, dict(operations=[]))["rows"]
        self.assertEqual(len({(r["work_key"], r["work_number"], r["color"]) for r in rows}), 1)


class MalformedConfirmationTests(unittest.TestCase):
    setUp = fixtures.AdapterTests.setUp
    tearDown = fixtures.AdapterTests.tearDown

    def test_malformed_confirmation_is_reported_once_without_crashing_or_entering_session(self):
        from adaptive_hrc_scheduling.control.gui_confirmation import bind_pending

        p = self.path / "p051-confirmations/inbox/bad.json"
        p.parent.mkdir(parents=True)
        p.write_text("[]")
        self.assertIsNone(bind_pending(self.session))
        self.assertIsNone(bind_pending(self.session))
        self.assertEqual(len(self.session.protocol_errors), 1)
        self.assertFalse(self.session.requests)

    def test_non_gui_confirmation_cannot_acquire_the_gui_boundary_binding(self):
        from adaptive_hrc_scheduling.contracts.session import request_digest
        from adaptive_hrc_scheduling.control.gui_confirmation import bind_pending
        from adaptive_hrc_scheduling.control.session import submit_file

        r = ConfirmationTests.request(self)
        r["source"] = "CLI"
        r["request_digest"] = request_digest(r)
        (self.path / "p051-confirmations/inbox").mkdir(parents=True)
        submit_file(self.path / "p051-confirmations", r)
        result = bind_pending(self.session)
        self.assertEqual(result["status"], "REJECTED")
        self.assertEqual(result["reason"], "CONFIRMATION_SOURCE")
        self.assertFalse(list((self.path / "inbox").glob("*.json")))
