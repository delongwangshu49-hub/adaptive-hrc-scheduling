import copy
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "scripts")]
import verify_p053_session as new  # noqa: E402
import verify_session as old  # noqa: E402


class PrefixCompatibilityTests(unittest.TestCase):
    def test_every_small_prefix_matches_original_normalization(self):
        records = [{"a": -0.0, "text": "雪"}, {"nested": [True, 1.0, 0.125, None]}, {"a": 2}]
        self.assertEqual(new.prefix_digests(records), [old.sha(records[:n]) for n in range(4)])

    def test_original_small_saved_session_has_identical_all_checks(self):
        folder = ROOT / "tests/fixtures/p053/legacy-session"
        if not folder.exists():
            raise RuntimeError("REGISTERED_SMALL_FIXTURE_NOT_FOUND")
        self.assertEqual(
            old.verify(folder, require_decisions=True), new.verify(folder, require_decisions=True)
        )

    def test_corrupt_prefix_and_launch_binding_rejected_by_both(self):
        folder = ROOT / "tests/fixtures/p053/legacy-session"
        state_path = folder / "session-state.json"
        original = json.loads(state_path.read_bytes())
        for kind in ("prefix", "launch"):
            bad = copy.deepcopy(original)
            if kind == "prefix":
                bad["observations"][0]["event_prefix_hash"] = "0" * 64
            else:
                bad["binding"]["method"] = (
                    "ADAPTIVE" if bad["binding"]["method"] == "EDD" else "EDD"
                )
            actual_read = Path.read_text

            def read(path, *args, **kwargs):
                return json.dumps(bad) if path == state_path else actual_read(path, *args, **kwargs)

            reasons = []
            for module in (old, new):
                with patch.object(Path, "read_text", read), self.assertRaises(ValueError) as caught:
                    module.verify(folder, require_decisions=True)
                reasons.append(str(caught.exception))
            self.assertEqual(reasons[0], reasons[1])


if __name__ == "__main__":
    unittest.main()
