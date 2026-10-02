"""Building contract positive/negative witnesses, separate from historical tests."""

import importlib.util
import json
import unittest
from dataclasses import replace
from pathlib import Path

from adaptive_hrc_scheduling.contracts.building import (
    TOP_LEVEL,
    ContractError,
    dumps,
    loads,
    planning_input,
    validate,
)
from adaptive_hrc_scheduling.domain import building as b

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "building_generator", ROOT / "scripts/build_building_contracts.py"
)
generator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(generator)


class BuildingContractsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.c = generator.build_configuration()

    def rejects(self, c, pattern):
        with self.assertRaisesRegex(ContractError, pattern):
            validate(c)

    def test_ten_schemas_and_round_trip(self):
        files = generator.generated()
        self.assertEqual(len(TOP_LEVEL), 10)
        for name, text in files.items():
            self.assertEqual((ROOT / name).read_bytes(), text.encode("utf-8"))
        names = {
            "Configuration": "configuration",
            "PlanningInput": "planning_input",
            "PlanningObservation": "planning_observation",
            "DispatchCommand": "dispatch",
            "ExecutionEvent": "execution_event",
            "ExecutionSnapshot": "execution_snapshot",
            "HiddenScenario": "hidden_scenario",
            "OfflineEvaluation": "offline_evaluation",
            "RunManifest": "run_manifest",
            "Plan": "plan",
        }
        for kind in TOP_LEVEL:
            text = files["examples/building_contracts/" + names[kind.__name__] + ".json"]
            value = loads(kind, text, config=self.c)
            self.assertEqual(loads(kind, dumps(value, config=self.c), config=self.c), value)

    def test_full_graph_and_modes(self):
        self.assertEqual(
            (
                len(self.c.activities),
                len(self.c.edges),
                sum(len(a.modes) for a in self.c.activities),
            ),
            (37, 40, 39),
        )
        self.assertEqual(
            sum(p.kind == "HR-seq" and p.enabled for a in self.c.activities for p in a.modes), 0
        )

    def test_variant_real_bom_and_work(self):
        c = generator.build_configuration("SR-W2")
        validate(c)
        a = next(a for a in c.activities if a.code == "MEP-P")
        self.assertEqual(len(a.modes[0].units), 4)
        self.assertIn("B-BRANCH", next(m for m in c.materials if m.activity_id == a.id).bom_ids)

    def test_unknown_version(self):
        with self.assertRaises(ContractError):
            loads(b.Configuration, dumps(self.c).replace("C04-1.0", "S06-1.1"))

    def test_pipe_not_coerced(self):
        with self.assertRaises(ContractError):
            loads(b.Configuration, (ROOT / "examples/contracts/toy.json").read_text())

    def test_duplicate_json_and_numeric_types(self):
        text = dumps(self.c)
        for bad in [
            text.replace('"cap": 0.8', '"cap": true'),
            text.replace('"cap": 0.8', '"cap": NaN'),
            text.replace('"cap": 0.8', '"cap": 0.8, "cap": 0.7'),
        ]:
            with self.assertRaises(ContractError):
                loads(b.Configuration, bad)

    def test_unknown_field(self):
        data = json.loads(dumps(self.c))
        data["hidden_future"] = []
        with self.assertRaises(ContractError):
            loads(b.Configuration, json.dumps(data))

    def test_duplicate_id(self):
        self.rejects(replace(self.c, people=self.c.people + (self.c.people[0],)), "duplicate")

    def test_dangling_edge(self):
        self.rejects(
            replace(
                self.c,
                edges=self.c.edges + (b.Edge("MISSING", self.c.activities[0].id, "precedence"),),
            ),
            "dangling",
        )

    def test_cycle(self):
        self.rejects(
            replace(
                self.c,
                edges=self.c.edges
                + (b.Edge(self.c.activities[-1].id, self.c.activities[0].id, "precedence"),),
            ),
            "cycle",
        )

    def test_missing_role(self):
        a = next(a for a in self.c.activities if a.code == "W-3D")
        m = a.modes[0]
        bad = replace(
            a,
            modes=(
                replace(m, units=(replace(m.units[0], roles=m.units[0].roles[:1]),) + m.units[1:]),
            ),
        )
        self.rejects(
            replace(
                self.c, activities=tuple(bad if x.id == a.id else x for x in self.c.activities)
            ),
            "role",
        )

    def test_illegal_material_release(self):
        m = replace(self.c.materials[0], arrived=False)
        self.rejects(replace(self.c, materials=(m,) + self.c.materials[1:]), "release before")

    def test_foreign_material(self):
        c = generator.build_configuration(products=2)
        a = c.activities[1]
        foreign = next(m for m in c.materials if m.product_id == "PRODUCT-2")
        self.rejects(
            replace(
                c,
                activities=tuple(
                    replace(x, material_ids=(foreign.id,)) if x == a else x for x in c.activities
                ),
            ),
            "illegal material",
        )

    def test_hr_unknown_rejected(self):
        c = replace(
            self.c,
            activities=tuple(
                replace(a, modes=tuple(replace(m, enabled=True) for m in a.modes))
                for a in self.c.activities
            ),
        )
        self.rejects(c, "HR unqualified")

    def test_synthetic_evidence_cannot_claim_industrial(self):
        c = generator.synthetic_fixture(self.c)
        self.rejects(replace(c, purpose="RESEARCH_BLOCKED"), "synthetic provenance")

    def test_same_person_two_roles(self):
        c = generator.synthetic_fixture(self.c)
        a = next(a for a in c.activities if a.code == "W-3D")
        cmd = b.DispatchCommand(
            "C04-1.0",
            c.id,
            "CMD",
            0,
            0,
            a.id,
            a.modes[0].id,
            0,
            0,
            (b.RoleBinding("W1", "W1"), b.RoleBinding("W2", "W1")),
        )
        with self.assertRaisesRegex(ContractError, "distinct"):
            validate(cmd, config=c)

    def test_future_observation(self):
        c = replace(self.c, products=(replace(self.c.products[0], release_h=10),))
        obs = b.PlanningObservation(
            "C04-1.0",
            c.id,
            "OBS",
            0,
            0,
            0,
            0,
            (b.ObservedProduct("PRODUCT-1", None, None, (), None),),
            (),
            (),
            (),
        )
        with self.assertRaisesRegex(ContractError, "future"):
            validate(obs, config=c)

    def test_planning_projection_excludes_future(self):
        obs = b.PlanningObservation("C04-1.0", self.c.id, "OBS", 0, 0, 0, 0, (), (), (), ())
        view = planning_input(self.c, obs)
        self.assertEqual(view.products, ())
        self.assertEqual(view.activities, ())
        with self.assertRaises(ContractError):
            validate(replace(view, products=self.c.products), config=self.c)

    def test_unassembled_has_no_product_residency(self):
        s = generator.initial_snapshot(self.c)
        with self.assertRaisesRegex(ContractError, "logical product"):
            validate(
                replace(s, residencies=(b.Residency("PRODUCT-1", "J3", "PRODUCT-1", False),)),
                config=self.c,
            )

    def test_conflicting_events(self):
        s = b.HiddenScenario(
            "C04-1.0",
            self.c.id,
            0,
            (
                b.WorldEvent("E1", 1, "FAILURE", "CR1", None, None),
                b.WorldEvent("E2", 1, "REPAIR", "CR1", None, None),
            ),
        )
        with self.assertRaisesRegex(ContractError, "conflicting"):
            validate(s, config=self.c)


if __name__ == "__main__":
    unittest.main()
