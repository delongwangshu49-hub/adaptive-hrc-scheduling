"""RP06 branch metadata and evidence selection, independent of execution."""

from adaptive_hrc_scheduling.contracts.codec import require


def pond_gate(config, product):
    return next(
        a.quality_evidence
        for a in config.core_activities
        if a.product_id == product and a.code == "Q-POND"
    )


def initial_failure(config, gates, product):
    gate = pond_gate(config, product)
    return config.rework_enabled and any(
        g.id == gate and g.product_id == product and g.attempt == 0 and g.result == "FAIL"
        for g in gates
    )


def active(config, gates, operation):
    return operation.attempt_index == 0 or initial_failure(config, gates, operation.product_id)


def quality_records(config, gates, ident, product, attempt):
    records = [g for g in gates if g.id == ident and g.product_id == product]
    if config.rework_enabled and ident == pond_gate(config, product) and attempt == 0:
        return sorted(records, key=lambda g: g.attempt)
    return [g for g in records if g.attempt == attempt]


def repair_gate_operation(config, event):
    """Return the declared attempt-one producer, never a replacement for old evidence."""
    if not config.rework_enabled or event.attempt != 1:
        return None
    for code, kind in (
        ("WAIT-W", "PROCESS_RELEASE"),
        ("WAIT-TEST", "PROCESS_RELEASE"),
        ("Q-POND", "QUALITY"),
    ):
        activity = next(
            a for a in config.core_activities if a.product_id == event.product_id and a.code == code
        )
        ident = activity.quality_evidence if kind == "QUALITY" else activity.release_evidence
        if event.kind == kind and event.entity_id == ident:
            return event.product_id + ".REPAIR." + code
    return None


def validate_rework(config):
    lots = {lot.id: lot for lot in config.lots}
    conditional = [op for op in config.operations if op.attempt_index]
    if not config.rework_enabled:
        require(not conditional, "REWORK_NOT_ENABLED")
        return set()
    expected_primary = set()
    all_conditional = set()
    for product in config.products:
        prefix = product.id + ".REPAIR."
        ops = {op.id.removeprefix(prefix): op for op in conditional if op.product_id == product.id}
        require(
            ops and all(op.id.startswith(prefix) and op.attempt_index == 1 for op in ops.values()),
            "UNAPPROVED_REPAIR_BRANCH",
        )
        expected_names = {
            "DIAGNOSE",
            "REMOVE",
            "INSTALL",
            "INSTALL.RESERVE",
            "WAIT-W",
            "TEST-DEPLOY",
            "TEST-SET",
            "TEST-SET.RESERVE",
            "WAIT-TEST",
            "Q-POND",
            "TEST-RETRIEVE",
            "SCRAP.RETURN",
            "WASTE-WATER.RETURN",
            *(
                f"{name}.DELIVER-{n}"
                for name in ("PATCH", "WATER-01", "WATER-02", "SCRAP", "WASTE-WATER")
                for n in range(4)
            ),
        }
        require(set(ops) == expected_names, "REPAIR_OPERATION_COVERAGE")
        routes = {r.id: r for r in config.routes}
        core = {a.code: a for a in config.core_activities if a.product_id == product.id}
        dependencies = {
            "DIAGNOSE": (
                product.id + ".WASTE-WATER.RETURN",
                product.id + ".TEST-Q-POND-RETRIEVE_TOOL",
            ),
            "REMOVE": (prefix + "DIAGNOSE",),
            "INSTALL.RESERVE": (prefix + "PATCH.DELIVER-3",),
            "INSTALL": (prefix + "INSTALL.RESERVE",),
            "WAIT-W": (prefix + "INSTALL",),
            "TEST-DEPLOY": (
                prefix + "WAIT-W",
                prefix + "WATER-01.DELIVER-3",
                prefix + "WATER-02.DELIVER-3",
            ),
            "TEST-SET.RESERVE": (prefix + "TEST-DEPLOY",),
            "TEST-SET": (prefix + "TEST-SET.RESERVE",),
            "WAIT-TEST": (prefix + "TEST-SET",),
            "Q-POND": (prefix + "WAIT-TEST",),
            "TEST-RETRIEVE": (prefix + "Q-POND",),
            "SCRAP.RETURN": (prefix + "SCRAP.DELIVER-3",),
            "WASTE-WATER.RETURN": (prefix + "WASTE-WATER.DELIVER-3",),
        }
        for name, prior in (
            ("PATCH", "SCRAP.RETURN"),
            ("WATER-01", "INSTALL"),
            ("WATER-02", "INSTALL"),
            ("SCRAP", "REMOVE"),
            ("WASTE-WATER", "Q-POND"),
        ):
            for index in range(4):
                dependencies[f"{name}.DELIVER-{index}"] = (
                    prefix + (prior if index == 0 else f"{name}.DELIVER-{index - 1}"),
                )
        for op in ops.values():
            name = op.id.removeprefix(prefix)
            require(
                not (
                    op.component_inputs
                    or op.component_outputs
                    or op.component_input_places
                    or op.scrap_quantity
                    or op.support_layout_id
                    or op.quality_gates
                )
                and op.qualification_ids == ("ML-METHOD",)
                and op.unit_index == 0,
                "REPAIR_EXTRA_EFFECT",
            )
            require(op.prerequisites == dependencies[name], "REPAIR_PREDECESSOR_DRIFT")
            require(
                op.wait_gate
                == (
                    core["WAIT-W"].release_evidence
                    if name == "TEST-SET"
                    else core["WAIT-TEST"].release_evidence
                    if name == "Q-POND"
                    else None
                )
                and op.hold_device == ("TEST1" if name == "TEST-SET" else None)
                and op.release_device == ("TEST1" if name == "Q-POND" else None),
                "REPAIR_GATE_OR_OWNERSHIP_DRIFT",
            )
            if not name.startswith("WAIT-"):
                require(op.wait_after is None and op.wait_h == 0, "REPAIR_EXTRA_WAIT")
            if (
                name in ("DIAGNOSE", "WAIT-W", "WAIT-TEST")
                or ".DELIVER-" in name
                or name.startswith("TEST-")
                and name.endswith(("DEPLOY", "RETRIEVE"))
            ):
                require(not (op.material_inputs or op.material_outputs), "REPAIR_EXTRA_MATERIAL")
        for name, op in ops.items():
            if ".DELIVER-" in name:
                require(
                    op.action == "TRANSFER"
                    and routes[op.route_id].device_id == "CART-01"
                    and any(r.id == "E1" and r.qualification == "CART" for r in op.roles),
                    "REPAIR_CARRIER_DRIFT",
                )
        for name, quantity, disposition in (
            ("PATCH", 0.02, "PRODUCT"),
            ("WATER-01", 0.05, "AUXILIARY"),
            ("WATER-02", 0.05, "AUXILIARY"),
        ):
            ident = prefix + name
            expected_primary.add(ident)
            require(ident in lots, "MISSING_REPAIR_PACKAGE")
            lot = lots[ident]
            require(
                lot.product_id == product.id
                and lot.quantity == lot.mass_t == quantity
                and lot.size_m == (1.2, 0.8, 0.6)
                and lot.unit == "t"
                and lot.initial_location == "SUPPLIER"
                and not lot.parent_ids
                and not (lot.arrived or lot.identified or lot.released)
                and lot.disposition == disposition
                and lot.group_id == product.id + ".GROUP-REPAIR",
                "REPAIR_PACKAGE_DRIFT",
            )
        expected_work = {
            "DIAGNOSE": 0.5,
            "REMOVE": 0.5,
            "INSTALL": 0.5,
            "WAIT-W": 0,
            "TEST-SET": 0.5,
            "WAIT-TEST": 0,
            "Q-POND": 0.5,
        }
        require(
            {name for name, op in ops.items() if op.action == "WORK"} == set(expected_work),
            "REPAIR_WORK_COVERAGE",
        )
        for name, hours in expected_work.items():
            op = ops[name]
            roles = (
                ()
                if name.startswith("WAIT-")
                else (("QA1", "QA"), ("T1", "WET"))
                if name == "Q-POND"
                else (("T1", "WET"),)
            )
            require(
                op.base_h == hours
                and tuple((r.id, r.qualification) for r in op.roles) == roles
                and op.location == "F1"
                and op.entity_id == product.id
                and op.kappa == (0 if name.startswith("WAIT-") or name == "Q-POND" else 0.5)
                and op.equipment == (("TEST1",) if name in ("TEST-SET", "Q-POND") else ())
                and tuple((p.person_id, p.location) for p in op.role_locations)
                == tuple((ident, "F1") for ident, _ in roles)
                and op.phase == "WORK"
                and op.target is None
                and op.route_id is None
                and op.production_mode == ("WAIT" if name.startswith("WAIT-") else None),
                "REPAIR_WORK_DRIFT",
            )
        require(
            ops["WAIT-W"].wait_after == prefix + "INSTALL"
            and ops["WAIT-W"].wait_h == 4
            and ops["WAIT-TEST"].wait_after == prefix + "TEST-SET"
            and ops["WAIT-TEST"].wait_h == 4,
            "REPAIR_WAIT_DRIFT",
        )
        require(
            ops["REMOVE"].mass_remove_t == 0.02
            and ops["Q-POND"].mass_remove_t == 0.1
            and ops["TEST-SET"].hold_device == "TEST1"
            and ops["Q-POND"].release_device == "TEST1",
            "REPAIR_MASS_OR_HOLD_DRIFT",
        )
        for name, inputs, outputs in (
            ("REMOVE", {}, {prefix + "SCRAP": 0.02}),
            ("INSTALL", {prefix + "PATCH": 0.02}, {}),
            ("TEST-SET", {prefix + "WATER-01": 0.05, prefix + "WATER-02": 0.05}, {}),
            ("Q-POND", {}, {prefix + "WASTE-WATER": 0.1}),
        ):
            require(
                {a.lot_id: a.quantity for a in ops[name].material_inputs} == inputs
                and {a.lot_id: a.quantity for a in ops[name].material_outputs} == outputs,
                "REPAIR_MATERIAL_RECIPE",
            )
        require(
            all(
                op.mass_remove_t == 0
                for name, op in ops.items()
                if name not in ("REMOVE", "Q-POND")
            ),
            "REPAIR_EXTRA_REMOVAL",
        )
        for name, quantity, parents in (
            (
                "SCRAP",
                0.02,
                tuple(lot.id for lot in config.lots if lot.id.startswith(product.id + ".WT-W.")),
            ),
            ("WASTE-WATER", 0.1, (prefix + "WATER-01", prefix + "WATER-02")),
        ):
            lot = lots.get(prefix + name)
            require(
                lot is not None
                and lot.quantity == lot.mass_t == quantity
                and lot.parent_ids == parents
                and lot.initial_location == "UNPRODUCED"
                and lot.product_id == product.id
                and lot.unit == "t"
                and lot.size_m == (1.2, 0.8, 0.6)
                and lot.disposition == ("SCRAP" if name == "SCRAP" else "WASTEWATER")
                and not (lot.arrived or lot.identified or lot.released)
                and lot.group_id == product.id + ".GROUP-REPAIR",
                "REPAIR_OUTPUT_LINEAGE",
            )
        all_conditional.update(op.id for op in ops.values())
    require(all_conditional == {op.id for op in conditional}, "FOREIGN_REPAIR_OPERATION")
    return expected_primary
