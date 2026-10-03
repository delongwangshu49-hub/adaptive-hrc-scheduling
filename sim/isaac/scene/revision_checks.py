"""Real USD evidence for r4 scope, separate from production simulation."""

import copy
import json
import statistics
import time

from .layout import layout_comparison, person_home
from .model import POSES, require
from .trial_scene import TrialScene, check_person_routes
from .trials import TRIALS, validate_placements


def verify_trials(scene, app, capture, save):
    report = {"trials": [], "negatives": [], "layout": layout_comparison()}

    def reject(name, callback, reason):
        try:
            callback()
        except ValueError as exc:
            require(reason in str(exc), "WRONG_NEGATIVE:" + str(exc))
            report["negatives"].append({"case": name, "reason": str(exc)})
        else:
            raise ValueError("NEGATIVE_ACCEPTED:" + name)

    for name in TRIALS:
        trial = TrialScene(scene, name)
        initial = trial.readback()
        trial.run.paused = True
        before = trial.run.snapshot()
        trial.advance(1)
        require(before == trial.run.snapshot(), "PAUSE_CHANGED_STATE")
        trial.advance(0.1, single_step=True)
        require(trial.run.elapsed == 0.1, "SINGLE_STEP:" + str(trial.run.blocked))
        trial.run.paused = False
        # Test speed against the same inspection clock, not production duration.
        trial.run.speed = 4
        t = trial.run.elapsed
        trial.advance(0.1)
        require(abs(trial.run.elapsed - t - 0.4) < 1e-8, "SPEED_CONTROL")
        trial.run.speed = 1
        injected = False
        captured = set()
        for _ in range(20000):
            action = trial.run.action
            if not action:
                break
            # A material, person, tool or target obstruction is an actual collider.
            fault_phase = (
                name == "T1"
                or (name == "T2" and action.equipment == "CR1")
                or (name == "T3" and action.actor == "WELD1")
                or (name == "T4" and action.equipment == "CR1")
            )
            if action.points and fault_phase and not injected:
                kind = {
                    "T1": "handoff_occupied",
                    "T2": "person",
                    "T3": "tool",
                    "T4": "target_occupied",
                }[name]
                trial.inject(kind)
                previous = copy.deepcopy(trial.run.positions)
                t = trial.run.elapsed
                trial.advance(0.5)
                require(
                    trial.run.status == "BLOCKED" and "COLLISION" in trial.run.blocked,
                    "FAULT_NOT_REJECTED:" + name,
                )
                require(
                    trial.run.positions == previous and trial.run.elapsed == t, "BLOCK_MOVED_ACTOR"
                )
                report["negatives"].append({"case": name + "_" + kind, "reason": trial.run.blocked})
                capture(
                    name.lower() + "_blocked",
                    {"T1": "PRE", "T2": "J3", "T3": "Weld", "T4": "F1"}[name],
                )
                trial.clear_fault()
                injected = True
            action_index = trial.run.index
            snapshot = trial.advance(0.5)
            require(
                snapshot["status"] != "BLOCKED",
                name + ":" + action.label + ":" + str(snapshot["blocked"]),
            )
            if trial.run.index != action_index:
                if action.actor == "SCN-MEP-BATCH":
                    capture("f1_delivery", "F1")
                if action.label.startswith("RIG AT SOURCE"):
                    capture("t2_rigging", "J3")
                if action.label.startswith("PEOPLE CLEAR"):
                    capture("t2_people_clear", "J3")
            if trial.run.owners:
                resource = next(iter(trial.run.owners))
                key = name + "_duplicate_" + resource
                if key not in captured:
                    reject(key, lambda: trial.run.claim(resource, "OTHER_PRODUCT"), "RESOURCE_BUSY")
                    captured.add(key)
            if action.label not in captured and trial.run.part_elapsed >= action.seconds * 0.5:
                views = {"T1": "PRE", "T2": "J3", "T3": "Weld", "T4": "Overview"}
                if action.actor in ("SCN-MEP-BATCH", "TEST1") or "TEST1 HELD" in action.label:
                    views["T3"] = "F1"
                if (
                    action.equipment
                    or action.actor in ("WELD1", "SCN-MEP-BATCH")
                    or "HELD" in action.label
                ):
                    capture(name.lower() + f"_phase_{trial.run.index:02d}", views[name])
                captured.add(action.label)
            app.update()
        require(trial.run.status == "COMPLETE_GEOMETRY_ONLY", "TRIAL_NOT_COMPLETE:" + name)
        require(not trial.run.owners, "TRIAL_LOCK_LEAK")
        final = trial.run.snapshot()
        sample_count = len(trial.trace)
        save(name + "-trajectory.json", trial.trace)
        capture(
            name.lower() + "_complete",
            {"T1": "J2", "T2": "F1", "T3": "J3", "T4": "Overview"}[name],
        )
        # Visual layers must never remove collision APIs or change owners/state.
        counts = scene.mapping_check()
        for layer in ("routes", "roles", "envelopes"):
            trial.set_layers(layer, True)
            trial.set_layers(layer, False)
            require(counts == scene.mapping_check(), "LAYER_CHANGED_COLLIDERS")
        trial.restart()
        require(trial.readback() == initial, "TRIAL_IN_PLACE_RESET_READBACK")
        trial.load(name)
        require(trial.readback() == initial, "TRIAL_RESET_READBACK")
        report["trials"].append(
            {
                "trial": name,
                "final": final,
                "samples": sample_count,
                "fault_resumed": injected,
                "reset_equal": True,
                "control_checks": ["pause", "single_step", "speed", "reset", "layers"],
            }
        )
        save("trials-partial.json", report)
    # Capacity and cross-product logic is scene-only and deliberately separate.
    for zone, count in (("J2", 2), ("BUF", 3), ("Q1", 2), ("OUT1", 2)):
        data = {f"P{i}.BOTTOM": {"product": f"P{i}", "zone": zone} for i in range(count)}
        reject("capacity_" + zone, lambda data=data: validate_placements(data), "CAPACITY")
    reject(
        "cross_product_component",
        lambda: validate_placements({"P1.BOTTOM": {"product": "P2", "zone": "J2"}}),
        "CROSS_PRODUCT",
    )
    validate_placements(
        {"P1.BOTTOM": {"product": "P1", "zone": "J2"}, "P1.TOP": {"product": "P1", "zone": "J2"}}
    )
    report["person_routes"] = check_person_routes(scene, app, capture)
    scene.reset("initial")
    capture("supply", "Supply")
    capture("pre_input_output", "PRE")
    report["scope"] = "SCENE_ONLY_NO_PRODUCTION_EVENTS"
    save("trials.json", report)
    return report


def measure_load(scene, app, viewport, level, out, sample_resources, warmup=30, seconds=120):
    """Same measurement for baseline and revised scene, no inferred render FPS.

    frame_info's integer counter has no trustworthy per-frame timestamp. Store
    observed counter-change intervals with that limitation, never call them FPS.
    """
    from isaacsim.core.experimental.utils import app as app_utils
    from isaacsim.core.simulation_manager import IsaacEvents, SimulationManager
    from pxr import UsdGeom

    from .trial_scene import TrialScene

    scene.reset("sr_w2")
    trial = (
        TrialScene(scene, "T4")
        if level == "L2"
        else TrialScene(scene, "T1")
        if level == "L1"
        else None
    )
    viewport.camera_path = "/World/Cameras/Overview"
    viewport.set_texture_resolution((1920, 1080))
    app_utils.play()
    app.update()
    app_utils.pause()
    callbacks = [0]

    def callback(dt, ctx):
        callbacks[0] += 1

    handle = SimulationManager.register_callback(callback, IsaacEvents.POST_PHYSICS_STEP)
    durations = []
    intervals = []
    memory = []
    deadline = time.perf_counter() + warmup
    motion_time = 0.0

    def tick():
        nonlocal motion_time
        motion_time += 1 / 60
        if trial:
            if not trial.run.action:
                trial.restart()
            trial.run.speed = 4
            state = trial.advance(1 / 60)
            require(state["status"] != "BLOCKED", "LOAD_MOTION_BLOCKED:" + str(state["blocked"]))
        if level == "L2":
            import math

            from .inspection import obstacles
            from .model import sweep

            supply_path = "/World/LoadSupply"
            supply_points = (
                (-6, 27, 0.6),
                (-1, 27, 0.6),
                (-1, 32.5, 0.6),
                (43, 32.5, 0.6),
                (43, 27.5, 0.6),
                (40.5, 27.5, 0.6),
            )
            if not scene.stage.GetPrimAtPath(supply_path):
                scene.group(supply_path, supply_points[0])
                scene.shape(
                    supply_path + "/Carrier", (0, 0, 0.35), (1.2, 0.8, 0.7), "teal", collision=True
                )
                scene.attr(scene.stage.GetPrimAtPath(supply_path), "sceneId", "SCN-LOAD-SUPPLY")
                sweep(
                    [(x, y, z + 0.35) for x, y, z in supply_points],
                    (1.2, 0.8, 0.7),
                    obstacles(scene, [supply_path]),
                )
            f = (1 - math.cos(motion_time * 0.3)) * 0.5 * (len(supply_points) - 1)
            i = min(int(f), len(supply_points) - 2)
            v = f - i
            scene.set_position(
                supply_path,
                tuple(a + (b - a) * v for a, b in zip(supply_points[i], supply_points[i + 1])),
            )

            # 15 independent in-place/short north-lane walking agents; positions
            # spaced 1.5 m, amplitude .25 m, with actual capsule bounds retained.
            for i, p in enumerate(scene.config["people"]):
                x, y, z = person_home(i)
                scene.set_position(
                    scene.mapping[p["id"]], (x, y + 0.25 * math.sin(motion_time + i), z)
                )
            q = [
                a + (b - a) * (1 + math.sin(motion_time)) * 0.5 for a, b in zip(POSES[0], POSES[1])
            ]
            scene.set_joints(q)
        SimulationManager.step()
        app.update()

    try:
        while time.perf_counter() < deadline:
            tick()
        started = time.perf_counter()
        count_start = viewport.frame_info["frame_number"]
        cb_start = callbacks[0]
        last_counter = count_start
        last_change = started
        next_memory = started
        while time.perf_counter() - started < seconds:
            t = time.perf_counter()
            tick()
            now = time.perf_counter()
            durations.append((now - t) * 1000)
            counter = viewport.frame_info["frame_number"]
            if counter != last_counter:
                intervals.append((now - last_change) * 1000)
                last_change, last_counter = now, counter
            if now >= next_memory:
                memory.append({"elapsed": now - started, **sample_resources()})
                next_memory = now + 10
        elapsed = time.perf_counter() - started
        counter_delta = viewport.frame_info["frame_number"] - count_start
        callback_delta = callbacks[0] - cb_start
    finally:
        SimulationManager.deregister_callback(handle)
        app_utils.stop()
        app.update()

    def stats(values):
        return {
            "count": len(values),
            "median_ms": statistics.median(values),
            "p95_ms": sorted(values)[int(len(values) * 0.95)],
            "max_ms": max(values),
            "over_50ms": sum(v > 50 for v in values),
            "over_100ms": sum(v > 100 for v in values),
        }

    prims = list(scene.stage.Traverse())
    result = {
        "level": level,
        "warmup_seconds": warmup,
        "measurement_seconds": elapsed,
        "updates": stats(durations),
        "observed_counter_change_intervals": stats(intervals),
        "render_frame_counter_delta": counter_delta,
        "physics_callbacks": callback_delta,
        "actual_render_timestamps_available": False,
        "actual_frame_target": "UNVERIFIED",
        "process_gpu_mib": "UNAVAILABLE_WDDM",
        "memory_samples": memory,
        "counts": scene.mapping_check(),
        "meshes": sum(p.IsA(UsdGeom.Mesh) for p in prims),
        "imageables": sum(bool(UsdGeom.Imageable(p)) for p in prims),
        "moving_actor_set": []
        if level == "L0"
        else ["PRODUCT-1.BOTTOM", "P1", "Lrig", "Lsig", "HST1"]
        if level == "L1"
        else ["PRODUCT-1", "SCN-PRODUCT-2", "CR1", "R1", "SCN-LOAD-SUPPLY"]
        + [p["id"] for p in scene.config["people"]],
        "cycle_reset": "IN_PLACE_SAME_SCENE" if trial else "NONE",
        "movement_schedule": "SEQUENTIAL_T1"
        if level == "L1"
        else "T4_PLUS_15_PEOPLE_R1_SUPPLY"
        if level == "L2"
        else "STATIC_BASELINE_PHYSICS_PROBE",
        "resolution": [1920, 1080],
        "renderer": "RayTracedLighting",
        "physics": "CPU PhysX",
    }
    resets = []
    for i in range(10):
        t = time.perf_counter()
        if trial:
            trial.load("T4" if level == "L2" else "T1")
        else:
            scene.reset("sr_w2")
        # Same state and a fixed settling duration for each reset.
        while time.perf_counter() - t < 3:
            app.update()
        resets.append({"reset": i, "seconds": time.perf_counter() - t, **sample_resources()})
    result["resets"] = resets
    for metric in ("rss", "private"):
        values = [x[metric] for x in resets if metric in x]
        if len(values) == 10:
            result[metric + "_reset_diagnostic_trigger"] = (
                all(a < b for a, b in zip(values[-5:], values[-4:]))
                and values[-1] > values[0] * 1.1
            )
    for name, value in (
        ("load.json", result),
        ("update-times.json", durations),
        ("counter-intervals.json", intervals),
    ):
        (out / name).write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    return result
