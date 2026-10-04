"""Observation-driven S14 light loop. Future event times remain in the driver."""

from dataclasses import dataclass

from adaptive_hrc_scheduling.contracts.codec import require
from adaptive_hrc_scheduling.logistics_checker import check_run
from adaptive_hrc_scheduling.planning.logistics import choose, planning_input


@dataclass(frozen=True)
class Turn:
    observation: object
    plan: object
    receipt: object


def run_loop(world, scenario, *, until_h=8, rule="EDD", budget_ms=1000, max_turns=1000):
    require(scenario.config_id == world.config.id, "SCENARIO_CONFIG")
    pending = sorted(scenario.events, key=lambda e: (e.occurred_sim_h, e.id))
    turns = []
    for sequence in range(max_turns):
        while pending and pending[0].occurred_sim_h <= world.s.time_h:
            world.apply_world(pending.pop(0))
        obs = world.observe()
        world.deliver()
        plan = choose(
            world.config, planning_input(world.config, obs, budget_ms), rule=rule, sequence=sequence
        )
        receipt = world.dispatch(plan.commands[0]) if plan.commands else None
        turns.append(Turn(obs, plan, receipt))
        if receipt and receipt.kind == "STARTED":
            continue
        next_times = [r.earliest_end_h for r in world.s.running if r.status == "STARTED"]
        if pending:
            next_times.append(pending[0].occurred_sim_h)
        if not next_times:
            break
        tick = min(next_times)
        if tick > until_h:
            world.advance(until_h)
            break
        world.advance(tick)
    else:
        raise ValueError("TURN_BUDGET_EXHAUSTED")
    return tuple(turns), check_run(world.config, world.snapshot())
