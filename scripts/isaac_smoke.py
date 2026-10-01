"""S03: real Isaac Sim 6.1 smoke check; run with its standalone interpreter.

CPU CI checks the pure callback contract without importing Isaac. Runtime success
requires a completed result and zero exit. Output is local evidence, not a public log.
"""

import argparse
import hashlib
import json
import os
import platform
import sys
import time
import traceback
from pathlib import Path


def write_json(path, value):
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, indent=2, allow_nan=False)
        stream.write("\n")


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def check_step_callbacks(records, expected_step, expected_time, dt):
    """Reject missing, duplicate, stale or mistimed observations of one step."""
    require(len(records) == 1, "Expected exactly one callback for this physics step")
    record = records[0]
    require(record["physics_step"] == expected_step, "Callback physics step mismatch")
    require(abs(record["simulation_time"] - expected_time) < 1e-4, "Callback time mismatch")
    require(abs(record["dt"] - dt) < 1e-6, "Unexpected callback dt")


def run_scene(app, args, output):
    # Kit must be initialized before importing any simulation modules.
    import isaacsim.core.experimental.utils.app as app_utils
    import isaacsim.core.experimental.utils.stage as stage_utils
    import numpy as np
    from isaacsim.core.experimental.objects import Cube, GroundPlane
    from isaacsim.core.experimental.prims import GeomPrim, RigidPrim
    from isaacsim.core.simulation_manager import IsaacEvents, SimulationManager

    stage_utils.create_new_stage()
    GroundPlane("/World/Ground")
    paths = [f"/World/Box_{i:03d}" for i in range(args.bodies)]
    positions = np.array([[i % 8, i // 8, 1.5] for i in range(args.bodies)])
    Cube(paths, positions=positions, sizes=0.25)
    GeomPrim(paths, apply_collision_apis=True)
    bodies = RigidPrim(paths)
    bodies.set_default_state(
        positions=positions,
        orientations=[1, 0, 0, 0],
        linear_velocities=[0, 0, 0],
        angular_velocities=[0, 0, 0],
    )
    require(SimulationManager.get_active_physics_engine() == "physx", "Expected PhysX")
    SimulationManager.set_physics_dt(1 / 60)
    SimulationManager.set_device("cpu")

    def state():
        pose, orientation = bodies.get_world_poses()
        linear, angular = bodies.get_velocities()
        values = [item.numpy().copy() for item in (pose, orientation, linear, angular)]
        require(all(np.isfinite(item).all() for item in values), "Nonfinite state")
        return values

    def delta(left, right):
        return max(float(np.max(np.abs(a - b))) for a, b in zip(left, right, strict=True))

    cycles = []
    reference = None
    with (output / "states.jsonl").open("x", encoding="utf-8", newline="\n") as log:
        for cycle in range(args.cycles):
            if cycle:
                app_utils.stop()
            app_utils.play()
            app.update()  # Let Kit initialize physics/tensor views; excluded warmup.
            app_utils.pause()
            bodies.reset_to_default_state()
            initial = state()
            expected = [
                positions,
                np.tile([1, 0, 0, 0], (args.bodies, 1)),
                np.zeros((args.bodies, 3)),
                np.zeros((args.bodies, 3)),
            ]
            reset_error = delta(initial, expected)
            require(reset_error <= 1e-5, "Reset did not restore pose and velocity")
            log.write(
                json.dumps(
                    {"cycle": cycle, "kind": "reset", "state": [item.tolist() for item in initial]}
                )
                + "\n"
            )
            samples = []
            callback_errors = []
            callback_records = []

            def observe(dt, context):
                try:
                    sample = state()
                    record = {
                        "physics_step": SimulationManager.get_num_physics_steps(),
                        "simulation_time": SimulationManager.get_simulation_time(),
                        "dt": float(dt),
                    }
                    samples.append(sample)
                    callback_records.append(record)
                except Exception:
                    callback_errors.append(traceback.format_exc())

            callback = SimulationManager.register_callback(observe, IsaacEvents.POST_PHYSICS_STEP)
            start_time = SimulationManager.get_simulation_time()
            start_steps = SimulationManager.get_num_physics_steps()
            started = time.perf_counter()
            try:
                for index in range(args.steps):
                    before = len(callback_records)
                    SimulationManager.step()
                    require(not callback_errors, str(callback_errors))
                    check_step_callbacks(
                        callback_records[before:],
                        start_steps + index + 1,
                        start_time + (index + 1) / 60,
                        1 / 60,
                    )
                duration = time.perf_counter() - started
                require(not callback_errors, str(callback_errors))
                require(len(samples) == args.steps, "Missing or duplicated physics callbacks")
                require(
                    SimulationManager.get_num_physics_steps() - start_steps == args.steps,
                    "Unexpected physics step count",
                )
                elapsed = SimulationManager.get_simulation_time() - start_time
                require(abs(elapsed - args.steps / 60) < 1e-4, "Simulation time mismatch")
                final = state()
                require(delta(final, samples[-1]) <= 1e-5, "Callback and direct state differ")
                require(np.all(samples[29][0][:, 2] < 1.0), "Gravity did not move all bodies")
                require(np.all(np.abs(final[0][:, 2] - 0.125) < 0.02), "Ground contact failed")
                require(float(np.max(np.abs(final[2]))) < 0.05, "Bodies did not settle")
                repeat_error = (
                    0.0
                    if reference is None
                    else max(delta(a, b) for a, b in zip(samples, reference, strict=True))
                )
                require(repeat_error <= 1e-4, "Reset replay differs from first trajectory")
                if reference is None:
                    reference = samples
                cycles.append(
                    {
                        "cycle": cycle,
                        "callbacks": len(samples),
                        "start_physics_step": start_steps,
                        "start_simulation_time": start_time,
                        "simulation_seconds": elapsed,
                        "step_wall_seconds": duration,
                        "reset_max_abs_error": reset_error,
                        "trajectory_max_abs_error": repeat_error,
                        "final_z_min": float(final[0][:, 2].min()),
                        "final_z_max": float(final[0][:, 2].max()),
                    }
                )
            finally:
                SimulationManager.deregister_callback(callback)
                # Keep partial observations on failure, without relabeling missing steps.
                for sample, record in zip(samples, callback_records, strict=True):
                    log.write(
                        json.dumps(
                            {
                                "cycle": cycle,
                                "kind": "post_physics_step",
                                "step": record["physics_step"] - start_steps,
                                **record,
                                "state": [item.tolist() for item in sample],
                            }
                        )
                        + "\n"
                    )
                log.flush()
        app_utils.stop()
        app.update()
        require(app_utils.is_stopped(), "Timeline failed to stop")
    return {
        "cycles": cycles,
        "physics_engine": "physx",
        "physics_device": "cpu",
        "headless": True,
        "render_resolution": [640, 480],
        "render_during_measured_steps": False,
        "dt": 1 / 60,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="New local evidence directory")
    parser.add_argument("--bodies", type=int, choices=range(1, 65), default=1)
    parser.add_argument("--cycles", type=int, choices=range(3, 11), default=3)
    parser.add_argument("--steps", type=int, choices=range(180, 601), default=240)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    write_json(
        output / "started.json",
        {
            "pid": os.getpid(),
            "python": platform.python_version(),
            "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "bodies": args.bodies,
            "cycles": args.cycles,
            "steps": args.steps,
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
                "width": 640,
                "height": 480,
                "multi_gpu": False,
                "fast_shutdown": False,
                "enable_crashreporter": False,
            }
        )
        result["startup_seconds"] = time.perf_counter() - started
        result.update(run_scene(app, args, output))
        result["status"] = "PASSED"
    except Exception:
        result["error"] = traceback.format_exc()
        traceback.print_exc()
    finally:
        if app is not None:
            try:
                app.close()
                result["closed"] = True
            except Exception:
                result["status"] = "FAILED"
                result["close_error"] = traceback.format_exc()
        result["wall_seconds"] = time.perf_counter() - started
        write_json(output / "result.json", result)
    print(json.dumps(result, allow_nan=False), flush=True)
    return 0 if result["status"] == "PASSED" and result["closed"] else 1


if __name__ == "__main__":
    sys.exit(main())
