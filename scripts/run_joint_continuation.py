"""S18-2 no-update controls and actual fixed-production boundary witnesses.

No new HR mapping, industrial qualification, A experiment or Kit claim.
"""

import argparse
import json
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace

from build_production_contracts import Builder
from run_building_witness import fact
from run_joint_mechanisms import first_mode, fixture, problem

from adaptive_hrc_scheduling.algorithms.joint_lns import FrozenJointPolicy, joint_search
from adaptive_hrc_scheduling.algorithms.joint_production import (
    FrozenProductionPolicy,
    joint_production_boundary,
)
from adaptive_hrc_scheduling.algorithms.lns import Options, fingerprint
from adaptive_hrc_scheduling.algorithms.production_lns import ProductionProblem
from adaptive_hrc_scheduling.control.production_decisions import check_decisions, record
from adaptive_hrc_scheduling.domain import production as m
from adaptive_hrc_scheduling.planning.production import planning_input
from adaptive_hrc_scheduling.production_backend import ProductionBackend
from adaptive_hrc_scheduling.production_checker import check_run


def production_problem(world):
    obs = world.observe()
    world.deliver()
    return ProductionProblem(
        world.config, planning_input(world.config, obs, 10000), world.snapshot()
    )


def run_cases():
    options = Options(seed=18, iterations=2, repair_trials=6, wall_seconds=30, stagnation=4)
    rows = []
    for name, event in (
        ("NORMAL", None),
        ("R1_FAILURE", ("FAILURE", "R1")),
        ("IRRELEVANT_FAILURE", ("FAILURE", "TEST1")),
        ("CANCELLATION", ("CANCEL", "PRODUCT-1")),
    ):
        world = fixture()
        anchor = problem(world)
        policy = FrozenJointPolicy(anchor)
        if event:
            fact(world, *event)
        current = problem(world)
        adaptive = joint_search(current, options)
        frozen = policy.decide(current, options)
        rows.append(
            {
                "name": name,
                "scope": "CONDITIONAL_C04_SAME_TICK_NO_UPDATE_TAIL",
                "adaptive_status": adaptive.status,
                "adaptive_mode": first_mode(adaptive, world.config),
                "adaptive_score": adaptive.best_score,
                "frozen_status": frozen.status,
                "nominal_mode": first_mode(frozen.proposal, world.config),
                "nominal_score": frozen.proposal.best_score,
                "nominal_candidate_sha256": fingerprint(frozen.proposal.best),
                "actual_safety": asdict(frozen.safety),
                "anchor_sha256": frozen.anchor_sha256,
                "current_sha256": frozen.current_sha256,
                "options": asdict(options),
            }
        )
    config = Builder().configuration()
    production = []
    for name, failed in (("NORMAL_WALK", False), ("GROUND_SPINE_FAILURE", True)):
        world = ProductionBackend(config)
        anchor = production_problem(world)
        policy = FrozenProductionPolicy(anchor)
        if failed:
            world.apply_world(
                m.WorldEvent(
                    "ROUTE-FAILED",
                    world.run_id,
                    0,
                    0,
                    "FAILURE",
                    "GROUND-SPINE",
                    "PRODUCT-1",
                    0,
                    "PASS",
                    "ML-METHOD",
                )
            )
        current = production_problem(world)
        boundary = joint_production_boundary(current)
        frozen = policy.decide(current, options)
        row = {
            "name": name,
            "scope": "CURRENT_S15_FIXED_MODE_PLUMBING_NOT_JOINT_HR",
            "joint_boundary": asdict(boundary),
            "frozen_status": frozen.status,
            "nominal_candidate_sha256": fingerprint(frozen.proposal.best),
            "nominal_score": frozen.proposal.best_score,
            "actual_safety": asdict(frozen.safety),
            "actual_execution": "NOT_DISPATCHED",
            "options": asdict(options),
        }
        if frozen.candidate and frozen.candidate.commands:
            command = frozen.candidate.commands[0]
            receipt = world.dispatch(command)
            if receipt.kind != "STARTED":
                raise RuntimeError(receipt.reason)
            world.advance(world.s.running[0].earliest_end_h)
            final = world.observe()
            world.deliver()
            trace = world.snapshot()
            ledger = (
                record(
                    SimpleNamespace(
                        observation=current.value.observation,
                        plan=frozen.candidate,
                        rejected_parents=current.rejected,
                        receipt_id=receipt.id,
                    )
                ),
                record(ProductionProblem._terminal(final)),
            )
            execution = check_run(config, trace)
            causal = check_decisions(config, trace, ledger)
            if execution.status != "PASS" or causal.status != "PASS":
                raise RuntimeError((execution, causal))
            row.update(
                actual_execution="WALK_COMPLETED",
                command_sha256=fingerprint(command),
                execution_audit=execution.status,
                decision_audit=causal.status,
                actual_time_h=trace.state.time_h,
                people_positions=[
                    asdict(p) for p in trace.state.positions if p.id == command.roles[0].person_id
                ],
            )
        production.append(row)
    welds = []
    for activity in config.core_activities:
        if activity.code not in ("W-B", "W-T"):
            continue
        welds.append(
            {
                "activity_id": activity.id,
                "location": activity.location,
                "modes": [
                    {
                        "id": mode.id,
                        "kind": mode.kind,
                        "enabled": mode.enabled,
                        "units": [asdict(unit) for unit in mode.units],
                    }
                    for mode in activity.modes
                ],
                "bindings": [asdict(b) for b in config.bindings if b.activity_id == activity.id],
            }
        )
    return {
        "research": "BLOCKED_G2_OPEN",
        "scope": "S18_2_CONDITIONAL_CONTROLS_AND_FIXED_PRODUCTION_BOUNDARY_ONLY",
        "conditional_cases": rows,
        "production_cases": production,
        "current_weld_mapping": welds,
        "limitations": [
            "Same-tick retained anchor; not a rolling production HR policy or full future-factory ablation.",
            "No current updates enter nominal ranking/repair/score/cache; actual shield only rejects and never retries.",
            "Safety scores are separately labelled; nominal scores are not actual performance.",
            "Current production joint gate remains closed. Actual walk is fixed-mode plumbing, not full-chain or Kit evidence.",
        ],
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
            {
                "conditional": [
                    (r["name"], r["adaptive_status"], r["frozen_status"])
                    for r in summary["conditional_cases"]
                ],
                "production": [
                    (r["name"], r["frozen_status"], r["actual_execution"])
                    for r in summary["production_cases"]
                ],
            }
        )
    )


if __name__ == "__main__":
    main()
