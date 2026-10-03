"""Real Isaac R5 target verification/load measurement; no production feedback."""

import argparse
import asyncio
import hashlib
import os
import statistics
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from build_building_scene import resources, save  # noqa: E402


def run(app, args, out):
    import omni.usd
    from omni.kit.viewport.utility import capture_viewport_to_file, get_active_viewport
    from pxr import UsdPhysics

    from sim.isaac.scene.model import load_config, require
    from sim.isaac.scene.target_layout import PEOPLE, TASK_BY_ID, transfer_matrix, verify_task
    from sim.isaac.scene.target_scene import TargetScene, TargetTrialScene

    omni.usd.get_context().new_stage()
    scene = TargetScene(
        omni.usd.get_context().get_stage(),
        load_config(ROOT / "examples/building_contracts/configuration.json"),
    )
    trial = TargetTrialScene(scene)
    vp = get_active_viewport()
    import carb

    carb.settings.get_settings().set("/app/viewport/grid/enabled", False)
    vp.set_texture_resolution((1920, 1080))
    vp.camera_path = "/World/Cameras/Overview"
    shots = []

    def capture(name, camera):
        vp.camera_path = "/World/Cameras/" + camera
        for _ in range(40):
            app.update()
        task = asyncio.ensure_future(
            capture_viewport_to_file(vp, str(out / (name + ".png"))).wait_for_result()
        )
        deadline = time.perf_counter() + 30
        while not task.done() and time.perf_counter() < deadline:
            app.update()
        require(task.done(), "CAPTURE_TIMEOUT")
        task.result()
        p = out / (name + ".png")
        while time.perf_counter() < deadline and (
            not p.is_file() or not p.read_bytes().endswith(b"IEND\xaeB`\x82")
        ):
            app.update()
        require(p.is_file() and p.read_bytes().endswith(b"IEND\xaeB`\x82"), "CAPTURE_INCOMPLETE")
        view = scene.world_matrix("/World/Cameras/" + camera).GetInverse()
        error = max(
            abs(vp.frame_info["view"][i * 4 + j] - view[i][j]) for i in range(4) for j in range(4)
        )
        require(error < 1e-4, "CAPTURE_VIEW_MISMATCH")
        record = {
            "name": name,
            "camera": camera,
            "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
            "view_error": error,
        }
        shots.append(record)
        save(out / "screenshots.json", shots)
        return record

    for _ in range(20):
        app.update()
    counts = {
        "prims": sum(1 for _ in scene.stage.Traverse()),
        "colliders": sum(p.HasAPI(UsdPhysics.CollisionAPI) for p in scene.stage.Traverse()),
    }
    save(
        out / "sources.json",
        {
            p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in [*(ROOT / "sim/isaac/scene").glob("*.py"), Path(__file__)]
        },
    )
    scene.stage.Export(str(out / "scene.usda"))
    capture("target_overview", "Overview")
    capture("target_top", "Top")
    capture("target_fork", "Fork")
    capture("target_equipment", "Equipment")
    if args.mode == "load":
        return measure(scene, trial, app, vp, args.level, out, capture, counts)

    # Actual USD bounds, not the scene controller's pass bit.
    excluded = tuple(PEOPLE) + tuple(trial.run.kinds) + ("SCN-FORK-01", "SCN-CART-01", "TEST1")
    coverage = transfer_matrix(scene.actual_obstacles(excluded))
    save(out / "coverage.json", coverage)
    adjacent = []
    trial.load("T4")
    for task_id, neighbor in (
        ("F01", "SCN-FG-P2"),
        ("F02", "SCN-FG-P1"),
        ("F03", "SCN-FG-P2"),
        ("F04", "SCN-FG-P1"),
    ):
        ignore = (
            tuple(PEOPLE)
            + tuple(n for n in trial.run.kinds if n != neighbor)
            + ("SCN-FORK-01", "SCN-CART-01", "TEST1")
        )
        adjacent.append(verify_task(TASK_BY_ID[task_id], scene.actual_obstacles(ignore)))
    save(out / "adjacent-slots.json", adjacent)
    bench = {}
    for cache in (False, True):
        trial.load("T1")
        timing = []
        for _ in range(160):
            if not cache:
                trial._bounds_key = None
            started = time.perf_counter()
            trial.advance(1 / 60)
            timing.append((time.perf_counter() - started) * 1000)
            require(trial.run.blocked is None, "BENCH_BLOCKED")
            app.update()
        bench["phase_cache" if cache else "rebuild_bounds_each_update"] = {
            "median_ms": statistics.median(timing),
            "p95_ms": sorted(timing)[152],
            "samples": len(timing),
        }
    save(out / "bounds-benchmark.json", bench)
    trials = []
    for name in ("T1", "T2", "T3", "T4"):
        trial.load(name)
        for _ in range(5):
            app.update()
        ids = set(trial.run.positions)
        capture(
            name.lower() + "_initial",
            "Finished" if name == "T4" else "Supply" if name == "T1" else "Overview",
        )
        if name == "T4":
            trial.advance(1)
            require(
                trial.run.blocked == "WAIT_EXTERNAL_RECEIVER_BUFFER_FULL", "MISSING_BACKPRESSURE"
            )
            save(out / "buffer-full.json", trial.run.snapshot())
            trial.run.signal_external()
        photographed = set()
        while trial.run.action:
            a = trial.run.action
            index = trial.run.index
            for _ in range(8):
                trial.advance(a.seconds / 7)
                app.update()
                require(trial.run.blocked is None, f"{name}:{index}:{a.label}:{trial.run.blocked}")
                require(set(trial.run.positions) == ids, "IDENTITY_CHANGED")
                if trial.run.index != index:
                    break
                trigger = None
                camera = "Overview"
                if a.label.startswith("CARRY S01"):
                    trigger, camera = "steel_carried", "Supply"
                elif a.label.startswith("CARRY M01"):
                    trigger, camera = "module_carried", "Gantry"
                elif a.concurrent:
                    trigger, camera = "people_yield", "Crossing"
                elif a.label.startswith("LAND / RECEIVER HANDOFF P03"):
                    trigger, camera = "mep_handoff", "F1"
                elif a.label == "TEST DELIVER":
                    trigger, camera = "test_pushed", "Test"
                elif a.label.startswith("CARRY F03"):
                    trigger, camera = "buffer_moving_out", "Finished"
                if trigger and trigger not in photographed and trial.run.part >= a.seconds * 0.45:
                    capture(trigger, camera)
                    photographed.add(trigger)
            if a.label.startswith("LAND / RECEIVER HANDOFF F03"):
                capture("buffer_slot_freed", "Finished")
        capture(
            name.lower() + "_complete",
            "Finished" if name == "T4" else "Supply" if name == "T1" else "Overview",
        )
        require(trial.run.status == "COMPLETE_GEOMETRY_ONLY", "TRIAL_INCOMPLETE")
        save(out / (name + "-trace.json"), trial.trace)
        save(out / (name + "-events.json"), trial.run.events)
        save(out / (name + "-routes.json"), trial.run.routes)
        trials.append(
            {
                "trial": name,
                "phases": len(trial.run.phases),
                "readbacks": len(trial.trace),
                "status": trial.run.status,
                "ids": sorted(ids),
                "walk_routes": len(trial.run.routes),
                "final_slots": trial.run.slots,
            }
        )
        save(out / "trials.json", trials)

    negatives = []
    for fault, expected in (
        ("operator_missing", "OPERATOR_MISSING"),
        ("unreleased", "BATCH_NOT_RELEASED"),
        ("source_missing", "SOURCE_MISSING"),
        ("target_full", "TARGET_FULL"),
        ("obstacle", "COLLISION"),
        ("person", "COLLISION"),
        ("occupied", "COLLISION"),
    ):
        trial.load("T1")
        prefix = (
            "CARRY S01"
            if fault in ("obstacle", "person", "occupied")
            else "LOAD / CHECK SUPPORT S01"
        )
        while not trial.run.action.label.startswith(prefix):
            trial.advance(trial.run.action.seconds)
            require(trial.run.blocked is None, "NEGATIVE_SETUP:" + str(trial.run.blocked))
        before = trial.run.snapshot()
        trial.inject(fault)
        trial.advance(1)
        require(expected in (trial.run.blocked or ""), "NEGATIVE_ACCEPTED:" + fault)
        require(before["positions"] == trial.run.positions, "REJECT_MOVED_ACTOR")
        negatives.append({"case": fault, "reason": trial.run.blocked})
        trial.clear_fault()
        trial.advance(1)
        require(trial.run.blocked is None, "RESUME_FAILED")
    trial.load("T2")
    while not trial.run.action.label.startswith("EMPTY HOOK APPROACH"):
        trial.advance(trial.run.action.seconds)
    before = trial.run.snapshot()
    scene.shape("/World/BogieBlock", (40, 4, 1), (0.7, 0.7, 1.9), "red", collision=True)
    trial._bounds_key = None
    trial.advance(1)
    require("COLLISION:/World/BogieBlock" in (trial.run.blocked or ""), "BOGIE_BYPASS")
    require(before["positions"] == trial.run.positions, "BOGIE_REJECT_MOVED")
    negatives.append({"case": "empty_hook_bogie_block", "reason": trial.run.blocked})
    scene.stage.RemovePrim("/World/BogieBlock")
    trial._bounds_key = None
    trial.advance(1)
    require(trial.run.blocked is None, "BOGIE_RESUME_FAILED")
    trial.load("T2")
    scene.set_position(scene.mapping["Lop"], (55, 18, 0))
    trial.advance(1)
    require("TARGET_USD_READBACK:Lop" == trial.run.blocked, "USD_ROLE_DISPLACEMENT_NOT_REJECTED")
    negatives.append({"case": "usd_operator_displaced", "reason": trial.run.blocked})
    save(out / "negatives.json", negatives)
    trial.load("T4", combined=True)
    trial.run.signal_external()
    while trial.run.action:
        trial.advance(trial.run.action.seconds / 5)
        app.update()
        require(trial.run.blocked is None, "COMBINED:" + str(trial.run.blocked))
    save(out / "combined-trace.json", trial.trace)
    capture("combined_complete", "Finished")
    # Unique scene IDs; no target object impersonates a frozen domain resource.
    ids = [
        p.GetAttribute("s13:sceneId").Get()
        for p in scene.stage.Traverse()
        if p.GetAttribute("s13:sceneId")
    ]
    require(len(ids) == len(set(ids)), "DUPLICATE_SCENE_ID")
    require(
        not any(p.GetAttribute("s13:domainId") for p in scene.stage.Traverse()),
        "TARGET_DOMAIN_ID_LEAK",
    )
    return {
        "trials": trials,
        "negative_cases": negatives,
        "coverage_rows": len(coverage),
        "screenshots": shots,
        "counts": counts,
        "status": "PASSED",
    }


def measure(scene, trial, app, viewport, level, out, capture, counts):
    from isaacsim.core.experimental.utils import app as app_utils
    from isaacsim.core.simulation_manager import IsaacEvents, SimulationManager
    from pxr import UsdPhysics

    from sim.isaac.scene.model import require

    trial.load("T4" if level == "L2" else "T1", combined=level == "L2")
    if level == "L2":
        trial.run.signal_external()
    counts = {
        "prims": sum(1 for _ in scene.stage.Traverse()),
        "colliders": sum(p.HasAPI(UsdPhysics.CollisionAPI) for p in scene.stage.Traverse()),
    }
    app_utils.play()
    app.update()
    app_utils.pause()
    callbacks = [0]

    def callback(dt, ctx):
        callbacks[0] += 1

    handle = SimulationManager.register_callback(callback, IsaacEvents.POST_PHYSICS_STEP)

    cycles = 0

    def tick():
        nonlocal cycles
        if level != "L0":
            if not trial.run.action:
                # Explicit timeline restart, separately counted below.
                trial.restart()
                cycles += 1
                if level == "L2":
                    trial.run.signal_external()
            trial.advance(1 / 6)
            require(trial.run.blocked is None, "LOAD_BLOCKED:" + str(trial.run.blocked))
            trial.trace.clear()
        SimulationManager.step()
        app.update()

    warm = time.perf_counter()
    while time.perf_counter() - warm < 30:
        tick()
    updates, intervals, samples = [], [], []
    start = previous = last_sample = time.perf_counter()
    while time.perf_counter() - start < 120:
        now = time.perf_counter()
        if now - last_sample >= 10:
            samples.append({"seconds": now - start, **resources()})
            last_sample = time.perf_counter()
        t = time.perf_counter()
        tick()
        end = time.perf_counter()
        updates.append((end - t) * 1000)
        intervals.append((end - previous) * 1000)
        previous = end
    measured = time.perf_counter() - start
    SimulationManager.deregister_callback(handle)
    app_utils.stop()
    app.update()
    resets = []
    for i in range(10):
        t = time.perf_counter()
        trial.restart()
        for _ in range(20):
            app.update()
        resets.append({"reset": i + 1, "seconds": time.perf_counter() - t, **resources()})

    def stats(values):
        return {
            "median_ms": statistics.median(values),
            "p95_ms": sorted(values)[math_index(len(values), 0.95)],
            "max_ms": max(values),
            "over_50_ms": sum(v > 50 for v in values),
            "over_100_ms": sum(v > 100 for v in values),
            "samples": len(values),
        }

    result = {
        "explicit_timeline_restarts": cycles,
        "physics_callbacks": callbacks[0],
        "level": level,
        "warmup_seconds": 30,
        "measurement_seconds": measured,
        "application_update": stats(updates),
        "wall_intervals": stats(intervals),
        "resources": samples,
        "resets": resets,
        "actual_render_frame_time": "UNAVAILABLE_UNVERIFIED",
        "resolution": [1920, 1080],
        "counts": counts,
        "scope": "STATIC"
        if level == "L0"
        else "SINGLE_CHAIN"
        if level == "L1"
        else "B_PLUS_ONE_AND_CONCURRENT_CROSSING",
    }
    capture("load_" + level, "Overview")
    save(out / "load.json", result)
    save(out / "timings.json", {"application_update_ms": updates, "wall_intervals_ms": intervals})
    return result


def math_index(count, q):
    return min(count - 1, int(count * q))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--mode", choices=("verify", "load"), default="verify")
    parser.add_argument("--level", choices=("L0", "L1", "L2"), default="L0")
    args = parser.parse_args()
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    os.environ.setdefault("WARP_CACHE_PATH", str(out / "warp-cache"))
    save(out / "started.json", {"pid": os.getpid()})
    app = None
    result = {"status": "FAILED", "closed": False}
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
        result.update(run(app, args, out))
        result["status"] = "PASSED"
    except Exception:
        result["error"] = traceback.format_exc()
        traceback.print_exc()
    finally:
        save(out / "before-close.json", result)
        if app:
            app.close()
            result["closed"] = True
        save(out / "result.json", result)
    return 0 if result["status"] == "PASSED" and result["closed"] else 1


if __name__ == "__main__":
    sys.exit(main())
