"""Resolved E20 input identity; historical production recipes remain unchanged."""

from dataclasses import replace

from .contracts.codec import require
from .contracts.production import validate
from .full_schedule import configuration as fixed
from .workforce_session import configuration as workforce

RECIPE = "P052-E20-r1"
RUN_PREFIX = "P051-E20-"


def configuration(base):
    require(len(base.products) == 1, "E20_INITIAL_ONE_PRODUCT")
    product = replace(base.products[0], order_id="ORD-BASE", due_h=2500.0)
    return validate(fixed(workforce(replace(base, id=RECIPE + ":" + base.id, products=(product,)))))
