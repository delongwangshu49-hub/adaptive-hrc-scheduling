"""Proof output remains exact compact JSON with bounded record-sized writes."""

import gzip
import io
import json
import tempfile
import unittest
from pathlib import Path

from build_simulation_production import configuration

from adaptive_hrc_scheduling.production_backend import ProductionBackend
from adaptive_hrc_scheduling.schedule_proof import decode, dump, encode


class ProofWriterTests(unittest.TestCase):
    def payload(self):
        return dict(
            scope="HYPOTHETICAL_FULL_REPLAY",
            configuration={"note": '中文 "quoted" \\ path\n', "value": -0.0},
            initial={},
            generations=[],
            snapshot_graph=encode(ProductionBackend(configuration()).snapshot()),
            decisions=[dict(id="D1", values=[1, 2.0, False, None])],
        )

    def test_exact_decompressed_json_and_snapshot_round_trip(self):
        payload = self.payload()
        expected = json.dumps(payload, separators=(",", ":"))
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "proof.gz"
            with gzip.open(path, "wt", encoding="utf8", compresslevel=1) as stream:
                dump(payload, stream)
            with gzip.open(path, "rt", encoding="utf8") as stream:
                actual = stream.read()
        self.assertEqual(actual, expected)
        self.assertEqual(
            decode(json.loads(actual)["snapshot_graph"]), decode(payload["snapshot_graph"])
        )

    def test_large_node_array_streams_without_one_full_proof_write(self):
        class Writes(io.StringIO):
            largest = 0

            def write(self, value):
                self.largest = max(self.largest, len(value))
                return super().write(value)

        proof = dict(
            snapshot_graph=dict(
                format="test", nodes=[dict(kind="tuple", values=[1] * 30)] * 5000, root={"ref": 0}
            ),
            decisions=[],
        )
        stream = Writes()
        dump(proof, stream)
        self.assertEqual(stream.getvalue(), json.dumps(proof, separators=(",", ":")))
        self.assertLess(stream.largest, 1000)
