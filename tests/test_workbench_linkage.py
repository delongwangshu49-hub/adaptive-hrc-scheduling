"""Contract-level tests for simultaneous native/schedule views and event transport."""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / p) for p in ("scripts", "desktop/p051/src", "desktop/s19b/src")]

from p051_desktop.geometry import dual_plan  # noqa: E402
from p051_desktop.linkage import (  # noqa: E402
    last_scene_capture,  # noqa: E402
    queue_view,
    read_bound,
    snapshot_result,
)
from p051_scene_link import label_visible, mapped_selection, related_work_ids  # noqa: E402


class LinkageTests(unittest.TestCase):
    def test_unchanged_physical_selection_refreshes_when_operation_catalog_changes(self):
        from p051_scene_link import SceneLink

        entities = [dict(id="PART", kind="part", paths=["/World/Part"])]
        link = SceneLink(
            Path("unused"),
            dict(run_id="R", request_id="Q"),
            Mock(),
            Mock(),
            "camera",
            lambda: entities,
            Mock(),
            Mock(),
            Mock(),
            Mock(),
        )
        link.selection = lambda: Mock(get_selected_prim_paths=lambda: ["/World/Part"])
        link.presentation = Mock()
        with (
            patch("p051_scene_link.visible_paths", return_value=["/World/Part"]),
            patch("p051_scene_link.atomic_json") as write,
        ):
            link.publish(force=True)
            first = write.call_args.args[1]["selection"]
            entities.append(dict(id="OP-NEW", kind="operation", targets=["PART"], paths=[]))
            link.publish(force=True)
            second = write.call_args.args[1]["selection"]
            self.assertGreater(second["sequence"], first["sequence"])
            self.assertEqual(second["entity_ids"], first["entity_ids"])
            self.assertEqual(second["related_ids"], ["OP-NEW", "PART"])
            link.publish(force=True)
            self.assertEqual(write.call_args.args[1]["selection"], second)

    def test_scene_label_density_preserves_zones_and_selected_objects(self):
        self.assertTrue(label_visible("/World/Pads/J2/Label", 100, []))
        self.assertTrue(label_visible("/World/Safety/Gate/Label", 100, []))
        self.assertFalse(label_visible("/World/P043/People/W1/Label", 100, []))
        self.assertTrue(label_visible("/World/P043/People/W1/Label", 20, []))
        self.assertTrue(
            label_visible("/World/P043/People/W1/Label", 100, ["/World/P043/People/W1"])
        )
        self.assertFalse(
            label_visible("/World/P043/People/W1/Label", 100, ["/World/P043/People/W10"])
        )

    def test_last_frame_rejects_wrong_run_changed_bytes_and_paths(self):
        import hashlib

        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            launch = dict(run_id="R", request_id="L")
            (root / "request.json").write_text(json.dumps(launch))
            raw = b"\x89PNG\r\n\x1a\nfixture"
            image = root / "scene-after.png"
            image.write_bytes(raw)
            result = dict(
                **launch,
                epoch=0,
                image=image.name,
                image_sha256=hashlib.sha256(raw).hexdigest(),
                scope="STATIC_FINAL_CAPTURE_NOT_LIVE_OR_REPLAY",
            )
            path = root / "p051-scene-last-frame.json"
            path.write_text(json.dumps(result))
            import base64

            self.assertEqual(
                base64.b64decode(last_scene_capture(root, "R")["image_url"].split(",")[1]), raw
            )
            self.assertIsNone(last_scene_capture(root, "OTHER"))
            image.write_bytes(raw + b"changed")
            self.assertIsNone(last_scene_capture(root, "R"))
            image.write_bytes(raw)
            result["image"] = "../scene-after.png"
            path.write_text(json.dumps(result))
            self.assertIsNone(last_scene_capture(root, "R"))

    def test_readable_plot_budget_and_form_coexistence(self):
        for width, height in ((1280, 720), (1366, 768), (1920, 1080)):
            for form, proportion in ((False, 0.65), (True, 0.5)):
                layout, _ = dual_plan(width, height, form_open=form)
                self.assertGreaterEqual((layout.plots[0].height - 16) / height, proportion)

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

    def test_physical_part_links_only_to_declared_operation_targets(self):
        rows = [
            dict(id="OP1", kind="operation", targets=["PART"]),
            dict(id="OP2", kind="operation", targets=["OTHER"]),
        ]
        self.assertEqual(related_work_ids(["PART"], rows), ["OP1", "PART"])
        self.assertEqual(related_work_ids([], rows), [])

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
