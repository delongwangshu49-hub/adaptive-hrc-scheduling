"""Byte equivalence and atomic failure checks for bounded session saving."""

import hashlib
import io
import math
import random
import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path

from build_simulation_production import configuration

from adaptive_hrc_scheduling.contracts.codec import as_data
from adaptive_hrc_scheduling.contracts.session import canonical
from adaptive_hrc_scheduling.contracts.session_stream import (
    FrozenEventArray,
    file_sha256,
    write_canonical,
)
from adaptive_hrc_scheduling.control.session import save_atomic
from adaptive_hrc_scheduling.production_backend import ProductionBackend


class SessionStreamTests(unittest.TestCase):
    def encoded(self, value):
        stream = io.BytesIO()
        write_canonical(stream, value, chunk_bytes=19)
        return stream.getvalue()

    def test_numeric_unicode_and_container_bytes_match(self):
        values = [
            None,
            True,
            False,
            0,
            -0.0,
            1.0,
            -2.0,
            1e-8,
            1e20,
            1e-300,
            math.pi,
            '中文\n"\\\t😀',
            [],
            (),
            {},
            {"z": [1.0, True], "a": (False, None)},
        ]
        for value in values:
            with self.subTest(value=value):
                self.assertEqual(self.encoded(value), canonical(value))

    def test_seeded_nested_values_match_original_bytes(self):
        rng = random.Random(52)

        def value(depth):
            if depth == 0:
                return rng.choice(
                    [None, True, False, rng.randint(-1000, 1000), rng.random(), "工位😀"]
                )
            return {"z": [value(depth - 1) for _ in range(3)], "a": (value(depth - 1),)}

        for _ in range(100):
            sample = value(3)
            self.assertEqual(self.encoded(sample), canonical(sample))

    def test_dataclass_and_real_snapshot_match_as_data(self):
        @dataclass(frozen=True)
        class Row:
            z: tuple
            a: float

        for sample in [
            Row((True, "中文", Row((), -0.0)), 2.0),
            ProductionBackend(configuration()).snapshot(),
        ]:
            self.assertEqual(self.encoded(sample), canonical(as_data(sample)))

    def test_original_invalid_values_still_rejected(self):
        for sample in [{1: "bad"}, {"x": float("nan")}, [float("inf")], {"x": {1, 2}}, b"bytes"]:
            with self.subTest(sample=sample):
                with self.assertRaises(ValueError):
                    canonical(sample)
                with self.assertRaises(ValueError):
                    self.encoded(sample)

    def test_failed_write_does_not_replace_previous_commit(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "state.json"
            save_atomic(path, {"old": 1.0})
            before = path.read_bytes()
            with self.assertRaises(ValueError):
                save_atomic(path, {"a": ["large" * 1000] * 20, "z": float("nan")})
            self.assertEqual(path.read_bytes(), before)
            save_atomic(path, {"new": 2.0})
            self.assertEqual(path.read_bytes(), canonical({"new": 2.0}))

    def test_writes_are_chunked_instead_of_one_document(self):
        class Sink:
            sizes = []

            def write(self, data):
                self.sizes.append(len(data))

        sink = Sink()
        write_canonical(sink, [{"value": "x" * 100, "time": 1.0}] * 10000)
        self.assertGreater(len(sink.sizes), 10)
        self.assertLess(max(sink.sizes), 66000)

    def test_cached_array_matches_every_growing_prefix(self):
        @dataclass(frozen=True)
        class Row:
            value: tuple

        events = tuple(Row((i, float(i), "工位", True)) for i in range(20))
        with tempfile.TemporaryDirectory() as folder:
            cache = FrozenEventArray(folder)
            try:
                for count in (0, 1, 5, 5, 20):
                    cache.append(events[:count])
                    self.assertEqual(self.encoded(cache), canonical(as_data(events[:count])))
            finally:
                cache.stream.close()

    def test_cache_rejects_replaced_truncated_and_mutable_prefix(self):
        @dataclass(frozen=True)
        class Row:
            value: int

        event = Row(1)
        with tempfile.TemporaryDirectory() as folder:
            cache = FrozenEventArray(folder)
            try:
                cache.append((event,))
                for bad in ((), (Row(1),), (event, {"value": 2})):
                    with self.assertRaises(ValueError):
                        cache.append(bad)
                self.assertEqual(self.encoded(cache), b'[{"value":1}]')
            finally:
                cache.stream.close()

    def test_corrupt_cache_cannot_replace_committed_file(self):
        @dataclass(frozen=True)
        class Row:
            value: int

        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "state.json"
            for corruption in ("changed", "truncated", "extended"):
                cache = FrozenEventArray(folder)
                try:
                    cache.append((Row(1),))
                    save_atomic(path, {"events": cache})
                    before = path.read_bytes()
                    if corruption == "changed":
                        cache.stream.seek(0)
                        cache.stream.write(b"!")
                    elif corruption == "truncated":
                        cache.stream.truncate(2)
                    else:
                        cache.stream.seek(0, 2)
                        cache.stream.write(b"!")
                    with self.assertRaises(ValueError):
                        save_atomic(path, {"events": cache})
                    self.assertEqual(path.read_bytes(), before)
                finally:
                    cache.stream.close()

    def test_failed_append_rolls_back_and_can_be_retried(self):
        @dataclass(frozen=True)
        class Row:
            value: float

        event = Row(1.0)
        with tempfile.TemporaryDirectory() as folder:
            cache = FrozenEventArray(folder)
            try:
                cache.append((event,))
                with self.assertRaises(ValueError):
                    cache.append((event, Row(float("nan"))))
                cache.append((event, Row(2.0)))
                self.assertEqual(self.encoded(cache), b'[{"value":1},{"value":2}]')
            finally:
                cache.stream.close()

    def test_stream_file_digest_matches_full_bytes(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "large.bin"
            raw = bytes(range(256)) * 10000
            path.write_bytes(raw)
            self.assertEqual(file_sha256(path), hashlib.sha256(raw).hexdigest())


if __name__ == "__main__":
    unittest.main()
