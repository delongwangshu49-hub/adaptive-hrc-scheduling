"""Call-owned replay preparation; only validated immutable records are shared."""

import copy
from dataclasses import fields, is_dataclass

from .contracts.codec import ContractError, _checked
from .production_backend import ProductionBackend


def _retain(value, memo):
    if type(value) in (str, int, float, bool, type(None)) or id(value) in memo:
        return
    memo[id(value)] = value
    if type(value) is tuple:
        children = value
    elif is_dataclass(value) and type(value).__dataclass_params__.frozen:
        children = (getattr(value, field.name) for field in fields(value))
    else:
        raise ContractError("PREVIEW_UNSHAREABLE_NATIVE_NODE")
    for child in children:
        _retain(child, memo)


def shareable_records(world):
    """Unknown backends or mutable contract records take the full-copy path."""
    if type(world) is not ProductionBackend:
        return {}
    memo = {}
    try:
        for value in (world.config, world.s, *world.events):
            _, immutable = _checked(type(value), value, "$ preview")
            if not immutable:
                return {}
            _retain(value, memo)
    except ContractError:
        return {}
    return memo


def fork_seed(seed):
    detached = copy.copy(seed)
    for key, value in vars(seed).items():
        if isinstance(value, (dict, list, set)):
            setattr(detached, key, copy.copy(value))
    return detached


class PreviewPreparation:
    """One preview owns one seed and priority cache; nothing is installed globally."""

    def __init__(self):
        self.seed = None
        self.priority_config = self.priority_inputs = self.priority_order = None
        self.priority = ()

    def world(self, config, *, run_id, epoch):
        seed = self.seed
        if (
            seed is None
            or seed.config is not config
            or seed.run_id != run_id
            or seed.epoch != epoch
        ):
            seed = self.seed = ProductionBackend(config, run_id=run_id, epoch=epoch)
        return fork_seed(seed)

    def decide(self, policy, value, *, sequence, rejected):
        from .planning.production import choose

        history = policy.session.history
        order = tuple(policy.order)
        if (
            history.current is not self.priority_config
            or history.priorities != self.priority_inputs
            or order != self.priority_order
        ):
            priority = dict(order)
            for aid, urgency in history.priority_bias():
                priority[aid] = priority.get(aid, 0) + urgency * 100000
            self.priority_config = history.current
            self.priority_inputs = dict(history.priorities)
            self.priority_order = order
            self.priority = tuple(priority.items())
        return choose(
            policy.config,
            value,
            sequence=sequence,
            excluded_operations=rejected,
            mode_choices=policy.modes,
            order_bias=self.priority,
            _world_factory=self.world,
        )
