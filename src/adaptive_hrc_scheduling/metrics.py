"""Independent S10 arithmetic. Hours and F.h; no executor imports."""

from math import isfinite


def integrate_segment(fatigue, duration_h, rate, recovering=False):
    """Exact piecewise-linear area, including a recovery zero crossing."""
    if not all(isfinite(x) and x >= 0 for x in (fatigue, duration_h, rate)):
        raise ValueError("nonnegative finite inputs required")
    if recovering:
        active = min(duration_h, fatigue / rate) if rate else duration_h
        end = max(0.0, fatigue - rate * duration_h)
        area = active * (fatigue + max(0.0, fatigue - rate * active)) / 2
    else:
        end = fatigue + rate * duration_h
        area = duration_h * (fatigue + end) / 2
    return end, area, max(fatigue, end)


def delivery_metrics(products, ready, cancelled, received, window_h, order_weights=None):
    """All released products remain in the denominator; unfinished delay is a bound.

    C04 has no order weights: default to unit-weight order tardiness, grouping by
    order_id and using max product due_h as the explicitly declared order due.
    An order enters evaluation when its first member is released, retaining all
    configured required members and their due dates, including future releases.
    Product counters still cover only released products. A partially cancelled
    order is reported as cancelled, with its entire membership retained.
    """
    rows = []
    orders = {}
    released_orders = {p.order_id for p in products if p.release_h <= window_h}
    for p in products:
        if p.order_id not in released_orders:
            continue
        c = ready.get(p.id)
        is_cancelled = p.id in cancelled
        row = {
            "product_id": p.id,
            "order_id": p.order_id,
            "due_h": p.due_h,
            "ready_h": c,
            "received_h": received.get(p.id),
            "cancelled": is_cancelled,
            "incomplete": c is None and not is_cancelled,
            "tardiness_h": max(0.0, c - p.due_h) if c is not None else None,
            "tardiness_lower_bound_h": max(0.0, (c if c is not None else window_h) - p.due_h)
            if not is_cancelled
            else None,
        }
        if p.release_h <= window_h:
            rows.append(row)
        orders.setdefault(p.order_id, []).append(row)
    order_rows = []
    weights = {oid: 1.0 for oid in orders} if order_weights is None else order_weights
    if set(weights) != set(orders) or any(
        type(w) not in (float, int) or not isfinite(w) or w <= 0 for w in weights.values()
    ):
        raise ValueError("weights must cover every released order with a positive finite value")
    for oid, group in sorted(orders.items()):
        cancel = any(p["cancelled"] for p in group)
        complete = all(p["ready_h"] is not None for p in group) and not cancel
        c = max(p["ready_h"] for p in group) if complete else None
        due = max(p["due_h"] for p in group)
        order_rows.append(
            {
                "order_id": oid,
                "weight": weights[oid],
                "due_h": due,
                "product_ids": [p["product_id"] for p in group],
                "ready_h": c,
                "cancelled": cancel,
                "incomplete": not cancel and not complete,
                "tardiness_h": max(0.0, c - due) if complete else None,
                "tardiness_lower_bound_h": None
                if cancel
                else max(0.0, (c if complete else window_h) - due),
            }
        )
    evaluated = [r for r in order_rows if not r["cancelled"]]
    return {
        "products": rows,
        "orders": order_rows,
        "released_products": len(rows),
        "ready_products": sum(r["ready_h"] is not None and not r["cancelled"] for r in rows),
        "incomplete_products": sum(r["incomplete"] for r in rows),
        "cancelled_products": sum(r["cancelled"] for r in rows),
        "received_products": sum(r["received_h"] is not None for r in rows),
        "order_tardiness_h": sum(r["weight"] * r["tardiness_h"] for r in evaluated)
        if all(r["ready_h"] is not None for r in evaluated)
        else None,
        "order_tardiness_lower_bound_h": sum(
            r["weight"] * r["tardiness_lower_bound_h"] for r in evaluated
        ),
        "order_weight_basis": "UNIT_WEIGHT_C04_NO_WEIGHT_FIELD"
        if order_weights is None
        else "EXPLICIT_ORDER_WEIGHTS",
    }
