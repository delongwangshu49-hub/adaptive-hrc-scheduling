"""Read-only S19B measurement adapter around the unchanged prescribed witness."""

import argparse
import gc
import hashlib
import json
import os
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "src"), str(ROOT / "scripts"), str(ROOT / "desktop/s19b/src")]


def sources():
    files = set()
    for pattern in (
        "src/**/*.py",
        "sim/**/*.py",
        "scripts/*.py",
        "desktop/s19b/src/**/*.py",
        "examples/online/*.json",
        "src/adaptive_hrc_scheduling/simulation_inputs/*",
        "sim/isaac/scene/assets/*",
        "schemas/**/*.json",
    ):
        files.update(p for p in ROOT.glob(pattern) if p.is_file())
    files.update(
        ROOT / p
        for p in (
            "sim/isaac/s19b_viewport.kit",
            "examples/building_contracts/configuration.json",
            "src/adaptive_hrc_scheduling/production_recipe.json",
            "desktop/s19b/uv.lock",
            "desktop/s19b/pyproject.toml",
        )
    )
    return {
        p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(files)
    }


def case_args(case, output, backend, run_id):
    # The original witness's own argparse defaults and recorded case arguments.
    # Capture parsing without invoking its process/bootstrap implementation.
    import verify_production_chain as witness

    original = argparse.ArgumentParser.parse_args
    argv = [
        "--output",
        str(output),
        "--backend",
        backend,
        "--simulation",
        "--run-id",
        run_id,
        "--online-limits-file",
        case["limits"],
        *case["arguments"],
    ]
    captured = []

    class Parsed(BaseException):
        pass

    def parse(parser, *args, **kwargs):
        captured.append(original(parser, argv))
        raise Parsed()

    argparse.ArgumentParser.parse_args = parse
    try:
        witness.main()
    except Parsed:
        pass
    finally:
        argparse.ArgumentParser.parse_args = original
    return captured[0]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--case", required=True)
    parser.add_argument("--mode", choices=("visible", "headless", "light"), required=True)
    parser.add_argument("--freeze", type=Path, required=True)
    opts = parser.parse_args()
    out = opts.output.resolve()
    if sys.platform == "win32":
        import ctypes

        # Only this owned measurement worker: native faults still fail with their
        # actual exit code rather than waiting indefinitely for an error dialog.
        ctypes.windll.kernel32.SetErrorMode(0x0001 | 0x0002)
    from s19b_desktop.control import process_token
    from s19b_desktop.model import PROTOCOL, atomic_json
    from s19b_desktop.review import entity_catalog, reason_fact

    frozen = json.loads(opts.freeze.read_text(encoding="utf-8"))
    assert sources() == frozen["sources"], "MEASURED_SOURCE_CHANGED"
    case = next(
        c
        for c in json.loads((ROOT / "examples/online/workloads.json").read_text(encoding="utf-8"))[
            "cases"
        ]
        if c["id"] == opts.case
    )
    identity = json.loads((out / "identity.json").read_text(encoding="utf-8"))
    args = case_args(case, out, "light" if opts.mode == "light" else "isaac", identity["run_id"])
    atomic_json(out / "sources.json", frozen["sources"])
    source_version = hashlib.sha256((out / "sources.json").read_bytes()).hexdigest()
    atomic_json(
        out / "started.json",
        dict(**identity, pid=os.getpid(), process_token=process_token(os.getpid())),
    )
    deadline = time.monotonic() + 30
    while not (out / "process-watch-ready.json").exists():
        if time.monotonic() >= deadline:
            raise TimeoutError("WORKER_EXIT_OBSERVER_NOT_READY")
        time.sleep(0.01)
    report = dict(
        status="FAILED",
        closed=False,
        sources=frozen["sources"],
        runtime="LIGHT_EVENT" if opts.mode == "light" else "KIT_APPLICATION",
        scope="SIMULATION_RESEARCH_ONLY",
        measurement_mode=opts.mode,
        run_id=identity["run_id"],
        request_id=identity["request_id"],
        industrial_qualification="NOT_ESTABLISHED",
    )
    app = None
    stages = {}
    cpu_boundaries = {}

    def cpu_boundary(name):
        # Actual worker counters at the call boundary. Remote frontend readings
        # follow immediately; read skew is exposed, not called exact tree CPU.
        from measure_s19b_ui import process_sample

        read_start = time.perf_counter()
        worker_cpu = time.process_time()
        boundary = time.perf_counter()
        watcher = json.loads((out / "process-watch-ready.json").read_text(encoding="utf-8"))
        observer = process_sample(watcher["observer_pid"])
        if name == "production_start":
            worker_cpu = time.process_time()
            boundary = time.perf_counter()
        cpu_boundaries[name] = dict(
            monotonic_s=boundary,
            worker_cpu_s=worker_cpu,
            observer=observer,
            read_started_monotonic_s=read_start,
            read_finished_monotonic_s=time.perf_counter(),
            scope="WORKER_CALL_BOUNDARY_AND_NEAR_SYNCHRONOUS_OBSERVER_NOT_PROCESS_TREE",
        )

    started = time.perf_counter()
    hooks = (out / "hook-samples.jsonl").open("x", encoding="utf-8")
    try:
        if opts.mode != "light":
            os.environ["OPTIX_CACHE_PATH"] = str(ROOT / ".local/s19b-render-cache/optix")
            from isaacsim import SimulationApp

            visible = opts.mode == "visible"
            settings = dict(
                headless=not visible,
                width=900 if visible else 1280,
                height=651 if visible else 720,
                window_width=900,
                window_height=651,
                multi_gpu=False,
                fast_shutdown=False,
                enable_crashreporter=False,
                renderer="RayTracedLighting" if visible else "MinimalRendering",
            )
            if visible:
                settings["extra_args"] = [
                    "--ext-folder",
                    str(Path(os.environ["ISAAC_PATH"]) / "extscache"),
                    "--ext-folder",
                    str(Path(os.environ["ISAAC_PATH"]) / "extsDeprecated"),
                    "--ext-folder",
                    str(Path(os.environ["ISAAC_PATH"]) / "extsUser"),
                    "--/app/extensions/registryEnabled=false",
                ]
                app = SimulationApp(settings, experience=str(ROOT / "sim/isaac/s19b_viewport.kit"))
            else:
                settings["disable_viewport_updates"] = True
                app = SimulationApp(settings)
        stages["bootstrap_s"] = time.perf_counter() - started
        import verify_production_chain as witness

        from adaptive_hrc_scheduling.contracts.codec import as_data
        from adaptive_hrc_scheduling.contracts.production import digest
        from adaptive_hrc_scheduling.control import production_loop

        original_run = production_loop.run
        sequence = 0

        def measured_run(engine, scenario, **kwargs):
            nonlocal sequence
            world = getattr(engine, "world", engine)
            policy = kwargs["joint_policy"]
            timing = next(
                cell.cell_contents
                for cell in kwargs["execution_hook"].__closure__
                if hasattr(cell.cell_contents, "kit_update")
            )
            config_hash = digest(world.config)
            assert world.run_id == identity["run_id"], "LIVE_PRODUCTION_IDENTITY_MISMATCH"
            atomic_json(
                out / "entity-catalog.json",
                dict(
                    **identity,
                    epoch=0,
                    config_sha256=config_hash,
                    scope="DISPLAY_ONLY",
                    entities=entity_catalog(
                        as_data(world.config),
                        engine.port.mapping if hasattr(engine, "port") else None,
                    ),
                ),
            )
            viewport = None
            if opts.mode == "visible":
                import carb
                import omni.appwindow
                import omni.ui
                from omni.kit.mainwindow import get_main_window
                from omni.kit.viewport.utility import get_active_viewport_window
                from pxr import Sdf, UsdGeom

                native = omni.appwindow.get_default_app_window()
                viewport_window = get_active_viewport_window()
                assert viewport_window.dock_in_window("DockSpace", omni.ui.DockPosition.SAME)
                viewport_window.visible = True
                for window in omni.ui.Workspace.get_windows():
                    if window.title not in (viewport_window.title, "DockSpace"):
                        window.visible = False
                get_main_window().get_main_menu_bar().visible = False
                get_main_window().get_status_bar_frame().visible = False
                viewport = viewport_window.viewport_api
                scene = engine.port.scene
                UsdGeom.Scope.Define(scene.stage, "/S19B")
                Sdf.CopySpec(
                    scene.stage.GetRootLayer(),
                    "/World/Cameras/Overview",
                    scene.stage.GetRootLayer(),
                    "/S19B/ReviewCamera",
                )
                viewport.camera_path = "/S19B/ReviewCamera"
                viewport.lock_to_render_result = False
                viewport.updates_enabled = True
                viewport.freeze_frame = False
                viewport.fill_frame = True
                viewport.resolution_scale = 1.0
                carb.settings.get_settings().set("/app/viewport/grid/enabled", False)
                for _ in range(30):
                    app.update()
                viewport_window.undock()
                viewport_window.flags |= (
                    omni.ui.WINDOW_FLAGS_NO_TITLE_BAR
                    | omni.ui.WINDOW_FLAGS_NO_MOVE
                    | omni.ui.WINDOW_FLAGS_NO_RESIZE
                    | omni.ui.WINDOW_FLAGS_NO_SCROLLBAR
                )
                viewport_window.dock_tab_bar_enabled = False
                viewport_window.padding_x = viewport_window.padding_y = 0
                atomic_json(out / "display-ready.json", dict(**identity, pid=os.getpid()))

                def fit():
                    for key, value in (
                        ("position_x", 0),
                        ("position_y", 0),
                        ("width", omni.ui.Workspace.get_main_window_width()),
                        ("height", omni.ui.Workspace.get_main_window_height()),
                    ):
                        if abs(getattr(viewport_window, key) - value) > 0.05:
                            setattr(viewport_window, key, value)

                deadline = time.monotonic() + 420
                while not (out / "host-ready.json").exists():
                    fit()
                    app.update()
                    if time.monotonic() >= deadline:
                        raise TimeoutError("NATIVE_HOST_NOT_READY")
                    time.sleep(0.025)
                for _ in range(40):
                    fit()
                    app.update()
                viewport = viewport_window.viewport_api
                viewport.lock_to_render_result = False
                viewport.updates_enabled = True
                viewport.freeze_frame = False
                viewport.fill_frame = True
                viewport.camera_path = "/S19B/ReviewCamera"
                for _ in range(10):
                    fit()
                    app.update()
                expected = (
                    UsdGeom.Camera(scene.stage.GetPrimAtPath("/S19B/ReviewCamera"))
                    .ComputeLocalToWorldTransform(0)
                    .GetInverse()
                )
                actual = viewport.frame_info.get("view")
                atomic_json(
                    out / "render-diagnostic.json",
                    dict(
                        context_stage_id=omni.usd.get_context().get_stage_id(),
                        viewport_stage_id=viewport.usd_context.get_stage_id(),
                        camera=str(viewport.camera_path),
                        stage_prim_count=sum(1 for _ in scene.stage.Traverse()),
                        actual_view=list(actual) if actual is not None else None,
                        expected_view=[expected[i][j] for i in range(4) for j in range(4)],
                    ),
                )
                scene.stage.GetRootLayer().Export(str(out / "display-stage.usda"))
                atomic_json(
                    out / "render-settings.json",
                    dict(
                        camera=str(viewport.camera_path),
                        resolution=list(viewport.resolution),
                        renderer="RayTracedLighting",
                        native_width=native.get_width(),
                        native_height=native.get_height(),
                    ),
                )
            else:

                def fit():
                    pass

            def capture(name):
                if viewport is None:
                    return
                import asyncio

                from omni.kit.renderer.capture import acquire_renderer_capture_interface
                from omni.kit.viewport.utility import capture_viewport_to_file

                async def take():
                    await capture_viewport_to_file(
                        viewport, str(out / ("viewport-" + name))
                    ).wait_for_result()

                task = asyncio.ensure_future(take())
                deadline = time.monotonic() + 30
                while not task.done() and time.monotonic() < deadline:
                    fit()
                    app.update()
                if not task.done():
                    raise TimeoutError("MEASUREMENT_VIEWPORT_CAPTURE_INCOMPLETE")
                task.result()
                deadline = time.monotonic() + 10
                while time.monotonic() < deadline:
                    fit()
                    app.update()
                    actual = viewport.frame_info.get("view")
                    if (
                        actual is not None
                        and max(
                            abs(actual[i * 4 + j] - expected[i][j])
                            for i in range(4)
                            for j in range(4)
                        )
                        < 1e-4
                    ):
                        break
                    time.sleep(0.01)
                atomic_json(
                    out / (name + ".frame.json"),
                    dict(
                        actual_view=list(actual) if actual is not None else None,
                        view_matrix_max_error=max(
                            abs(actual[i * 4 + j] - expected[i][j])
                            for i in range(4)
                            for j in range(4)
                        )
                        if actual is not None
                        else None,
                        frame_keys=list(viewport.frame_info),
                        resolution=list(viewport.resolution),
                    ),
                )
                if (
                    actual is None
                    or max(
                        abs(actual[i * 4 + j] - expected[i][j]) for i in range(4) for j in range(4)
                    )
                    >= 1e-4
                ):
                    raise RuntimeError("MEASUREMENT_RENDER_FRAME_NOT_CONFIRMED")
                for _ in range(10):
                    fit()
                    app.update()
                    time.sleep(0.01)

                acquire_renderer_capture_interface().capture_next_frame_swapchain(str(out / name))
                deadline = time.monotonic() + 30
                while time.monotonic() < deadline:
                    fit()
                    app.update()
                    try:
                        if (out / name).read_bytes().endswith(b"IEND\xaeB`\x82"):
                            return
                    except (FileNotFoundError, PermissionError):
                        pass
                raise TimeoutError("MEASUREMENT_SWAPCHAIN_CAPTURE_INCOMPLETE")

            capture("display-before.png")
            stages["initialized_s"] = time.perf_counter() - started
            base_hook = kwargs["execution_hook"]

            def publish(phase):
                nonlocal sequence
                sequence += 1
                atomic_json(
                    out / "live.json",
                    dict(
                        protocol=PROTOCOL,
                        **identity,
                        epoch=0,
                        sequence=sequence,
                        revision=world.s.revision,
                        config_sha256=config_hash,
                        time_h=world.s.time_h,
                        phase=phase,
                        backend=args.backend if args.backend == "isaac" else "cpu",
                        published_wall_s=time.time(),
                        published_monotonic_s=time.monotonic(),
                        source_version=source_version,
                        completed=len(world.s.completed),
                        active=[
                            dict(
                                operation=r.command.operation_id,
                                product=r.command.product_id,
                                status=r.status,
                                phase=world.operations[r.command.operation_id].phase,
                            )
                            for r in world.s.running
                        ],
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
                    ),
                )

            def hook(backend, phase):
                if phase == "before_audit":
                    cpu_boundary("production_end_audit_start")
                began = time.perf_counter()
                fit()
                base_hook(backend, phase)
                if opts.mode == "visible" and phase != "before_decision":
                    timing.kit_update(app)
                published = time.perf_counter()
                publish("AUDITING" if phase == "before_audit" else "RUNNING")
                hooks.write(
                    json.dumps(
                        dict(
                            phase=phase,
                            time_h=world.s.time_h,
                            elapsed_s=time.perf_counter() - began,
                            publish_s=time.perf_counter() - published,
                            elapsed_production_s=time.perf_counter()
                            - stages["production_start_counter"],
                        )
                    )
                    + "\n"
                )
                hooks.flush()
                if phase == "before_audit":
                    stages["production_s"] = (
                        time.perf_counter() - stages["production_start_counter"]
                    )
                    stages["audit_start_counter"] = time.perf_counter()
                    stages["audit_started_monotonic_s"] = stages["audit_start_counter"]

            kwargs["execution_hook"] = hook
            publish("INITIALIZED")
            stages["production_start_counter"] = time.perf_counter()
            stages["production_started_monotonic_s"] = stages["production_start_counter"]
            cpu_boundary("production_start")
            result = original_run(engine, scenario, **kwargs)
            cpu_boundary("audit_end")
            stages["audit_s"] = time.perf_counter() - stages["audit_start_counter"]
            atomic_json(
                out / "timing-raw.json",
                dict(categories=dict(timing.samples), feedback=timing.feedback),
            )
            publish("PRODUCTION_SAVED")
            capture("display-after.png")
            if hasattr(engine, "port"):
                # Break the original synthetic receiver's bound-method cycle
                # after all execution/readback and evidence capture are complete.
                receiver_step = engine.port.step
                for cell in getattr(receiver_step, "__closure__", ()) or ():
                    value = cell.cell_contents
                    if getattr(value, "__self__", None) is engine.port:
                        engine.port.step = value
                        break
            return result

        production_loop.run = measured_run
        try:
            report.update(witness.witness(args, app))
        finally:
            production_loop.run = original_run
        stages["witness_finished_s"] = time.perf_counter() - started
        assert sources() == frozen["sources"], "MEASURED_SOURCE_CHANGED_DURING_RUN"
    except BaseException:
        report["error"] = traceback.format_exc()
    finally:
        hooks.close()
        atomic_json(out / "cpu-boundaries.json", cpu_boundaries)
        atomic_json(out / "report.json", report)
        if app:
            gc.collect()
            atomic_json(out / "preclose-stages.json", stages)
            atomic_json(out / "closing-ready.json", dict(**identity, pid=os.getpid()))
            deadline = time.monotonic() + 15
            while not (out / "host-quiesced.json").exists():
                if time.monotonic() >= deadline:
                    raise TimeoutError("OBSERVER_CLOSE_QUIESCENCE_NOT_CONFIRMED")
                time.sleep(0.01)
            ack = json.loads((out / "host-quiesced.json").read_text(encoding="utf-8"))
            if (
                any(ack.get(key) != value for key, value in identity.items())
                or ack.get("worker_pid") != os.getpid()
            ):
                raise ValueError("CLOSE_QUIESCENCE_IDENTITY_MISMATCH")
            close_began = time.perf_counter()
            app.close()
            stages["close_s"] = time.perf_counter() - close_began
        report["closed"] = True
        report["process_exit_strategy"] = (
            "EXPLICIT_EXIT_AFTER_FULL_KIT_CLOSE_RETURN" if app else "NORMAL_CPYTHON_EXIT"
        )
        stages["total_s"] = time.perf_counter() - started
        stages = {k: v for k, v in stages.items() if not k.endswith("counter")}
        atomic_json(out / "stages.json", stages)
        atomic_json(out / "report.json", report)
    code = 0 if report["status"] == "PASS" else 1
    print(
        json.dumps(dict(status=report["status"], stages=stages, error=report.get("error"))),
        flush=True,
    )
    if app:
        sys.stdout.flush()
        sys.stderr.flush()
        os._exit(code)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
