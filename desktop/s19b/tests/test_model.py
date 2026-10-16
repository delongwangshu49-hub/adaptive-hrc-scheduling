import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from s19b_desktop.i18n import TEXT
from s19b_desktop.model import (
    Draft,
    InputError,
    atomic_json,
    canonical_digest,
    configuration_digest,
    read_history,
    read_json,
    validate_live,
)


class PrototypeInputTests(unittest.TestCase):
    def test_transient_windows_read_sharing_retries_but_persistent_denial_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "live.json"
            path.write_text('{"note":"中文"}', encoding="utf-8")
            with patch.object(
                Path, "read_text", side_effect=[PermissionError(), '{"note":"中文"}']
            ):
                self.assertEqual(read_json(path), {"note": "中文"})
            with (
                patch.object(Path, "read_text", side_effect=PermissionError()),
                patch("s19b_desktop.model.time.monotonic", side_effect=[0.0, 1.1]),
                self.assertRaises(PermissionError),
            ):
                read_json(path)

    def test_draft_rejects_nonfinite_and_unsupported_times(self):
        for value in (float("nan"), float("inf"), -1, 720, True):
            with self.subTest(value=value), self.assertRaises(InputError):
                Draft(release_times=(value,)).validate()

    def test_product_count_strict_not_bool_and_release_count(self):
        for count in (True, 0, 4, 1.0):
            with self.subTest(count=count), self.assertRaises(InputError):
                Draft(products=count).validate()
        with self.assertRaises(InputError):
            Draft(products=2).validate()

    def test_utf8_note_roundtrip_and_unrelated_locale(self):
        draft = Draft(products=2, release_times=(0.0, 0.5), note="小组中文输入 / English")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "draft.json"
            atomic_json(path, draft.data())
            self.assertEqual(Draft.from_data(read_json(path)), draft)
            self.assertEqual(canonical_digest(draft.data()), canonical_digest(read_json(path)))

    def test_history_is_read_only_and_detects_configuration_drift(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            config = {"schema_version": "TEST-ONLY", "note": "合成测试"}
            atomic_json(path / "configuration.json", config)
            atomic_json(
                path / "report.json",
                {"run_id": "test", "manifest": {"config_sha256": canonical_digest(config)}},
            )
            before = {p.name: p.read_bytes() for p in path.iterdir()}
            self.assertEqual(read_history(path)["run_id"], "test")
            self.assertEqual(before, {p.name: p.read_bytes() for p in path.iterdir()})
            atomic_json(path / "configuration.json", {**config, "note": "changed"})
            with self.assertRaisesRegex(InputError, "DIGEST_MISMATCH"):
                read_history(path)

    def test_duplicate_keys_and_nonfinite_json_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bad.json"
            for text in ('{"run_id":"old","run_id":"new"}', '{"time":NaN}'):
                path.write_text(text, encoding="utf-8")
                with self.assertRaises(InputError):
                    read_json(path)

    def test_stale_identity_sequence_and_clock_rejected(self):
        value = dict(
            protocol="S19B-PROTOTYPE-1",
            run_id="r",
            request_id="q",
            epoch=0,
            sequence=2,
            time_h=0.5,
            published_wall_s=123.0,
            products=[],
            active=[],
        )
        self.assertEqual(validate_live(value, "r", "q", 1), value)
        for update in (
            {"run_id": "old"},
            {"epoch": 1},
            {"sequence": 0},
            {"sequence": True},
            {"time_h": float("inf")},
        ):
            with self.subTest(update=update), self.assertRaises(InputError):
                validate_live({**value, **update}, "r", "q", 1)

    def test_every_ui_message_has_two_nonempty_translations(self):
        self.assertTrue(all(len(value) == 2 and all(value) for value in TEXT.values()))
        json.dumps(TEXT, ensure_ascii=False)

    def test_typed_production_configuration_restores_float_fields_for_digest(self):
        root = Path(__file__).resolve().parents[3]
        sys.path[:0] = [str(root / "src"), str(root / "scripts")]
        from build_simulation_production import configuration

        from adaptive_hrc_scheduling.contracts.codec import as_data
        from adaptive_hrc_scheduling.contracts.production import digest

        record = configuration()
        saved = as_data(record)
        self.assertNotEqual(canonical_digest(saved), digest(record))
        self.assertEqual(configuration_digest(saved), digest(record))


if __name__ == "__main__":
    unittest.main()
