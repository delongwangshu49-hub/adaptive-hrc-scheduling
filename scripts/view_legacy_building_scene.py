"""Portable S13 interactive scene review. Run with the existing Isaac Python wrapper."""

import argparse
import asyncio
import hashlib
import json
import os
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--self-test", action="store_true", help="Exercise the same UI callbacks, then close."
    )
    args = parser.parse_args()
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    # Per-session cache is a runtime output; the installed environment is unchanged.
    os.environ.setdefault("WARP_CACHE_PATH", str(out / "warp-cache"))

    def save(name, data):
        (out / name).write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )

    def log(action, **data):
        with (out / "actions.jsonl").open("a", encoding="utf-8") as f:
            f.write(
                json.dumps({"action": action, "wall_time": time.time(), **data}, ensure_ascii=False)
                + "\n"
            )

    save("started.json", {"pid": os.getpid(), "scope": "SCENE_REHEARSAL_NO_PRODUCTION"})
    app = None
    result = {"status": "FAILED", "closed": False}
    try:
        from isaacsim import SimulationApp

        app = SimulationApp(
            {
                "headless": False,
                "width": 1920,
                "height": 1080,
                "window_width": 1600,
                "window_height": 1000,
                "multi_gpu": False,
                "fast_shutdown": False,
                "enable_crashreporter": False,
                "renderer": "RayTracedLighting",
            }
        )
        import omni.kit.app
        import omni.ui as ui
        import omni.usd
        from omni.kit.viewport.utility import capture_viewport_to_file, get_active_viewport

        from sim.isaac.scene.layout import VERSION
        from sim.isaac.scene.model import FIXTURES, load_config, require
        from sim.isaac.scene.trial_scene import TrialScene
        from sim.isaac.scene.trials import TRIALS
        from sim.isaac.scene.usd_scene import BuildingScene

        omni.usd.get_context().new_stage()
        scene = BuildingScene(
            omni.usd.get_context().get_stage(),
            load_config(ROOT / "examples/building_contracts/configuration.json"),
        )
        trial = TrialScene(scene, "T1")
        trial.run.paused = True
        import carb

        carb.settings.get_settings().set("/app/viewport/grid/enabled", False)
        viewport = get_active_viewport()
        viewport.set_texture_resolution((1920, 1080))
        viewport.camera_path = "/World/Cameras/Overview"
        queue = []
        mode = "trial"
        message = "T1 loaded and PAUSED. Run or single-step to inspect."
        capture_task = None
        issue_count = 0
        last = time.perf_counter()
        last_save = 0
        layers = {"routes": True, "roles": True, "envelopes": False}

        async def save_issue(note):
            nonlocal issue_count, message
            issue_count += 1
            name = f"issue-{issue_count:03d}"
            trial.run.paused = True
            scene.stage.Export(str(out / (name + ".usda")))
            save(
                name + ".json",
                {
                    "note": note,
                    "layout": VERSION,
                    "mode": mode,
                    "state": trial.run.snapshot() if mode == "trial" else scene.state.snapshot(),
                    "actual_world": trial.readback()
                    if mode == "trial"
                    else {k: scene.world_position(v) for k, v in scene.mapping.items()},
                    "camera": str(viewport.camera_path),
                    "scene_fixture": scene.fixture,
                    "disclosure": "SCENE_REHEARSAL_PRODUCTION_FEEDBACK_NOT_CONNECTED",
                },
            )
            await capture_viewport_to_file(viewport, str(out / (name + ".png"))).wait_for_result()
            deadline = time.perf_counter() + 30
            while time.perf_counter() < deadline:
                p = out / (name + ".png")
                if p.is_file() and p.read_bytes().endswith(b"IEND\xaeB`\x82"):
                    break
                await omni.kit.app.get_app().next_update_async()
            else:
                raise RuntimeError("ISSUE_PNG_INCOMPLETE")
            message = "Saved " + name + " / PNG + USD + state + note"
            log("issue_saved", name=name)

        def enqueue(action, value=None):
            queue.append((action, value))

        def dispatch(action, value):
            nonlocal mode, message, capture_task
            if action in ("trial", "reset"):
                chosen = value if action == "trial" else trial.run.name
                if action == "reset" and mode == "trial":
                    trial.restart()
                else:
                    trial.load(chosen)
                trial.run.paused = True
                mode = "trial"
                for layer, visible in layers.items():
                    trial.set_layers(layer, visible)
                message = chosen + " RESET / new independent timeline / PAUSED"
            elif action == "pause":
                require(mode == "trial", "LOAD_A_TRIAL_FIRST")
                trial.run.paused = not trial.run.paused
            elif action == "step":
                require(mode == "trial", "LOAD_A_TRIAL_FIRST")
                trial.run.paused = True
                trial.advance(1 / 60, single_step=True)
            elif action == "speed":
                trial.run.speed = {1.0: 4.0, 4.0: 10.0, 10.0: 1.0}[trial.run.speed]
            elif action == "inject":
                trial.inject(value)
            elif action == "clear":
                trial.clear_fault()
                message = "Obstruction removed. Resume retains current positions and ownership."
            elif action == "duplicate":
                resource = next(iter(trial.run.owners), "WELD1")
                if resource not in trial.run.owners:
                    message = "Run to a held-resource phase first."
                else:
                    try:
                        trial.run.claim(resource, "SECOND_REQUEST")
                    except ValueError as exc:
                        message = "EXPECTED REJECTION / " + str(exc)
                        log("duplicate_rejected", reason=str(exc))
                    else:
                        raise ValueError("DUPLICATE_REQUEST_ACCEPTED")
            elif action == "fixture":
                trial.run.paused = True
                scene.reset(value)
                mode = "fixture"
                message = "FIXTURE RESET / " + value + " / independent static coverage view"
            elif action == "camera":
                viewport.camera_path = "/World/Cameras/" + value
                from pxr import UsdGeom

                for camera in scene.stage.GetPrimAtPath("/World/Cameras").GetChildren():
                    hud = UsdGeom.Imageable(
                        scene.stage.GetPrimAtPath(str(camera.GetPath()) + "/HUD")
                    )
                    hud.MakeVisible() if camera.GetName() == value else hud.MakeInvisible()
            elif action == "layer":
                layers[value] = not layers[value]
                trial.set_layers(value, layers[value])
            elif action == "save":
                if capture_task is None:
                    capture_task = asyncio.ensure_future(save_issue(value))
            else:
                raise ValueError("UNKNOWN_ACTION")
            log(action, value=value, state=trial.run.snapshot())

        window = ui.Window("S13 r2 - Scene Review", width=430, height=820)
        window.setPosition(1125, 55)
        with window.frame:
            with ui.VStack(spacing=4):
                ui.Label("S13 / CONTINUOUS SCENE REHEARSALS", height=24)
                ui.Label(
                    "Production feedback NOT connected. Quality UNKNOWN. HR disabled.\nChanging trial or fixture RESETS the timeline.",
                    word_wrap=True,
                    height=52,
                )
                status_label = ui.Label(message, word_wrap=True, height=80)
                with ui.HStack(height=30):
                    for name in TRIALS:
                        ui.Button(name, clicked_fn=lambda name=name: enqueue("trial", name))
                with ui.HStack(height=30):
                    ui.Button("Run / Pause", clicked_fn=lambda: enqueue("pause"))
                    ui.Button("Step 1/60s", clicked_fn=lambda: enqueue("step"))
                    ui.Button("1x / 4x / 10x", clicked_fn=lambda: enqueue("speed"))
                ui.Button(
                    "RESET current trial (starts paused)",
                    height=26,
                    clicked_fn=lambda: enqueue("reset"),
                )
                ui.Label("Faults need a moving phase; clear then resume.", height=24)
                with ui.HStack(height=28):
                    ui.Button("Obstacle", clicked_fn=lambda: enqueue("inject", "obstacle"))
                    ui.Button("Person", clicked_fn=lambda: enqueue("inject", "person"))
                    ui.Button("Occupied", clicked_fn=lambda: enqueue("inject", "occupied"))
                with ui.HStack(height=28):
                    ui.Button("Clear fault", clicked_fn=lambda: enqueue("clear"))
                    ui.Button(
                        "Duplicate equipment request", clicked_fn=lambda: enqueue("duplicate")
                    )
                with ui.HStack(height=28):
                    for name in layers:
                        ui.Button(name, clicked_fn=lambda name=name: enqueue("layer", name))
                ui.Label("Cameras / mouse orbit and zoom also available", height=24)
                for row in (
                    ("Overview", "Top", "Supply"),
                    ("PRE", "J2", "J3"),
                    ("F1", "Crossing", "Weld"),
                    ("Robot", "Gantry", "Q1", "OUT1"),
                ):
                    with ui.HStack(height=26):
                        for name in row:
                            ui.Button(name, clicked_fn=lambda name=name: enqueue("camera", name))
                ui.Label("37-activity coverage: independent fixtures below", height=24)
                fixture = ui.ComboBox(0, *FIXTURES, height=26)
                ui.Button(
                    "Load selected fixture / RESET",
                    height=26,
                    clicked_fn=lambda: enqueue(
                        "fixture", FIXTURES[fixture.model.get_item_value_model().as_int]
                    ),
                )
                note = ui.StringField(height=26)
                ui.Button(
                    "Save issue / pauses motion",
                    height=30,
                    clicked_fn=lambda: enqueue("save", note.model.as_string),
                )
                ui.Label(
                    "T1 raw > PRE > J2 / T2 rig > withdraw > lift\nT3 WELD1 + supply + TEST1 / T4 two products\nInspection clock is NOT production process time.",
                    word_wrap=True,
                    height=54,
                )
        for _ in range(30):
            app.update()
        sources = [p for p in (ROOT / "sim/isaac/scene").glob("*.py")] + [Path(__file__)]
        save(
            "ready.json",
            {
                "pid": os.getpid(),
                "layout": VERSION,
                "seed": 0,
                "sources": {
                    p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                    for p in sources
                },
            },
        )
        selftest_actions = [
            ("step", None),
            ("speed", None),
            ("pause", None),
            ("pause", None),
            ("inject", "obstacle"),
            ("step", None),
            ("clear", None),
            ("step", None),
            ("camera", "PRE"),
            ("layer", "routes"),
            ("layer", "roles"),
            ("layer", "envelopes"),
            ("reset", None),
            ("trial", "T2"),
            ("trial", "T3"),
            ("trial", "T4"),
            ("fixture", "mep_wait"),
            ("trial", "T1"),
            ("save", "Automated UI callback smoke test"),
        ]
        selftest_index = 0
        selftest_at = time.perf_counter()
        while app.is_running():
            now = time.perf_counter()
            dt = min(now - last, 0.1)
            last = now
            if (
                args.self_test
                and now - selftest_at > 0.3
                and selftest_index < len(selftest_actions)
            ):
                enqueue(*selftest_actions[selftest_index])
                selftest_index += 1
                selftest_at = now
            try:
                while queue:
                    dispatch(*queue.pop(0))
                if mode == "trial" and not trial.run.paused and trial.run.action:
                    trial.advance(dt)
                if capture_task and capture_task.done():
                    capture_task.result()
                    capture_task = None
                a = trial.run.action
                status_label.text = (
                    message
                    + "\n"
                    + (a.label if a else trial.run.status)
                    + f"\n{trial.run.elapsed:.2f}s / {trial.run.speed:g}x / "
                    + ("PAUSED" if trial.run.paused else trial.run.status)
                    + ("\n" + trial.run.blocked if trial.run.blocked else "")
                )
                if now - last_save > 1:
                    save("live.json", {"mode": mode, "message": message, **trial.run.snapshot()})
                    last_save = now
                if (
                    args.self_test
                    and selftest_index == len(selftest_actions)
                    and capture_task is None
                ):
                    require((out / "issue-001.png").is_file(), "SELF_TEST_ISSUE_MISSING")
                    save(
                        "ui-self-test.json",
                        {
                            "status": "PASSED",
                            "method": "SAME_CALLBACK_QUEUE_NO_PHYSICAL_MOUSE_TEST",
                            "actions": selftest_actions,
                        },
                    )
                    break
            except Exception:
                trial.run.paused = True
                message = "ERROR / " + traceback.format_exc().splitlines()[-1]
                log("error", traceback=traceback.format_exc())
                if args.self_test:
                    raise
            app.update()
        # Destroy native widgets while the UI extension is still loaded.
        window.destroy()
        window = None
        status_label = None
        fixture = None
        note = None
        capture_task = None
        queue.clear()
        import gc

        gc.collect()
        for _ in range(5):
            app.update()
        result["status"] = "PASSED"
    except Exception:
        result["error"] = traceback.format_exc()
    finally:
        save("before-close.json", result)
        if app:
            app.close()
            result["closed"] = True
        save("result.json", result)
    return 0 if result["status"] == "PASSED" and result["closed"] else 1


if __name__ == "__main__":
    sys.exit(main())
