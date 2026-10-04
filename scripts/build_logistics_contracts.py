"""Generate the independent S14 shared contract family and explicit witness fixtures."""

import argparse
import importlib.util
import json
import sys
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from adaptive_hrc_scheduling.contracts.codec import schema  # noqa: E402
from adaptive_hrc_scheduling.contracts.logistics import (  # noqa: E402
    TOP_LEVEL,
    digest,
    dumps,
    mode_for,
    validate,
)
from adaptive_hrc_scheduling.domain import logistics as m  # noqa: E402
from adaptive_hrc_scheduling.logistics_backend import LogisticsBackend  # noqa: E402
from adaptive_hrc_scheduling.logistics_geometry import standing_point  # noqa: E402
from sim.isaac.scene.model import Box  # noqa: E402
from sim.isaac.scene.target_layout import (  # noqa: E402
    HOMES,
    PADS,
    PERSON_SIZE,
    TASKS,
    WalkGraph,
    static_boxes,
)

spec = importlib.util.spec_from_file_location(
    "c04_generator", ROOT / "scripts/build_building_contracts.py"
)
legacy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(legacy)


def operation(
    ident,
    action,
    *,
    product="PRODUCT-1",
    activity=None,
    entity=None,
    source="RECEIVE",
    target=None,
    route=None,
    roles=(),
    equipment=(),
    inputs=(),
    outputs=(),
    scrap=0,
    prior=(),
    phase="WORK",
    duration=0,
    hold=None,
    release=None,
):
    return m.Operation(
        ident,
        product,
        activity or ident,
        action,
        phase,
        tuple(prior),
        tuple(m.Role(person, qualification) for person, qualification, place in roles),
        tuple(m.PersonPosition(person, place) for person, qualification, place in roles),
        tuple(equipment),
        source,
        target,
        route,
        entity,
        tuple(m.Amount(*x) for x in inputs),
        tuple(m.Amount(*x) for x in outputs),
        scrap,
        duration,
        0,
        ("ML-METHOD",),
        (),
        None,
        hold,
        release,
    )


def configuration(*, synthetic=False, witness="V01", variant="SR-W1"):
    old = legacy.build_configuration(variant, products=3 if witness == "V03" else 1)
    purpose = "SYNTHETIC_TEST_ONLY" if synthetic else "RESEARCH_BLOCKED"
    extra = ("ML-METHOD", "ML-DEVICE", "ML-ROUTE", "ML-RELEASE", "ML-INITIAL-READY")
    evidence = old.evidence + tuple(
        m.Evidence(
            x,
            "PASS" if synthetic else "UNKNOWN",
            "SYNTHETIC_TEST" if synthetic else "UNRESOLVED",
            "S14 explicit test fixture; not industrial",
            "v1",
        )
        for x in extra
    )
    places = tuple(
        m.Place(
            k,
            "FINISHED"
            if k in ("FG1", "FG2")
            else "INTERFACE"
            if k == "DISPATCH"
            else "COMPONENT"
            if k == "BUF"
            else "BAY"
            if k in ("J2", "J3", "F1", "Q1", "OUT1")
            else "MATERIAL",
            2 if k == "BUF" else 1,
            tuple(p),
        )
        for k, p in PADS.items()
    )
    places += (m.Place("CRANE-PARK", "CONTROL", 1, (30, 18, 8)),)
    places += tuple(
        m.Place("CONTROL-" + p.id, "CONTROL", 1, HOMES[p.id]) for i, p in enumerate(old.people)
    )
    people = tuple(
        replace(
            p,
            qualifications=p.qualifications
            + (
                ("FORK",)
                if p.id == "P1"
                else ("CUT",)
                if p.id == "W1"
                else ("CART",)
                if p.id == "E1"
                else ("TOOL",)
                if p.id == "QA1"
                else ()
            ),
        )
        for p in old.people
    )
    devices = tuple(
        m.Device(i, k, loc, cap, "ML-DEVICE")
        for i, k, loc, cap in (
            ("CUT1", "FIXED", "PRE-IN", 0),
            ("WELD-J2", "FIXED", "J2", 0),
            ("WELD-J3", "FIXED", "J3", 0),
            ("R1", "FIXED", "J2", 0),
            ("CR1", "CRANE", "CRANE-PARK" if witness == "V01" else "PRE-OUT", 12),
            ("TEST1", "TOOL", "TEST-PARK", 0),
            ("FORK-01", "VEHICLE", "RECEIVE", 0.3),
            ("CART-01", "VEHICLE", "MEP-RECEIVE", 0.1),
            ("FIX-J2", "FIXTURE", "J2", 0),
            ("FIX-J3", "FIXTURE", "J3", 0),
        )
    )
    routes = tuple(
        m.Route(
            t.id,
            t.source,
            t.target,
            {"SCN-FORK-01": "FORK-01", "SCN-CART-01": "CART-01"}.get(t.carrier, t.carrier),
            ("AISLE-CR1",) if t.carrier == "CR1" else ("AISLE-WEST",),
            tuple(m.Point(*p) for p in t.points),
            0.5,
            0.2 if t.carrier == "CR1" else 0.5,
            "ML-ROUTE",
            tuple(t.size),
        )
        for t in TASKS
    )
    locations = {p.id: "CONTROL-" + p.id for p in people}
    core = []
    for a in old.activities:
        modes = []
        for mode in a.modes:
            units = []
            for u in mode.units:
                eq = tuple(
                    "WELD-J3"
                    if x == "WELD1" and a.code == "W-3D"
                    else "WELD-J2"
                    if x == "WELD1"
                    else "CR1"
                    if x == "HST1"
                    else x
                    for x in u.equipment
                )
                roles = u.roles
                if a.code.startswith("MV-"):
                    roles = tuple(
                        m.Role(i, q)
                        for i, q in (("Lop", "CRANE"), ("Lrig", "RIG"), ("Lsig", "SIGNAL"))
                    )
                elif a.code == "CUT":
                    roles = (m.Role("W1", "CUT"),)
                units.append(replace(u, equipment=eq, roles=roles))
            modes.append(
                replace(mode, units=tuple(units), enabled=mode.enabled and mode.kind != "HR-seq")
            )
        move = (
            replace(
                a.move,
                equipment="CR1",
                source="PRE-OUT" if a.move.source == "PRE" else a.move.source,
            )
            if a.move
            else None
        )
        core.append(
            replace(
                a,
                modes=tuple(modes),
                location="PRE-IN"
                if a.code == "CUT"
                else "PRE-OUT"
                if a.location == "PRE"
                else a.location,
                move=move,
            )
        )
    lots = ()
    entities = ()
    initial_ready = ()
    if witness == "V01":
        entities = (
            m.Entity("STEEL-COMP", "PRODUCT-1", "COMPONENT", "UNFABRICATED", 0.03, (2.8, 0.8, 0.2)),
        )
        locations.update(P1="RECEIVE", QA1="STEEL", W1="PRE-IN")
        lots = (
            m.Lot(
                "RAW",
                "PRODUCT-1",
                "STEEL",
                "piece",
                6,
                0.06,
                (2.8, 0.8, 0.2),
                "SUPPLIER",
                (),
                False,
                False,
                False,
            ),
            m.Lot(
                "PREPARED",
                "PRODUCT-1",
                "STEEL",
                "piece",
                5,
                0.03,
                (2.8, 0.8, 0.2),
                "UNPRODUCED",
                ("RAW",),
                False,
                False,
                False,
            ),
        )
        operations = [
            operation(
                "TAKE-IN",
                "TRANSFER",
                entity="RAW",
                source="RECEIVE",
                target="STEEL",
                route="S01",
                roles=(("P1", "FORK", "RECEIVE"), ("QA1", "QA", "STEEL")),
                equipment=("FORK-01",),
                phase="DRIVE",
            ),
            operation(
                "TO-PRE",
                "TRANSFER",
                entity="RAW",
                source="STEEL",
                target="PRE-IN",
                route="S02",
                prior=("TAKE-IN",),
                roles=(("P1", "FORK", "STEEL"), ("W1", "CUT", "PRE-IN")),
                equipment=("FORK-01",),
                phase="DRIVE",
            ),
            operation(
                "RESERVE-CUT",
                "RESERVE",
                activity="CUT",
                source="PRE-IN",
                inputs=(("RAW", 6),),
                prior=("TO-PRE",),
            ),
            operation(
                "CUT",
                "CONVERT",
                source="PRE-IN",
                inputs=(("RAW", 6),),
                outputs=(("PREPARED", 5),),
                scrap=1,
                prior=("RESERVE-CUT",),
                roles=(("W1", "CUT", "PRE-IN"),),
                equipment=("CUT1",),
                duration=1,
            ),
            operation(
                "DELIVER",
                "TRANSFER",
                entity="PREPARED",
                source="PRE-IN",
                target="PRE-OUT",
                route="S03",
                prior=("CUT",),
                roles=(("P1", "FORK", "PRE-IN"), ("W1", "CUT", "PRE-OUT")),
                equipment=("FORK-01",),
                phase="DRIVE",
            ),
            operation(
                "RESERVE-WORK",
                "RESERVE",
                activity="OPEN-WORK",
                source="PRE-OUT",
                inputs=(("PREPARED", 5),),
                prior=("DELIVER",),
            ),
            operation(
                "OPEN-WORK",
                "WORK",
                source="PRE-OUT",
                inputs=(("PREPARED", 5),),
                prior=("RESERVE-WORK",),
                roles=(("W1", "CUT", "PRE-OUT"),),
                duration=0.1,
            ),
        ]
    elif witness == "V02":
        locations.update(Lop="CONTROL-Lop", Lrig="PRE-OUT", Lsig="CONTROL-Lsig", W1="J2", W2="J3")
        entities = (m.Entity("BOTTOM", "PRODUCT-1", "COMPONENT", "PRE-OUT", 2, (6, 3, 0.2)),)
        operations = [
            operation(
                "MV-IN-B",
                "TRANSFER",
                entity="BOTTOM",
                source="PRE-OUT",
                target="J2",
                route="C01",
                equipment=("CR1",),
                roles=(
                    ("Lop", "CRANE", "CONTROL-Lop"),
                    ("Lrig", "RIG", "PRE-OUT"),
                    ("Lsig", "SIGNAL", "CONTROL-Lsig"),
                    ("W1", "WELD", "J2"),
                ),
            ),
            operation(
                "W-B",
                "WORK",
                source="J2",
                prior=("MV-IN-B",),
                roles=(("W1", "WELD", "J2"),),
                equipment=("WELD-J2", "FIX-J2"),
                duration=0.1,
            ),
            operation(
                "W-3D",
                "WORK",
                source="J3",
                roles=(("W1", "WELD", "J3"), ("W2", "WELD", "J3")),
                equipment=("WELD-J3", "FIX-J3"),
                duration=0.1,
            ),
        ]
    else:
        locations.update(Lop="CONTROL-Lop", Lrig="FG1", Lsig="CONTROL-Lsig", QA1="DISPATCH")
        entities = tuple(
            m.Entity(p.id, p.id, "PRODUCT", loc, 8, (6, 3, 3.2))
            for p, loc in zip(old.products, ("FG1", "FG2", "OUT1"), strict=True)
        )
        devices = tuple(replace(d, initial_location="FG1") if d.id == "CR1" else d for d in devices)
        initial_ready = tuple(p.id for p in old.products) if synthetic else ()
        operations = [
            operation(
                "SHIP-1",
                "TRANSFER",
                entity="PRODUCT-1",
                source="FG1",
                target="DISPATCH",
                route="F03",
                equipment=("CR1",),
                roles=(
                    ("Lop", "CRANE", "CONTROL-Lop"),
                    ("Lrig", "RIG", "FG1"),
                    ("Lsig", "SIGNAL", "CONTROL-Lsig"),
                    ("QA1", "QA", "DISPATCH"),
                ),
            ),
            operation(
                "RECEIVE-1",
                "RECEIVE_EXTERNAL",
                entity="PRODUCT-1",
                source="DISPATCH",
                target="EXTERNAL",
                prior=("SHIP-1",),
            ),
            operation(
                "BUFFER-3",
                "TRANSFER",
                product="PRODUCT-3",
                entity="PRODUCT-3",
                source="OUT1",
                target="FG1",
                route="F01",
                equipment=("CR1",),
                roles=(
                    ("Lop", "CRANE", "CONTROL-Lop"),
                    ("Lrig", "RIG", "OUT1"),
                    ("Lsig", "SIGNAL", "CONTROL-Lsig"),
                    ("QA1", "QA", "FG1"),
                ),
            ),
        ]
    # Explicit travel operations, never direct position setters in the public executor.
    movements = []
    if witness == "V01":
        movements = [
            ("W1", "PRE-IN", "PRE-OUT", "CUT"),
        ]
    if witness == "V02":
        movements = [("W1", "J2", "J3", "W-B")]
    if witness == "V03":
        movements = [("Lrig", "FG1", "OUT1", "SHIP-1"), ("QA1", "DISPATCH", "FG1", "SHIP-1")]
        empty_route = m.Route(
            "EMPTY-TO-OUT",
            "DISPATCH",
            "OUT1",
            "CR1",
            ("AISLE-CR1",),
            tuple(m.Point(PADS[x][0], PADS[x][1], 8) for x in ("DISPATCH", "OUT1")),
            0.5,
            0.2,
            "ML-ROUTE",
            (6, 3, 0.8),
        )
        routes += (empty_route,)
        operations.append(
            operation(
                "EMPTY-CR1",
                "EMPTY_RETURN",
                product="PRODUCT-3",
                entity="CR1",
                source="DISPATCH",
                target="OUT1",
                route=empty_route.id,
                roles=(("Lop", "CRANE", "CONTROL-Lop"),),
                equipment=("CR1",),
                prior=("SHIP-1",),
            )
        )
    planned_people = dict(locations)
    if witness == "V01":
        operations = [
            replace(o, component_outputs=("STEEL-COMP",)) if o.id == "OPEN-WORK" else o
            for o in operations
        ]
    for n, (person, source, target, pre) in enumerate(movements):
        context = SimpleNamespace(places=places, people=people)
        obstacles = static_boxes() + [
            Box(p, (point[0], point[1], point[2] + PERSON_SIZE[2] / 2), PERSON_SIZE)
            for p, loc in planned_people.items()
            if p != person
            for point in (standing_point(context, p, loc),)
        ]
        route = "WALK-ROUTE-" + str(n)
        route_record = m.Route(
            route,
            source,
            target,
            None,
            ("WALK-WEST",),
            tuple(
                m.Point(*point)
                for point in WalkGraph(obstacles).route(
                    *(
                        standing_point(SimpleNamespace(places=places, people=people), person, x)
                        for x in (source, target)
                    )
                )
            ),
            1,
            1,
            "ML-ROUTE",
            (0.6, 1.2, 1.9),
        )
        routes += (route_record,)
        planned_people[person] = target
        walk = operation(
            "WALK-" + str(n),
            "WALK",
            product="PRODUCT-3" if witness == "V03" else "PRODUCT-1",
            entity=person,
            source=source,
            target=target,
            route=route,
            roles=(
                (person, people[[p.id for p in people].index(person)].qualifications[0], source),
            ),
            prior=(pre,),
            phase="WALK",
        )
        operations.append(walk)
        # Make arrival an explicit prerequisite of operations requiring this person at the new place.
        operations = [
            replace(o, prerequisites=tuple(dict.fromkeys((*o.prerequisites, walk.id))))
            if o.id != walk.id
            and o.id != pre
            and any(x.person_id == person and x.location == target for x in o.role_locations)
            and walk.id not in o.prerequisites
            else o
            for o in operations
        ]
    c = m.Configuration(
        "S14-ML-1.0",
        "S14-ML-SPEC-1.0",
        "S13-TARGET-R5-2",
        "ML-" + witness + "-" + variant,
        purpose,
        "WITNESS_FRAGMENT",
        old.products,
        tuple(core),
        old.edges,
        people,
        tuple(m.PersonPosition(p, loc) for p, loc in locations.items()),
        places,
        devices,
        routes,
        lots,
        entities,
        tuple(operations),
        evidence,
        old.cap,
        old.min_rest_h,
        0.02,
        0.02,
        0.02,
        1,
        initial_ready,
        ("ML-INITIAL-READY",) if initial_ready else (),
    )
    validate(c)
    return c


def tool_configuration():
    c = configuration(synthetic=True, witness="V02")
    places = {p.id: p.position for p in c.places}
    routes = []
    operations = []
    for ident, source, target, action in (
        ("DEPLOY", "TEST-PARK", "TEST-USE", "DEPLOY_TOOL"),
        ("RETRIEVE", "TEST-USE", "TEST-PARK", "RETRIEVE_TOOL"),
    ):
        a, b = places[source], places[target]
        routes.append(
            m.Route(
                ident,
                source,
                target,
                "TEST1",
                ("TEST-AISLE",),
                tuple(m.Point(*p) for p in (a, (57, a[1], 0), (57, b[1], 0), b)),
                0.5,
                0.5,
                "ML-ROUTE",
                (0.8, 1.1, 1.2),
            )
        )
        operations.append(
            operation(
                ident,
                action,
                entity="TEST1",
                source=source,
                target=target,
                route=ident,
                roles=(("QA1", "TOOL", source),),
                equipment=("TEST1",),
                phase="PUSH",
                hold="TEST1" if ident == "DEPLOY" else None,
                release="TEST1" if ident == "RETRIEVE" else None,
                prior=("TEST-CHECK",) if ident == "RETRIEVE" else (),
            )
        )
    operations.append(
        operation(
            "TEST-CHECK",
            "WORK",
            source="TEST-USE",
            roles=(("QA1", "TOOL", "TEST-USE"),),
            equipment=("TEST1",),
            hold="TEST1",
            release="TEST1",
            prior=("DEPLOY",),
            duration=0.1,
        )
    )
    operations.append(operation("STEAL", "WORK", source="TEST-USE", equipment=("TEST1",)))
    return replace(
        c,
        operations=tuple(operations),
        routes=c.routes + tuple(routes),
        person_positions=tuple(
            replace(p, location="TEST-PARK") if p.person_id == "QA1" else p
            for p in c.person_positions
        ),
    )


def command(world, op_id, ident=None):
    o = world.operations[op_id]
    return m.DispatchCommand(
        "S14-ML-1.0",
        world.config.id,
        world.config_hash,
        world.run_id,
        world.epoch,
        ident or "CMD-" + op_id,
        o.product_id,
        o.activity_id,
        o.id,
        o.attempt_index,
        o.unit_index,
        mode_for(o),
        world.s.time_h,
        world.s.revision,
        tuple(m.RoleBinding(r.id, r.id) for r in o.roles),
    )


def generated():
    c = configuration()
    world = LogisticsBackend(c)
    obs = world.observe()
    cmd = command(world, "TAKE-IN")
    receipt = world.dispatch(cmd)
    records = [
        c,
        cmd,
        receipt,
        world.snapshot(),
        obs,
        m.PlanningInput("S14-ML-1.0", c.id, obs, c.operations, 100),
        m.Plan("S14-ML-1.0", c.id, obs.id, (), "WAIT", "QUALIFICATION_HOLD"),
        m.HiddenScenario("S14-ML-1.0", c.id, ()),
        m.OfflineEvaluation(
            "S14-ML-1.0", c.id, 0, 0, 0, 0, 0, 1, 0, 0, "INDEPENDENT_EVENT_RECONSTRUCTION"
        ),
        m.RunManifest(
            "S14-ML-1.0",
            c.id,
            digest(c),
            c.specification,
            c.layout_version,
            "logistics-event",
            world.run_id,
            0,
            "WORKING_TREE",
            "HOLD",
            "NOT_ESTABLISHED",
        ),
    ]
    out = {
        f"examples/logistics_contracts/{type(x).__name__}.json": dumps(x, config=c) for x in records
    }
    for witness in ("V01", "V02", "V03"):
        value = configuration(synthetic=True, witness=witness)
        out[f"examples/logistics_contracts/{witness}.json"] = dumps(value)
    value = configuration(variant="SR-W2")
    out["examples/logistics_contracts/SR-W2.json"] = dumps(value)
    for kind in TOP_LEVEL:
        out[f"schemas/logistics/{kind.__name__}.schema.json"] = (
            json.dumps(schema(kind), indent=2, sort_keys=True) + "\n"
        )
    return out


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    for name, text in generated().items():
        path = ROOT / name
        if args.check:
            if not path.exists() or path.read_bytes() != text.encode():
                raise SystemExit("Generated drift: " + name)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8", newline="\n")
    print("S14: 14 examples and 10 schemas " + ("verified" if args.check else "generated"))
