"""RP06 cancellation: reverse declared unused-package legs without restoring stock."""

from dataclasses import replace

from adaptive_hrc_scheduling.contracts.codec import require
from adaptive_hrc_scheduling.domain import production as m


def service(config, lot_id, location, quantity):
    lot = next((x for x in config.lots if x.id == lot_id), None)
    require(lot is not None and not lot.parent_ids, "CANCEL_PRIMARY_PACKAGE_ONLY")
    require(0 < quantity <= lot.quantity, "CANCEL_QUANTITY")
    legs = [o for o in config.operations if o.entity_id == lot_id and o.action == "TRANSFER"]
    require(legs, "CANCEL_NO_DECLARED_ROUTE")
    original = next((o for o in legs if o.target == location), None)
    boundary = legs[0].location
    ident = lot_id + ".CANCEL." + location
    if location == boundary:
        op = replace(
            legs[0],
            id=ident,
            activity_id=ident,
            action="RETURN",
            phase="WORK",
            prerequisites=(),
            roles=(),
            role_locations=(),
            equipment=(),
            location=location,
            target="EXTERNAL",
            route_id=None,
            material_inputs=(m.Amount(lot_id, quantity),),
            input_places=(m.MaterialPort(lot_id, location),),
            quality_gates=(),
            attempt_index=0,
            production_mode=None,
        )
        return m.Service(op, None)
    require(original is not None, "CANCEL_NO_REVERSE_LEG")
    rt = next(r for r in config.routes if r.id == original.route_id)
    reverse = replace(
        rt,
        id=ident + "-ROUTE",
        source=rt.target,
        target=rt.source,
        points=tuple(reversed(rt.points)),
    )
    # Retain the declared operator and any receiving role. The receiver stays
    # at the original work face to hand the unused package back to the carrier.
    locations = tuple(
        replace(p, location=location) if p.location == original.location else p
        for p in original.role_locations
    )
    op = replace(
        original,
        id=ident,
        activity_id=ident,
        prerequisites=(),
        location=location,
        target=original.location,
        route_id=reverse.id,
        role_locations=locations,
        quality_gates=(),
        attempt_index=0,
        production_mode=None,
    )
    return m.Service(op, reverse)


def validate(config, item):
    op = item.operation
    quantity = (
        op.material_inputs[0].quantity
        if op.material_inputs
        else next((x.quantity for x in config.lots if x.id == op.entity_id), 0)
    )
    require(item == service(config, op.entity_id, op.location, quantity), "CANCEL_SERVICE_FIELDS")


def candidates(config, state):
    cancelled = {p.product_id for p in state.products if p.cancelled}
    lots = {x.id: x for x in config.lots}
    result = []
    for stock in state.lots:
        lot = lots[stock.id]
        if lot.product_id not in cancelled or lot.parent_ids or stock.available <= 1e-9:
            continue
        if not stock.arrived or stock.location in ("IN_TRANSIT", "EXTERNAL"):
            continue
        result.append(service(config, lot.id, stock.location, stock.available))
    return tuple(result)


def disposal(config, op):
    return op.action == "TRANSFER" and any(
        lot.id == op.entity_id and lot.disposition in ("SCRAP", "WASTEWATER") for lot in config.lots
    )
