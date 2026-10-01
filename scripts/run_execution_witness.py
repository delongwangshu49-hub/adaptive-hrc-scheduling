"""Run the fixed S05 manual dispatch order through S09; no scheduling search."""

import json
from pathlib import Path

from adaptive_hrc_scheduling.contracts.codec import as_data, loads
from adaptive_hrc_scheduling.contracts.messages import Assignment, DispatchCommand
from adaptive_hrc_scheduling.domain.models import Configuration
from adaptive_hrc_scheduling.event_backend import EventBackend

ROOT = Path(__file__).resolve().parents[1]


def run_witness():
    config = loads(
        Configuration, (ROOT / "examples/contracts/toy.json").read_text(encoding="utf-8")
    )
    e = EventBackend(config)
    ops = {op.kind: op for op in config.operations}
    modes = {"CUT": "R", "BRACKET": "H", "ASSEMBLE": "HR", "WELD": "R", "INSPECT": "H", "LIFT": "H"}
    people = {"CUT": "W1", "BRACKET": "W2", "ASSEMBLE": "W1", "WELD": "W2", "INSPECT": "W2"}
    count = 0

    def bind(kind):
        op = ops[kind]
        mode = next(m for m in config.modes if m.id == f"mode.{kind}.{modes[kind]}")
        q = next(
            q
            for q in config.allocations
            if q.id in mode.allocation_ids and q.worker_id == people[kind]
        )
        e.select_process(op.id, mode.id, q.id)

    def start(kind, phase, transfer=False):
        nonlocal count
        count += 1
        op = ops[kind]
        mode = next(m for m in config.modes if m.id == f"mode.{kind}.{modes[kind]}")
        ids = op.transfers[0].allocation_ids if transfer else mode.allocation_ids
        q = next(
            q
            for q in config.allocations
            if q.id in ids and q.worker_id == ("W1" if transfer else people[kind])
        )
        group = op.transfers[0].id if transfer else op.process_group_id
        a = Assignment(
            op.id, mode.id, group, phase, q.id, 1, 0, e.now, e.now + 100, "FIXED_WITNESS"
        )
        cmd = DispatchCommand(
            "S06-1.1",
            "dispatch",
            f"manual.{count}",
            e.snapshot.run_id,
            config.id,
            "observation.manual",
            config.units,
            e.now,
            "start",
            a,
            None,
            None,
            None,
        )
        result = e.dispatch(cmd)
        if not result.accepted:
            raise RuntimeError(f"{kind}.{phase}: {result.reason}")

    def finish(kind, transfer=False):
        op = ops[kind]
        group = op.transfers[0].id if transfer else op.process_group_id
        e.advance(e.completion_time(group))

    def serial(kind, phases, transfer=False):
        for phase in phases:
            start(kind, phase, transfer)
            finish(kind, transfer)

    start("CUT", "setup")
    start("BRACKET", "work")
    finish("CUT")
    start("CUT", "work")
    finish("BRACKET")
    start("BRACKET", "handoff")
    finish("CUT")
    start("CUT", "handoff")
    finish("BRACKET")
    finish("CUT")
    serial("ASSEMBLE", ("setup", "align", "work", "handoff"))
    bind("WELD")
    serial("WELD", ("preposition", "rig", "move", "unload"), True)
    start("WELD", "reset", True)
    start("WELD", "setup")
    finish("WELD")
    serial("WELD", ("work", "handoff"))
    bind("INSPECT")
    serial("INSPECT", ("preposition", "rig", "move", "unload"), True)
    start("INSPECT", "reset", True)
    start("INSPECT", "work")
    finish("INSPECT", True)
    finish("INSPECT")
    serial("LIFT", ("preposition", "rig", "move", "unload", "reset"), True)
    e.advance(config.observation_window_min)
    return e


def summary(e):
    return {
        "case": "S05_FIXED_MANUAL_DISPATCH_EXECUTED_BY_S09",
        "status": e.status().code,
        "completion_min": e.snapshot.orders[0].actual_completion_min,
        "drained_min": e.drained_at_min,
        "window_min": e.now,
        "phases": [
            {
                "operation_id": p.operation_id,
                "group_id": p.group_id,
                "phase_id": p.phase_id,
                "start_min": p.started_min,
                "completed_min": p.completed_min,
            }
            for p in e.snapshot.phases
        ],
        "workers": [as_data(w) for w in e.snapshot.workers],
        "limitation": "DETERMINISTIC_EXECUTION_WITNESS_NOT_OPTIMIZATION_OR_EXPERIMENT",
    }


if __name__ == "__main__":
    print(json.dumps(summary(run_witness()), indent=2, ensure_ascii=False))
