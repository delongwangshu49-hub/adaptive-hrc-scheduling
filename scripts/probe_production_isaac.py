"""Early real-USD geometry probe; no production validation claim."""

import json
import os
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "src"), str(ROOT / "scripts")]


def run(app, out, *, native_usd=False):
    from build_production_contracts import Builder

    from adaptive_hrc_scheduling.backends.production_isaac_adapter import IsaacAdapter
    from adaptive_hrc_scheduling.domain import production as m
    from adaptive_hrc_scheduling.planning.production import choose, planning_input
    from sim.isaac.scene.model import load_config
    from sim.isaac.scene.production_port import USDProductionPort
    from sim.isaac.scene.target_scene import TargetScene

    if native_usd:
        from pxr import Usd

        stage = Usd.Stage.CreateInMemory()
    else:
        import omni.usd

        omni.usd.get_context().new_stage()
        stage = omni.usd.get_context().get_stage()
    scene = TargetScene(
        stage,
        load_config(ROOT / "examples/building_contracts/configuration.json"),
    )
    b = Builder()
    c = b.configuration()
    port = USDProductionPort(scene)
    a = IsaacAdapter(c, port)
    w = a.world
    lot = "PRODUCT-1.ST-B.01"
    for kind, evidence in [
        ("ARRIVAL", b.ports[lot]["RECEIVE"]),
        ("IDENTIFY", "ML-METHOD"),
        ("RELEASE", "ML-METHOD"),
    ]:
        a.apply_world(
            m.WorldEvent(kind, w.run_id, 0, 0, kind, lot, "PRODUCT-1", 0, "PASS", evidence)
        )
    results = []
    for seq in range(8):
        plan = choose(c, planning_input(c, w.observe(), 10000), sequence=seq)
        if not plan.commands:
            break
        cmd = plan.commands[0]
        receipt = a.dispatch(cmd)
        results.append({"op": cmd.operation_id, "kind": receipt.kind, "reason": receipt.reason})
        if receipt.kind != "STARTED":
            break
        end = max(r.earliest_end_h for r in w.s.running)
        a.advance((end - w.s.time_h) * 3600)
        if app:
            app.update()
        results.append({"kind": w.events[-1].kind, "reason": w.events[-1].reason})
        if w.events[-1].kind == "EXCEPTION":
            break
    scene.stage.Export(str(out / "scene.usda"))
    return {"probe": results, "scope": "INITIAL_GEOMETRY_ONLY", "production_verified": False}


def main():
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    out = parser.parse_args().output
    out.mkdir(parents=True, exist_ok=False)

    def save(name, value):
        (out / name).write_text(json.dumps(value, indent=2), encoding="utf-8")

    save("started.json", {"pid": os.getpid()})
    app = None
    result = {"status": "FAILED", "closed": False}
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
        result.update(run(app, out))
        result["status"] = (
            "PASSED"
            if result["probe"]
            and all(x["kind"] in ("STARTED", "COMPLETED") for x in result["probe"])
            else "FAILED"
        )
    except Exception:
        result["error"] = traceback.format_exc()
        traceback.print_exc()
    finally:
        save("before-close.json", result)
        if app:
            app.close()
            result["closed"] = True
        save("result.json", result)
    return 0 if result["status"] == "PASSED" and result["closed"] else 1


if __name__ == "__main__":
    sys.exit(main())
