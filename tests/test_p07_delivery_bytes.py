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

        candidate_migrations = load("docs/delivery/p08_w5_release_candidate_r1.json")
        historical_w5 = {
            row["original_path"]: row
            for row in candidate_migrations["previous_artifact_relocations"]
        }

        publication = load("docs/delivery/w5_publication_binding_r1.json")
        publication_moves = {
            row["original_path"]: row for row in publication["previous_artifact_relocations"]
        }
        self.assertEqual(
            set(publication_moves),
            {"README.md", "README.zh-CN.md", "tests/test_p07_delivery_bytes.py"},
        )

        def add(pin):
            path = pin["path"]
            # Earlier contracts retain their exact published bytes. Only an
            # explicit path AND original digest can select that historical file.
            moved = historical_w5.get(path)
            if moved is not None and pin["sha256"] == moved["sha256"]:
                pin = moved
                path = pin["path"]
            published_prior = publication_moves.get(path)
            if published_prior is not None and pin["sha256"] == published_prior["sha256"]:
                pin = published_prior
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
        ):
            add(completion[key])
        # r3's completion describes its original README. Retain that exact
        # document while the current README advances under its own contract.
        presentation = load("docs/delivery/p07_presentation_r1.json")
        historical = presentation["historical_README"]
        self.assertEqual(completion["README"]["path"], "README.md")
        self.assertEqual(historical["sha256"], completion["README"]["sha256"])
        self.assertEqual(historical["path"], "docs/archive/p07/r3/README.md")
        add(historical)
        self.assertIn("README.md", [row["path"] for row in presentation["current_artifacts"]])
        current = load("docs/delivery/p07_presentation_r2.json")
        add(current["previous_presentation"])
        self.assertEqual(
            current["previous_presentation"]["path"], "docs/delivery/p07_presentation_r1.json"
        )
        relocations = {
            row["original_path"]: row for row in current["previous_artifact_relocations"]
        }
        self.assertEqual(len(relocations), len(current["previous_artifact_relocations"]))
        self.assertEqual(
            set(relocations),
            {
                "README.md",
                "tests/test_p07_delivery_bytes.py",
                "docs/public_results/README.md",
                "docs/public_results/status.md",
                "docs/public_results/package_scope.json",
            },
        )
        for row in presentation["current_artifacts"]:
            if row["path"] in relocations:
                moved = relocations[row["path"]]
                self.assertEqual(moved["sha256"], row["sha256"])
                self.assertEqual(moved["path"], "docs/archive/p07/presentation-r1/" + row["path"])
                add(moved)
            else:
                add(row)
        current_paths = [row["path"] for row in current["current_artifacts"]]
        self.assertIn("README.md", current_paths)
        self.assertIn("README.zh-CN.md", current_paths)
        released = load("docs/delivery/p07_presentation_r3.json")
        add(released["previous_presentation"])
        self.assertEqual(
            released["previous_presentation"]["path"], "docs/delivery/p07_presentation_r2.json"
        )
        final_moves = {
            row["original_path"]: row for row in released["previous_artifact_relocations"]
        }
        self.assertEqual(len(final_moves), len(released["previous_artifact_relocations"]))
        self.assertEqual(
            set(final_moves),
            {
                "README.md",
                "README.zh-CN.md",
                "tests/test_p07_delivery_bytes.py",
                "docs/public_results/README.md",
                "docs/public_results/status.md",
                "docs/public_results/package_scope.json",
            },
        )
        for row in current["current_artifacts"]:
            if row["path"] in final_moves:
                moved = final_moves[row["path"]]
                self.assertEqual(moved["sha256"], row["sha256"])
                self.assertEqual(
                    moved["path"], "docs/archive/p07/bilingual-candidate-r2/" + row["path"]
                )
                add(moved)
            else:
                add(row)
        released_paths = [row["path"] for row in released["current_artifacts"]]
        self.assertIn("README.md", released_paths)
        self.assertIn("README.zh-CN.md", released_paths)
        delivery = load("docs/delivery/p08_release_r1.json")
        add(delivery["previous_presentation"])
        self.assertEqual(
            delivery["previous_presentation"]["path"], "docs/delivery/p07_presentation_r3.json"
        )
        moves = {row["original_path"]: row for row in delivery["previous_artifact_relocations"]}
        self.assertEqual(len(moves), len(delivery["previous_artifact_relocations"]))
        self.assertEqual(
            set(moves), {"README.md", "README.zh-CN.md", "tests/test_p07_delivery_bytes.py"}
        )
        for row in released["current_artifacts"]:
            if row["path"] in moves:
                moved = moves[row["path"]]
                self.assertEqual(moved["sha256"], row["sha256"])
                self.assertEqual(moved["path"], "docs/archive/p07/published-r3/" + row["path"])
                add(moved)
            else:
                add(row)
        revision = load("docs/delivery/p08_release_r2.json")
        add(revision["previous_delivery"])
        self.assertEqual(revision["previous_delivery"]["path"], "docs/delivery/p08_release_r1.json")
        revised_moves = {
            row["original_path"]: row for row in revision["previous_artifact_relocations"]
        }
        self.assertEqual(len(revised_moves), len(revision["previous_artifact_relocations"]))
        self.assertEqual(
            set(revised_moves), {"README.md", "README.zh-CN.md", "tests/test_p07_delivery_bytes.py"}
        )
        for row in delivery["current_artifacts"]:
            if row["path"] in revised_moves:
                moved = revised_moves[row["path"]]
                self.assertEqual(moved["sha256"], row["sha256"])
                self.assertEqual(moved["path"], "docs/archive/p08/candidate-r1/" + row["path"])
                add(moved)
            else:
                add(row)
        candidate = load("docs/delivery/p08_w5_release_candidate_r1.json")
        add(candidate["previous_delivery"])
        self.assertEqual(
            candidate["previous_delivery"]["path"], "docs/delivery/p08_release_r2.json"
        )
        w5_moves = {row["original_path"]: row for row in candidate["previous_artifact_relocations"]}
        self.assertEqual(len(w5_moves), len(candidate["previous_artifact_relocations"]))
        self.assertEqual(
            set(w5_moves),
            {
                "README.zh-CN.md",
                "desktop/p051/src/p051_desktop/app.py",
                "desktop/p051/web/src/main.jsx",
                "desktop/p051/src/p051_desktop/gantt.py",
                "tests/test_p07_delivery_bytes.py",
                "README.md",
                "scripts/run_s19b_prototype.py",
                "desktop/p051/web/src/style.css",
            },
        )
        for row in revision["current_artifacts"]:
            if row["path"] in w5_moves:
                moved = w5_moves[row["path"]]
                self.assertEqual(moved["sha256"], row["sha256"])
                self.assertEqual(moved["path"], "docs/archive/p08/v1.0.1/" + row["path"])
                add(moved)
            else:
                add(row)
        for row in candidate["current_artifacts"]:
            add(row)
        add(publication["previous_candidate"])
        for row in publication["current_artifacts"]:
            add(row)
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
