"""Source-bound, once-initialized S15 synthetic production witnesses.

The independent boundary receiver is enabled only by this synthetic verifier.
It does not certify industrial transport, physics or human reach.
"""

import argparse
import gzip
import hashlib
import json
import os
import sys
import time
import traceback
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "src"), str(ROOT / "scripts")]


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def witness(args):
    from build_production_contracts import Builder

    from adaptive_hrc_scheduling.contracts.codec import as_data
    from adaptive_hrc_scheduling.contracts.production import validate
    from adaptive_hrc_scheduling.control.production_decisions import record
    from adaptive_hrc_scheduling.control.production_loop import Scenario, run
    from adaptive_hrc_scheduling.production_backend import ProductionBackend

    if args.simulation:
        from build_simulation_production import configuration

        config = configuration(products=args.products, variant=args.variant, rework=args.rework)
    else:
        config = Builder(
            products=args.products, variant=args.variant, rework=args.rework
        ).configuration()
    if args.release_times is not None:
        if len(args.release_times) != args.products:
            raise ValueError("release-times requires one time per product")
        config = replace(
            config,
            products=tuple(
                replace(p, release_h=t) for p, t in zip(config.products, args.release_times)
            ),
        )
        validate(config)
    if args.delayed_lot and not any(
        lot.id == args.delayed_lot and not lot.parent_ids for lot in config.lots
    ):
        raise ValueError("delayed-lot must identify a declared primary package")
    save(args.output / "configuration.json", as_data(config))
    receiver = None
    r1_physical_unavailable = False
    if args.backend == "light":
        engine = ProductionBackend(config)
        if args.actual_r1_before_setup or args.actual_r1_after_bottom:
            original_dispatch = engine.dispatch

            def mirrored_physical_dispatch(command, **options):
                def preflight(cmd):
                    from adaptive_hrc_scheduling.contracts.codec import ContractError

                    op = (
                        cmd.service.operation
                        if cmd.service
                        else engine.operations[cmd.operation_id]
                    )
                    if r1_physical_unavailable and "R1" in op.equipment:
                        raise ContractError("ACTUAL_PREFLIGHT:ACTUAL_DEVICE_FAILED:R1")

                return original_dispatch(command, preflight=preflight, **options)

            engine.dispatch = mirrored_physical_dispatch
    else:
        import omni.usd

        from adaptive_hrc_scheduling.backends.production_isaac_adapter import IsaacAdapter
        from sim.isaac.scene.model import load_config
        from sim.isaac.scene.production_port import USDProductionPort
        from sim.isaac.scene.production_receiver import SyntheticReceiver
        from sim.isaac.scene.target_scene import TargetScene

        omni.usd.get_context().new_stage()
        scene = TargetScene(
            omni.usd.get_context().get_stage(),
            load_config(ROOT / "examples/building_contracts/configuration.json"),
        )
        engine = IsaacAdapter(config, USDProductionPort(scene))
        receiver = SyntheticReceiver(engine.port)
        execution_step = engine.port.step

        def with_receiver(command_id, now_h):
            receiver.step(engine.port.running[command_id], now_h)
            return execution_step(command_id, now_h)

        engine.port.step = with_receiver
    world = getattr(engine, "world", engine)
    r1_injected = False
    last_count = -1
    last_heartbeat = time.monotonic()

    def progress(_engine, _phase):
        nonlocal last_count, last_heartbeat, r1_injected, r1_physical_unavailable
        if (
            (args.actual_r1_before_setup or args.actual_r1_after_bottom)
            and not r1_injected
            and _phase == "after_dispatch"
        ):
            moving = next(
                (
                    r
                    for r in world.s.running
                    if world.operations[r.command.operation_id].action == "TRANSFER"
                    and world.operations[r.command.operation_id].entity_id == "PRODUCT-1.BOTTOM"
                    and (
                        world.operations[r.command.operation_id].target == "J2"
                        if args.actual_r1_before_setup
                        else world.operations[r.command.operation_id].target.startswith("BUF.")
                        and any(
                            a.activity_id == "PRODUCT-1.W-B" and a.state == "COMPLETE"
                            for a in world.s.mode_attempts
                        )
                    )
                ),
                None,
            )
            if moving is not None:
                from adaptive_hrc_scheduling.production_backend import route_hours

                op = world.operations[moving.command.operation_id]
                halfway = (
                    moving.started_h
                    + config.setup_h
                    + config.load_h
                    + route_hours(world.routes[op.route_id]) / 2
                )
                if args.backend == "isaac":
                    engine.advance_to(halfway)
                else:
                    world.advance(halfway)
                if not any(
                    p.command_id == moving.command.id and 0 < p.progress < 1
                    for p in world.s.motions
                ):
                    raise ValueError("R1 intervention requires loaded execution progress")
                if args.backend == "isaac":
                    engine.port.scene.attr(engine.port.prim("R1"), "s15Available", False)
                else:
                    r1_physical_unavailable = True
                r1_injected = True
                save(
                    args.output / "actual-r1-intervention.json",
                    dict(
                        time_h=world.s.time_h,
                        source="ACTUAL_USD_ONLY"
                        if args.backend == "isaac"
                        else "LIGHT_EXECUTION_PREFLIGHT_MIRROR",
                        device="R1",
                        planner_notice="ONLY_AFTER_EXECUTION_PREFLIGHT_FAILURE",
                    ),
                )
        count = sum(o.id in world.s.completed for o in config.operations)
        if _phase == "before_audit":
            print(
                f"audit_start completed={count} time_h={world.s.time_h:.9f} events={len(world.events)}",
                flush=True,
            )
        if count != last_count and count % 20 == 0:
            print(
                f"completed={count}/{len(config.operations)} time_h={world.s.time_h:.9f}",
                flush=True,
            )
            last_count = count
        if time.monotonic() - last_heartbeat >= 30:
            save(
                args.output / "heartbeat.json",
                {
                    "time_h": world.s.time_h,
                    "state": as_data(replace(world.s, intervals=())),
                    "revision": world.s.revision,
                    "completed_static": count,
                    "running": as_data(world.s.running),
                    "positions": as_data(world.s.positions),
                    "lots": as_data(world.s.lots),
                    "products": as_data(world.s.products),
                    "supports": as_data(world.s.supports),
                    "recent_events": [
                        {
                            "kind": e.kind,
                            "time_h": e.occurred_sim_h,
                            "operation": e.command.operation_id if e.command else None,
                            "reason": e.reason,
                        }
                        for e in world.events[-12:]
                    ],
                },
            )
            print(
                f"heartbeat completed={count} time_h={world.s.time_h:.9f} revision={world.s.revision}",
                flush=True,
            )
            last_heartbeat = time.monotonic()

    policy = None
    if args.method:
        if not args.simulation or args.budget_file is None:
            raise ValueError(
                "Joint controls require explicit simulation admission and predeclared budget file"
            )
        from adaptive_hrc_scheduling.control.simulation_joint_policy import (
            Budget,
            SimulationJointPolicy,
        )

        data = json.loads(args.budget_file.read_text(encoding="utf-8"))
        data["opportunities_h"] = tuple(data["opportunities_h"])
        budget = Budget(**data)
        budget.validate()
        save(args.output / "predeclared-search-budget.json", data)
        policy = SimulationJointPolicy(config, budget, method=args.method, end_h=args.until_h)
    result = run(
        engine,
        Scenario(
            id=args.scenario,
            until_h=args.until_h,
            receive_after_h=args.receive_after_h,
            quality_fail=args.quality_fail,
            rework_fail=args.rework_fail,
            cancel_product=args.cancel_product if args.cancel_stage else None,
            cancel_stage=args.cancel_stage,
            loaded_failure=args.loaded_failure,
            actual_device_failure=args.actual_device_failure,
            actual_path_obstruction=args.actual_path_obstruction,
            delayed_lot=args.delayed_lot,
            arrival_after_h=args.arrival_after_h,
        ),
        execution_hook=progress,
        joint_policy=policy,
        fixed_mode=args.fixed_mode,
        handover_after_setup=args.handover_after_setup,
    )
    # Stream each event independently. Expanding the entire shared event graph
    # into one JSON object can exhaust memory on continuous multi-product runs.
    with gzip.open(args.output / "events.jsonl.gz", "wt", encoding="utf-8") as stream:
        for event in result.snapshot.events:
            stream.write(json.dumps(as_data(event), separators=(",", ":")) + "\n")
    save(args.output / "state.json", as_data(result.snapshot.state))
    save(args.output / "audit.json", as_data(result.audit))
    save(args.output / "decision-audit.json", as_data(result.decision_audit))
    with gzip.open(args.output / "decisions.jsonl.gz", "wt", encoding="utf-8") as stream:
        for decision in result.decisions:
            stream.write(
                json.dumps(
                    record(decision),
                    separators=(",", ":"),
                )
                + "\n"
            )
    if receiver is not None:
        save(args.output / "receiver-samples.json", receiver.samples)
    manifest = result.manifest
    expected = (
        "STALLED"
        if args.expect_quality_hold or args.cancel_stage
        else "WINDOW_CENSORED"
        if args.expect_window
        else "OPERATIONS_COMPLETE"
    )
    passed = (
        manifest["audit"] == "PASS"
        and manifest["decision_audit"] == "PASS"
        and manifest["termination"] == expected
    )
    if args.loaded_failure or args.actual_device_failure:
        passed = passed and manifest["loaded_failure_injected"] and not world.s.failed_resources
    if args.actual_path_obstruction:
        passed = (
            passed and manifest["actual_path_obstruction_injected"] and not world.s.failed_resources
        )
    if args.cancel_stage:
        p = world._product(args.cancel_product)
        passed = (
            passed
            and p.cancelled
            and p.received_h is None
            and manifest["received"] == args.products - 1
            and not world.s.running
            and not any(r.product_id == p.product_id for r in world.s.reservations)
            and all(
                world._lot(lot.id).available <= 1e-9
                for lot in config.lots
                if lot.product_id == p.product_id and not lot.parent_ids
            )
            and (p.ready_h is not None if args.cancel_stage == "READY" else p.ready_h is None)
        )
    elif args.expect_quality_hold:
        passed = (
            passed
            and manifest["received"] == 0
            and all(
                any(
                    g.product_id == p.id
                    and g.attempt == 1
                    and g.result == "FAIL"
                    and g.id
                    == next(
                        a.quality_evidence
                        for a in config.core_activities
                        if a.product_id == p.id and a.code == "Q-POND"
                    )
                    for g in world.s.gates
                )
                and all(
                    o.id in world.s.completed
                    for o in config.operations
                    if o.product_id == p.id and o.attempt_index == 1
                )
                for p in config.products
            )
        )
    elif not args.expect_window:
        passed = passed and manifest["received"] == args.products
    if args.actual_r1_before_setup or args.actual_r1_after_bottom:
        passed = (
            passed
            and r1_injected
            and any(
                e.kind == "REJECTED" and "ACTUAL_DEVICE_FAILED:R1" in e.reason for e in world.events
            )
            and all(
                a.definition_id.endswith(".H-SIM-v1")
                for a in world.s.mode_attempts
                if args.actual_r1_before_setup or a.activity_id == "PRODUCT-1.W-T"
            )
            and (
                args.actual_r1_before_setup
                or any(
                    a.activity_id == "PRODUCT-1.W-B" and a.definition_id.endswith(".HR-SIM-v1")
                    for a in world.s.mode_attempts
                )
            )
        )
    manifest["r1_intervention"] = (
        "AFTER_BOTTOM_DURING_LOADED_OUTBOUND"
        if args.actual_r1_after_bottom
        else "BEFORE_SETUP_DURING_LOADED_INBOUND"
        if args.actual_r1_before_setup
        else None
    )
    manifest["r1_intervention_injected"] = r1_injected
    backpressure = None
    if args.scenario == "B2_SUPPLEMENTAL_960":
        from adaptive_hrc_scheduling.production_witness import buffer_backpressure

        backpressure = buffer_backpressure(
            config,
            result.snapshot.events,
            (
                (d.observation.sampled_h, bool(d.plan.commands), d.plan.reason)
                for d in result.decisions
            ),
        )
        passed = (
            passed
            and not args.expect_window
            and manifest["received"] == 3
            and backpressure is not None
        )
    return dict(
        status="PASS" if passed else "FAILED",
        manifest=manifest,
        expected_termination=expected,
        initialization_count=1,
        synthetic_receiver_samples=len(receiver.samples) if receiver is not None else 0,
        boundary_scope="independent synthetic finite kinematics; no industrial capability claim",
        buffer_backpressure=backpressure,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--backend", choices=("light", "isaac"), required=True)
    parser.add_argument("--products", type=int, choices=(1, 2, 3), default=1)
    parser.add_argument("--variant", choices=("SR-W1", "SR-W2"), default="SR-W1")
    parser.add_argument("--scenario", default="NORMAL")
    parser.add_argument("--until-h", type=float, choices=(240, 720, 960), default=720)
    parser.add_argument("--receive-after-h", type=float, default=0)
    parser.add_argument("--expect-window", action="store_true")
    parser.add_argument("--rework", action="store_true")
    parser.add_argument("--simulation", action="store_true")
    parser.add_argument(
        "--method", choices=("ADAPTIVE_JOINT", "FIXED_H", "FIXED_HR", "NO_OBSERVATION_UPDATE")
    )
    parser.add_argument("--budget-file", type=Path)
    parser.add_argument("--actual-r1-before-setup", action="store_true")
    parser.add_argument("--actual-r1-after-bottom", action="store_true")
    parser.add_argument("--fixed-mode", choices=("H", "HR-seq"))
    parser.add_argument("--handover-after-setup", action="store_true")
    parser.add_argument("--quality-fail", choices=("Q-POND",))
    parser.add_argument("--rework-fail", action="store_true")
    parser.add_argument("--expect-quality-hold", action="store_true")
    parser.add_argument("--cancel-stage", choices=("UNSTARTED", "STOCK", "WIP", "READY"))
    parser.add_argument("--cancel-product", default="PRODUCT-1")
    parser.add_argument("--release-times", nargs="+", type=float)
    parser.add_argument("--loaded-failure", action="store_true")
    parser.add_argument("--actual-device-failure", action="store_true")
    parser.add_argument("--actual-path-obstruction", action="store_true")
    parser.add_argument("--delayed-lot")
    parser.add_argument("--arrival-after-h", type=float, default=0)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    save(args.output / "started.json", {"pid": os.getpid()})
    files = [
        *ROOT.glob("src/adaptive_hrc_scheduling/**/*.py"),
        *ROOT.glob("sim/**/*.py"),
        *ROOT.glob("scripts/*production*.py"),
        ROOT / "src/adaptive_hrc_scheduling/production_recipe.json",
        *ROOT.glob("src/adaptive_hrc_scheduling/simulation_inputs/*"),
        *ROOT.glob("schemas/production_simulation/*.json"),
        Path(__file__),
    ]
    report = dict(
        status="FAILED",
        closed=False,
        runtime="KIT_APPLICATION" if args.backend == "isaac" else "LIGHT_EVENT",
        scope="SIMULATION_RESEARCH_ONLY" if args.simulation else "SYNTHETIC_TEST_ONLY",
        S15_complete=False,
        industrial_qualification="NOT_ESTABLISHED" if args.simulation else "UNKNOWN",
        rendered_frame_validation=False,
        sources={
            p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in files
        },
    )
    app = None
    try:
        if args.backend == "isaac":
            from isaacsim import SimulationApp

            app = SimulationApp(
                {
                    "headless": True,
                    "width": 1280,
                    "height": 720,
                    "multi_gpu": False,
                    "fast_shutdown": True,
                    "enable_crashreporter": False,
                    "renderer": "MinimalRendering",
                    "disable_viewport_updates": True,
                }
            )
        report.update(witness(args))
    except Exception:
        report["error"] = traceback.format_exc()
    finally:
        report["shutdown_requested"] = app is not None
        save(args.output / "report.json", report)
        if app:
            app.close()
        report["closed"] = True
        save(args.output / "report.json", report)
    print(json.dumps({k: v for k, v in report.items() if k != "sources"}), flush=True)
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
