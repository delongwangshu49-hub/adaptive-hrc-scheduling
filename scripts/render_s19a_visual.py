"""Actual Kit comparison, per-frame guards, relocated texture replay and ABBA load."""

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
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--verified-snapshots", type=Path, required=True)
    parser.add_argument("--ffmpeg-path", type=Path, required=True)
    parser.add_argument("--baseline-ref", default="step-S19A-static-r1")
    parser.add_argument(
        "--protocol", type=Path, default=ROOT / "docs/model/S19A_visual_protocol_r2.json"
    )
    parser.add_argument(
        "--cases", type=Path, default=ROOT / "examples/visual/S19A_motion_cases_r2.json"
    )
    args = parser.parse_args()
    if not args.ffmpeg_path.is_file():
        parser.error("--ffmpeg-path must identify an installed encoder executable")
    BASE = args.output.resolve().parent
    OUT = args.output.resolve()
    OUT.mkdir(parents=True, exist_ok=False)
    FRAMES = OUT / "frames"
    FRAMES.mkdir()
    sys.path[:0] = [str(ROOT), str(ROOT / "src"), str(ROOT / "scripts")]
    os.environ["WARP_CACHE_PATH"] = str(OUT / "warp-cache")
    protocol = json.loads(args.protocol.read_text(encoding="utf-8"))
    settings = protocol["performance"]
    if (
        settings["resolution"] != [1280, 720]
        or settings["warmup_frames"] != 60
        or settings["samples_per_run"] != 180
        or settings["order"] != ["before", "after", "after", "before"]
    ):
        raise ValueError("UNSUPPORTED_VISUAL_MEASUREMENT_PROTOCOL")
    limits = (settings["candidate_median_ratio_max"], settings["candidate_p95_ratio_max"])
    if any(type(v) not in (int, float) or not math.isfinite(v) or v <= 0 for v in limits):
        raise ValueError("INVALID_VISUAL_PERFORMANCE_LIMIT")
    report = {
        "status": "FAILED",
        "closed": False,
        "images": [],
        "frame_guards": [],
        "load_runs": [],
        "protocol_sha256": hashlib.sha256(args.protocol.read_bytes()).hexdigest(),
        "scope": "BOUNDED_VISUAL_FIXED_CASES; NO_NEW_PROCESS_TIMES_OR_INDUSTRIAL_CLAIMS",
    }

    def save():
        (OUT / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    app = None
    try:
        from isaacsim import SimulationApp

        app = SimulationApp(
            {
                "headless": True,
                "width": 1280,
                "height": 720,
                "multi_gpu": False,
                "fast_shutdown": False,
                "enable_crashreporter": False,
                "renderer": "RayTracedLighting",
            }
        )
        import carb
        import omni.usd
        from omni.kit.viewport.utility import capture_viewport_to_file, get_active_viewport
        from pxr import Gf, Sdf, Usd, UsdGeom, UsdLux

        from adaptive_hrc_scheduling.logistics_geometry import interpolate
        from sim.isaac.scene.model import load_config
        from sim.isaac.scene.person_motion import present_route, set_person_pose
        from sim.isaac.scene.target_scene import TargetScene, TargetTrialScene
        from sim.isaac.scene.usd_scene import BuildingScene

        cfg = load_config(ROOT / "examples/building_contracts/configuration.json")
        old = types.ModuleType("sim.isaac.scene._kit_static_reference")
        old.__package__ = "sim.isaac.scene"
        exec(
            compile(
                subprocess.check_output(
                    ["git", "show", args.baseline_ref + ":sim/isaac/scene/target_scene.py"],
                    cwd=ROOT,
                ),
                "static-reference.py",
                "exec",
            ),
            old.__dict__,
        )
        sources = {}
        source_scenes = {}
        for kind, cls in [("before", old.TargetScene), ("after", TargetScene)]:
            sc = cls(Usd.Stage.CreateInMemory(), cfg, "T3")
            sources[kind] = sc.stage
            source_scenes[kind] = sc
        viewport = get_active_viewport()
        viewport.set_texture_resolution((1280, 720))
        carb.settings.get_settings().set("/app/viewport/grid/enabled", False)

        def capture(path, frames=2, matrix=None):
            for _ in range(frames):
                app.update()
            if matrix is not None:
                error = 1.0
                for _ in range(120):
                    error = max(
                        abs(viewport.frame_info["view"][i * 4 + j] - matrix[i][j])
                        for i in range(4)
                        for j in range(4)
                    )
                    if error < 1e-4:
                        break
                    app.update()
                assert error < 1e-4, error
            else:
                error = None
            started = time.perf_counter()
            task = asyncio.ensure_future(
                capture_viewport_to_file(viewport, str(path)).wait_for_result()
            )
            while not task.done() and time.perf_counter() - started < 30:
                app.update()
            assert task.done()
            task.result()
            payload = b""
            while time.perf_counter() - started < 30:
                try:
                    if path.is_file():
                        payload = path.read_bytes()
                except OSError:
                    app.update()
                    continue
                if payload.endswith(b"IEND\xaeB`\x82"):
                    break
                app.update()
            assert payload.endswith(b"IEND\xaeB`\x82")
            return error

        def photo(name, matrix=None):
            p = OUT / (name + ".png")
            error = capture(p, 45, matrix)
            report["images"].append(
                {
                    "file": p.name,
                    "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
                    "camera_error": error,
                }
            )
            save()

        fixture = json.loads(args.cases.read_text(encoding="utf-8"))
        if fixture["fps"] != 24 or fixture["frames_per_case"] != 72:
            raise ValueError("UNSUPPORTED_VISUAL_VIDEO_PROTOCOL")
        cases = fixture["cases"]
        number = 0
        for name, who, path, mode, root_yaw in cases:
            omni.usd.get_context().new_stage()
            stage = omni.usd.get_context().get_stage()
            helper = BuildingScene.__new__(BuildingScene)
            helper.stage, helper.materials, helper.mapping = stage, {}, {}
            helper.group("/World")
            helper.group("/World/People")
            helper._person_motions = {}
            UsdGeom.SetStageMetersPerUnit(stage, 1)
            UsdGeom.SetStageUpAxis(stage, "Z")
            Sdf.CopySpec(
                sources["after"].GetRootLayer(),
                "/World/Looks",
                stage.GetRootLayer(),
                "/World/Looks",
            )
            roots = {}
            for kind, x in [("before", -1.35), ("after", 1.35)]:
                destination = (
                    "/World/Reference/" + who if kind == "before" else "/World/People/" + who
                )
                helper.group("/World/Reference") if kind == "before" else None
                Sdf.CopySpec(
                    sources[kind].GetRootLayer(),
                    "/World/People/" + who,
                    stage.GetRootLayer(),
                    destination,
                )
                stage.RemovePrim(destination + "/Role")
                roots[kind] = UsdGeom.Xformable(stage.GetPrimAtPath(destination))
                roots[kind].GetOrderedXformOps()[-1].Set(root_yaw)
                if kind == "after":
                    cached = source_scenes["after"]._person_motions[who]
                    helper._person_motions[who] = {
                        "bounds": cached["bounds"],
                        "yaw": 0,
                        "signature": None,
                        "parts": [
                            (
                                p.GetName(),
                                UsdGeom.XformOp(p.GetAttribute("xformOp:transform:s19aVisual")),
                            )
                            for p in stage.GetPrimAtPath(destination).GetChildren()
                            if p.GetAttribute("xformOp:transform:s19aVisual")
                        ],
                    }
                if name in ("TOOL-CONTROL", "LOADED-CART"):
                    identity = "TEST1" if name == "TOOL-CONTROL" else "SCN-CART-01"
                    parent = "/World/Device" + kind
                    helper.group(parent)
                    Sdf.CopySpec(
                        sources[kind].GetRootLayer(),
                        source_scenes[kind].mapping[identity],
                        stage.GetRootLayer(),
                        parent + "/Model",
                    )
                    UsdGeom.Xformable(stage.GetPrimAtPath(parent + "/Model")).GetOrderedXformOps()[
                        0
                    ].Set(Gf.Vec3d(x, 0, 0))
                    stage.RemovePrim(parent + "/Model/Label")
                    if name == "LOADED-CART":
                        source = source_scenes[kind].mapping["SCN-MEP-001"]
                        Sdf.CopySpec(
                            sources[kind].GetRootLayer(),
                            source,
                            stage.GetRootLayer(),
                            parent + "/Load",
                        )
                        stage.RemovePrim(parent + "/Load/Identity")
            helper.shape("/World/ReviewFloor", (0, 0, -0.055), (160, 160, 0.1), "dark")
            fill = UsdLux.DomeLight.Define(stage, "/World/Fill")
            fill.CreateIntensityAttr(650)
            key = UsdLux.DistantLight.Define(stage, "/World/Key")
            key.CreateIntensityAttr(1250)
            key.AddRotateXYZOp().Set(Gf.Vec3f(25, -20, -25))
            cam = UsdGeom.Camera.Define(stage, "/World/ReviewCamera")
            cam.CreateProjectionAttr("orthographic")
            cam.CreateHorizontalApertureAttr(64)
            cam.CreateVerticalApertureAttr(36)
            cam.CreateClippingRangeAttr(Gf.Vec2f(0.01, 1000))
            op = cam.AddTransformOp()
            viewport.camera_path = "/World/ReviewCamera"
            for side, x in [("Before", -1.35), ("After", 1.35)]:
                cap = helper.group("/World/Caption" + side, (x + 0.6, 0, 2.2))
                cap.AddRotateXYZOp().Set(Gf.Vec3f(90, 0, 180))
                helper.label(
                    "/World/Caption" + side + "/Text", side.upper(), (0, 0, 0), 0.09, "white"
                )
            total = sum(math.dist(a, b) for a, b in zip(path, path[1:]))
            case = {
                "case": name,
                "identity": who,
                "frames": 72,
                "mode": mode,
                "root_yaw_preserved": root_yaw,
                "body_growth_max_m": 0,
                "control_hand_error_max_m": 0,
                "root_pair_offset_error_max_m": 0,
            }
            paused = None
            for frame in range(72):
                fraction = frame / 71
                moving = True
                if name == "STOP-RESUME":
                    if frame < 24:
                        fraction = frame / 48
                    elif frame < 48:
                        fraction = 23 / 48
                        moving = False
                    else:
                        fraction = 23 / 48 + (frame - 47) / 24 * (1 - 23 / 48)
                point = interpolate(path, fraction, 1, 1)
                for kind, x in [("before", -1.35), ("after", 1.35)]:
                    roots[kind].GetOrderedXformOps()[0].Set(
                        Gf.Vec3d(point[0] + x, point[1], point[2])
                    )
                    if name in ("TOOL-CONTROL", "LOADED-CART"):
                        device_y = point[1] - (1.25 if name == "TOOL-CONTROL" else -1.35)
                        model = stage.GetPrimAtPath("/World/Device" + kind + "/Model")
                        UsdGeom.Xformable(model).GetOrderedXformOps()[0].Set(
                            Gf.Vec3d(point[0] + x, device_y, 0)
                        )
                        if name == "LOADED-CART":
                            cargo = stage.GetPrimAtPath("/World/Device" + kind + "/Load")
                            UsdGeom.Xformable(cargo).GetOrderedXformOps()[0].Set(
                                Gf.Vec3d(point[0] + x, device_y + 0.65, 0.8)
                            )
                if mode == "WALK":
                    present_route(helper, who, path, fraction, fraction * total, moving=moving)
                else:
                    set_person_pose(helper, who, mode=mode, moving=True, clock_s=frame / 24)
                body_root = stage.GetPrimAtPath("/World/People/" + who)
                cache = UsdGeom.BBoxCache(0, ["default"], False, True)
                boxes = [
                    cache.ComputeRelativeBound(p, body_root).ComputeAlignedRange()
                    for p in Usd.PrimRange(body_root)
                    if p.IsA(UsdGeom.Boundable) and p.GetName() not in ("Role", "Occupancy")
                ]
                lo, hi = helper._person_motions[who]["bounds"]
                growth = max(
                    [
                        0,
                        *[lo[i] - min(b.GetMin()[i] for b in boxes) for i in range(3)],
                        *[max(b.GetMax()[i] for b in boxes) - hi[i] for i in range(3)],
                    ]
                )
                assert growth <= 1e-6, (name, frame, growth)
                case["body_growth_max_m"] = max(case["body_growth_max_m"], growth)
                a = roots["after"].ComputeLocalToWorldTransform(0)
                b = roots["before"].ComputeLocalToWorldTransform(0)
                delta = a.ExtractTranslation() - b.ExtractTranslation()
                error = (delta - Gf.Vec3d(2.7, 0, 0)).GetLength()
                assert error < 1e-9
                case["root_pair_offset_error_max_m"] = max(
                    case["root_pair_offset_error_max_m"], error
                )
                if mode != "WALK":
                    hands = [
                        UsdGeom.Xformable(
                            stage.GetPrimAtPath("/World/People/" + who + "/Arm" + str(i))
                        )
                        .ComputeLocalToWorldTransform(0)
                        .Transform(Gf.Vec3d(0, 0, 0.5))
                        for i in (0, 1)
                    ]
                    control = a.Transform(Gf.Vec3d(0, 0.5, 1.05))
                    error = ((hands[0] + hands[1]) * 0.5 - control).GetLength()
                    assert error < 1e-6, (name, error)
                    case["control_hand_error_max_m"] = max(case["control_hand_error_max_m"], error)
                if name == "STOP-RESUME" and 24 <= frame < 48:
                    value = [str(pose.Get()) for _, pose in helper._person_motions[who]["parts"]]
                    if paused is not None:
                        assert paused == value
                    paused = value
                for side, x in [("Before", -1.35), ("After", 1.35)]:
                    helper.set_position(
                        "/World/Caption" + side, (point[0] + x + 0.6, point[1], 2.2 + point[2])
                    )
                matrix = Gf.Matrix4d().SetLookAt(
                    Gf.Vec3d(point[0], point[1] + 8, 4 + point[2]),
                    Gf.Vec3d(point[0], point[1], 1 + point[2]),
                    Gf.Vec3d(0, 0, 1),
                )
                op.Set(matrix.GetInverse())
                output = FRAMES / f"frame-{number:05d}.png"
                capture_error = capture(output, frames=4 if frame == 0 else 1, matrix=matrix)
                if frame == 36:
                    target = OUT / (name + ".png")
                    target.write_bytes(output.read_bytes())
                    report["images"].append(
                        {
                            "file": target.name,
                            "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
                            "camera_error": capture_error,
                        }
                    )
                number += 1
            report["frame_guards"].append(case)
            print("CASE_COMPLETE", name, flush=True)
            save()
        video = OUT / "motion-before-after.mp4"
        with (OUT / "video-encode.log").open("wb") as stream:
            subprocess.run(
                [
                    str(args.ffmpeg_path.resolve()),
                    "-n",
                    "-framerate",
                    "24",
                    "-i",
                    str(FRAMES / "frame-%05d.png"),
                    "-c:v",
                    "libx264",
                    "-pix_fmt",
                    "yuv420p",
                    "-crf",
                    "23",
                    "-movflags",
                    "+faststart",
                    str(video),
                ],
                stdout=stream,
                stderr=stream,
                check=True,
            )
        report["video"] = {
            "file": video.name,
            "sha256": hashlib.sha256(video.read_bytes()).hexdigest(),
            "frames": number,
            "fps": 24,
            "duration_s": number / 24,
            "recorded_route": "12 original points / 40.4m / original 1m/s; accelerated review playback only",
        }
        save()

        # Replay actual portable production initialization snapshots; texture is relative.
        for variant in ("SR-W1", "SR-W2"):
            source = args.verified_snapshots / (variant + "-relocated/scene.usda")
            omni.usd.get_context().open_stage(str(source))
            stage = omni.usd.get_context().get_stage()
            viewport.camera_path = "/World/Cameras/Overview"
            photo("relocated-" + variant)
        # Representative fixed T3 execution with identical domain input and ABBA order.
        for kind in ("before", "after", "after", "before"):
            omni.usd.get_context().new_stage()
            stage = omni.usd.get_context().get_stage()
            cls = old.TargetScene if kind == "before" else TargetScene
            scene = cls(stage, cfg, "T3")
            trial = TargetTrialScene(scene, "T3")
            viewport.camera_path = "/World/Cameras/Overview"
            timings = []
            snapshots = []
            workloads = []
            for label in ("TWO PEOPLE CROSS / W2 YIELDS TO W1", "CARRY P01", "TEST DELIVER"):
                trial.load("T3")
                target = next(i for i, a in enumerate(trial.run.phases) if a.label == label)
                for _ in range(2000):
                    if trial.run.index == target:
                        break
                    trial.advance(1)
                    assert trial.run.blocked is None
                assert trial.run.index == target
                for _ in range(20):
                    trial.advance(1 / 30)
                    app.update()
                for _ in range(60):
                    began = time.perf_counter()
                    snapshot = trial.advance(1 / 30)
                    app.update()
                    timings.append((time.perf_counter() - began) * 1000)
                    snapshots.append(snapshot)
                workloads.append(label)
            digest = hashlib.sha256(
                json.dumps(snapshots, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest()
            report["load_runs"].append(
                {
                    "kind": kind,
                    "workloads": workloads,
                    "median_ms": statistics.median(timings),
                    "p95_ms": sorted(timings)[170],
                    "max_ms": max(timings),
                    "domain_snapshots_sha256": digest,
                    "raw_ms": timings,
                }
            )
            save()
        assert len({r["domain_snapshots_sha256"] for r in report["load_runs"]}) == 1
        before = [r for r in report["load_runs"] if r["kind"] == "before"]
        after = [r for r in report["load_runs"] if r["kind"] == "after"]
        median_ratio = statistics.mean(r["median_ms"] for r in after) / statistics.mean(
            r["median_ms"] for r in before
        )
        p95_ratio = statistics.mean(r["p95_ms"] for r in after) / statistics.mean(
            r["p95_ms"] for r in before
        )
        report["performance"] = {
            "median_ratio": median_ratio,
            "p95_ratio": p95_ratio,
            "predeclared_candidate_limits_satisfied": median_ratio <= limits[0]
            and p95_ratio <= limits[1],
            "owner_protocol_acceptance": "PENDING; NO_HARD_REALTIME_CLAIM",
        }
        report["status"] = "REAL_KIT_MATRIX_VIDEO_AND_LOAD_COMPLETE"
    except Exception:
        report["error"] = traceback.format_exc()
        print(report["error"], flush=True)
    finally:
        save()
        if app:
            if "sources" in locals():
                sources.clear()
            if "source_scenes" in locals():
                source_scenes.clear()
            stage = scene = trial = helper = viewport = cam = op = roots = body_root = cache = (
                boxes
            ) = sc = cached = model = cargo = cap = None
            omni.usd.get_context().close_stage()
            for _ in range(30):
                app.update()
            import gc

            gc.collect()
            app.close()
        report["closed"] = True
        save()
    sys.exit(0 if report["status"] == "REAL_KIT_MATRIX_VIDEO_AND_LOAD_COMPLETE" else 1)


if __name__ == "__main__":
    main()
