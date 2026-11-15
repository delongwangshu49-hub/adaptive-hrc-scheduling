"""Contract-level tests for simultaneous native/schedule views and event transport."""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / p) for p in ("scripts", "desktop/p051/src", "desktop/s19b/src")]

from p051_desktop.geometry import dual_plan  # noqa: E402
from p051_desktop.linkage import queue_view, read_bound, snapshot_result  # noqa: E402
from p051_scene_link import mapped_selection  # noqa: E402


class LinkageTests(unittest.TestCase):
    def test_domain_person_ids_map_to_unique_usd_paths_and_keep_legacy_ids(self):
        from adaptive_hrc_scheduling.workforce_session import scene_person_path

        self.assertEqual(scene_person_path("W3"), "/World/P043/People/W3")
        ids = ["PERSON-LINK", "person.name", "1PERSON", "id_504552534f4e2d4c494e4b", "W3"]
        paths = [scene_person_path(pid) for pid in ids]
        self.assertEqual(len(set(paths)), len(paths))
        for path in paths:
            self.assertRegex(path, r"^/World/P043/People/[A-Za-z_][A-Za-z0-9_]*$")

    def test_gui_person_preview_uses_canonical_scene_path_for_hyphenated_id(self):
        from test_p051_client import AdapterTests

        from adaptive_hrc_scheduling.workforce_session import check_request, scene_person_path

        fixture = AdapterTests()
        fixture.setUp()
        try:
            fixture.client.spec["backend"] = "ISAAC"
            fixture.session.spec["backend"] = "ISAAC"
            request = fixture.client.build_request(
                dict(
                    kind="PERSON_ARRIVE",
                    target_id="PERSON-LINK",
                    payload=dict(template_id="P043-W1-v1", arrival_location="F1", initial_f=0.1),
                )
            )
            self.assertEqual(
                request["payload"]["scene_reference"]["prim_path"], scene_person_path("PERSON-LINK")
            )
            check_request(fixture.session, request)
            request["payload"]["scene_reference"]["prim_path"] = "/World/P043/People/PERSON-LINK"
            with self.assertRaisesRegex(ValueError, "PERSON_SCENE_PATH"):
                check_request(fixture.session, request)
        finally:
            fixture.client.schedules.close()
            fixture.tearDown()

    def test_scene_export_rejects_changed_bytes_and_cross_run_evidence(self):
        import hashlib

        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "p051-view-results").mkdir()
            image = root / "capture.png"
            image.write_bytes(b"captured image")
            path = root / "p051-view-results/000000000002.json"
            launch = dict(run_id="R", request_id="L")
            result = dict(
                **launch,
                epoch=0,
                sequence=2,
                action="snapshot",
                accepted=True,
                image=image.name,
                image_sha256=hashlib.sha256(image.read_bytes()).hexdigest(),
            )
            path.write_text(json.dumps(result))
            self.assertEqual(snapshot_result(root, launch, 2)[0], image.resolve())
            self.assertIsNone(snapshot_result(root, dict(run_id="OTHER", request_id="L"), 2))
            image.write_bytes(b"changed")
            with self.assertRaisesRegex(ValueError, "SCENE_EXPORT_DIGEST"):
                snapshot_result(root, launch, 2)
            result["image"] = "../capture.png"
            path.write_text(json.dumps(result))
            with self.assertRaisesRegex(ValueError, "SCENE_EXPORT_PATH"):
                snapshot_result(root, launch, 2)

    def test_modes_keep_two_useful_panels_at_supported_sizes(self):
        for w, h in [(1280, 720), (1366, 768), (1920, 1080)]:
            for ratio in [0.42, 0.5, 0.58, 0.1, 0.9]:
                for form in [False, True]:
                    layout, chrome = dual_plan(w, h, split_ratio=ratio, form_open=form)
                    self.assertTrue(layout.geometry_admissible)
                    self.assertGreaterEqual(layout.plots[0].width, 500)
                    self.assertGreaterEqual(layout.plots[1].width, 300)
                    self.assertGreaterEqual(layout.plots[0].height, 160)
                    self.assertEqual(layout.plots[0].height, layout.plots[1].height)
                    self.assertLessEqual(
                        layout.plots[0].x + layout.plots[0].width,
                        layout.plots[1].x - layout.label_width,
                    )
                    self.assertGreater(chrome["aux_y"], layout.plots[0].y + layout.plots[0].height)

    def test_selection_maps_native_descendants_to_specific_entities(self):
        entities = [
            dict(id="PRODUCT", kind="product", paths=["/World/P"]),
            dict(id="PART", kind="entity", paths=["/World/P/Part"]),
            dict(id="OP", kind="operation", paths=["/World/P/Part"]),
        ]
        self.assertEqual(mapped_selection(["/World/P/Part/mesh"], entities), ["PART"])
        self.assertEqual(mapped_selection(["/World/Unknown"], entities), [])

    def test_fast_view_commands_keep_distinct_durable_ids_across_reconnect(self):
        with tempfile.TemporaryDirectory() as d:
            launch = dict(run_id="R", request_id="L")
            first = queue_view(d, launch, "locate", dict(entity_id="P1"), 0)
            second = queue_view(d, launch, "focus", dict(entity_id="P2"), 0)
            self.assertEqual((first, second), (1, 2))
            paths = sorted((Path(d) / "p051-view-inbox").glob("*.json"))
            self.assertEqual([json.loads(p.read_bytes())["entity_id"] for p in paths], ["P1", "P2"])

    def test_foreign_scene_evidence_is_not_accepted(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "context.json"
            p.write_text(json.dumps(dict(run_id="R", request_id="old", epoch=0)))
            self.assertIsNone(read_bound(p, dict(run_id="R", request_id="new")))

    def test_reversed_file_enumeration_preserves_producer_confirmation_order(self):
        from test_p051_client import AdapterTests

        from adaptive_hrc_scheduling.control.gui_confirmation import bind_pending

        fixture = AdapterTests()
        fixture.setUp()
        try:
            requests = []
            for device in fixture.session.world.config.devices[:2]:
                r = fixture.client.build_request(
                    dict(kind="DEVICE_FAIL", target_id=device.id, payload=dict(reason="ORDER_TEST"))
                )
                fixture.client.submit(r)
                requests.append(r)
            original = Path.glob
            inbox = fixture.path / "p051-confirmations/inbox"

            def reversed_files(path, pattern):
                paths = list(original(path, pattern))
                if path == inbox:
                    paths.sort(
                        key=lambda p: json.loads(p.read_bytes())["client_sequence"], reverse=True
                    )
                return iter(paths)

            with patch.object(Path, "glob", reversed_files):
                for _ in requests:
                    bind_pending(fixture.session)
                    fixture.session.boundary()
            for r in requests:
                statuses = [
                    x["status"]
                    for x in fixture.session.receipts
                    if x["request_id"] == r["request_id"]
                ]
                self.assertEqual(statuses, ["ACCEPTED", "APPLIED"])
            reconnect = type(fixture.client)(fixture.path, writable=True)
            self.addCleanup(reconnect.schedules.close)
            self.assertEqual(reconnect.journal["sequence"], 2)
            with self.assertRaisesRegex(ValueError, "DO_NOT_RESUBMIT"):
                reconnect.submit(requests[0])
        finally:
            fixture.client.schedules.close()
            fixture.tearDown()
