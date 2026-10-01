"""Compare actual execution with S05's independent, unchanged hand arithmetic."""

import importlib.util
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "execution_witness", ROOT / "scripts/run_execution_witness.py"
)
witness = importlib.util.module_from_spec(spec)
spec.loader.exec_module(witness)


class WitnessTests(unittest.TestCase):
    def test_all_28_stages_completion_drain_and_worker_integrals_match_s05(self):
        expected = json.loads((ROOT / "examples/toy_instance.json").read_text(encoding="utf-8"))[
            "witness"
        ]
        e = witness.run_witness()
        self.assertEqual(e.status().code, "DRAINED")
        self.assertEqual(len(e.snapshot.phases), len(expected["phases"]))
        aliases = {
            "C1": "CUT",
            "B1": "BRACKET",
            "A1": "ASSEMBLE",
            "W1": "WELD",
            "I1": "INSPECT",
            "L1": "LIFT",
        }
        by_id = {p["phase_id"]: p for p in expected["phases"]}
        for p in e.snapshot.phases:
            kind = aliases[p.operation_id.split(".")[-1]]
            transfer = ".in." in p.group_id and kind != "LIFT"
            key = f"J1.{kind}.{'in_' if transfer else ''}{p.phase_id}"
            self.assertAlmostEqual(p.started_min, by_id[key]["start_min"], delta=1e-10)
            self.assertAlmostEqual(p.completed_min, by_id[key]["end_min"], delta=1e-10)
        metrics = expected["metrics"]
        self.assertAlmostEqual(
            e.snapshot.orders[0].actual_completion_min,
            metrics["physical_arrival_and_completion_min"],
            delta=1e-10,
        )
        self.assertAlmostEqual(e.drained_at_min, metrics["system_drained_min"], delta=1e-10)
        for w in e.snapshot.workers:
            target = metrics["worker"][w.worker_id]
            self.assertAlmostEqual(w.fatigue, target["final_F"], delta=1e-10)
            self.assertAlmostEqual(w.exposure_min, target["exposure_min"], delta=1e-10)

    def test_repeated_manual_witness_has_identical_events_and_state(self):
        a, b = witness.run_witness(), witness.run_witness()
        self.assertEqual(a.snapshot, b.snapshot)
        self.assertEqual(a.events, b.events)
        self.assertEqual(a.activity_intervals, b.activity_intervals)


if __name__ == "__main__":
    unittest.main()
