"""Build S15 production candidates from approved recipe and unchanged core units."""

import argparse
import json
import sys
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
# Runtime launchers choose their package source. Importing this builder during
# an isolated wheel test must not redirect package imports to the checkout.
sys.path.insert(0, str(ROOT))

import build_logistics_contracts as old  # noqa: E402

from adaptive_hrc_scheduling import production_supports as supports  # noqa: E402
from adaptive_hrc_scheduling.contracts.codec import as_data, decode  # noqa: E402
from adaptive_hrc_scheduling.contracts.production import dumps, validate  # noqa: E402
from adaptive_hrc_scheduling.domain import production as m  # noqa: E402
from adaptive_hrc_scheduling.production_geometry import ground_points, pack, route  # noqa: E402
from adaptive_hrc_scheduling.production_mapping import RECIPE_DIGEST, recipe  # noqa: E402


class Builder:
    def __init__(self, products=1, variant="SR-W1", synthetic=True, rework=False):
        self.rework_enabled = rework
        base = old.configuration(synthetic=synthetic, variant=variant)
        self.base = base
        self.places = {p.id: m.Place(p.id, p.kind, p.capacity, p.position) for p in base.places}
        self.places.update(
            {
                name: m.Place(name, "CONTROL", 1, point)
                for name, point in (("FORK-PARK", (3, 19, 0.8)), ("CART-PARK", (10, 34, 0.8)))
            }
        )
        self.places["CONTROL-PARK-Lsig"] = m.Place("CONTROL-PARK-Lsig", "CONTROL", 1, (58, 42, 0))
        self.lots, self.entities, self.operations, self.routes, self.bindings = [], [], [], [], []
        self.groups, self.products, self.core, self.edges = [], [], [], []
        self.evidence = {e.id: e for e in base.evidence if not e.id.startswith("PRODUCT-")}
        self.evidence["SC-SUPPORT"] = replace(
            self.evidence["ML-METHOD"],
            id="SC-SUPPORT",
            status="UNKNOWN",
            reference="SC01-SC04 manual support reconfiguration; not industrial qualification",
        )
        for root in supports.ROOTS:
            point = self.places[root].position
            x = point[0] + (4.5 if root == "J3" else -4.5 if root == "F1" else 0)
            for person, sign in (("P1", -1), ("E1", 1)):
                name = f"CONTROL-SUPPORT-{root}-{person}"
                station = (
                    (58.5, 8 if person == "P1" else 10, 0)
                    if root == "J3"
                    else (x + sign * 1.8, point[1] + (4.0 if root == "F1-KIT" else -4.0), 0)
                )
                self.places[name] = m.Place(name, "CONTROL", 1, station)
        self.synthetic = synthetic
        self.ports, self.last_delivery, self.rows, self.steel_nets = {}, {}, {}, {}
        for n in range(1, products + 1):
            pid = f"PRODUCT-{n}"
            self.products.append(
                replace(
                    base.products[0],
                    id=pid,
                    order_id=f"ORDER-{n}",
                    mass_t=8.05 if variant == "SR-W2" else 8,
                )
            )
            for source, destination, kind in (
                (base.core_activities, self.core, m.Activity),
                (base.core_edges, self.edges, m.Edge),
            ):
                destination.extend(
                    decode(kind, json.loads(json.dumps(as_data(item)).replace("PRODUCT-1", pid)))
                    for item in source
                )
            for e in base.evidence:
                if e.id.startswith("PRODUCT-"):
                    e = replace(e, id=e.id.replace("PRODUCT-1", pid))
                    self.evidence[e.id] = e
            self.add_materials(pid, variant)
        for p in self.products:
            self.add_production(p.id)
        if rework:
            from build_production_rework import append_rework

            for p in self.products:
                append_rework(self, p.id)

    def operation(
        self,
        ident,
        action,
        *,
        product,
        activity=None,
        source="PRE-OUT",
        target=None,
        entity=None,
        prior=(),
        roles=(),
        equipment=(),
        inputs=(),
        outputs=(),
        input_places=(),
        output_places=(),
        duration=0,
        phase="WORK",
        rt=None,
        **extra,
    ):
        op = m.Operation(
            ident,
            product,
            activity or ident,
            action,
            phase,
            tuple(prior),
            tuple(m.Role(i, q) for i, q, loc in roles),
            tuple(m.PersonPosition(i, loc) for i, q, loc in roles),
            tuple(equipment),
            source,
            target,
            rt.id if rt else None,
            entity,
            tuple(m.Amount(i, q) for i, q in inputs),
            tuple(m.Amount(i, q) for i, q in outputs),
            0,
            duration,
            0,
            ("ML-METHOD",),
            (),
            None,
            None,
            None,
            input_places=tuple(m.MaterialPort(i, p) for i, p in input_places),
            output_places=tuple(m.MaterialPort(i, p) for i, p in output_places),
        )
        op = replace(op, **extra)
        self.operations.append(op)
        if rt:
            self.routes.append(rt)
        return op.id

    def material_slot(self, root, ident, offset, *, working=False):
        base = self.places[root].position
        if working:
            base = (
                base[0] + (4.5 if root == "J3" else -4.5 if root == "F1" else 0),
                base[1],
                0.8,
            )
        name = root + "." + ident
        self.places[name] = m.Place(
            name, "MATERIAL", 1, tuple(a + b for a, b in zip(base, offset)), root
        )
        return name

    def add_materials(self, pid, variant):
        data = recipe()
        rows = list(data["rows"])
        if variant == "SR-W2":
            rows += [
                dict(
                    r,
                    net_mass_each_t=r["mass_t"],
                    gross_mass_each_t=r["mass_t"],
                    scrap_each_t=0,
                    transport_size_m=r["size_m"],
                    content=r["id"],
                )
                for r in data["extensions"]
            ]
        rows += [
            dict(
                id="WATER",
                bom_id="AUX-WATER",
                content="test_water",
                activity="TEST-SET",
                packages=2,
                net_mass_each_t=0.05,
                gross_mass_each_t=0.05,
                scrap_each_t=0,
                transport_size_m=[1.2, 0.8, 0.6],
                carrier="CART-01",
            )
        ]
        groups = {}
        for row in rows:
            group = "STEEL" if row["id"] in ("ST-B", "ST-T", "ST-C") else row["activity"]
            for index in range(row["packages"]):
                ident = f"{pid}.{row['id']}.{index + 1:02}"
                self.rows[ident] = row
                groups.setdefault(group, []).append((ident, tuple(row["transport_size_m"])))
        for code, boxes in groups.items():
            steel = code == "STEEL"
            bounds = (6, 2.4, 1.6) if steel else (2.4, 2.4, 2)
            group_id = pid + ".GROUP-" + code
            self.groups.append(
                m.Group(group_id, pid, code, 28 if steel else 11, 3.318 if steel else 1.2, bounds)
            )
            offsets = pack(
                boxes,
                bounds,
                vertical_clearance={
                    i: (
                        0.17
                        if self.rows[i]["id"] == "FL"
                        else 0.12
                        if self.rows[i]["carrier"] == "FORK-01"
                        else 0.1
                    )
                    for i, _ in boxes
                },
                depth_first=True,
            )
            if code == "LINING":
                # Keep the tallest package at the top of the five-pack column
                # so the highest handoff remains within SH01's LINING-only
                # 2.45 m limit; other groups retain the 2.4 m limit.
                panels = sorted(i for i, _ in boxes if self.rows[i]["id"] == "EN-L")
                ceilings = sorted(i for i, _ in boxes if self.rows[i]["id"] == "FI-C")
                sizes = dict(boxes)
                offsets = {}
                for y, column in ((0.6, panels[:4]), (-0.6, [*ceilings, *panels[4:]])):
                    z = 0
                    for n, ident in enumerate(column):
                        offsets[ident] = (0, y, z)
                        z += sizes[ident][2] + 0.161
            if code == "EXT":
                panels = sorted(i for i, _ in boxes if self.rows[i]["id"] == "EN-X")
                openings = sorted(i for i, _ in boxes if self.rows[i]["id"] != "EN-X")
                sizes = dict(boxes)
                offsets = {}
                for y, column in ((0.6, panels[:4]), (-0.6, [*panels[4:], *openings])):
                    z = 0
                    for ident in column:
                        offsets[ident] = (0, -0.75 if self.rows[ident]["id"] == "FI-D" else y, z)
                        z += sizes[ident][2] + 0.161
            if code == "FIT":
                # Rear kitchen/sink packages need the same full-tine gap as
                # other wide packs. Both front columns remain inside the
                # original group envelope and below the unchanged 2.4 m limit.
                sizes = dict(boxes)
                rear = sorted((i for i, _ in boxes if self.rows[i]["id"] == "FI-S")) + sorted(
                    i for i, _ in boxes if self.rows[i]["id"] == "FI-K"
                )
                vents = sorted(i for i, _ in boxes if self.rows[i]["id"] == "ME-V")
                columns = (
                    (0, 0.7, rear),
                    (
                        -0.6,
                        -0.6,
                        [*(i for i, _ in boxes if self.rows[i]["id"] == "FI-WC"), vents[1]],
                    ),
                    (
                        0.6,
                        -0.6,
                        [
                            *(i for i, _ in boxes if self.rows[i]["id"] == "FI-B"),
                            vents[0],
                            *(i for i, _ in boxes if self.rows[i]["id"] == "W2-BASIN"),
                        ],
                    ),
                )
                offsets = {}
                for x, y, column in columns:
                    z = 0
                    for ident in column:
                        offsets[ident] = (x, y, z)
                        z += sizes[ident][2] + (0.161 if y == 0.7 else 0.1)
            if code == "FLOOR":
                # Use the available 0.35 m depth gap between the broad floor
                # stack and the two front wet-material columns. The fork mast
                # needs this gap during lateral access to the rear stack.
                offsets = {
                    i: (x, -0.8 if self.rows[i]["id"] == "WT-F" else y, z)
                    for i, (x, y, z) in offsets.items()
                }
            if steel:
                long_ids = sorted(i for i, size in boxes if size[0] == 6)
                column_ids = sorted(i for i, size in boxes if size[0] != 6)
                offsets = {
                    i: (0, 0.8 - 0.8 * (n // 8), 0.172 * (n % 8)) for n, i in enumerate(long_ids)
                }
                offsets.update(
                    {
                        i: (x, y, 1.5)
                        for i, (x, y) in zip(
                            column_ids, ((-1.6, 0.8), (-1.6, 0), (-1.6, -0.8), (1.2, -0.8))
                        )
                    }
                )
            for ident, size in boxes:
                row = self.rows[ident]
                self.lots.append(
                    m.Lot(
                        ident,
                        pid,
                        "STEEL" if steel else row["bom_id"],
                        "t",
                        row["gross_mass_each_t"],
                        row["gross_mass_each_t"],
                        size,
                        "SUPPLIER",
                        (),
                        False,
                        False,
                        False,
                        group_id,
                        row["bom_id"],
                        "AUXILIARY" if code == "TEST-SET" else "PRODUCT",
                    )
                )
                roots = (
                    ("RECEIVE", "STEEL", "PRE-IN")
                    if steel
                    else (
                        "MEP-RECEIVE",
                        "MEP-STORE",
                        "KIT",
                        "F1-KIT",
                        "J3" if code == "COAT" else "F1",
                    )
                )
                self.ports[ident] = {
                    r: self.material_slot(
                        r,
                        ident,
                        (offsets[ident][0], -offsets[ident][1], offsets[ident][2])
                        if r == "PRE-IN"
                        else offsets[ident],
                        working=r in ("J3", "F1"),
                    )
                    for r in roots
                }
                if steel:
                    net = ident + ".NET"
                    self.lots.append(
                        m.Lot(
                            net,
                            pid,
                            "STEEL",
                            "t",
                            row["net_mass_each_t"],
                            row["net_mass_each_t"],
                            size,
                            "UNPRODUCED",
                            (ident,),
                            False,
                            False,
                            False,
                            group_id,
                            "B-ST",
                        )
                    )
                    self.ports[net] = {
                        "PRE-IN": self.material_slot("PRE-IN", net, (1.0, 0, 1.38))
                        if row["id"] == "ST-C" and ident.endswith(".04")
                        else self.ports[ident]["PRE-IN"],
                        "PRE-OUT": self.material_slot(
                            "PRE-OUT",
                            net,
                            (
                                -1.6 + 2.8 * ((int(ident.rsplit(".", 1)[-1]) - 1) % 2),
                                0.8,
                                1.5 + 0.224 * ((int(ident.rsplit(".", 1)[-1]) - 1) // 2),
                            )
                            if row["id"] == "ST-C"
                            else offsets[ident],
                        ),
                    }
                    self.steel_nets[ident] = net
        for name, mass, size in (
            ("BOTTOM", 1.2, (6, 3, 0.2)),
            ("TOP", 1.2, (6, 3, 0.2)),
            ("COLUMNS", 0.76, (1.6, 1.6, 2.8)),
        ):
            self.entities.append(
                m.Entity(pid + "." + name, pid, "COMPONENT", "UNFABRICATED", mass, size)
            )
        self.entities.append(
            m.Entity(
                pid, pid, "PRODUCT", "UNASSEMBLED", 8.05 if variant == "SR-W2" else 8, (6, 3, 3.2)
            )
        )

    def transfer(
        self,
        ident,
        pid,
        entity,
        source,
        target,
        device,
        prior,
        *,
        activity=None,
        core_roles=None,
        mode=None,
        unit_index=0,
    ):
        a, b = self.places[source].position, self.places[target].position
        if device == "CR1":
            points = (a, (*a[:2], 4.1), (b[0], a[1], 4.1), (*b[:2], 4.1), b)
            rs = (
                ("Lop", "CRANE", "CONTROL-Lop"),
                ("Lrig", "RIG", "CONTROL-Lrig"),
                ("Lsig", "SIGNAL", "CONTROL-Lsig"),
            )
            speed, vertical = 0.5, 0.2
        else:
            points = ground_points(
                SimpleNamespace(places=tuple(self.places.values())), source, target, device
            )
            who, qual = ("P1", "FORK") if device == "FORK-01" else ("E1", "CART")
            rs = ((who, qual, source),)
            root = self.places[target].parent
            if root in ("J3", "F1") and entity in self.rows:
                code = self.rows[entity]["activity"]
                activity_row = next(a for a in self.core if a.product_id == pid and a.code == code)
                unit = next(mode for mode in activity_row.modes if mode.enabled).units[0]
                receiver = next((r for r in unit.roles if r.id != who), None)
                if receiver:
                    rs += ((receiver.id, receiver.qualification, root),)
            speed, vertical = 0.5, 0.5
        if core_roles:
            rs = tuple((r.id, r.qualification, "CONTROL-" + r.id) for r in core_roles)
        rt = m.Route(
            "ROUTE-" + ident,
            source,
            target,
            device,
            ("AISLE-CR1",) if device == "CR1" else ("GROUND-SPINE",),
            tuple(m.Point(*p) for p in points),
            speed,
            vertical,
            "ML-ROUTE",
            (6, 3, 3.2),
        )
        return self.operation(
            ident,
            "TRANSFER",
            product=pid,
            activity=activity,
            source=source,
            target=target,
            entity=entity,
            prior=prior,
            roles=rs,
            equipment=(device,),
            rt=rt,
            phase="WORK" if device == "CR1" else "DRIVE" if device == "FORK-01" else "PUSH",
            production_mode=mode,
            unit_index=unit_index,
        )

    def deliver(self, ident, pid, prior):
        if ident in self.last_delivery:
            return self.last_delivery[ident]
        row = self.rows.get(ident) or self.rows[ident.removesuffix(".NET")]
        roots = list(self.ports[ident])
        previous = tuple(prior)
        for n, (src, dst) in enumerate(zip(roots, roots[1:])):
            task = self.transfer(
                f"{ident}.DELIVER-{n}",
                pid,
                ident,
                self.ports[ident][src],
                self.ports[ident][dst],
                row["carrier"],
                previous,
            )
            previous = (task,)
        self.last_delivery[ident] = previous[-1]
        return previous[-1]

    def add_production(self, pid):
        core = [a for a in self.core if a.product_id == pid]
        terminal = {}
        first = {}
        by_code = {a.code: a for a in core}
        component_offsets = {
            pid + ".BOTTOM": (0, 0, 2.2),
            pid + ".TOP": (0, 0, 2.2),
            pid + ".COLUMNS": (-2.0, -0.7, 0),
        }
        component_places = {
            ident: self.material_slot("PRE-OUT", ident, offset)
            for ident, offset in component_offsets.items()
        }
        buffer_places = {
            pid + "." + kind: self.material_slot("BUF", pid + "." + kind, (0, dy, 0))
            for kind, dy in (("BOTTOM", -1.5), ("TOP", 1.5))
        }
        join_places = {
            pid + "." + kind: self.material_slot("J3", pid + "." + kind, (0, 0, dz))
            for kind, dz in (("BOTTOM", 0), ("COLUMNS", 0.2), ("TOP", 3))
        }
        for a in core:
            prior = tuple(terminal[e.source] for e in self.edges if e.target == a.id)
            mode = next(x for x in a.modes if x.enabled)
            mapped = []
            gates = tuple(
                next(x.quality_evidence for x in core if x.id == e.source)
                for e in self.edges
                if e.target == a.id and e.relation == "quality"
            )
            wait_gate = next(
                (
                    next(x.release_evidence for x in core if x.id == e.source)
                    for e in self.edges
                    if e.target == a.id and e.relation == "wait_release"
                ),
                None,
            )
            material = [
                i
                for i, row in self.rows.items()
                if i.startswith(pid + ".") and row["activity"] == a.code
            ]
            if a.code == "CUT":
                material = [i for i in self.steel_nets if i.startswith(pid + ".")]
            if a.move:
                entities = (
                    tuple(pid + "." + kind for kind in ("BOTTOM", "COLUMNS", "TOP"))
                    if a.code == "JOIN-IN"
                    else a.move.entity_ids
                )
                for index, entity in enumerate(entities):
                    source = (
                        component_places[entity]
                        if a.move.source == "PRE-OUT" or entity.endswith("COLUMNS")
                        else buffer_places[entity]
                        if a.move.source == "BUF"
                        else a.move.source
                    )
                    before = prior
                    if a.code in ("MV-IN-B", "MV-IN-T", "JOIN-IN"):
                        kind = entity.rsplit(".", 1)[-1]
                        row_id = {"BOTTOM": "ST-B", "TOP": "ST-T", "COLUMNS": "ST-C"}[kind]
                        net_ids = [
                            v
                            for k, v in self.steel_nets.items()
                            if k.startswith(pid + "." + row_id + ".")
                        ]
                        deliveries = [
                            self.deliver(i, pid, (terminal[by_code["CUT"].id],)) for i in net_ids
                        ]
                        form_id = pid + ".FORM-" + kind
                        if not any(o.id == form_id for o in self.operations):
                            amounts = [
                                (i, next(lot.quantity for lot in self.lots if lot.id == i))
                                for i in net_ids
                            ]
                            reserve = self.operation(
                                form_id + ".RESERVE",
                                "RESERVE",
                                product=pid,
                                activity=form_id,
                                prior=deliveries,
                                inputs=amounts,
                                input_places=[(i, self.ports[i]["PRE-OUT"]) for i in net_ids],
                            )
                            self.operation(
                                form_id,
                                "CONVERT",
                                product=pid,
                                prior=(reserve, *prior),
                                source=component_places[entity],
                                inputs=amounts,
                                input_places=[(i, self.ports[i]["PRE-OUT"]) for i in net_ids],
                                component_outputs=(entity,),
                            )
                        if self.places[source].parent == "PRE-OUT":
                            before = (*prior, form_id)
                    ident = a.id + f".MOVE-{index}"
                    mapped.append(
                        self.transfer(
                            ident,
                            pid,
                            entity,
                            source,
                            buffer_places[entity]
                            if a.move.target == "BUF"
                            else join_places[entity]
                            if a.code == "JOIN-IN"
                            else a.move.target,
                            "CR1",
                            (*before, *mapped),
                            activity=a.id,
                            core_roles=mode.units[0].roles,
                            mode=mode.kind,
                        )
                    )
                self.bindings.append(m.CoreBinding(a.id, mode.id, mode.units[0].id, tuple(mapped)))
            else:
                if a.code == "Q-MEP":
                    tool_route = route(
                        SimpleNamespace(places=tuple(self.places.values())),
                        pid + ".TEST-DEPLOY-ROUTE",
                        "TEST-PARK",
                        "TEST-USE",
                        "TEST1",
                    )
                    deploy = self.operation(
                        pid + ".TEST-DEPLOY",
                        "DEPLOY_TOOL",
                        product=pid,
                        source="TEST-PARK",
                        target="TEST-USE",
                        entity="TEST1",
                        prior=prior,
                        roles=(("QA1", "TOOL", "TEST-PARK"),),
                        equipment=("TEST1",),
                        rt=tool_route,
                    )
                    prior = (*prior, deploy)
                deliveries = [self.deliver(i, pid, prior) for i in material]
                self.operations = [
                    replace(o, quality_gates=gates)
                    if self.rework_enabled
                    and a.code == "TILE"
                    and o.entity_id in material
                    and o.id.endswith(tuple(f".DELIVER-{n}" for n in range(4)))
                    else o
                    for o in self.operations
                ]
                if material and a.code != "CUT":
                    # Every rear row reaches its consuming station before a
                    # nearer row enters the corridor. The shared ingress and
                    # dispatch constraints protect the full carrier/operator,
                    # including low cart trays that cannot cross stored packs.
                    depth = {
                        i: self.places[next(iter(self.ports[i].values()))].position[1]
                        for i in material
                    }
                    predecessors = {
                        i + ".DELIVER-0": tuple(
                            self.last_delivery[j] for j in material if depth[j] > depth[i]
                        )
                        for i in material
                    }
                    self.operations = [
                        replace(o, prerequisites=(*o.prerequisites, *predecessors[o.id]))
                        if o.id in predecessors
                        else o
                        for o in self.operations
                    ]
                amounts = [
                    (i, next(lot.quantity for lot in self.lots if lot.id == i)) for i in material
                ]
                ports = [(i, list(self.ports[i].values())[-1]) for i in material]
                if amounts:
                    reserve = self.operation(
                        a.id + ".RESERVE",
                        "RESERVE",
                        product=pid,
                        activity=a.id,
                        source=a.location,
                        prior=(*prior, *deliveries),
                        inputs=amounts,
                        input_places=ports,
                    )
                    prior = (reserve,)
                units = mode.units or (
                    SimpleNamespace(
                        id="GATE", base_h=0, roles=(), equipment=(), kappa=0, phase="WORK"
                    ),
                )
                for index, u in enumerate(units):
                    selected = [
                        (i, q) for n, (i, q) in enumerate(amounts) if n % len(units) == index
                    ]
                    if a.code == "CUT":
                        selected = [
                            (i, q)
                            for i, q in amounts
                            if (".ST-B." in i or ".ST-C." in i and int(i.rsplit(".", 1)[-1]) <= 2)
                            == (index == 0)
                        ]
                    inputs = selected
                    outputs = (
                        [
                            (
                                self.steel_nets[i],
                                next(
                                    lot.quantity
                                    for lot in self.lots
                                    if lot.id == self.steel_nets[i]
                                ),
                            )
                            for i, q in inputs
                        ]
                        if a.code == "CUT"
                        else []
                    )
                    if a.code == "CUT":
                        scrap_id = pid + f".SCRAP-{index}"
                        amount = round(sum(q for i, q in inputs) - sum(q for i, q in outputs), 9)
                        self.lots.append(
                            m.Lot(
                                scrap_id,
                                pid,
                                "STEEL",
                                "t",
                                amount,
                                amount,
                                (1.2, 0.8, 0.3),
                                "UNPRODUCED",
                                tuple(i for i, q in inputs),
                                False,
                                False,
                                False,
                                pid + ".GROUP-STEEL",
                                "B-ST",
                                "SCRAP",
                            )
                        )
                        self.ports[scrap_id] = {
                            "PRE-IN": self.material_slot(
                                "PRE-IN", scrap_id, (2.4, -0.8 if index == 0 else 0.8, 1.3)
                            )
                        }
                        outputs.append((scrap_id, amount))
                    entity = (
                        pid
                        if a.location in ("J3", "F1", "OUT1")
                        else (
                            pid + ".BOTTOM"
                            if a.code == "W-B"
                            else pid + ".TOP"
                            if a.code == "W-T"
                            else None
                        )
                    )
                    components = (
                        tuple(pid + "." + k for k in ("BOTTOM", "TOP", "COLUMNS"))
                        if a.code == "W-3D" and index == 0
                        else ()
                    )
                    ident = a.id + "." + u.id
                    self.operation(
                        ident,
                        "CONVERT" if a.code == "CUT" else "READY" if a.code == "READY" else "WORK",
                        product=pid,
                        activity=a.id,
                        source=a.location,
                        target=a.location if components else None,
                        entity=entity,
                        prior=(*prior, *mapped),
                        roles=tuple((r.id, r.qualification, a.location) for r in u.roles),
                        equipment=u.equipment,
                        inputs=inputs,
                        outputs=outputs,
                        input_places=[p for p in ports if p[0] in dict(inputs)],
                        output_places=[(i, self.ports[i]["PRE-IN"]) for i, q in outputs],
                        duration=u.base_h,
                        phase="SETUP" if u.phase == "SETUP" else "WORK",
                        kappa=u.kappa,
                        quality_gates=gates,
                        wait_gate=wait_gate,
                        production_mode=mode.kind,
                        unit_index=index,
                        component_inputs=components,
                        component_input_places=tuple(
                            m.ComponentPort(i, join_places[i]) for i in components
                        ),
                        hold_device="TEST1" if a.code == "TEST-SET" else None,
                        release_device="TEST1" if a.code == "Q-POND" else None,
                        wait_after=prior[0] if a.wait_h else None,
                        wait_h=a.wait_h,
                        scrap_quantity=0,
                    )
                    mapped.append(ident)
                    self.bindings.append(m.CoreBinding(a.id, mode.id, u.id, (ident,)))
            # Gate requirements apply to every mapped sub-unit, including MOVE.
            self.operations = [
                replace(o, quality_gates=gates, wait_gate=wait_gate) if o.id in mapped else o
                for o in self.operations
            ]
            terminal[a.id] = mapped[-1]
            first[a.id] = mapped[0]
        # TEST1 shares the material approach. Return it between separated
        # test campaigns, with the same QA1, finite route and handling times.
        # The TEST-SET to Q-POND hold remains uninterrupted.
        for after, before in (("Q-MEP", "TEST-SET"), ("Q-POND", "Q-EXT"), ("Q-EXT", "Q-FIN")):
            previous = terminal[by_code[after].id]
            for phase, source, target in (
                ("RETRIEVE_TOOL", "TEST-USE", "TEST-PARK"),
                ("DEPLOY_TOOL", "TEST-PARK", "TEST-USE"),
            ):
                ident = f"{pid}.TEST-{after}-{phase}"
                rt = route(
                    SimpleNamespace(places=tuple(self.places.values())),
                    ident + "-ROUTE",
                    source,
                    target,
                    "TEST1",
                )
                prerequisites = (previous,)
                if phase == "DEPLOY_TOOL":
                    # Do not occupy the approach until material deliveries
                    # and the preceding process for this test are complete.
                    initial = next(o for o in self.operations if o.id == first[by_code[before].id])
                    prerequisites = (*prerequisites, *initial.prerequisites)
                previous = self.operation(
                    ident,
                    phase,
                    product=pid,
                    source=source,
                    target=target,
                    entity="TEST1",
                    prior=prerequisites,
                    roles=(("QA1", "TOOL", source),),
                    equipment=("TEST1",),
                    rt=rt,
                )
            self.operations = [
                replace(o, prerequisites=(*o.prerequisites, previous))
                if o.id == first[by_code[before].id]
                else o
                for o in self.operations
            ]
        tool_route = route(
            SimpleNamespace(places=tuple(self.places.values())),
            pid + ".TEST-RETRIEVE-ROUTE",
            "TEST-USE",
            "TEST-PARK",
            "TEST1",
        )
        self.operation(
            pid + ".TEST-RETRIEVE",
            "RETRIEVE_TOOL",
            product=pid,
            source="TEST-USE",
            target="TEST-PARK",
            entity="TEST1",
            prior=(terminal[by_code["Q-FIN"].id],),
            roles=(("QA1", "TOOL", "TEST-USE"),),
            equipment=("TEST1",),
            rt=tool_route,
        )
        self.operations = [
            replace(o, prerequisites=(*o.prerequisites, pid + ".TEST-RETRIEVE"))
            if o.activity_id == by_code["MOVE-OUT"].id
            else o
            for o in self.operations
        ]
        scrap_ids = (pid + ".SCRAP-0", pid + ".SCRAP-1")
        water_ids = tuple(i for i in self.rows if i.startswith(pid + ".WATER."))
        waste_water = pid + ".WASTE-WATER"
        self.lots.append(
            m.Lot(
                waste_water,
                pid,
                "WATER",
                "t",
                0.1,
                0.1,
                (1.2, 0.8, 0.6),
                "UNPRODUCED",
                water_ids,
                False,
                False,
                False,
                pid + ".GROUP-TEST-SET",
                "AUX-WATER",
                "WASTEWATER",
            )
        )
        self.ports[waste_water] = {
            r: self.material_slot(r, waste_water, (0, 0, 0), working=r == "F1")
            for r in ("F1", "F1-KIT", "KIT", "MEP-STORE", "MEP-RECEIVE")
        }
        qpond = terminal[by_code["Q-POND"].id]
        self.operations = [
            replace(
                o,
                material_outputs=(m.Amount(waste_water, 0.1),),
                output_places=(m.MaterialPort(waste_water, self.ports[waste_water]["F1"]),),
                mass_remove_t=0.1,
            )
            if o.id == qpond
            else o
            for o in self.operations
        ]
        self.rows[waste_water] = dict(carrier="CART-01")
        departed = self.deliver(waste_water, pid, (qpond,))
        self.operation(
            waste_water + ".RETURN",
            "RETURN",
            product=pid,
            source=self.ports[waste_water]["MEP-RECEIVE"],
            entity=waste_water,
            target="EXTERNAL",
            prior=(departed,),
            inputs=[(waste_water, 0.1)],
            input_places=[(waste_water, self.ports[waste_water]["MEP-RECEIVE"])],
        )
        combined = pid + ".SCRAP-TOTAL"
        self.lots.append(
            m.Lot(
                combined,
                pid,
                "STEEL",
                "t",
                0.158,
                0.158,
                (1.2, 0.8, 0.6),
                "UNPRODUCED",
                scrap_ids,
                False,
                False,
                False,
                pid + ".GROUP-STEEL",
                "B-ST",
                "SCRAP",
            )
        )
        self.ports[combined] = {
            r: self.material_slot(r, combined, (-1.6, -0.8, 0))
            for r in ("PRE-IN", "STEEL", "RECEIVE")
        }
        reserve = self.operation(
            combined + ".RESERVE",
            "RESERVE",
            product=pid,
            activity=combined,
            source="PRE-IN",
            prior=tuple(
                self.last_delivery[net]
                for raw, net in self.steel_nets.items()
                if raw.startswith(pid + ".")
            ),
            inputs=[(i, 0.079) for i in scrap_ids],
            input_places=[(i, self.ports[i]["PRE-IN"]) for i in scrap_ids],
        )
        merged = self.operation(
            combined,
            "CONVERT",
            product=pid,
            source="PRE-IN",
            prior=(reserve,),
            inputs=[(i, 0.079) for i in scrap_ids],
            input_places=[(i, self.ports[i]["PRE-IN"]) for i in scrap_ids],
            outputs=[(combined, 0.158)],
            output_places=[(combined, self.ports[combined]["PRE-IN"])],
        )
        self.rows[combined] = dict(carrier="FORK-01")
        moved = self.deliver(combined, pid, (merged,))
        self.operation(
            combined + ".RETURN",
            "RETURN",
            product=pid,
            source=self.ports[combined]["RECEIVE"],
            entity=combined,
            target="EXTERNAL",
            prior=(moved,),
            inputs=[(combined, 0.158)],
            input_places=[(combined, self.ports[combined]["RECEIVE"])],
        )
        slot = "FG1" if int(pid.split("-")[-1]) % 2 else "FG2"
        buffer = self.transfer(
            pid + ".BUFFER", pid, pid, "OUT1", slot, "CR1", (terminal[by_code["READY"].id],)
        )
        ship = self.transfer(pid + ".SHIP", pid, pid, slot, "DISPATCH", "CR1", (buffer,))
        self.operation(
            pid + ".RECEIVE",
            "RECEIVE_EXTERNAL",
            product=pid,
            source="DISPATCH",
            target="EXTERNAL",
            entity=pid,
            prior=(ship,),
        )

    def configuration(self):
        evidence = tuple(
            replace(
                e,
                status="PASS",
                basis="SYNTHETIC_TEST",
                reference="S15 explicit synthetic test input; industrial qualification unknown",
            )
            if self.synthetic and e.id != "G2" and not e.id.startswith("G2-")
            else e
            for e in self.evidence.values()
        )
        c = m.Configuration(
            "S15-PROD-1.0",
            "S15-PROD-SPEC-1.0",
            "S15-RECIPE-LAYOUT-r2",
            "S15-" + str(len(self.products)) + "-" + self.products[0].variant,
            "SYNTHETIC_TEST_ONLY" if self.synthetic else "RESEARCH_BLOCKED",
            "PRODUCTION",
            tuple(self.products),
            tuple(self.core),
            tuple(self.edges),
            tuple(
                replace(p, qualifications=p.qualifications + ("SC-SUPPORT",))
                if p.id in ("P1", "E1")
                else p
                for p in self.base.people
            ),
            tuple(m.PersonPosition(p.id, "CONTROL-" + p.id) for p in self.base.people),
            tuple(self.places.values()),
            self.base.devices,
            tuple(self.routes),
            tuple(self.lots),
            tuple(self.entities),
            tuple(self.operations),
            evidence,
            self.base.cap,
            self.base.min_rest_h,
            0.02,
            0.02,
            0.02,
            1,
            (),
            (),
            RECIPE_DIGEST,
            "S15-RP-APPROVAL-001",
            tuple(self.groups),
            tuple(self.bindings),
        )
        c = replace(
            c,
            support_layouts=supports.layouts(c),
            support_height_approval_id="S15-SH-APPROVAL-001",
            rework_enabled=self.rework_enabled,
            support_approval_id=supports.APPROVAL,
            support_proposal_sha256=supports.PROPOSAL_SHA256,
        )
        validate(c)
        return c


def generated():
    from adaptive_hrc_scheduling.contracts.codec import schema
    from adaptive_hrc_scheduling.contracts.production import TOP_LEVEL, digest, mode_for
    from adaptive_hrc_scheduling.production_backend import ProductionBackend

    c = Builder(synthetic=False).configuration()
    world = ProductionBackend(c)
    op = next(o for o in c.operations if o.id == "PRODUCT-1.KIT.U1")
    command = m.DispatchCommand(
        "S15-PROD-1.0",
        c.id,
        digest(c),
        world.run_id,
        0,
        "EXAMPLE-HOLD",
        op.product_id,
        op.activity_id,
        op.id,
        0,
        0,
        mode_for(op),
        0,
        0,
        tuple(m.RoleBinding(r.id, r.id) for r in op.roles),
    )
    receipt = world.dispatch(command)
    if receipt.kind != "REJECTED":
        raise ValueError("Normal research example must remain HOLD")
    observation = world.observe()
    records = [
        c,
        command,
        receipt,
        world.snapshot(),
        observation,
        m.PlanningInput("S15-PROD-1.0", c.id, observation, c.operations, 10000),
        m.Plan("S15-PROD-1.0", c.id, observation.id, (), "WAIT", "QUALIFICATION_HOLD"),
        m.HiddenScenario("S15-PROD-1.0", c.id, ()),
        m.OfflineEvaluation(
            "S15-PROD-1.0", c.id, 0, 0, 0, 0, 0, 1, 0, 0, "INDEPENDENT_EVENT_RECONSTRUCTION"
        ),
        m.RunManifest(
            "S15-PROD-1.0",
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
    result = {
        f"examples/production_contracts/{type(x).__name__}.json": dumps(x, config=c)
        for x in records
    }
    for variant in ("SR-W1", "SR-W2"):
        synthetic = Builder(variant=variant, synthetic=True).configuration()
        result[f"examples/production_contracts/{variant}-SYNTHETIC-TEST-ONLY.json"] = dumps(
            synthetic
        )
        repair = Builder(variant=variant, synthetic=True, rework=True).configuration()
        result[f"examples/production_contracts/{variant}-REPAIR-SYNTHETIC-TEST-ONLY.json"] = dumps(
            repair
        )
    result.update(
        {
            f"schemas/production/{kind.__name__}.schema.json": json.dumps(
                schema(kind), indent=2, sort_keys=True
            )
            + "\n"
            for kind in TOP_LEVEL
        }
    )
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--output", type=Path)
    target.add_argument("--generate", action="store_true")
    target.add_argument("--check", action="store_true")
    parser.add_argument("--products", type=int, default=1)
    parser.add_argument("--variant", choices=("SR-W1", "SR-W2"), default="SR-W1")
    parser.add_argument("--synthetic-test-only", action="store_true")
    parser.add_argument("--rework", action="store_true")
    args = parser.parse_args()
    if args.output:
        config = Builder(
            args.products, args.variant, synthetic=args.synthetic_test_only, rework=args.rework
        ).configuration()
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(dumps(config), encoding="utf-8", newline="\n")
        print(f"S15 configuration: {len(config.lots)} lots; {len(config.operations)} operations")
    else:
        items = generated()
        for name, content in items.items():
            path = ROOT / name
            if args.check:
                if not path.exists() or path.read_bytes() != content.encode("utf-8"):
                    raise SystemExit("Generated drift: " + name)
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding="utf-8", newline="\n")
        print(f"S15: {len(items)} examples/schemas " + ("verified" if args.check else "generated"))
