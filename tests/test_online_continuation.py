"""S19 continuation: strict cache boundaries and concurrent crane route safety."""

import hashlib
import json
import random
import sys
import unittest
from dataclasses import dataclass, replace
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from build_simulation_production import configuration

from adaptive_hrc_scheduling.contracts.codec import (
    ContractError,
    as_data,
    canonical_json,
    checked,
    decode,
)
from adaptive_hrc_scheduling.contracts.production import digest
from adaptive_hrc_scheduling.domain import production as m
from adaptive_hrc_scheduling.production_backend import ProductionBackend
from adaptive_hrc_scheduling.production_navigation import (
    _boxes_uncached,
    boxes,
    clear_segment,
    concurrent_crane_blocker,
)


class NativeBoundaryTests(unittest.TestCase):
    def test_native_matches_wire_decode_and_rejects_changed_invalid_leaf(self):
        @dataclass(frozen=True)
        class Item:
            count: int
            value: float

        a = Item(2, 3)
        self.assertEqual(checked(a), decode(Item, as_data(a)))
        self.assertEqual(type(checked(a).value), float)
        for bad in (replace(a, count=True), replace(a, value=float("nan"))):
            with self.assertRaises(ContractError):
                checked(bad)

    def test_mutable_nested_collection_is_never_trusted_from_cache(self):
        @dataclass(frozen=True)
        class Item:
            values: tuple[int, ...]

        a = Item([1])
        self.assertEqual(checked(a).values, (1,))
        a.values.append("invalid")
        with self.assertRaises(ContractError):
            checked(a)

    def test_same_shape_frozen_types_preserve_wire_semantics(self):
        @dataclass(frozen=True)
        class Source:
            x: float

        a = Source(1)
        self.assertEqual(checked(a), decode(Source, as_data(a)))


class GeometryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = configuration(products=3, rework=True)

    def test_crane_return_cannot_cross_accepted_forklift_route(self):
        c = self.config
        ground = next(o for o in c.operations if o.id == "PRODUCT-3.ST-C.04.DELIVER-1")
        route = next(r for r in c.routes if r.id == ground.route_id)
        crane = next(r for r in c.routes if r.device_id == "CR1")
        crane = replace(
            crane, points=(replace(crane.points[0], x=50), replace(crane.points[-1], x=18))
        )
        op = replace(
            ground, id="CRANE-RETURN", entity_id="CR1", route_id=crane.id, action="EMPTY_RETURN"
        )

        def state(operation, path):
            return SimpleNamespace(
                running=(
                    SimpleNamespace(
                        command=SimpleNamespace(
                            operation_id=operation.id,
                            service=SimpleNamespace(operation=operation, route=path),
                        )
                    ),
                )
            )

        self.assertIsNotNone(concurrent_crane_blocker(c, state(ground, route), op, crane))
        self.assertIsNotNone(concurrent_crane_blocker(c, state(op, crane), ground, route))
        self.assertIsNone(concurrent_crane_blocker(c, SimpleNamespace(running=()), op, crane))

    def test_geometry_cache_tracks_stock_positions_and_returned_list_isolated(self):
        c = self.config
        state = ProductionBackend(c).s
        state = replace(
            state,
            lots=(replace(state.lots[0], available=c.lots[0].quantity),) + state.lots[1:],
            positions=tuple(
                replace(x, location="RECEIVE") if x.id == c.lots[0].id else x
                for x in state.positions
            ),
        )
        original = boxes(c, state)
        original.clear()
        self.assertEqual(boxes(c, state), _boxes_uncached(c, state))
        lot = next(x for x in state.lots if x.available > 0)
        depleted = replace(
            state, lots=tuple(replace(x, available=0) if x.id == lot.id else x for x in state.lots)
        )
        moved = replace(
            state,
            positions=tuple(
                replace(x, location="J3") if x.id == "CR1" else x for x in state.positions
            ),
        )
        for value in (depleted, moved, state):
            self.assertEqual(boxes(c, value), _boxes_uncached(c, value))
        self.assertTrue(boxes(c, state) != boxes(c, depleted), "stock change must alter geometry")
        self.assertTrue(boxes(c, state) != boxes(c, moved), "crane location must alter geometry")

    def test_configuration_digest_same_as_strict_wire_roundtrip(self):
        clone = decode(m.Configuration, as_data(self.config))
        self.assertEqual(digest(clone), digest(self.config))
        self.assertNotEqual(digest(replace(clone, id="DIFFERENT")), digest(self.config))
        original = json.dumps(
            as_data(clone), sort_keys=True, separators=(",", ":"), allow_nan=False
        )
        self.assertEqual(canonical_json(clone), original)
        self.assertEqual(digest(clone), hashlib.sha256(original.encode()).hexdigest())

    def test_segment_broad_phase_preserves_slab_intersection(self):
        def reference(a, b, obstacles, size, margin):
            a = (*a[:2], a[2] + size[2] / 2)
            b = (*b[:2], b[2] + size[2] / 2)
            for _, lo, hi in obstacles:
                lower, upper = 0.0, 1.0
                for i in range(3):
                    left, right = lo[i] - size[i] / 2 - margin, hi[i] + size[i] / 2 + margin
                    delta = b[i] - a[i]
                    if abs(delta) < 1e-12:
                        if a[i] <= left + 1e-9 or a[i] >= right - 1e-9:
                            lower, upper = 1, 0
                            break
                    else:
                        item, r = sorted(((left - a[i]) / delta, (right - a[i]) / delta))
                        lower, upper = max(lower, item), min(upper, r)
                if lower < upper - 1e-9:
                    return False
            return True

        rng = random.Random(19)
        for _ in range(1000):
            a = tuple(rng.uniform(-10, 10) for _ in range(3))
            b = tuple(rng.choice((a[i], rng.uniform(-10, 10))) for i in range(3))
            lo = tuple(rng.uniform(-10, 10) for _ in range(3))
            hi = tuple(x + rng.uniform(0.01, 5) for x in lo)
            boxes = (("box", lo, hi),)
            size = (0.6, 1.2, 1.9)
            self.assertEqual(clear_segment(a, b, boxes, size), reference(a, b, boxes, size, 0.02))


if __name__ == "__main__":
    unittest.main()
