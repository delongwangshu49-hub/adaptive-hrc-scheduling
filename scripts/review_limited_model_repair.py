"""Isaac-native review of the unchanged SR-W1 NORMAL single-product flow.

Runs the existing audited controller and actual USD port. Display pacing only
adds wall time. This review candidate retains unresolved support-frame issues.
"""

import argparse
import asyncio
import hashlib
import json
import os
import sys
import time
import traceback
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "src"), str(ROOT / "scripts")]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--auto-run", action="store_true")
    parser.add_argument("--exit-after-run", action="store_true")
    parser.add_argument("--headless", action="store_true")
    cli = parser.parse_args()
    cli.output.mkdir(parents=True, exist_ok=False)
    report = dict(
        status="REVIEW_READY",
        closed=False,
        pid=os.getpid(),
        scope="LIMITED_CANDIDATE_SUPPORT_REPAIR_UNRESOLVED",
        images=[],
        display="ACTUAL_USD_EVENT_BOUNDARIES_NOT_CONTINUOUS_PHYSICS",
        sources={
            p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in [
                *ROOT.glob("src/**/*.py"),
                *ROOT.glob("sim/**/*.py"),
                Path(__file__),
            ]
        },
    )

    def save():
        (cli.output / "report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    from isaacsim import SimulationApp

    app = SimulationApp(
        dict(
            headless=cli.headless,
            width=1600,
            height=1000,
            multi_gpu=False,
            fast_shutdown=False,
            enable_crashreporter=False,
            renderer="RayTracedLighting",
            disable_viewport_updates=False,
        )
    )
    import carb
    import omni.ui as ui
    import omni.usd
    import verify_production_chain as verify
    from build_simulation_production import configuration
    from omni.kit.viewport.utility import capture_viewport_to_file, get_active_viewport
    from omni.kit.viewport.window import ViewportWindow
    from pxr import Gf, Usd, UsdGeom

    import adaptive_hrc_scheduling.control.production_loop as loop
    from adaptive_hrc_scheduling.backends.production_isaac_adapter import IsaacAdapter
    from sim.isaac.scene.model import load_config
    from sim.isaac.scene.production_port import USDProductionPort
    from sim.isaac.scene.target_scene import TargetScene

    owned_viewport = None
    viewport_window = ui.Workspace.get_window("Viewport")
    vp = get_active_viewport()
    if viewport_window is None or vp is None:
        owned_viewport = ViewportWindow(
            "Limited repair - actual scene", width=1160, height=920, visible=True
        )
        viewport_window = ui.Workspace.get_window(owned_viewport.title)
        vp = owned_viewport.viewport_api
    vp.updates_enabled = True
    carb.settings.get_settings().set("/app/renderer/skipWhileInvisible", False)
    carb.settings.get_settings().set("/app/viewport/grid/enabled", False)
    pending, has_run = cli.auto_run, False
    trial_number = 0
    pacing = ui.SimpleFloatModel(0.02)
    camera_preset = 0
    cameras = [
        ((81, -57, 72), (29, 21, 0)),
        ((20, 4, 5), (17.5, 8.5, 0.8)),
        ((3, 19, 3), (6, 23.9, 0.4)),
        ((33, 10, 2), (35, 12, 0.45)),
    ]

    def camera(index=0):
        nonlocal camera_preset
        camera_preset = index
        stage = omni.usd.get_context().get_stage()
        eye, target = cameras[index]
        with Usd.EditContext(stage, stage.GetSessionLayer()):
            cam = UsdGeom.Camera.Define(stage, "/LimitedReviewCamera")
            xform = UsdGeom.Xformable(cam)
            xform.ClearXformOpOrder()
            xform.AddTransformOp().Set(
                Gf.Matrix4d()
                .SetLookAt(Gf.Vec3d(*eye), Gf.Vec3d(*target), Gf.Vec3d(0, 0, 1))
                .GetInverse()
            )
            cam.CreateFocalLengthAttr(32)
            cam.CreateClippingRangeAttr(Gf.Vec2f(0.01, 300))
        vp.camera_path = "/LimitedReviewCamera"

    def start():
        nonlocal pending
        if not has_run:
            pending = True

    window = ui.Window("Model repair review", width=430, height=720, position_x=1150, position_y=60)

    def label(*args, **kwargs):
        kwargs["style"] = {"font_size": 16, **kwargs.get("style", {})}
        return ui.Label(*args, **kwargs)

    def button(*args, **kwargs):
        kwargs["style"] = {"font_size": 16, **kwargs.get("style", {})}
        return ui.Button(*args, **kwargs)

    with window.frame:
        with ui.VStack(spacing=10):
            label("SR-W1 / NORMAL / 1 product", height=25)
            label(
                "Original process, timings, routes, landing points and hand poses retained.",
                height=50,
                word_wrap=True,
            )
            label(
                "SUPPORT FRAME REPAIR REMAINS OPEN",
                height=40,
                word_wrap=True,
                style={"color": 0xFF66BBFF},
            )
            label(
                "Actual event-boundary scene. No continuous physics claim.",
                height=45,
                word_wrap=True,
            )
            start_button = button("Start full product", height=44, clicked_fn=start)
            status = label("Ready", height=100, word_wrap=True)
            label("Display delay (wall time only)", height=25)
            ui.FloatSlider(model=pacing, min=0, max=0.5, height=25)
            for i, text in enumerate(("Overview", "Fixed bars", "Attachments", "Robot")):
                button(text, height=32, clicked_fn=lambda n=i: camera(n))
            label(
                "PASS requires receipt of 1 product and both audits. Original evidence preserved. Industrial G2 OPEN.",
                height=70,
                word_wrap=True,
            )
            label(str(cli.output), height=65, word_wrap=True)

    omni.usd.get_context().new_stage()
    preview_scene = TargetScene(
        omni.usd.get_context().get_stage(),
        load_config(ROOT / "examples/building_contracts/configuration.json"),
    )
    _preview_engine = IsaacAdapter(configuration(), USDProductionPort(preview_scene))
    camera()
    for _ in range(60):
        vp.updates_enabled = True
        app.update()
    try:
        window.dock_in(viewport_window, ui.DockPosition.RIGHT, 0.28)
        report["panel_dock_requested"] = True
    except Exception as error:
        report["panel_dock_error"] = str(error)
    for title in ("Stage", "Content", "Console", "Render Settings", "Property"):
        handle = ui.Workspace.get_window(title)
        if handle:
            handle.visible = False
    save()

    def capture(name):
        path = cli.output / (name + ".png")
        task = asyncio.ensure_future(capture_viewport_to_file(vp, str(path)).wait_for_result())
        began = time.monotonic()
        while not task.done() and time.monotonic() - began < 30:
            vp.updates_enabled = True
            app.update()
        if not task.done():
            raise RuntimeError("VIEWPORT_CAPTURE_TIMEOUT")
        task.result()
        while time.monotonic() - began < 30:
            if path.exists() and path.read_bytes().endswith(bytes.fromhex("49454e44ae426082")):
                report["images"].append(
                    dict(file=path.name, sha256=hashlib.sha256(path.read_bytes()).hexdigest())
                )
                save()
                return
            app.update()
        raise RuntimeError("INCOMPLETE_VIEWPORT_PNG")

    original_run = loop.run

    def review_run(engine, scenario, **options):
        original_hook = options.pop("execution_hook", None)
        world = getattr(engine, "world", engine)
        camera(camera_preset)
        captured = set()

        def hook(current, phase):
            if original_hook:
                original_hook(current, phase)
            if phase != "before_decision":
                return
            status.text = f"Running\nTime: {world.s.time_h:.6f} h\nCompleted: {len(world.s.completed)} (incl. services)\nEvents: {len(world.events)}"
            until = time.monotonic() + pacing.as_float
            while True:
                vp.updates_enabled = True
                app.update()
                if time.monotonic() >= until:
                    break
            if world.s.time_h >= 70 and "mid" not in captured:
                capture(f"trial-{trial_number:03}-mid-production")
                captured.add("mid")

        return original_run(engine, scenario, execution_hook=hook, **options)

    loop.run = review_run
    try:
        capture("initial")
        while app.is_running():
            vp.updates_enabled = True
            app.update()
            if not pending:
                continue
            pending, has_run = False, True
            start_button.enabled = False
            _preview_engine = preview_scene = None
            trial_number += 1
            run_output = cli.output / f"trial-{trial_number:03}"
            run_output.mkdir(exist_ok=False)
            report.update(status="RUNNING", trial_directory=run_output.name)
            save()
            args = SimpleNamespace(
                output=run_output,
                backend="isaac",
                products=1,
                variant="SR-W1",
                simulation=True,
                rework=False,
                release_times=None,
                delayed_lot=None,
                actual_r1_before_setup=False,
                actual_r1_after_bottom=False,
                method=None,
                online_limits_file=None,
                online_measure_window_h=None,
                scenario="NORMAL",
                until_h=720,
                receive_after_h=0,
                quality_fail=None,
                rework_fail=False,
                cancel_stage=None,
                cancel_product="PRODUCT-1",
                loaded_failure=False,
                actual_device_failure=False,
                actual_path_obstruction=False,
                arrival_after_h=0,
                expect_quality_hold=False,
                expect_window=False,
                fixed_mode=None,
                handover_after_setup=False,
            )
            report.update(verify.witness(args, app))
            manifest = report["manifest"]
            status.text = f"{report['status']}\nTime: {manifest['time_h']:.9f} h\nReceived: {manifest['received']} / 1\nAudit: {manifest['audit']}\nDecision audit: {manifest['decision_audit']}\nSupport issues remain OPEN"
            omni.usd.get_context().get_stage().GetRootLayer().Export(str(run_output / "final.usda"))
            capture(f"trial-{trial_number:03}-final")
            report["trial_directory"] = run_output.name
            (run_output / "report.json").write_text(
                json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            start_button.text = "Start new full trial"
            start_button.enabled = True
            has_run = False
            save()
            if cli.exit_after_run:
                break
    except Exception:
        report.update(status="FAILED", error=traceback.format_exc())
        traceback.print_exc()
    finally:
        loop.run = original_run
        save()
        window.visible = False
        if owned_viewport:
            owned_viewport.destroy()
        omni.usd.get_context().close_stage()
        for _ in range(30):
            app.update()
        app.close()
        report["closed"] = True
        report["shutdown_strategy"] = (
            "FULL_KIT_CLOSE_RETURN_THEN_EXPLICIT_HELPER_EXIT_SKIP_RC_INTERPRETER_FINALIZATION"
        )
        save()
        code = 0 if report["status"] in ("PASS", "REVIEW_READY") else 1
        print("FULL_KIT_CLOSE_RETURN", code, flush=True)
        os._exit(code)


if __name__ == "__main__":
    main()
