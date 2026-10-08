"""S18 conditional branch witnesses; no research qualification or A experiment."""

import argparse
import json
from dataclasses import asdict, replace
from pathlib import Path

from build_building_contracts import build_configuration, synthetic_fixture
from run_building_witness import fact, run_activity

from adaptive_hrc_scheduling.algorithms.joint_lns import (
    JointProblem,
    Switches,
    admission,
    joint_search,
)
from adaptive_hrc_scheduling.algorithms.lns import Options, fingerprint
from adaptive_hrc_scheduling.building_backend import BuildingBackend
from adaptive_hrc_scheduling.control.light_loop import capture
from adaptive_hrc_scheduling.domain import building as b


def fixture(
    *, hr=True, failure=None, initial=None, future=(), late_unload=False, both_frames=False
):
    c = synthetic_fixture(build_configuration(), hr=hr)
    if initial:
        c = replace(
            c, people=tuple(replace(p, initial_f=initial.get(p.id, p.initial_f)) for p in c.people)
        )
    if late_unload:
        c = replace(
            c,
            people=tuple(
                replace(p, calendar=b.Calendar(24, (b.Window(0, 3), b.Window(7, 8.5))))
                if p.id == "OP1"
                else p
                for p in c.people
            ),
        )
    world = BuildingBackend(c, b.HiddenScenario("C04-1.0", c.id, 0, tuple(future)))
    for code in ("KIT", "CUT", "MV-IN-B"):
        run_activity(world, "PRODUCT-1." + code)
    if both_frames:
        run_activity(world, "PRODUCT-1.MV-IN-T")
    if failure:
        fact(world, "FAILURE", failure)
    return world


def problem(world, *, fixed=None, state=True, targets=("PRODUCT-1.W-B",), window=8):
    feedback = capture(world)
    modes = ()
    if fixed:
        scope = set(targets)
        while True:
            more = {e.source for e in world.config.edges if e.target in scope} - scope
            if not more:
                break
            scope |= more
        modes = tuple(
            (
                aid,
                next(
                    m.id
                    for m in world.activities[aid].modes
                    if m.kind == fixed or len(world.activities[aid].modes) == 1
                ),
            )
            for aid in sorted(scope)
        )
    return JointProblem(
        feedback, world.s.intervals, targets, switches=Switches(modes, state), window_h=window
    )


def first_mode(result, config):
    if result.best is None:
        return None
    for action in result.best.actions:
        if action.command:
            activity = next(a for a in config.activities if a.id == action.command.activity_id)
            return next(m.kind for m in activity.modes if m.id == action.command.mode_id)
    return None


def run_cases():
    rows = []
    opts = Options(seed=18, iterations=4, repair_trials=6, wall_seconds=30, stagnation=4)
    for name, kwargs, controls in (
        ("NORMAL", {}, {}),
        ("OBSERVED_R1_FAILURE", {"failure": "R1"}, {}),
        ("IRRELEVANT_TEST1_FAILURE", {"failure": "TEST1"}, {}),
        ("FIXED_H", {}, {"fixed": "H"}),
        ("LATE_UNLOAD_JOINT", {"late_unload": True}, {}),
        ("LATE_UNLOAD_FIXED_H", {"late_unload": True}, {"fixed": "H"}),
        ("LATE_UNLOAD_FIXED_HR", {"late_unload": True}, {"fixed": "HR-seq"}),
        ("FIXED_HR", {}, {"fixed": "HR-seq"}),
        ("NO_FATIGUE_RANKING", {}, {"state": False}),
    ):
        w = fixture(**kwargs)
        pr = problem(w, **controls)
        result = joint_search(pr, opts)
        row = {
            "name": name,
            "scope": "CONDITIONAL_C04_BRANCH_ONLY",
            "status": result.status,
            "termination": result.termination,
            "initial_reasons": result.initial_reasons,
            "mode": first_mode(result, w.config),
            "initial_score": result.initial_score,
            "best_score": result.best_score,
            "trace_status": None,
            "window_h": 8,
            "targets": pr.targets,
            "candidate_sha256": fingerprint(result.best),
            "options": asdict(opts),
            "history": [
                {
                    "index": x.index,
                    "removed": x.removed,
                    "candidate_sha256": x.candidate_sha256,
                    "score": x.score,
                    "accepted": x.accepted,
                    "improved": x.improved,
                    "reasons": x.reasons,
                    "trials": x.trials,
                    "termination": x.repair_termination,
                    "wall_seconds": x.wall_seconds,
                }
                for x in result.history
            ],
        }
        if result.best:
            trace = pr.preview(result.best)
            row["trace_status"] = pr.verify(result.best).valid
            row["completed"] = [a.activity_id for a in trace.attempts if a.state == "COMPLETED"]
            row["preserved_J2"] = any(r.location == "J2" for r in trace.residencies)
        rows.append(row)
    return {
        "scope": "SYNTHETIC_CONDITIONAL_PROGRAM_BRANCHES_NOT_A_EXPERIMENT",
        "research": "BLOCKED_G2_OPEN",
        "actual_gate": asdict(admission(build_configuration())),
        "cases": rows,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    summary = run_cases()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            [
                {k: x.get(k) for k in ("name", "status", "mode", "best_score", "trace_status")}
                for x in summary["cases"]
            ]
        )
    )


if __name__ == "__main__":
    main()
