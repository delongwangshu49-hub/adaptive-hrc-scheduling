"""Limited migration witnesses, separate from a complete S15 production run."""

import unittest
from dataclasses import replace

from test_logistics import finish, fixture

from adaptive_hrc_scheduling.contracts.codec import ContractError
from adaptive_hrc_scheduling.contracts.logistics import validate
from adaptive_hrc_scheduling.domain import logistics as m
from adaptive_hrc_scheduling.logistics_backend import LogisticsBackend
from adaptive_hrc_scheduling.logistics_checker import check_run


class MigrationTests(unittest.TestCase):
    def audit(self, w):
        report = check_run(w.config, w.snapshot())
        self.assertEqual(report.status, "PASS", report.findings[:4])

    def test_four_component_moves_keep_distinct_identity_and_crane_roles(self):
        for code, route_id in (
            ("MV-IN-B", "C01"),
            ("MV-IN-T", "C01"),
            ("MV-B", "C02"),
            ("MV-T", "C02"),
        ):
            with self.subTest(code=code):
                c = fixture.configuration(synthetic=True, witness="V02")
                route = next(r for r in c.routes if r.id == route_id)
                ident = "TOP" if code.endswith("T") else "BOTTOM"
                roles = (
                    ("Lop", "CRANE", "CONTROL-Lop"),
                    ("Lsig", "SIGNAL", "CONTROL-Lsig"),
                    ("Lrig", "RIG", route.source),
                    ("W1", "WELD", route.target),
                )
                op = fixture.operation(
                    code,
                    "TRANSFER",
                    entity=ident,
                    source=route.source,
                    target=route.target,
                    route=route.id,
                    roles=roles,
                    equipment=("CR1",),
                )
                locs = {i: p for i, q, p in roles}
                c = replace(
                    c,
                    entities=(
                        m.Entity(ident, "PRODUCT-1", "COMPONENT", route.source, 2, (6, 3, 0.2)),
                    ),
                    operations=(op,),
                    devices=tuple(
                        replace(d, initial_location=route.source) if d.id == "CR1" else d
                        for d in c.devices
                    ),
                    person_positions=tuple(
                        replace(p, location=locs.get(p.person_id, p.location))
                        for p in c.person_positions
                    ),
                )
                w = LogisticsBackend(c)
                finish(w, code)
                self.assertEqual(w._position(ident).location, route.target)
                self.assertEqual(len(w.events[0].command.roles), 4)
                self.audit(w)

    def test_join_requires_each_component_landed_before_assembly(self):
        c = fixture.configuration(synthetic=True, witness="V02")
        entities = (
            m.Entity("BOTTOM", "PRODUCT-1", "COMPONENT", "BUF", 2, (6, 3, 0.2)),
            m.Entity("TOP", "PRODUCT-1", "COMPONENT", "BUF", 2, (6, 3, 0.2)),
            m.Entity("COLUMNS", "PRODUCT-1", "COMPONENT", "PRE-OUT", 0.8, (1.6, 1.6, 2.8)),
            m.Entity("PRODUCT-1", "PRODUCT-1", "PRODUCT", "UNASSEMBLED", 4.8, (6, 3, 3.2)),
        )
        locs = {p.id: p.position for p in c.places}
        roles = (
            ("Lop", "CRANE", "CONTROL-Lop"),
            ("Lrig", "RIG", "CONTROL-Lrig"),
            ("Lsig", "SIGNAL", "CONTROL-Lsig"),
            ("W1", "WELD", "J3"),
        )
        operations = []
        routes = list(c.routes)

        def empty(ident, source, target):
            route = m.Route(
                ident,
                source,
                target,
                "CR1",
                ("AISLE-CR1",),
                tuple(m.Point(locs[x][0], locs[x][1], 8) for x in (source, target)),
                0.5,
                0.2,
                "ML-ROUTE",
                (6, 3, 3.2),
            )
            routes.append(route)
            operations.append(
                fixture.operation(
                    ident,
                    "EMPTY_RETURN",
                    entity="CR1",
                    source=source,
                    target=target,
                    route=ident,
                    roles=roles[:3],
                    equipment=("CR1",),
                    prior=(operations[-1].id,),
                )
            )

        for ident, source, route_id in (
            ("BOTTOM", "BUF", "C03"),
            ("TOP", "BUF", "C03"),
            ("COLUMNS", "PRE-OUT", "C04"),
        ):
            if operations:
                empty("EMPTY-" + ident, "J3", source)
            operations.append(
                fixture.operation(
                    "JOIN-" + ident,
                    "TRANSFER",
                    entity=ident,
                    source=source,
                    target="J3",
                    route=route_id,
                    roles=roles,
                    equipment=("CR1",),
                    prior=(operations[-1].id,) if operations else (),
                )
            )
        assembly = replace(
            fixture.operation(
                "ASSEMBLE",
                "WORK",
                entity="PRODUCT-1",
                source="J3",
                target="J3",
                equipment=("FIX-J3",),
                roles=(("W1", "WELD", "J3"), ("W2", "WELD", "J3")),
                duration=0.1,
                prior=(operations[-1].id,),
            ),
            component_inputs=("BOTTOM", "TOP", "COLUMNS"),
        )
        operations.append(assembly)
        starts = {i: p for i, q, p in roles}
        starts["W2"] = "J3"
        c = replace(
            c,
            entities=entities,
            operations=tuple(operations),
            routes=tuple(routes),
            devices=tuple(
                replace(d, initial_location="BUF") if d.id == "CR1" else d for d in c.devices
            ),
            person_positions=tuple(
                replace(p, location=starts.get(p.person_id, p.location)) for p in c.person_positions
            ),
        )
        w = LogisticsBackend(c)
        rejected = w.dispatch(fixture.command(w, "ASSEMBLE", "EARLY-JOIN"))
        self.assertEqual(rejected.kind, "DEFERRED")
        for op in operations:
            finish(w, op.id)
        self.assertEqual(w._position("PRODUCT-1").location, "J3")
        self.assertTrue(
            all(w._position(i).location == "INCORPORATED" for i in assembly.component_inputs)
        )
        self.audit(w)

    def test_migration_keeps_work_durations_graph_and_hr_disabled(self):
        for variant in ("SR-W1", "SR-W2"):
            old = fixture.legacy.build_configuration(variant, products=1)
            new = fixture.configuration(variant=variant)
            self.assertEqual(new.core_edges, old.edges)
            self.assertEqual(len(new.core_activities), 37)
            for a, b in zip(old.activities, new.core_activities):
                self.assertEqual(a.id, b.id)
                self.assertEqual(a.quality_evidence, b.quality_evidence)
                for x, y in zip(a.modes, b.modes):
                    self.assertEqual([u.base_h for u in x.units], [u.base_h for u in y.units])
                    if y.kind == "HR-seq":
                        self.assertFalse(y.enabled)
                    if a.code in ("MV-IN-B", "MV-IN-T", "MV-B", "MV-T"):
                        self.assertTrue(
                            all(
                                "CR1" in u.equipment
                                and {r.id for r in u.roles} == {"Lop", "Lrig", "Lsig"}
                                for u in y.units
                            )
                        )
            self.assertFalse(any(e.status == "PASS" for e in new.evidence))

    def test_components_cannot_be_borrowed_from_another_product(self):
        c = fixture.configuration(synthetic=True, witness="V03")
        op = replace(
            fixture.operation("BAD-JOIN", "WORK", entity="PRODUCT-1", source="J3", target="J3"),
            component_inputs=("PRODUCT-2",),
        )
        with self.assertRaisesRegex(ContractError, "COMPONENT_INPUTS"):
            validate(replace(c, operations=c.operations + (op,)))


if __name__ == "__main__":
    unittest.main()
