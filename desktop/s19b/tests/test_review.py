"""Adversarial display identities and byte integrity; no synthetic production claims."""

import tempfile
import unittest
from pathlib import Path

from s19b_desktop.model import InputError, atomic_json, read_history, read_json, validate_live
from s19b_desktop.review import (
    REQUIRED,
    data_age,
    entity_catalog,
    evidence_status,
    explain_reason,
    preview_evidence,
    reason_fact,
    seal_evidence,
    validate_confirmation,
    validate_display_request,
)


class InformationReviewTests(unittest.TestCase):
    def request(self):
        return dict(
            run_id="r", request_id="q", epoch=0, sequence=1, action="locate", entity_id="P1"
        )

    def test_display_identity_boolean_epoch_and_replay_rejected(self):
        value = self.request()
        self.assertEqual(validate_display_request(value, value, 0), value)
        for update in (
            {"run_id": "old"},
            {"request_id": "old"},
            {"epoch": False},
            {"sequence": True},
            {"sequence": 0},
            {"action": "stop"},
        ):
            with self.subTest(update=update), self.assertRaises(InputError):
                validate_display_request({**value, **update}, value, 0)
        with self.assertRaises(InputError):
            validate_display_request(value, value, 1)

    def test_confirmation_requires_exact_request_action_target_and_boolean(self):
        pending = self.request()
        ack = {
            **pending,
            "accepted": True,
            "scope": "DISPLAY_ONLY",
            "paths": ["/World/P1"],
            "selected_paths": ["/World/P1"],
            "usd_before_sha256": "a" * 64,
            "usd_after_sha256": "a" * 64,
            "state_before_sha256": "b" * 64,
            "state_after_sha256": "b" * 64,
        }
        self.assertEqual(validate_confirmation(ack, pending), ack)
        for update in (
            {"run_id": "old"},
            {"request_id": "old"},
            {"epoch": False},
            {"sequence": 0},
            {"action": "camera"},
            {"entity_id": "W2"},
            {"accepted": "true"},
            {"scope": "PRODUCTION"},
        ):
            with self.subTest(update=update), self.assertRaises(InputError):
                validate_confirmation({**ack, **update}, pending)
        self.assertFalse(validate_confirmation({**ack, "accepted": False}, pending)["accepted"])
        for update in (
            {"paths": []},
            {"selected_paths": []},
            {"usd_after_sha256": "c" * 64},
            {"state_before_sha256": None},
        ):
            with self.subTest(update=update), self.assertRaises(InputError):
                validate_confirmation({**ack, **update}, pending)
        camera = {**pending, "action": "camera", "camera": "Fork"}
        for error in (None, True, float("nan"), 0.001):
            with self.subTest(error=error), self.assertRaises(InputError):
                validate_confirmation(
                    {
                        **camera,
                        "accepted": True,
                        "scope": "DISPLAY_ONLY",
                        "view_matrix_max_error": error,
                    },
                    camera,
                )

    def test_wall_clock_future_and_stale_are_not_fresh(self):
        self.assertEqual(data_age({"published_wall_s": 90}, now=100), 10)
        for value in (float("nan"), float("inf"), True, 103):
            with self.subTest(value=value), self.assertRaises(InputError):
                data_age({"published_wall_s": value}, now=100)

    def test_live_malformed_rows_and_false_epoch_rejected(self):
        live = dict(
            protocol="S19B-PROTOTYPE-1",
            run_id="r",
            request_id="q",
            epoch=0,
            sequence=1,
            time_h=0,
            published_wall_s=100,
            products=[],
            active=[],
        )
        for update in (
            {"active": None},
            {"active": [{}]},
            {"epoch": False},
            {"published_monotonic_s": float("nan")},
            {"products": [{}]},
        ):
            with self.subTest(update=update), self.assertRaises(InputError):
                validate_live({**live, **update}, "r", "q", 0)

    def test_actual_final_reason_takes_precedence_over_proposed_and_unknown_is_explicit(self):
        row = dict(
            plan_reason="EDD",
            final_reason="S19:STALE_OBSERVATION",
            sequence=7,
            observation_id="OBS-3",
            time_h=1.2,
            receipt_kind="REJECTED",
            failures=[],
        )
        fact = reason_fact([row])
        self.assertEqual(fact["code"], "S19:STALE_OBSERVATION")
        self.assertEqual(fact["source"], "online-journal.json")
        self.assertIn("派工被拒绝", explain_reason(fact["code"], "zh-CN"))
        self.assertIn("dispatch rejected", explain_reason(fact["code"], "en"))
        self.assertIn("unknown", explain_reason("", "en"))
        self.assertIn("no reviewed translation", explain_reason("NEW_REASON", "en"))

    def test_wait_reason_retains_exact_subject_and_does_not_invent_current_wait(self):
        value = "PRODUCT-1.A:PREDECESSORS;PRODUCT-2.B:PATH_BLOCKED"
        for locale in ("en", "zh-CN"):
            text = explain_reason(value, locale)
            self.assertIn("PRODUCT-1.A", text)
            self.assertIn("PRODUCT-2.B", text)

    def test_entity_mapping_is_exact_and_absence_cannot_be_fabricated(self):
        config = dict(
            products=[{"id": "PRODUCT-1"}],
            people=[{"id": "P1"}],
            devices=[{"id": "FORK-01"}],
            operations=[dict(id="OP-1", entity_id="P1", equipment=["FORK-01"])],
        )
        rows = {r["id"]: r for r in entity_catalog(config, {"P1": "/World/P1"})}
        self.assertEqual(rows["PRODUCT-1"]["paths"], [])
        self.assertEqual(rows["FORK-01"]["paths"], [])
        self.assertEqual(rows["OP-1"]["paths"], ["/World/P1"])
        self.assertEqual(rows["OP-1"]["targets"], ["P1", "FORK-01"])

    def sealed(self, root):
        for name in REQUIRED:
            (root / name).write_text("{}", encoding="utf-8")
        seal_evidence(root, self.request())
        return dict(run_id="r", request_id="q")

    def test_each_required_file_drift_or_absence_rejected(self):
        for name in REQUIRED:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                report = self.sealed(root)
                self.assertEqual(evidence_status(root, report)[0], "integrity_checked")
                path = root / name
                path.write_text("damage", encoding="utf-8")
                with self.assertRaisesRegex(InputError, "DAMAGED"):
                    evidence_status(root, report)
                path.unlink()
                with self.assertRaisesRegex(InputError, "DAMAGED"):
                    evidence_status(root, report)

    def test_index_identity_missing_required_and_path_escape_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            report = self.sealed(root)
            path = root / "evidence-index.json"
            original = read_json(path)
            for update in (
                {"run_id": "old"},
                {"request_id": "old"},
                {"epoch": False},
                {"files": {}},
                {"files": {**original["files"], "../escape": "x"}},
            ):
                atomic_json(path, {**original, **update})
                with self.subTest(update=list(update)), self.assertRaises(InputError):
                    evidence_status(root, report)
            with self.assertRaisesRegex(InputError, "PATH_REJECTED"):
                preview_evidence(root, "../escape")

    def test_legacy_remains_readonly_unverified_and_cross_identity_exit_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            atomic_json(root / "report.json", dict(run_id="r", request_id="q"))
            before = (root / "report.json").read_bytes()
            self.assertEqual(read_history(root)["integrity"], "unsealed")
            self.assertEqual((root / "report.json").read_bytes(), before)
            atomic_json(root / "process-exit.json", dict(run_id="old", request_id="q", exit_code=0))
            with self.assertRaisesRegex(InputError, "IDENTITY_MISMATCH"):
                read_history(root)


if __name__ == "__main__":
    unittest.main()
