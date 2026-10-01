"""Project authorized records at the planning boundary; no event processing."""

from dataclasses import replace

from .messages import PlanningInput
from .validation import validate


def planning_input(configuration, observation):
    """Copy static data for already observed orders, including cancelled cleanup.

    Authorization/timestamps are supplied by the future observation layer.
    This function cannot certify that the caller told the truth about them.
    It never accepts a hidden scenario or an execution snapshot.
    """
    validate(observation, config=configuration)
    ids = {o.order_id for o in observation.known_orders}
    visible = replace(
        configuration,
        orders=tuple(o for o in configuration.orders if o.id in ids),
        operations=tuple(o for o in configuration.operations if o.order_id in ids),
        materials=tuple(m for m in configuration.materials if m.order_id in ids),
    )
    result = PlanningInput("S06-1.0", "planning_input", configuration.id, observation, visible)
    validate(result, config=configuration)
    return result
