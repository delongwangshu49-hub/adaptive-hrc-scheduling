"""S13 original building scene and real Isaac evidence. Use Isaac's Python wrapper."""

import argparse
import asyncio
import hashlib
import json
import math
import os
import statistics
import subprocess
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def save(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def resources():
    """Local-only measurements; whole-card GPU use includes other processes."""
    import ctypes
    from ctypes import wintypes

    class Memory(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD), ("faults", wintypes.DWORD)] + [
            (n, ctypes.c_size_t)
            for n in (
                "peak_rss",
                "rss",
                "peak_pool",
                "pool",
                "peak_nonpool",
                "nonpool",
                "pagefile",
                "peak_pagefile",
                "private",
            )
        ]

    result = {}
    if sys.platform == "win32":
        mem = Memory()
        mem.cb = ctypes.sizeof(mem)
        kernel = ctypes.WinDLL("kernel32")
        kernel.GetCurrentProcess.restype = wintypes.HANDLE
        api = ctypes.WinDLL("psapi")
        api.GetProcessMemoryInfo.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(Memory),
            wintypes.DWORD,
        ]
        if api.GetProcessMemoryInfo(
            kernel.GetCurrentProcess(), ctypes.byref(mem), ctypes.sizeof(mem)
        ):
            result.update(rss=mem.rss, private=mem.private)
    query = subprocess.run(
        ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
        capture_output=True,
        text=True,
        timeout=10,
        check=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    result["whole_card_gpu_mib"] = [int(x) for x in query.stdout.splitlines()]
    processes = subprocess.run(
        ["nvidia-smi", "--query-compute-apps=pid,used_gpu_memory", "--format=csv,noheader,nounits"],
        capture_output=True,
        text=True,
        timeout=10,
        check=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    own = [
        line.split(",", 1)[1].strip()
        for line in processes.stdout.splitlines()
        if line.split(",", 1)[0].strip() == str(os.getpid())
    ]
    result["process_gpu_mib"] = (
        int(own[0]) if own and own[0].isdigit() else "UNAVAILABLE_NVIDIA_SMI"
    )
    return result


def run(app, args, out):
    import isaacsim.core.experimental.utils.app as app_utils
    import isaacsim.core.experimental.utils.stage as stage_utils
    import omni.usd
    from isaacsim.core.experimental.prims import RigidPrim
    from isaacsim.core.simulation_manager import IsaacEvents, SimulationManager
    from omni.kit.viewport.utility import capture_viewport_to_file, get_active_viewport
    from pxr import UsdGeom

    from sim.isaac.scene.model import FIXTURES, POSES, Transfer, fk, load_config, require
    from sim.isaac.scene.usd_scene import BuildingScene

    config = load_config(ROOT / "examples/building_contracts/configuration.json")
    stage_utils.create_new_stage()
    stage = omni.usd.get_context().get_stage()
    if args.mode == "load" and args.load == "L0":
        import importlib
        import importlib.util

        require(args.baseline_source is not None, "L0_REQUIRES_SEALED_BASELINE_SOURCE")
        folder = args.baseline_source.resolve() / "sim/isaac/scene"
        spec = importlib.util.spec_from_file_location(
            "_s13_l0", folder / "__init__.py", submodule_search_locations=[str(folder)]
        )
        module = importlib.util.module_from_spec(spec)
        sys.modules["_s13_l0"] = module
        spec.loader.exec_module(module)
        baseline = importlib.import_module("_s13_l0.usd_scene")
        scene = baseline.BuildingScene(stage, config, args.fixture)
        save(
            out / "baseline-source.json",
            {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in folder.glob("*.py")},
        )
    else:
        scene = BuildingScene(stage, config, args.fixture)
    counts = scene.mapping_check()
    SimulationManager.set_physics_dt(1 / 60)
    SimulationManager.set_device("cpu")
    import carb

    carb.settings.get_settings().set("/app/viewport/grid/enabled", False)
    viewport = get_active_viewport()
    require(viewport is not None, "NO_VIEWPORT")
    viewport.set_texture_resolution((1920, 1080))
    viewport.camera_path = "/World/Cameras/Overview"
    for _ in range(15):
        app.update()
    stage.Export(str(out / "scene.usda"))

    def capture(name, camera):
        import numpy as np
        from PIL import Image

        # Consume deletion notices before selecting a re-created camera.
        for _ in range(5):
            app.update()
        viewport.camera_path = "/World/Cameras/" + camera
        for prim in scene.stage.GetPrimAtPath("/World/Cameras").GetChildren():
            hud = UsdGeom.Imageable(scene.stage.GetPrimAtPath(str(prim.GetPath()) + "/HUD"))
            if prim.GetName() == camera:
                hud.MakeVisible()
            else:
                hud.MakeInvisible()
        started = time.perf_counter()
        for _ in range(60):
            app.update()
        require(str(viewport.camera_path) == "/World/Cameras/" + camera, "CAPTURE_CAMERA_CHANGED")
        expected_view = scene.world_matrix("/World/Cameras/" + camera).GetInverse()
        view_error = max(
            abs(viewport.frame_info["view"][i * 4 + j] - expected_view[i][j])
            for i in range(4)
            for j in range(4)
        )
        require(view_error <= 1e-4, "CAPTURE_VIEW_MISMATCH")
        task = asyncio.ensure_future(
            capture_viewport_to_file(viewport, str(out / (name + ".png"))).wait_for_result()
        )
        while not task.done() and time.perf_counter() - started < 30:
            app.update()
        require(task.done(), "CAPTURE_TIMEOUT")
        task.result()
        # The viewport future precedes asynchronous image encoding in this RC build.
        # Require a complete PNG terminator instead of assuming the future flushed disk.
        file = out / (name + ".png")
        while time.perf_counter() - started < 30:
            if file.is_file() and file.read_bytes().endswith(b"IEND\xaeB`\x82"):
                break
            app.update()
        require((out / (name + ".png")).is_file(), "CAPTURE_MISSING")
        require(file.read_bytes().endswith(b"IEND\xaeB`\x82"), "CAPTURE_INCOMPLETE")
        with Image.open(file) as im:
            require(im.size == (1920, 1080), "CAPTURE_RESOLUTION")
            pixels = np.asarray(im.convert("RGB"))[:850].astype(float)
            colored = float(np.mean(pixels.max(axis=2) - pixels.min(axis=2) > 20))
            white = float(np.mean(pixels.min(axis=2) > 245))
            require(colored > 0.01 and white < 0.9, "CAPTURE_EMPTY_TRANSITION")
        return {
            "name": name,
            "camera": camera,
            "view_matrix_error": view_error,
            "colored_fraction_above_banner": colored,
            "seconds": time.perf_counter() - started,
            "sha256": hashlib.sha256((out / (name + ".png")).read_bytes()).hexdigest(),
        }

    screenshots = [capture("overview", "Overview"), capture("top", "Top")]
    if args.mode == "trials":
        from sim.isaac.scene.revision_checks import verify_trials

        report = verify_trials(scene, app, capture, lambda name, data: save(out / name, data))
        return {"verification": "T1_T4_REAL_USD", "trials": report}
    if args.mode == "load":
        from sim.isaac.scene.revision_checks import measure_load

        return {
            "verification": "LOAD_MEASUREMENT",
            "load": measure_load(scene, app, viewport, args.load, out, resources),
        }
    if args.mode == "preview":
        return {"counts": counts, "screenshots": screenshots, "verification": "PREVIEW_ONLY"}
    if args.mode == "inspection":
        from sim.isaac.scene.inspection import run_inspection

        report = run_inspection(
            scene, app, capture, lambda r: save(out / "inspection-partial.json", r)
        )
        save(out / "inspection.json", report)
        return {
            "counts": scene.mapping_check(),
            "verification": "SPACE_INSPECTION_ONLY",
            "screenshots": screenshots + report["screenshots"],
        }
    cycles = []
    fixture_snapshots = {}
    trajectory_reference = {}
    capture_views = {
        "dual_frame": "J2",
        "joining": "J3",
        "structure": "J3",
        "mep_wait": "F1",
        "sr_w2": "F1",
        "quarantine": "Q1",
        "outbound": "OUT1",
        "manual_weld": "J2",
        "robot_demo": "Robot",
    }
    with (out / "steps.jsonl").open("w", encoding="utf-8") as trace:
        for fixture in FIXTURES:
            for cycle in range(3):
                app_utils.stop()
                app.update()
                scene.reset(fixture)
                scene.mapping_check()
                viewport.camera_path = "/World/Cameras/" + capture_views.get(fixture, "Overview")
                initial = {k: scene.scene_position(v) for k, v in scene.mapping.items()}
                initial["TCP"] = scene.scene_position(scene.tcp_path)
                for jp, angle in zip(scene.joint_paths, POSES[0]):
                    require(
                        UsdGeom.Xformable(scene.stage.GetPrimAtPath(jp))
                        .GetOrderedXformOps()[1]
                        .Get()
                        == angle,
                        "RESET_JOINT",
                    )
                if cycle == 0:
                    fixture_snapshots[fixture] = initial
                error = max(math.dist(initial[k], fixture_snapshots[fixture][k]) for k in initial)
                require(error <= 1e-5, "RESET_POSITION")
                require(
                    scene.state.route is None and scene.state.quality == "UNKNOWN", "RESET_STATE"
                )
                app_utils.play()
                app.update()
                app_utils.pause()
                # Warmup may advance a variable number of ticks. Reset both pose
                # and velocity through PhysX after initialization, as in S03.
                probe = RigidPrim("/World/ContactProbe")
                probe.set_default_state(
                    positions=[[15, 32, 1.4]],
                    orientations=[[1, 0, 0, 0]],
                    linear_velocities=[[0, 0, 0]],
                    angular_velocities=[[0, 0, 0]],
                )
                probe.reset_to_default_state()
                pose, orientation = probe.get_world_poses()
                linear, angular = probe.get_velocities()
                require(abs(float(pose.numpy()[0][2]) - 1.4) <= 1e-5, "RESET_PHYSICS_POSE")
                require(
                    max(abs(float(v)) for array in (linear, angular) for v in array.numpy()[0])
                    <= 1e-5,
                    "RESET_PHYSICS_VELOCITY",
                )
                records = []

                def callback(dt, context):
                    records.append(
                        {
                            "dt": float(dt),
                            "step": SimulationManager.get_num_physics_steps(),
                            "time": SimulationManager.get_simulation_time(),
                            # PhysX tensor state is authoritative in its callback;
                            # USD publication occurs later in the frame in this RC.
                            "probe": probe.get_world_poses()[0].numpy()[0].tolist(),
                        }
                    )

                handle = SimulationManager.register_callback(
                    callback, IsaacEvents.POST_PHYSICS_STEP
                )
                start_steps = SimulationManager.get_num_physics_steps()
                start_time = SimulationManager.get_simulation_time()
                samples = []
                try:
                    for i in range(240):
                        q = [
                            a + (b - a) * (1 - math.cos(2 * math.pi * i / 239)) / 2
                            for a, b in zip(POSES[0], POSES[1])
                        ]
                        scene.set_joints(q)
                        SimulationManager.step()
                        require(len(records) == i + 1, "CALLBACK_COUNT")
                        record = records[-1]
                        require(
                            record["step"] == start_steps + i + 1
                            and abs(record["time"] - start_time - (i + 1) / 60) < 1e-4
                            and abs(record["dt"] - 1 / 60) < 1e-6,
                            "CALLBACK_CLOCK",
                        )
                        samples.append(record["probe"])
                        trace.write(
                            json.dumps({"fixture": fixture, "cycle": cycle, "i": i, **record})
                            + "\n"
                        )
                finally:
                    SimulationManager.deregister_callback(handle)
                require(abs(samples[-1][2] - 0.15) < 0.02, "DYNAMIC_GROUND_CONTACT")
                if cycle == 0:
                    trajectory_reference[fixture] = samples
                replay_error = max(
                    math.dist(a, b) for a, b in zip(samples, trajectory_reference[fixture])
                )
                require(replay_error <= 1e-4, "RESET_REPLAY")
                cycles.append(
                    {
                        "fixture": fixture,
                        "cycle": cycle,
                        "callbacks": len(records),
                        "reset_error_m": error,
                        "replay_error_m": replay_error,
                        "final_probe_z": samples[-1][2],
                    }
                )
                app_utils.stop()
                app.update()
                if cycle == 0 and fixture in capture_views:
                    screenshots.append(capture(fixture, capture_views[fixture]))
                save(out / "cycles-partial.json", cycles)
    # Independent numerical FK vs the USD hierarchy, including orientation.
    scene.reset("robot_demo")
    robot = []
    for pose in POSES:
        scene.set_joints(pose)
        expected, _ = fk(pose)
        actual = scene.scene_matrix(scene.tcp_path)
        pos_error = math.dist(
            [expected[k][3] for k in range(3)], tuple(actual.ExtractTranslation())
        )
        cosine = (sum(expected[i][j] * actual[j][i] for i in range(3) for j in range(3)) - 1) / 2
        angle = math.degrees(math.acos(max(-1, min(1, cosine))))
        require(pos_error <= 0.001 and angle <= 0.1, "USD_TCP_FK")
        robot.append(
            {"angles_deg": pose, "position_error_m": pos_error, "orientation_error_deg": angle}
        )
    # Full-size module move: real USD world pose readback, source is not duplicated.
    scene.reset("structure")
    product = scene.mapping[scene.state.product_id]
    move = Transfer("CR1", (36, 10, 0.6), (36, 24, 0.6), (6, 3, 3.8), 8, 1)
    move.attach()
    scene.set_crane(move.source)
    screenshots.append(capture("cr1_source", "J3"))
    path_samples = []
    for i in range(241):
        pos = move.sample(i / 240)
        scene.set_position(product, pos)
        scene.set_crane(pos)
        actual = scene.scene_position(product)
        require(math.dist(pos, actual) <= 0.01, "USD_MOVE_READBACK")
        path_samples.append(
            {"fraction": i / 240, "commanded": pos, "actual": actual, "state": move.state}
        )
        if i % 4 == 0:
            app.update()
    move.land(scene.scene_position(product))
    move.detach()
    screenshots.append(capture("cr1_target", "F1"))
    screenshots.append(capture("gantry", "Gantry"))
    screenshots.append(capture("rigging", "Rigging"))
    save(out / "transfer.json", path_samples)
    from sim.isaac.scene.inspection import run_inspection

    inspection = run_inspection(
        scene, app, capture, lambda r: save(out / "inspection-partial.json", r)
    )
    save(out / "inspection.json", inspection)
    screenshots.extend(inspection["screenshots"])
    # Performance includes complete scene, physics step and actual viewport updates.
    scene.reset("sr_w2")
    viewport.camera_path = "/World/Cameras/Overview"
    app_utils.play()
    app.update()
    app_utils.pause()
    for _ in range(30):
        SimulationManager.step()
        app.update()
    frames = []
    started = time.perf_counter()
    render_before = dict(viewport.frame_info)
    while time.perf_counter() - started < 60.1:
        t = time.perf_counter()
        SimulationManager.step()
        app.update()
        frames.append((time.perf_counter() - t) * 1000)
    render_after = dict(viewport.frame_info)
    require(render_after["frame_number"] > render_before["frame_number"], "NO_RENDERED_FRAMES")
    save(
        out / "render-frame-info.json",
        {
            "before": {k: str(v) for k, v in render_before.items()},
            "after": {k: str(v) for k, v in render_after.items()},
        },
    )
    app_utils.stop()
    app.update()
    save(out / "frame-times-ms.json", frames)
    reset_times = []
    for i in range(10):
        t = time.perf_counter()
        scene.reset("sr_w2")
        for _ in range(5):
            app.update()
        reset_times.append(
            {
                "reset": i,
                "seconds": time.perf_counter() - t,
                "monotonic": time.perf_counter(),
                **scene.mapping_check(),
                **resources(),
            }
        )
    save(out / "reset-times.json", reset_times)
    stage.Export(str(out / "scene.usda"))
    bbox = (
        UsdGeom.BBoxCache(0, ["default", "render", "proxy"])
        .ComputeWorldBound(
            stage.GetPrimAtPath(scene.mapping[scene.state.product_id] + "/Occupancy")
        )
        .ComputeAlignedRange()
    )
    require(
        max(abs(a - b) for a, b in zip(bbox.GetSize(), (6, 3, 3.2))) <= 0.001, "MODULE_ENVELOPE"
    )
    return {
        "counts": scene.mapping_check(),
        "input_sha256": config["source_sha256"],
        "cycles": cycles,
        "robot": robot,
        "screenshots": screenshots,
        "resets": reset_times,
        "performance": {
            "duration_seconds": sum(frames) / 1000,
            "frames": len(frames),
            "median_ms": statistics.median(frames),
            "p95_ms": sorted(frames)[int(len(frames) * 0.95)],
            "max_ms": max(frames),
            "target_met": statistics.median(frames) <= 33.3,
            "resolution": [1920, 1080],
            "physics": "CPU PhysX",
            "render_updates": True,
            "renderer": "RayTracedLighting",
            "render_frame_counter_delta": render_after["frame_number"]
            - render_before["frame_number"],
        },
        "scope": "S13_SYNTHETIC_GEOMETRY_KINEMATICS_NO_PRODUCTION_RECEIPTS",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--mode", choices=("preview", "inspection", "verify", "trials", "load"), default="verify"
    )
    parser.add_argument("--fixture", default="mep_wait")
    parser.add_argument("--baseline-source", type=Path)
    parser.add_argument("--load", choices=("L0", "L1", "L2"), default="L1")
    args = parser.parse_args()
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    os.environ.setdefault("WARP_CACHE_PATH", str(out / "warp-cache"))
    save(
        out / "started.json",
        {
            "pid": os.getpid(),
            "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "monotonic_started": time.perf_counter(),
        },
    )
    app = None
    result = {"status": "FAILED", "closed": False}
    started = time.perf_counter()
    try:
        from isaacsim import SimulationApp

        app = SimulationApp(
            {
                "headless": True,
                "width": 1920,
                "height": 1080,
                "multi_gpu": False,
                "fast_shutdown": False,
                "enable_crashreporter": False,
                "renderer": "RayTracedLighting",
            }
        )
        result["startup_seconds"] = time.perf_counter() - started
        runtime_root = os.environ.get("ISAAC_SIM_ROOT")
        result["isaac_version"] = (
            (Path(runtime_root) / "VERSION").read_text(encoding="utf-8").strip()
            if runtime_root
            else "UNKNOWN"
        )
        result.update(run(app, args, out))
        result["status"] = "PASSED"
        save(out / "before-close.json", result)
    except Exception:
        result["error"] = traceback.format_exc()
        traceback.print_exc()
        save(out / "before-close.json", result)
    finally:
        if app is not None:
            try:
                app.close()
                result["closed"] = True
            except Exception:
                result["status"] = "FAILED"
                result["close_error"] = traceback.format_exc()
        result["wall_seconds"] = time.perf_counter() - started
        save(out / "result.json", result)
    return 0 if result["status"] == "PASSED" and result["closed"] else 1


if __name__ == "__main__":
    sys.exit(main())
