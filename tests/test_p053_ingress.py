"""Receiving stock blocks clearance; an empty cancellation lane must clear."""

import sys
import unittest
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from build_simulation_production import configuration

from adaptive_hrc_scheduling.contracts.codec import ContractError
from adaptive_hrc_scheduling.contracts.production import validate
from adaptive_hrc_scheduling.planning.production import choose, planning_input
from adaptive_hrc_scheduling.production_backend import ProductionBackend
from adaptive_hrc_scheduling.research_initial import configuration as research


class ResearchIngressTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = research(configuration(products=2))

    def world(self, occupied):
        world = ProductionBackend(self.config)
        lot = next(x for x in self.config.lots if x.bom_id == "B-ST" and not x.parent_ids)
        place = "RECEIVE." + lot.id
        world.s = replace(
            world.s,
            products=tuple(replace(p, released=True) for p in world.s.products),
            positions=tuple(
                replace(p, location=place, support=place) if p.id == "FORK-01" else p
                for p in world.s.positions
            ),
            lots=tuple(
                replace(s, arrived=True, available=lot.quantity, location=place)
                if occupied and s.id == lot.id
                else s
                for s in world.s.lots
            ),
        )
        return world

    def test_empty_receive_child_requests_physical_clearance(self):
        w = self.world(False)
        p = choose(self.config, planning_input(self.config, w.observe(), 10000))
        self.assertTrue(p.reason.startswith("P042:INGRESS_CLEARANCE:"))
        self.assertTrue(p.commands)
        self.assertEqual(w._position("FORK-01").location, "RECEIVE.PRODUCT-1.ST-B.01")

    def test_stock_in_receiving_lane_prevents_clearance_loop(self):
        w = self.world(True)
        p = choose(self.config, planning_input(self.config, w.observe(), 10000))
        self.assertFalse(p.reason.startswith("P042:INGRESS_CLEARANCE:"))

    def test_serialized_research_due_drift_is_rejected(self):
        c = self.config
        with self.assertRaisesRegex(ContractError, "SIM_PRESERVED_PRODUCT:due_h"):
            validate(replace(c, products=(replace(c.products[0], due_h=169), *c.products[1:])))


if __name__ == "__main__":
    unittest.main()
