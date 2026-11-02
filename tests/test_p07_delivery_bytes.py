"""Byte contracts must survive real Git checkout, not just a working ZIP."""

import hashlib
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class P07DeliveryBytesTests(unittest.TestCase):
    def test_published_bytes_match_replay_and_evidence_manifests(self):
        expected = {}

        def load(path):
            return json.loads((ROOT / path).read_bytes())

        def add(pin):
            path = pin["path"]
            self.assertTrue((ROOT / path).resolve().is_relative_to(ROOT.resolve()))
            self.assertFalse(path.startswith(".local/"))
            if path in expected:
                self.assertEqual(expected[path], pin["sha256"], path)
            expected[path] = pin["sha256"]

        base = "examples/reproduction/p07/r3/"
        m = load(base + "manifest.json")
        for key in ("metadata", "inventory", "E20_reference"):
            add(m[key])
        for row in m["inputs"]:
            add(dict(path=base + "inputs/" + row["file"], sha256=row["sha256"]))
        for row in m["auxiliary"]:
            add(dict(path=base + "auxiliary/" + row["file"], sha256=row["sha256"]))
        validation = load("results/p07/r3/validation.json")
        for row in validation["inputs"] + list(validation["source_code"].values()):
            add(row)
        figures = load("figures/p07/r3/manifest.json")
        add(figures["native_mermaid"])
        add(figures["data_validation"])
        for figure in figures["figures"]:
            for row in figure["source_data"] + figure["files"] + [figure["script"]]:
                add(row)
        completion = load("docs/delivery/p07_completion_r3.json")
        for key in (
            "resolution",
            "validation",
            "report",
            "source_registry",
            "claims",
            "figures",
            "portable_inputs",
            "README",
        ):
            add(completion[key])
        binding = load("docs/delivery/feedback_metric_binding_r3.json")
        for row in binding["upstream_contracts"]:
            add(row)
        source = load("docs/delivery/p07_source_registry_r3.json")
        for row in (
            source["current_analysis_source"]
            + source["reused_algorithms"]
            + [source["original_frozen_extractor"]]
        ):
            add(row)
        for path, digest in expected.items():
            with self.subTest(path=path):
                with (ROOT / path).open("rb") as stream:
                    self.assertEqual(hashlib.file_digest(stream, "sha256").hexdigest(), digest)


if __name__ == "__main__":
    unittest.main()
