"""SC01--SC04 isolated mechanism witnesses; not a production-chain verdict."""

import argparse
import hashlib
import json
import os
import sys
import traceback
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "src"), str(ROOT / "scripts")]


def run(
    output,
    backend,
    app=None,
    *,
    selected_variant=None,
    selected_root=None,
    actual_obstruction=False,
):
    from build_production_contracts import Builder

    from adaptive_hrc_scheduling import production_supports as support
    from adaptive_hrc_scheduling.contracts.codec import as_data
    from adaptive_hrc_scheduling.contracts.production import mode_for
    from adaptive_hrc_scheduling.domain import production as m
    from adaptive_hrc_scheduling.production_backend import ProductionBackend
    from adaptive_hrc_scheduling.production_checker import check_run

    results = []
    for variant in (selected_variant,) if selected_variant else ("SR-W1", "SR-W2"):
        for root in (selected_root,) if selected_root else support.ROOTS:
            config = Builder(variant=variant).configuration()
            config = replace(
                config,
                devices=tuple(
                    replace(d, initial_location="CART-PARK") if d.id == "CART-01" else d
                    for d in config.devices
                ),
                person_positions=tuple(
                    replace(p, location=f"CONTROL-SUPPORT-{root}-{p.person_id}")
                    if p.person_id in ("P1", "E1")
                    else p
                    for p in config.person_positions
                ),
            )
            if backend == "light":
                world = ProductionBackend(config)
                engine = world

                def advance(hours):
                    world.advance(world.s.time_h + hours)
            else:
                import omni.usd

                from adaptive_hrc_scheduling.backends.production_isaac_adapter import IsaacAdapter
                from sim.isaac.scene.model import load_config
                from sim.isaac.scene.production_port import USDProductionPort
                from sim.isaac.scene.target_scene import TargetScene

                omni.usd.get_context().new_stage()
                scene = TargetScene(
                    omni.usd.get_context().get_stage(),
                    load_config(ROOT / "examples/building_contracts/configuration.json"),
                )
                engine = IsaacAdapter(config, USDProductionPort(scene))
                world = engine.world

                def advance(hours):
                    engine.advance(hours * 3600)
                    # This witness audits authored USD kinematics in the live
                    # Kit stage. Rendering and rigid-body dynamics are outside
                    # its scope; a frame must not determine production time.

            case = dict(variant=variant, root=root, config_sha256=world.config_hash, changes=[])
            results.append(case)
            try:
                layouts = sorted(
                    (layout for layout in config.support_layouts if layout.root == root),
                    key=lambda layout: len(layout.contacts),
                )
                if actual_obstruction:
                    layouts = layouts[:1]
                for layout in layouts:
                    old = world._support_layout(world._support_state(root).layout_id)
                    if support.equivalent(old, layout):
                        case["changes"].append(dict(layout=layout.id, status="REUSED"))
                        continue
                    op = support.change_operation(
                        config, layout, "PRODUCT-1", "CHECK-" + str(len(case["changes"]))
                    )
                    cmd = m.DispatchCommand(
                        "S15-PROD-1.0",
                        config.id,
                        world.config_hash,
                        world.run_id,
                        0,
                        op.id,
                        op.product_id,
                        op.activity_id,
                        op.id,
                        0,
                        0,
                        mode_for(op),
                        world.s.time_h,
                        world.s.revision,
                        tuple(m.RoleBinding(r.id, r.id) for r in op.roles),
                        service=m.Service(op, None),
                    )
                    receipt = engine.dispatch(cmd)
                    if receipt.kind != "STARTED":
                        raise RuntimeError(receipt.reason)
                    if not case["changes"]:
                        advance(0.0205)
                        before = world._support_state(root).beams
                        if actual_obstruction:
                            path = support.movements(config, old, layout)[0].paths[0]
                            # Obstruct the first remaining lift segment, using
                            # the declared path rather than an obsolete fixed
                            # height after a bounded layout change.
                            lift = next((a, b) for a, b in zip(path, path[1:]) if a[2] != b[2])
                            obstruction_position = tuple((a + b) / 2 for a, b in zip(*lift))
                            obstacle = "/World/Static/S15_TEST_OBSTRUCTION"
                            engine.port.scene.shape(
                                obstacle,
                                obstruction_position,
                                (0.12, 0.6, 0.2),
                                "red",
                                collision=True,
                            )
                            advance(0.005)
                            failure = world.events[-1]
                            if failure.kind != "EXCEPTION" or "COLLISION" not in failure.reason:
                                raise RuntimeError("ACTUAL_OBSTACLE_NOT_DETECTED")
                            case["actual_fault"] = failure.reason
                            case["obstruction_position_m"] = obstruction_position
                            case["fault_report_h"] = world.s.time_h
                            engine.port.scene.stage.RemovePrim(obstacle)
                            advance(0.01)
                        else:
                            world.exception(cmd.id, "INTERRUPT_AT_VERIFIED_SAMPLE")
                            advance(0.005)
                        if world._support_state(root).beams != before:
                            raise RuntimeError("HELD_BEAMS_MOVED")
                        if (
                            backend == "isaac"
                            and tuple(
                                m.BeamPose(b.index, b.position)
                                for b in engine.port.support_port.read(root)
                            )
                            != before
                        ):
                            raise RuntimeError("HELD_USD_BEAMS_MOVED")
                        cmd = replace(
                            cmd,
                            id=cmd.id + "-RESUME",
                            resume_of=cmd.id,
                            issued_sim_h=world.s.time_h,
                            expected_revision=world.s.revision,
                        )
                        receipt = engine.dispatch(cmd)
                        if receipt.kind != "STARTED":
                            raise RuntimeError(receipt.reason)
                        case["verified_sample_resume"] = True
                        case["last_verified_h"] = 0.0205
                    for _ in range(100):
                        running = next((r for r in world.s.running if r.command.id == cmd.id), None)
                        if running is None:
                            break
                        if running.status != "STARTED":
                            raise RuntimeError(world.events[-1].reason)
                        advance(min(0.02, max(0, running.earliest_end_h - world.s.time_h)))
                    else:
                        raise RuntimeError("FINITE_SAMPLE_LIMIT")
                    case["changes"].append(dict(layout=layout.id, status=world.events[-1].kind))
                audit = check_run(config, world.snapshot())
                case.update(
                    audit=audit.status,
                    findings=[as_data(f) for f in audit.findings],
                    time_h=world.s.time_h,
                    status="PASS" if audit.status == "PASS" else "FAILED",
                )
            except Exception as exc:
                case.update(status="FAILED", error=str(exc), time_h=world.s.time_h)
            path = output / f"{variant}-{root}"
            path.mkdir()
            (path / "configuration.json").write_text(json.dumps(as_data(config)), encoding="utf-8")
            (path / "snapshot.json").write_text(
                json.dumps(as_data(world.snapshot())), encoding="utf-8"
            )
            print(variant, root, case["status"], flush=True)
    return results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--backend", choices=("light", "isaac"), required=True)
    parser.add_argument("--variant", choices=("SR-W1", "SR-W2"))
    parser.add_argument("--root", choices=("MEP-RECEIVE", "MEP-STORE", "KIT", "F1-KIT", "J3", "F1"))
    parser.add_argument("--actual-obstruction", action="store_true")
    args = parser.parse_args()
    if args.actual_obstruction and args.backend != "isaac":
        parser.error("actual-obstruction requires the actual Kit backend")
    args.output.mkdir(parents=True, exist_ok=False)
    (args.output / "started.json").write_text(json.dumps({"pid": os.getpid()}), encoding="utf-8")
    files = [
        *ROOT.glob("src/adaptive_hrc_scheduling/**/*production*.py"),
        *ROOT.glob("sim/isaac/scene/production*.py"),
        ROOT / "scripts/build_production_contracts.py",
        Path(__file__),
    ]
    report = dict(
        status="FAILED",
        closed=False,
        backend=args.backend,
        runtime="KIT_APPLICATION" if args.backend == "isaac" else "LIGHT_EVENT",
        scope="separate empty-rack fixtures; no continuous production claim",
        industrial_qualification="UNKNOWN",
        human_reach="NOT_VALIDATED",
        failure_scope=(
            "actual obstruction after last verified sample; first layout only"
            if args.actual_obstruction
            else "interruptions only at already verified samples"
        ),
        rendered_frame_validation=False,
        shutdown_mode="KIT_FAST" if args.backend == "isaac" else "PYTHON_NORMAL",
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
        report["cases"] = run(
            args.output,
            args.backend,
            app,
            selected_variant=args.variant,
            selected_root=args.root,
            actual_obstruction=args.actual_obstruction,
        )
        report["status"] = (
            "PASS" if all(c["status"] == "PASS" for c in report["cases"]) else "FAILED"
        )
    except Exception:
        report["error"] = traceback.format_exc()
    finally:
        report["shutdown_requested"] = app is not None
        (args.output / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        if app:
            app.close()
        report["closed"] = True
        (args.output / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
