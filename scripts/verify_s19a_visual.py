"""Check bounded S19A motion and portable exports with the installed USD runtime."""

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "src"), str(ROOT / "scripts")]


def run(output, baseline_ref="step-S19A-static-r1"):
    from build_simulation_production import configuration
    from pxr import Ar, Gf, Sdf, Usd, UsdGeom, UsdPhysics

    from sim.isaac.scene.model import load_config
    from sim.isaac.scene.person_motion import present_route, set_person_pose
    from sim.isaac.scene.production_port import USDProductionPort
    from sim.isaac.scene.review_export import export_review_stage
    from sim.isaac.scene.target_layout import PEOPLE
    from sim.isaac.scene.target_scene import TargetScene, TargetTrialScene

    output.mkdir(parents=True, exist_ok=False)
    original = types.ModuleType("sim.isaac.scene._s19a_static_reference")
    original.__package__ = "sim.isaac.scene"
    source = subprocess.check_output(
        ["git", "show", baseline_ref + ":sim/isaac/scene/target_scene.py"], cwd=ROOT
    )
    exec(compile(source, "static-reference-target.py", "exec"), original.__dict__)
    config = load_config(ROOT / "examples/building_contracts/configuration.json")
    report = {"status": "RUNNING", "cases": [], "frames": 0, "exports": []}

    def save():
        (output / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    def build(cls, trial="T1"):
        return cls(Usd.Stage.CreateInMemory(), config, trial)

    def body(scene, identity):
        root = scene.stage.GetPrimAtPath("/World/People/" + identity)
        cache = UsdGeom.BBoxCache(0, ["default"], False, True)
        boxes = [
            cache.ComputeRelativeBound(p, root).ComputeAlignedRange()
            for p in Usd.PrimRange(root)
            if p.IsA(UsdGeom.Boundable) and p.GetName() not in ("Role", "Occupancy")
        ]
        return (
            [min(b.GetMin()[i] for b in boxes) for i in range(3)],
            [max(b.GetMax()[i] for b in boxes) for i in range(3)],
        )

    def guard(scene, identity):
        actual = body(scene, identity)
        lo, hi = scene._person_motions[identity]["bounds"]
        assert all(actual[0][i] >= lo[i] - 1e-6 and actual[1][i] <= hi[i] + 1e-6 for i in range(3))

    def collider_table(scene):
        cache = UsdGeom.BBoxCache(0, ["default"], False, True)
        return {
            str(p.GetPath()): str(cache.ComputeWorldBound(p).ComputeAlignedRange())
            for p in scene.stage.Traverse()
            if p.HasAPI(UsdPhysics.CollisionAPI)
        }

    # Every heading, individual and gait phase, including shortest-path fold-back.
    scene = build(TargetScene)
    colliders = collider_table(scene)
    for identity in PEOPLE:
        root = scene.stage.GetPrimAtPath("/World/People/" + identity)
        matrix = UsdGeom.Xformable(root).ComputeLocalToWorldTransform(0)
        for yaw in range(-180, 181, 5):
            for clock in (0.0, 0.23):
                set_person_pose(scene, identity, yaw, moving=True, clock_s=clock)
                guard(scene, identity)
                assert UsdGeom.Xformable(root).ComputeLocalToWorldTransform(0) == matrix
                report["frames"] += 1
        for mode in ("OPERATION", "BACKSTEP", "SIDESTEP"):
            set_person_pose(scene, identity, mode=mode)
            assert all(
                pose.Get() == Gf.Matrix4d(1) for _, pose in scene._person_motions[identity]["parts"]
            )
        for frame in range(60):
            set_person_pose(scene, identity, mode="CONTROL_WALK", moving=True, clock_s=frame / 30)
            guard(scene, identity)
            assert all(
                pose.Get() == Gf.Matrix4d(1)
                for name, pose in scene._person_motions[identity]["parts"]
                if not name.startswith(("Leg", "Boot"))
            )
            report["frames"] += 1
        report["cases"].append(
            {"case": identity + "-all-headings-and-control-restore", "status": "PASS"}
        )
    assert collider_table(scene) == colliders

    scenarios = {
        "north": ((0, 0, 0), (0, 3, 0)),
        "east": ((0, 0, 0), (3, 0, 0)),
        "south": ((0, 0, 0), (0, -3, 0)),
        "west": ((0, 0, 0), (-3, 0, 0)),
        "turn": ((0, 0, 0), (0, 2, 0), (2, 2, 0)),
        "fold": ((0, 0, 0), (0, 2, 0), (0, 0, 0)),
    }
    for name, path in scenarios.items():
        for frame in range(121):
            present_route(scene, "W1", path, frame / 120, frame / 30)
            guard(scene, "W1")
            report["frames"] += 1
        set_person_pose(scene, "W1", moving=False)
        paused = [str(pose.Get()) for _, pose in scene._person_motions["W1"]["parts"]]
        set_person_pose(scene, "W1", moving=False, clock_s=100)
        assert paused == [str(pose.Get()) for _, pose in scene._person_motions["W1"]["parts"]]
        report["cases"].append({"case": name + "-route-stop-stability", "status": "PASS"})

    # Complete the original four fixed scene trials with both implementations.
    for trialname in ("T1", "T2", "T3", "T4"):
        before, after = build(original.TargetScene, trialname), build(TargetScene, trialname)
        a, b = TargetTrialScene(before, trialname), TargetTrialScene(after, trialname)
        if trialname == "T4":
            a.run.external_signal = b.run.external_signal = True
        for step in range(4000):
            left, right = a.advance(0.5), b.advance(0.5)
            assert left == right, (trialname, step, "DOMAIN_OR_ROOT_DRIFT")
            for who in PEOPLE:
                guard(after, who)
            if step % 20 == 0:
                assert before.actual_obstacles() == after.actual_obstacles()
            if b.run.status in ("BLOCKED", "COMPLETE_GEOMETRY_ONLY"):
                break
        assert b.run.status == "COMPLETE_GEOMETRY_ONLY", (trialname, b.run.blocked)
        assert before.actual_obstacles() == after.actual_obstacles()
        a.restart()
        b.restart()
        assert a.run.snapshot() == b.run.snapshot()
        report["cases"].append(
            {
                "case": trialname + "-complete-fixed-trial-and-reset",
                "steps": step + 1,
                "status": "PASS",
            }
        )
        save()

    for variant in ("SR-W1", "SR-W2"):
        before, after = build(original.TargetScene), build(TargetScene)
        settings = configuration(products=1, variant=variant, rework=False)
        for target in (before, after):
            USDProductionPort(target).reset(settings, "S19A-FINAL-GUARD", 0)
        assert before.actual_obstacles() == after.actual_obstacles()
        for identity in PEOPLE:
            guard(after, identity)
        dependencies = export_review_stage(after.stage, output / (variant + ".usda"))
        relocated = output / (variant + "-relocated")
        relocated.mkdir()
        shutil.copyfile(output / (variant + ".usda"), relocated / "scene.usda")
        shutil.copytree(output / "_assets", relocated / "_assets")
        loaded = Usd.Stage.Open(str(relocated / "scene.usda"))
        for prim in loaded.Traverse():
            for attribute in prim.GetAttributes():
                value = attribute.Get()
                if not isinstance(value, Sdf.AssetPath) or not value.path:
                    continue
                assert not Path(value.path).is_absolute()
                resolved = Path(str(Ar.GetResolver().Resolve(value.resolvedPath))).resolve()
                assert resolved.is_relative_to(relocated.resolve()) and resolved.is_file()
        report["exports"].append(
            {"variant": variant, "dependencies": dependencies, "relocated_relative_assets": "PASS"}
        )
        # The export must not convert the original live texture binding to a copy.
        file = (
            after.stage.GetPrimAtPath("/World/Looks/S19A_floor_paint_r2/Paint")
            .GetAttribute("inputs:file")
            .Get()
        )
        assert Path(file.path).is_absolute()
    # Real negative exports on a separate copy: never hide a missing texture.
    broken = Usd.Stage.Open(after.stage.Flatten())
    broken.GetPrimAtPath("/World/Looks/S19A_floor_paint_r2/Paint").GetAttribute("inputs:file").Set(
        Sdf.AssetPath(str(output / "deliberately-absent.png"))
    )
    try:
        export_review_stage(broken, output / "invalid.usda")
    except ValueError as error:
        assert "REVIEW_ASSET_UNRESOLVED" in str(error)
    else:
        raise AssertionError("MISSING_ASSET_NOT_REJECTED")
    assert not (output / "invalid.usda").exists()
    report["negative_missing_asset"] = "REJECTED_WITHOUT_EXPORT"
    assert Path(file.path).is_file()
    report["status"] = "PASS_WITH_OWNER_VISUAL_AND_PROTOCOL_ACCEPTANCE_PENDING"
    report["source_hashes"] = {
        p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in [*(ROOT / "sim/isaac/scene").glob("*.py"), Path(__file__)]
    }
    save()
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--baseline-ref", default="step-S19A-static-r1")
    args = parser.parse_args()
    result = run(args.output.resolve(), args.baseline_ref)
    print(
        json.dumps(
            {"status": result["status"], "frames": result["frames"], "cases": len(result["cases"])}
        )
    )


if __name__ == "__main__":
    main()
