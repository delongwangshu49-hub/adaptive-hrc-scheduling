"""Fixed C05 witness script, not a general scheduling policy or S10 checker."""

import argparse
import importlib.util
import json
from pathlib import Path

from adaptive_hrc_scheduling.building_backend import BuildingBackend
from adaptive_hrc_scheduling.contracts.codec import as_data
from adaptive_hrc_scheduling.domain import building as b

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "building_generator", ROOT / "scripts/build_building_contracts.py"
)
generator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(generator)


def command(world, aid, *, bindings=None, mode=None):
    a = world.activities[aid]
    attempt = world._attempt(aid)
    selected = next(m for m in a.modes if m.id == mode) if mode else a.modes[0]
    idx = attempt.completed_units if attempt else 0
    roles = selected.units[idx].roles if selected.units else ()
    roles = tuple(b.RoleBinding(r.id, (bindings or {}).get(r.id, r.id)) for r in roles)
    return b.DispatchCommand(
        "C04-1.0",
        world.config.id,
        f"CMD-{len(world.s.consumed_commands) + 1}",
        world.time,
        world.s.revision,
        aid,
        selected.id,
        attempt.number if attempt else 0,
        idx,
        roles,
    )


def fact(world, kind, entity, value=None, attempt=None):
    e = b.WorldEvent(f"FACT-{len(world.s.events) + 1}", world.time, kind, entity, value, attempt)
    return world.apply_event(e)


def run_activity(world, aid):
    """Follow a predeclared activity, retry only legal calendar/rest boundaries."""
    a = world.activities[aid]
    for _ in range(1000):
        state = world._attempt(aid)
        if state and state.state == "COMPLETED":
            if a.quality_evidence and not any(
                q.activity_id == aid and q.attempt == state.number for q in world.s.quality
            ):
                fact(world, "QUALITY_RESULT", aid, "PASS", state.number)
            return
        if state and state.state == "WAITING_RELEASE":
            if world.time < state.wait_until_h:
                world.advance(state.wait_until_h)
            if aid not in world.s.released_processes:
                fact(world, "PROCESS_RELEASE", aid)
            if not a.modes[0].units:
                continue
        receipt = world.dispatch(command(world, aid))
        if not receipt.accepted:
            if receipt.reason not in (
                "CALENDAR_OR_QUALIFICATION",
                "FATIGUE_PROTECTION",
                "REST_COMMITTED",
            ):
                raise RuntimeError(a.code + ": " + receipt.reason)
            if receipt.reason == "FATIGUE_PROTECTION":
                roles = command(world, aid).roles
                world.rest(tuple(r.person_id for r in roles), world.config.min_rest_h)
            world.advance(world.time + 0.25)
        else:
            runs = [r for r in world.s.running if r.activity_id == aid]
            if runs:
                world.advance(runs[0].end_h)
    raise RuntimeError("Witness retry bound exceeded: " + a.code)


def run_chain(*, variant="SR-W1", until="READY", test_fixture=True):
    c = generator.build_configuration(variant)
    if test_fixture:
        c = generator.synthetic_fixture(c)
    world = BuildingBackend(c)
    for a in c.activities:
        run_activity(world, a.id)
        if a.code == until:
            break
    return world


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--until", default="READY")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    try:
        world = run_chain(until=args.until)
    except Exception as error:
        (args.output / "failure.json").write_text(
            json.dumps({"status": "FAIL", "error": str(error)}, indent=2) + "\n", encoding="utf-8"
        )
        raise
    summary = {
        "status": "SYNTHETIC_TEST_ONLY",
        "industrial_qualification": "NOT_ESTABLISHED",
        "time_h": world.time,
        "products": as_data(world.s.products),
        "people": as_data(world.s.people),
        "events": len(world.s.events),
        "intervals": len(world.s.intervals),
        "gaps": ["G1", "G2", "G4", "G5", "G6", "G7"],
    }
    (args.output / "summary.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8"
    )
    (args.output / "checkpoint.json").write_text(world.checkpoint(), encoding="utf-8")
    print(
        json.dumps(
            {
                "time_h": world.time,
                "state": world.s.products[0].state,
                "events": len(world.s.events),
            }
        )
    )


if __name__ == "__main__":
    main()
