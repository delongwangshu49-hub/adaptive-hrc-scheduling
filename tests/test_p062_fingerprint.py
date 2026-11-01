"""Prefix reuse preserves the existing decision wire digest at every boundary."""

import concurrent.futures
import hashlib
import json
import random
import unittest

from adaptive_hrc_scheduling.control.production_decisions import fingerprint


def reference(value):
    return hashlib.sha256(
        json.dumps(list(value), sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


class PrefixFingerprintTests(unittest.TestCase):
    def test_growth_reuse_truncation_and_same_length_fork(self):
        rows = [(), ("EV1",), ("EV1", "EV2"), ("EV1", "EV2"), ("EV1",), ("X",), ()]
        for row in rows:
            self.assertEqual(fingerprint(row), reference(row))

    def test_escaped_and_non_ascii_strings_use_original_json_bytes(self):
        for row in [('引号"', "a\\b", "\n", "Ω"), ("",), ("EV1", "é")]:
            self.assertEqual(fingerprint(row), reference(row))

    def test_seeded_append_and_branch_history(self):
        rng = random.Random(7023)
        row = ()
        for i in range(300):
            if rng.random() < 0.2:
                row = row[: rng.randrange(len(row) + 1)]
            row += (f"EV{i}",)
            self.assertEqual(fingerprint(row), reference(row))

    def test_mutable_lists_and_non_string_tuples_do_not_reuse_prefix(self):
        row = ["EV1"]
        self.assertEqual(fingerprint(row), reference(row))
        row[0] = "CHANGED"
        self.assertEqual(fingerprint(row), reference(row))
        for row, wire in [((True,), "[true]"), ((1,), "[1]"), ((1.0,), "[1]"), (("1",), '["1"]')]:
            self.assertEqual(fingerprint(row), hashlib.sha256(wire.encode()).hexdigest())

    def test_independent_threads_cannot_mix_prefix_hash_state(self):
        def run(prefix):
            row = ()
            for i in range(250):
                row += (prefix + str(i),)
                if fingerprint(row) != reference(row):
                    return False
            return True

        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            self.assertTrue(all(pool.map(run, ["A", "B", "C", "D"])))
