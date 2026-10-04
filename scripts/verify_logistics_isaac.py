"""Supervised real-Kit S14 command/readback mechanism witnesses."""

import argparse
import asyncio
import hashlib
import json
import os
import sys
import time
import traceback
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]


def save(path, data):
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def run(app, out):
    import carb
    import omni.usd
    from build_logistics_contracts import command, configuration, tool_configuration

    from adaptive_hrc_scheduling.backends.isaac_adapter import IsaacAdapter
    from adaptive_hrc_scheduling.contracts.codec import as_data
    from adaptive_hrc_scheduling.domain import logistics as m
    from adaptive_hrc_scheduling.logistics_checker import check_run
    from adaptive_hrc_scheduling.planning.logistics import choose, planning_input
    from sim.isaac.scene.logistics_port import USDLogisticsPort
    from sim.isaac.scene.model import load_config, sweep
    from sim.isaac.scene.target_scene import TargetScene

    omni.usd.get_context().new_stage()
    scene = TargetScene(
        omni.usd.get_context().get_stage(),
        load_config(ROOT / "examples/building_contracts/configuration.json"),
    )
    port = USDLogisticsPort(scene)
    carb.settings.get_settings().set("/app/viewport/grid/enabled", False)
    results = []
    shots = []

    def capture(name):
        from omni.kit.viewport.utility import capture_viewport_to_file, get_active_viewport

        vp = get_active_viewport()
        vp.camera_path = "/World/Cameras/" + {
            "take-in-carry": "Supply",
            "v02-crane-weld": "Equipment",
            "tool-deploy-hold-retrieve": "Test",
            "v03-receiver-b-plus-one": "Finished",
        }.get(name, "Overview")
        vp.set_texture_resolution((1280, 720))
        for _ in range(15):
            app.update()
        path = out / (name + ".png")
        pending = asyncio.ensure_future(capture_viewport_to_file(vp, str(path)).wait_for_result())
        deadline = time.monotonic() + 30
        while not pending.done() and time.monotonic() < deadline:
            app.update()
        assert pending.done(), "CAPTURE_TIMEOUT"
        pending.result()
        while time.monotonic() < deadline and (
            not path.exists() or not path.read_bytes().endswith(b"IEND\xaeB`\x82")
        ):
            app.update()
        assert path.exists() and path.read_bytes().endswith(b"IEND\xaeB`\x82"), "CAPTURE_INCOMPLETE"
        shots.append({"file": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
        save(out / "screenshots.json", shots)

    def new(name="V01", config=None):
        return IsaacAdapter(config or configuration(synthetic=True, witness=name), port)

    def fact(a, kind, entity="RAW", evidence="ML-RELEASE", product="PRODUCT-1"):
        w = a.world
        a.apply_world(
            m.WorldEvent(
                "W-" + str(len(w.events)),
                w.run_id,
                w.epoch,
                w.s.time_h,
                kind,
                entity,
                product,
                0,
                "PASS",
                evidence,
            )
        )

    def arrived(a, release=True):
        fact(a, "ARRIVAL", evidence="RECEIVE")
        if release:
            fact(a, "IDENTIFY")
            fact(a, "RELEASE")

    def audit(a, name):
        w = a.world
        report = check_run(w.config, w.snapshot())
        save(out / (name + "-events.json"), as_data(w.snapshot()))
        save(out / (name + "-audit.json"), as_data(report))
        save(
            out / (name + "-actual.json"),
            {
                i: port.position(i) if scene.stage.GetPrimAtPath(port.mapping[i]) else None
                for i in port.expected
            },
        )
        assert report.status == "PASS", (name, report.findings[:5])
        results.append({"case": name, "audit": report.status, "events": len(w.events)})
        save(out / "cases.json", results)
        if name in ("v02-crane-weld", "tool-deploy-hold-retrieve", "v03-receiver-b-plus-one"):
            capture(name)

    def finish(a, op, ident=None, resume=None, planned=None):
        w = a.world
        c = planned or replace(command(w, op, ident), resume_of=resume)
        receipt = a.dispatch(c)
        assert receipt.kind == "STARTED", (op, receipt.reason)
        run = next(r for r in w.s.running if r.command.id == c.id)
        start = w.s.time_h
        for i in range(1, 13):
            target = start + (run.earliest_end_h - start) * i / 12
            a.advance(max(0, (target - w.s.time_h) * 3600))
            app.update()
            if op == "TAKE-IN" and i == 8 and not shots:
                capture("take-in-carry")
            save(out / "latest-events.json", as_data(w.snapshot()))
            assert not any(r.status == "EXCEPTION" for r in w.s.running), (op, w.events[-1].reason)
        assert op in w.s.completed, (op, "not completed")
        return c

    a = new()
    arrived(a)
    for op in (
        "TAKE-IN",
        "TO-PRE",
        "RESERVE-CUT",
        "CUT",
        "WALK-0",
        "DELIVER",
        "RESERVE-WORK",
        "OPEN-WORK",
    ):
        finish(a, op)
    audit(a, "v01-chain")
    # Duplicate world messages must not replay placement, quantity or failure effects.
    original_arrival = next(
        e.world for e in a.world.events if e.world and e.world.kind == "ARRIVAL"
    )
    original_state = a.world.s
    original_position = port.position("RAW")
    original_quantity = port.prim("RAW").GetAttribute("s13:s14Quantity").Get()
    a.apply_world(original_arrival)
    assert a.world.s == original_state and port.position("RAW") == original_position
    assert port.prim("RAW").GetAttribute("s13:s14Quantity").Get() == original_quantity == 0
    fact(a, "FAILURE", entity="FORK-01")
    failure = a.world.events[-1].world
    fact(a, "REPAIR", entity="FORK-01")
    a.apply_world(failure)
    assert port.prim("FORK-01").GetAttribute("s13:s14Available").Get() is True
    audit(a, "duplicate-world-effects")

    from pxr import UsdGeom

    for kind in ("position", "quantity", "visibility", "support", "identity", "deleted", "running"):
        a = new()
        arrived(a)
        for op in ("TAKE-IN", "TO-PRE", "RESERVE-CUT"):
            finish(a, op)
        w = a.world
        c = command(w, "CUT")
        if kind == "running":
            assert a.dispatch(c).kind == "STARTED"
        before = w.s
        if kind in ("position", "running"):
            scene.set_position(port.mapping["RAW"], (45, 40, 1))
        elif kind == "quantity":
            scene.attr(port.prim("RAW"), "s14Quantity", 0.0)
        elif kind == "visibility":
            UsdGeom.Imageable(port.prim("RAW")).MakeInvisible()
        elif kind == "identity":
            scene.attr(port.prim("RAW"), "sceneId", "WRONG-LOT")
        elif kind == "deleted":
            scene.stage.RemovePrim(port.mapping["RAW"])
        else:
            for prim in tuple(scene.stage.Traverse()):
                attr = prim.GetAttribute("s13:obstacleId")
                if attr and str(attr.Get()).startswith("PRE-IN-support-"):
                    scene.set_position(str(prim.GetPath()), (45, 40, 1))
        if kind == "running":
            a.advance((w.s.running[0].earliest_end_h - w.s.time_h) * 3600)
            assert w.s.running[0].status == "EXCEPTION" and w.s.owners == before.owners
        else:
            assert a.dispatch(c).kind == "REJECTED"
            assert w.s.owners == before.owners and w.s.running == before.running
        assert w.s.lots == before.lots and "CUT" not in w.s.completed
        assert port.quantities["PREPARED"] == 0
        audit(a, "actual-input-" + kind)

    for displaced in (False, True):
        config = configuration(synthetic=True, witness="V02")
        assembly = replace(
            next(o for o in config.operations if o.id == "W-3D"),
            prerequisites=(),
            component_inputs=("BOTTOM",),
            entity_id="PRODUCT-1",
            target="J3",
        )
        config = replace(
            config,
            operations=(assembly,),
            entities=(
                replace(config.entities[0], initial_location="J3"),
                m.Entity("PRODUCT-1", "PRODUCT-1", "PRODUCT", "UNASSEMBLED", 8, (6, 3, 3.2)),
            ),
            person_positions=tuple(
                replace(p, location="J3") if p.person_id == "W1" else p
                for p in config.person_positions
            ),
        )
        a = new(config=config)
        if displaced:
            scene.set_position(port.mapping["BOTTOM"], (45, 40, 1))
            assert a.dispatch(command(a.world, "W-3D")).kind == "REJECTED"
            assert a.world._position("PRODUCT-1").location == "UNASSEMBLED"
        else:
            finish(a, "W-3D")
            assert a.world._position("BOTTOM").location == "INCORPORATED"
        audit(a, "actual-component-" + ("missing" if displaced else "assembly"))
    a = new("V02")
    for op in ("MV-IN-B", "W-B", "WALK-0", "W-3D"):
        finish(a, op)
    audit(a, "v02-crane-weld")
    a = new(config=tool_configuration())
    finish(a, "DEPLOY")
    assert any(
        x.resource_id == "TEST1" and x.command_id == "HELD:PRODUCT-1" for x in a.world.s.owners
    )
    assert a.dispatch(command(a.world, "STEAL")).kind == "DEFERRED"
    finish(a, "TEST-CHECK")
    finish(a, "RETRIEVE")
    assert not a.world.s.owners
    audit(a, "tool-deploy-hold-retrieve")
    a = new()
    arrived(a, False)
    assert a.dispatch(command(a.world, "TAKE-IN")).kind == "REJECTED"
    audit(a, "unreleased")
    for kind in ("person", "device", "obstacle", "target", "support", "controls"):
        a = new()
        arrived(a)
        w = a.world
        c = command(w, "TAKE-IN")
        if kind == "person":
            scene.set_position(port.mapping["P1"], (50, 40, 0))
            assert a.dispatch(c).kind == "REJECTED"
        elif kind == "device":
            scene.attr(port.prim("FORK-01"), "s14Available", False)
            assert a.dispatch(c).kind == "REJECTED"
        else:
            assert a.dispatch(c).kind == "STARTED"
            a.advance(w.s.running[0].earliest_end_h * 2520)
            app.update()
            if kind == "controls":
                from pxr import UsdGeom

                UsdGeom.Xformable(port.prim("P1")).GetOrderedXformOps()[-1].Set(180)
            elif kind == "support":
                scene.set_position(port.mapping["FORK-01"] + "/Forks", (0, 0, 3))
            else:
                point = (6, 14, 1.1) if kind == "target" else (11, 7, 1.1)
                scene.shape("/World/S14/Injected", point, (1, 1, 2), "red", collision=True)
            a.advance(1)
            assert w.events[-1].kind == "EXCEPTION", (kind, w.events[-1].kind)
            assert w.s.owners and w._position("RAW").location == "IN_TRANSIT"
        audit(a, "actual-" + kind)
    a = new()
    arrived(a)
    w = a.world
    c = command(w, "TAKE-IN")
    first = a.dispatch(c)
    assert a.dispatch(c) == first
    assert a.dispatch(command(w, "TAKE-IN", "CONFLICT")).kind != "STARTED"
    a.advance(w.s.running[0].earliest_end_h * 2520)
    scene.attr(port.prim("FORK-01"), "s14Available", False)
    a.advance(1)
    assert w.s.running[0].status == "EXCEPTION"
    scene.attr(port.prim("FORK-01"), "s14Available", True)
    plan = choose(w.config, planning_input(w.config, w.observe(), 10000))
    assert plan.commands and plan.commands[0].resume_of == c.id
    finish(a, "TAKE-IN", planned=plan.commands[0])
    old = w.events[-1].readback
    assert a.feedback(old).kind == "COMPLETED"
    audit(a, "fault-resume-duplicate")
    a.reset()
    state = a.world.s
    assert a.feedback(old) == "STALE_EPOCH" and a.world.s == state
    a.advance(100, playing=False)
    assert a.world.s.time_h == 0
    a = new("V03")
    finish(a, "SHIP-1")
    w = a.world
    assert w._product("PRODUCT-1").received_h is None
    fact(a, "RECEIVE_PERMIT", entity="PRODUCT-1")
    c = command(w, "RECEIVE-1")
    assert a.dispatch(c).kind == "STARTED"
    a.advance(0)
    assert w._product("PRODUCT-1").received_h is None
    # Independent synthetic receiver fixture supplies geometry plus correlated acknowledgement.
    path = ((30, 34, 0.6), (30, 34, 4.1), (64, 34, 4.1), (64, 34, 0.6))
    size = port.loads["PRODUCT-1"].size_m
    sweep(
        tuple((x, y, z + size[2] / 2) for x, y, z in path),
        size,
        scene.actual_obstacles(("PRODUCT-1",)),
        0,
    )
    for point in path:
        scene.set_position(port.mapping["PRODUCT-1"], point)
        app.update()
    receiver = scene.group("/World/S14/Receiver").GetPrim()
    scene.shape("/World/S14/Receiver/Deck", (64, 34, 0.3), (7, 4, 0.6), "blue", collision=True)
    for k, v in {
        "runId": w.run_id,
        "epoch": w.epoch,
        "commandId": c.id,
        "productId": "PRODUCT-1",
        "receiptId": "RECEIVER-001",
    }.items():
        scene.attr(receiver, k, v)
    a.advance(0)
    assert w._product("PRODUCT-1").received_h is not None, w.events[-1].reason
    for op in ("EMPTY-CR1", "WALK-0", "WALK-1", "BUFFER-3"):
        finish(a, op)
    audit(a, "v03-receiver-b-plus-one")
    scene.stage.Export(str(out / "scene.usda"))
    return {"cases": results, "scope": "SYNTHETIC_USD_KINEMATIC_AND_SYNTHETIC_EXTERNAL_RECEIVER"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    save(out / "started.json", {"pid": os.getpid()})
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
