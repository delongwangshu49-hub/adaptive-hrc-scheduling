"""S11/S12 consumers of the S14 shared observation. Hidden scenarios are not inputs."""

import time

from adaptive_hrc_scheduling.contracts.logistics import mode_for, validate
from adaptive_hrc_scheduling.domain import logistics as m
from adaptive_hrc_scheduling.logistics_backend import LogisticsBackend


def planning_input(config, observation, budget_ms=100):
    validate(observation, config=config)
    released = {p.product_id for p in observation.state.products if p.released}
    value = m.PlanningInput(
        "S14-ML-1.0",
        config.id,
        observation,
        tuple(o for o in config.operations if o.product_id in released),
        budget_ms,
    )
    validate(value, config=config)
    return value


def choose(config, value, *, rule="EDD", sequence=0):
    validate(value, config=config)
    if rule not in ("EDD", "SPT", "FASTEST_LEGAL"):
        raise ValueError("Unknown rule")
    start = time.perf_counter()
    obs = value.observation
    deadlines = {p.id: p.due_h for p in config.products}
    estimator = LogisticsBackend(config, run_id=obs.run_id, epoch=obs.epoch)
    estimator.s = obs.state

    def duration(op):
        class Roles:
            roles = tuple(m.RoleBinding(r.id, r.id) for r in op.roles)

        return estimator._duration(op, Roles())

    candidates = sorted(
        value.operations,
        key=lambda o: (deadlines[o.product_id] if rule == "EDD" else duration(o), o.id),
    )
    reasons = []
    for op in candidates:
        if (time.perf_counter() - start) * 1000 > value.budget_ms:
            return m.Plan("S14-ML-1.0", config.id, obs.id, (), "NO_PLAN_FOUND", "DECISION_BUDGET")
        if op.id in obs.state.completed or any(
            r.command.operation_id == op.id for r in obs.state.running
        ):
            continue
        world = LogisticsBackend(config, run_id=obs.run_id, epoch=obs.epoch)
        world.s = obs.state
        cmd = m.DispatchCommand(
            "S14-ML-1.0",
            config.id,
            obs.config_sha256,
            obs.run_id,
            obs.epoch,
            f"PLAN-{sequence}-{op.id}",
            op.product_id,
            op.activity_id,
            op.id,
            op.attempt_index,
            op.unit_index,
            mode_for(op),
            obs.sampled_h,
            obs.state.revision,
            tuple(m.RoleBinding(r.id, r.id) for r in op.roles),
        )
        receipt = world.dispatch(cmd)
        if receipt.kind == "STARTED":
            return m.Plan("S14-ML-1.0", config.id, obs.id, (cmd,), "CANDIDATE", rule)
        reasons.append(op.id + ":" + receipt.reason)
    return m.Plan(
        "S14-ML-1.0", config.id, obs.id, (), "WAIT", ";".join(reasons) or "NO_PENDING_OPERATION"
    )
