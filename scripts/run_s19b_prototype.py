"""S19B legacy prefix or explicitly confirmed B2 single-worker production control."""

import argparse
import gc
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
sys.path[:0] = [str(ROOT), str(ROOT / "src"), str(ROOT / "scripts"), str(ROOT / "desktop/s19b/src")]

from s19b_desktop.control import (  # noqa: E402
    Controller,
    canonical_digest,
    process_token,
    validate_control,
)
from s19b_desktop.model import (  # noqa: E402 -- isolate Qt from CPU/Kit; bootstrap source path
    CAMERAS,
    PROTOCOL,
    atomic_json,
    read_json,
    validate_request,
)
from s19b_desktop.review import (  # noqa: E402
    entity_catalog,
    reason_fact,
    seal_evidence,
    validate_display_request,
)


def run(request, output, app=None, control=None):
    from build_simulation_production import configuration

    from adaptive_hrc_scheduling.contracts.codec import as_data
    from adaptive_hrc_scheduling.contracts.production import digest, validate
    from adaptive_hrc_scheduling.control.online import Limits, OnlinePolicy
    from adaptive_hrc_scheduling.control.online_timing import OnlineTiming
    from adaptive_hrc_scheduling.control.production_decisions import record
    from adaptive_hrc_scheduling.control.production_loop import Scenario
    from adaptive_hrc_scheduling.control.production_loop import run as production_run
    from adaptive_hrc_scheduling.production_backend import ProductionBackend

    draft = request["draft"]
    config = configuration(products=draft["products"], variant=draft["variant"])
    config = replace(
        config,
        products=tuple(
            replace(p, release_h=t) for p, t in zip(config.products, draft["release_times"])
        ),
    )
    validate(config)
    atomic_json(output / "configuration.json", as_data(config))
    limits_data = read_json(ROOT / "examples/online/limits.json")
    atomic_json(output / "predeclared-online-limits.json", limits_data)
    engine = ProductionBackend(config, run_id=request["run_id"], epoch=0)
    viewport = None
    display_camera = None
    receiver = None
    if app is not None:
        import carb
        import omni.appwindow
        import omni.ui
        import omni.usd
        from omni.kit.viewport.utility import get_active_viewport, get_active_viewport_window
        from pxr import Sdf, UsdGeom

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
        engine = IsaacAdapter(config, USDProductionPort(scene), run_id=request["run_id"], epoch=0)
        receiver = SyntheticReceiver(engine.port)
        original_step = engine.port.step

        def with_receiver(command_id, now_h):
            receiver.step(engine.port.running[command_id], now_h)
            return original_step(command_id, now_h)

        engine.port.step = with_receiver
        viewport = get_active_viewport()
        viewport_window = get_active_viewport_window()
        if not viewport_window.dock_in_window("DockSpace", omni.ui.DockPosition.SAME):
            raise RuntimeError("KIT_VIEWPORT_DOCK_NOT_CONFIRMED")
        viewport_window.visible = True
        # Render the scene only; keep editing panels and menus outside this trial UI.
        for kit_window in omni.ui.Workspace.get_windows():
            if kit_window.title not in (viewport_window.title, "DockSpace"):
                kit_window.visible = False
        from omni.kit.mainwindow import get_main_window

        get_main_window().get_main_menu_bar().visible = False
        get_main_window().get_status_bar_frame().visible = False
        # This SDK defaults to locking the view to the previous render result.
        # A desktop camera request must sync USD camera state into the new frame.
        viewport.lock_to_render_result = False
        viewport.updates_enabled = True
        viewport.freeze_frame = False
        # Let Kit use the actual embedded UI frame, including after DPI/resize changes.
        viewport.fill_frame = True
        viewport.resolution_scale = 1.0
        UsdGeom.Scope.Define(scene.stage, "/S19B")
        display_camera = "/S19B/ReviewCamera"
        Sdf.CopySpec(
            scene.stage.GetRootLayer(),
            "/World/Cameras/Overview",
            scene.stage.GetRootLayer(),
            display_camera,
        )
        scene.stage.GetPrimAtPath(display_camera).SetCustomDataByKey("scope", "S19B_DISPLAY_ONLY")
        viewport.camera_path = display_camera
        carb.settings.get_settings().set("/app/viewport/grid/enabled", False)
        for _ in range(30):
            app.update()
        # ui.Window is an in-process child of the same native Kit window.
        # Remove its internal editor docking and fill that native client's UI frame.
        # This never creates or moves to another OS window.
        viewport_window.undock()
        viewport_window.flags |= (
            omni.ui.WINDOW_FLAGS_NO_TITLE_BAR
            | omni.ui.WINDOW_FLAGS_NO_MOVE
            | omni.ui.WINDOW_FLAGS_NO_RESIZE
            | omni.ui.WINDOW_FLAGS_NO_SCROLLBAR
        )
        viewport_window.dock_tab_bar_enabled = False
        viewport_window.padding_x = viewport_window.padding_y = 0

        def fit_viewport():
            for key, value in (
                ("position_x", 0),
                ("position_y", 0),
                ("width", omni.ui.Workspace.get_main_window_width()),
                ("height", omni.ui.Workspace.get_main_window_height()),
            ):
                if abs(getattr(viewport_window, key) - value) > 0.05:
                    setattr(viewport_window, key, value)

        for _ in range(10):
            fit_viewport()
            app.update()
        viewport = viewport_window.viewport_api
        viewport.lock_to_render_result = False
        viewport.updates_enabled = True
        viewport.freeze_frame = False
        viewport.fill_frame = True
        viewport.camera_path = display_camera
    world = getattr(engine, "world", engine)
    policy = OnlinePolicy(config, Limits(**limits_data), end_h=720)
    timing = OnlineTiming(engine, policy)
    sequence = 0
    view_sequence = -1

    def catalog():
        return entity_catalog(as_data(config), engine.port.mapping if app else None)

    atomic_json(
        output / "entity-catalog.json",
        dict(
            run_id=request["run_id"],
            request_id=request["request_id"],
            epoch=0,
            config_sha256=digest(config),
            scope="DISPLAY_ONLY",
            entities=catalog(),
        ),
    )

    def publish(phase, **extra):
        nonlocal sequence
        sequence += 1
        active = [
            {
                "operation": r.command.operation_id,
                "product": r.command.product_id,
                "status": r.status,
                "phase": world.operations[r.command.operation_id].phase,
            }
            for r in world.s.running
        ]
        value = dict(
            protocol=PROTOCOL,
            run_id=request["run_id"],
            request_id=request["request_id"],
            epoch=0,
            sequence=sequence,
            revision=world.s.revision,
            config_sha256=digest(config),
            time_h=world.s.time_h,
            phase=phase,
            backend=request["backend"],
            published_wall_s=time.time(),
            published_monotonic_s=time.monotonic(),
            source_version=hashlib.sha256((output / "sources.json").read_bytes()).hexdigest(),
            control_phase=control.state["phase"] if control else None,
            completed=len(world.s.completed),
            active=active,
            products=[
                dict(
                    id=p.product_id,
                    released=p.released,
                    cancelled=p.cancelled,
                    ready=p.ready_h is not None,
                    received=p.received_h is not None,
                )
                for p in world.s.products
            ],
            reason=reason_fact(policy.journal),
            camera=str(viewport.camera_path) if viewport else None,
            **extra,
        )
        atomic_json(output / "live.json", value)

    def view_request():
        nonlocal view_sequence
        path = output / "view-request.json"
        if viewport is None or not path.is_file():
            return None
        data = read_json(path)
        try:
            validate_display_request(data, request, view_sequence)
        except ValueError:
            return None
        view_sequence = data["sequence"]
        if data["action"] == "locate":
            row = next((r for r in catalog() if r["id"] == data.get("entity_id")), None)
            paths = row["paths"] if row else []
            accepted = bool(paths) and all(scene.stage.GetPrimAtPath(p).IsValid() for p in paths)
            before = hashlib.sha256(
                scene.stage.GetRootLayer().ExportToString().encode()
            ).hexdigest()
            state_before = digest(world.s)
            selection = omni.usd.get_context().get_selection()
            if accepted:
                selection.set_selected_prim_paths(paths, False)
                accepted = set(selection.get_selected_prim_paths()) == set(paths)
            after = hashlib.sha256(scene.stage.GetRootLayer().ExportToString().encode()).hexdigest()
            if before != after or state_before != digest(world.s):
                raise RuntimeError("LOCATION_CHANGED_PRODUCTION_OR_USD")
            atomic_json(
                output / "location-confirmation.json",
                {
                    **data,
                    "accepted": accepted,
                    "scope": "DISPLAY_ONLY",
                    "reason": "SELECTED_EXISTING_USD_PRIMS" if accepted else "ENTITY_UNMAPPED",
                    "paths": paths,
                    "targets": row["targets"] if row else [],
                    "unmapped_targets": [
                        ident for ident in row["targets"] if ident not in engine.port.mapping
                    ]
                    if row
                    else [data.get("entity_id")],
                    "selected_paths": selection.get_selected_prim_paths(),
                    "usd_before_sha256": before,
                    "usd_after_sha256": after,
                    "state_before_sha256": state_before,
                    "state_after_sha256": digest(world.s),
                },
            )
            if accepted:
                capture("location-scene.png")
        elif data["action"] == "camera" and data.get("camera") in CAMERAS:
            # Keep one dedicated render-camera identity; preserve original presets.
            # This RC kept a stale render view when switching bound prim paths.
            source_camera = "/World/Cameras/" + data["camera"]
            # Keep the live render camera prim alive. Replacing its spec while
            # RTX uses it can invalidate renderer camera state in this RC.
            source_prim = scene.stage.GetPrimAtPath(source_camera)
            target_prim = scene.stage.GetPrimAtPath(display_camera)
            for attr in source_prim.GetAttributes():
                if attr.HasAuthoredValueOpinion():
                    target_prim.GetAttribute(attr.GetName()).Set(attr.Get())
            scene.stage.GetPrimAtPath(display_camera).SetCustomDataByKey(
                "scope", "S19B_DISPLAY_ONLY"
            )

            expected_view = (
                UsdGeom.Xformable(scene.stage.GetPrimAtPath(viewport.camera_path))
                .ComputeLocalToWorldTransform(0)
                .GetInverse()
            )
            camera_error = 1.0
            camera_deadline = time.monotonic() + 10
            viewport.lock_to_render_result = False
            while time.monotonic() < camera_deadline:
                fit_viewport()
                app.update()
                actual_view = viewport.frame_info.get("view")
                if actual_view is not None:
                    camera_error = max(
                        abs(actual_view[i * 4 + j] - expected_view[i][j])
                        for i in range(4)
                        for j in range(4)
                    )
                    if camera_error < 1e-4:
                        break
                time.sleep(0.01)
            if camera_error >= 1e-4:
                atomic_json(
                    output / "camera-frame-diagnostic.json",
                    {
                        "run_id": request["run_id"],
                        "camera_path": str(viewport.camera_path),
                        "error": camera_error,
                        "actual_view": list(actual_view) if actual_view is not None else None,
                        "expected_view": [expected_view[i][j] for i in range(4) for j in range(4)],
                    },
                )
                raise RuntimeError("CAMERA_FRAME_NOT_CONFIRMED")
            atomic_json(
                output / "view-confirmation.json",
                {
                    **data,
                    "accepted": True,
                    "camera_path": str(viewport.camera_path),
                    "preset_source": source_camera,
                    "scope": "DISPLAY_ONLY",
                    "view_matrix_max_error": camera_error,
                },
            )
        return data.get("action")

    def capture(name):
        if viewport is None:
            return
        import asyncio

        from omni.kit.viewport.utility import capture_viewport_to_file

        async def take():
            await capture_viewport_to_file(viewport, str(output / name)).wait_for_result()

        task = asyncio.ensure_future(take())
        deadline = time.monotonic() + 30
        while not task.done() and time.monotonic() < deadline:
            fit_viewport()
            app.update()
        if not task.done():
            raise RuntimeError("CAPTURE_TIMEOUT")
        task.result()
        while time.monotonic() < deadline:
            try:
                if (output / name).read_bytes().endswith(b"IEND\xaeB`\x82"):
                    return
            except (FileNotFoundError, PermissionError):
                pass
            fit_viewport()
            app.update()
        raise RuntimeError("CAPTURE_INCOMPLETE")

    publish("INITIALIZED")
    capture("scene-before.png")
    if control:
        control.initialized()

    def progress(_engine, phase):
        if app is not None:
            if not app.is_running():
                raise RuntimeError("DISPLAY_CLOSED_DURING_PREFIX")
            fit_viewport()
            timing.kit_update(app)
            view_request()
        if control:
            control.poll()
        publish(
            "AUDITING"
            if phase == "before_audit"
            else "STOPPING"
            if control and control.state["stop"]
            else "RUNNING"
        )

    result = production_run(
        engine,
        Scenario(id="NORMAL", until_h=720),
        joint_policy=policy,
        execution_hook=progress,
        stop_condition=None if control else lambda w: w.s.time_h >= 1.0,
        orderly_stop=(lambda w: control.poll()) if control else None,
    )
    manifest = dict(result.manifest)
    manifest.pop("joint_journal", None)
    manifest["online_journal"] = {"path": "online-journal.json", "records": len(policy.journal)}
    report = dict(
        protocol=PROTOCOL,
        run_id=request["run_id"],
        request_id=request["request_id"],
        backend=request["backend"],
        manifest=manifest,
        scope="B2_CONTROLLED_PRODUCTION"
        if control
        else "FINITE_1H_EVENT_BOUNDARY_PREFIX_NOT_COMPLETE_ORDER",
        closed=False,
        display_mode="VISIBLE_KIT_RAYTRACED_PROTOTYPE" if app else "CPU_EVENT",
        industrial_qualification="NOT_ESTABLISHED",
    )
    report["status"] = (
        "PASS"
        if result.audit.status == result.decision_audit.status == "PASS"
        and result.manifest["termination"]
        in (("ORDERLY_STOPPED", "OPERATIONS_COMPLETE") if control else ("DECLARED_CHECKPOINT",))
        else "FAILED"
    )
    atomic_json(output / "state.json", as_data(result.snapshot.state))
    atomic_json(output / "audit.json", as_data(result.audit))
    atomic_json(output / "decision-audit.json", as_data(result.decision_audit))
    with gzip.open(output / "events.jsonl.gz", "wt", encoding="utf-8") as stream:
        for event in result.snapshot.events:
            stream.write(
                json.dumps(as_data(event), ensure_ascii=False, separators=(",", ":")) + "\n"
            )
    with gzip.open(output / "decisions.jsonl.gz", "wt", encoding="utf-8") as stream:
        for decision in result.decisions:
            stream.write(
                json.dumps(record(decision), ensure_ascii=False, separators=(",", ":")) + "\n"
            )
    timing_report = timing.report()
    timing_report["rendering"] = (
        "VISIBLE_KIT_PROTOTYPE_NOT_FORMAL_PERFORMANCE_ACCEPTANCE"
        if app
        else "NOT_APPLICABLE_LIGHT_BACKEND"
    )
    atomic_json(output / "online-timing.json", timing_report)
    atomic_json(output / "online-journal.json", policy.journal)
    timing.close()
    if receiver is not None:
        atomic_json(output / "receiver-samples.json", receiver.samples)
        from inspect_s19b_scene_supports import inspect_supports

        atomic_json(
            output / "scene-support-diagnostic.json",
            inspect_supports(scene, request["run_id"], request["request_id"]),
        )
    capture("scene-after.png")
    if app is not None:
        from omni.kit.renderer.capture import acquire_renderer_capture_interface

        for kit_window in omni.ui.Workspace.get_windows():
            if kit_window.title not in (viewport_window.title, "DockSpace"):
                kit_window.visible = False
        get_main_window().get_main_menu_bar().visible = False
        for _ in range(10):
            fit_viewport()
            app.update()
        acquire_renderer_capture_interface().capture_next_frame_swapchain(
            str(output / "kit-ui-frame.png")
        )
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            fit_viewport()
            app.update()
            try:
                if (output / "kit-ui-frame.png").read_bytes().endswith(b"IEND\xaeB`\x82"):
                    break
            except (FileNotFoundError, PermissionError):
                pass
        else:
            raise RuntimeError("KIT_SWAPCHAIN_CAPTURE_TIMEOUT")
    atomic_json(output / "report.json", report)
    if control:
        phase = {
            "ORDERLY_STOPPED": "STOPPED",
            "ORDERLY_STOP_BLOCKED": "STOP_BLOCKED",
            "OPERATIONS_COMPLETE": "COMPLETED",
        }.get(manifest["termination"], "FAILED")
        if result.audit.status != "PASS" or result.decision_audit.status != "PASS":
            phase = "FAILED"
        control.finish(phase, manifest)
    seal_evidence(output, request)
    publish(
        "PRODUCTION_SAVED" if control else "CHECKPOINT_SAVED",
        audit=result.audit.status,
        decision_audit=result.decision_audit.status,
    )
    if app is not None and not control:
        end = time.monotonic() + request["display_hold_s"]
        last_view_publish = 0.0
        while app.is_running() and time.monotonic() < end:
            fit_viewport()
            app.update()
            frame_view = viewport.frame_info.get("view")
            if frame_view is not None and time.monotonic() - last_view_publish >= 0.2:
                last_view_publish = time.monotonic()
                atomic_json(
                    output / "view-state.json",
                    dict(
                        run_id=request["run_id"],
                        camera_path=str(viewport.camera_path),
                        view_matrix=[float(value) for value in frame_view],
                        published_monotonic_s=time.monotonic(),
                        scope="DISPLAY_ONLY",
                        ui_viewport_visible=viewport_window.visible,
                        ui_viewport_width=viewport_window.width,
                        ui_viewport_height=viewport_window.height,
                        app_width=omni.appwindow.get_default_app_window().get_width(),
                        app_height=omni.appwindow.get_default_app_window().get_height(),
                        fill_frame=viewport.fill_frame,
                        render_resolution=list(viewport.resolution),
                        ui_main_width=omni.ui.Workspace.get_main_window_width(),
                        ui_main_height=omni.ui.Workspace.get_main_window_height(),
                    ),
                )
            if view_request() == "close_display":
                break
            publish(
                "CHECKPOINT_DISPLAY_OPEN",
                audit=result.audit.status,
                decision_audit=result.decision_audit.status,
            )
            time.sleep(0.03)
    if app is not None:
        engine.port.step = original_step
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", type=Path, required=True)
    args = parser.parse_args()
    request = validate_request(read_json(args.request))
    output = args.request.resolve().parent
    if (output / "report.json").exists() or (output / "started.json").exists():
        raise RuntimeError("RUN_DIRECTORY_ALREADY_STARTED")
    control = None
    if "control" in request:
        validate_control(request, ROOT, output)
        # A permanent exclusive claim prevents two workers and prevents restart
        # after a crash. Never overwrite an existing run or evidence.
        with (output / "worker-claim.json").open("x", encoding="utf-8") as stream:
            json.dump(
                dict(
                    run_id=request["run_id"],
                    request_id=request["request_id"],
                    request_sha256=canonical_digest(request),
                    pid=os.getpid(),
                ),
                stream,
            )
        control = Controller(output, request)
        start_path = output / "start-command.json"
        start_receipt = control.accept(read_json(start_path))
        if not start_receipt["accepted"]:
            control.finish("FAILED", {"rejected_start": start_receipt["reason"]})
            raise RuntimeError(start_receipt["reason"])
        if control.state["commands"][start_receipt["command_id"]]["request"]["action"] != "start":
            raise RuntimeError("CONTROL_START_REQUIRED")
    atomic_json(
        output / "started.json",
        dict(
            run_id=request["run_id"],
            request_id=request["request_id"],
            pid=os.getpid(),
            process_token=process_token(os.getpid()) if control else None,
        ),
    )
    sources = [
        *ROOT.glob("src/**/*.py"),
        *ROOT.glob("sim/**/*.py"),
        ROOT / "scripts/build_production_contracts.py",
        ROOT / "scripts/build_simulation_production.py",
        ROOT / "scripts/inspect_s19b_scene_supports.py",
        Path(__file__),
        *ROOT.glob("desktop/s19b/src/**/*.py"),
        ROOT / "examples/online/limits.json",
        ROOT / "examples/building_contracts/configuration.json",
        ROOT / "src/adaptive_hrc_scheduling/production_recipe.json",
        ROOT / "sim/isaac/s19b_viewport.kit",
        ROOT / "desktop/s19b/uv.lock",
        ROOT / "desktop/s19b/pyproject.toml",
    ]
    atomic_json(
        output / "sources.json",
        {
            p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sources
        },
    )
    report = dict(
        protocol=PROTOCOL,
        run_id=request["run_id"],
        request_id=request["request_id"],
        backend=request["backend"],
        status="FAILED",
        closed=False,
    )
    app = None
    try:
        if request["backend"] == "isaac":
            cache = ROOT / ".local/s19b-render-cache/optix"
            cache.mkdir(parents=True, exist_ok=True)
            os.environ["OPTIX_CACHE_PATH"] = str(cache)
            from isaacsim import SimulationApp

            app = SimulationApp(
                {
                    "headless": False,
                    "width": 1280,
                    "height": 720,
                    "window_width": 1000,
                    "window_height": 820,
                    "multi_gpu": False,
                    "fast_shutdown": False,
                    "enable_crashreporter": False,
                    "renderer": "RayTracedLighting",
                    "extra_args": [
                        "--ext-folder",
                        str(Path(os.environ["ISAAC_PATH"]) / "extscache"),
                        "--ext-folder",
                        str(Path(os.environ["ISAAC_PATH"]) / "extsDeprecated"),
                        "--ext-folder",
                        str(Path(os.environ["ISAAC_PATH"]) / "extsUser"),
                        "--/app/extensions/registryEnabled=false",
                    ],
                },
                experience=str(ROOT / "sim/isaac/s19b_viewport.kit"),
            )
        report = run(request, output, app, control)
    except Exception:
        report["error"] = traceback.format_exc()
        if control:
            control.finish("FAILED", {"error": report["error"]})
    finally:
        atomic_json(output / "report.json", report)
        if app is not None:
            gc.collect()
            app.close()
        report["closed"] = True
        report["process_exit_strategy"] = (
            "EXPLICIT_EXIT_AFTER_FULL_KIT_CLOSE_RETURN"
            if app is not None
            else "NORMAL_CPYTHON_EXIT"
        )
        atomic_json(output / "report.json", report)
        if report["status"] == "PASS":
            seal_evidence(output, request)
    print(json.dumps({k: v for k, v in report.items() if k != "manifest"}), flush=True)
    exit_code = 0 if report["status"] == "PASS" else 1
    if app is not None:
        # This installed RC leaves framework unload to interpreter finalization;
        # visible RTX runs hung there after full extension teardown returned.
        # All files are closed, Kit close returned, and failures keep exit 1.
        sys.stdout.flush()
        sys.stderr.flush()
        os._exit(exit_code)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
