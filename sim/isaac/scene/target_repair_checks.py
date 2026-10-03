"""Independent USD counterexamples for the four S13 r4 repair findings."""

import math

from .model import Box, require, sweep


def verify_repairs(trial, tick=lambda: None):
    from pxr import UsdGeom

    scene = trial.scene
    records = []

    def reach(name, prefix):
        trial.load(name)
        while not trial.run.action.label.startswith(prefix):
            trial.advance(trial.run.action.seconds)
            tick()
            require(trial.run.blocked is None, "REPAIR_SETUP:" + str(trial.run.blocked))

    reach("T3", "WALK QA1 / TEST_PUSH")
    a = trial.run.action
    cache = UsdGeom.BBoxCache(0, ["default"], False, True)
    b = cache.ComputeWorldBound(
        scene.stage.GetPrimAtPath("/World/Crane/Bogie1")
    ).ComputeAlignedRange()
    bogie = Box("actual-north-bogie", tuple(b.GetMidpoint()), tuple(b.GetSize()))
    sweep([(x, y, z + 0.95) for x, y, z in a.paths["QA1"]], (0.6, 1.2, 1.9), [bogie])
    legal_route = a.paths["QA1"]
    a.paths["QA1"] = (legal_route[0], (13, 31.5, 0), (13, 39, 0), (55, 39, 0), legal_route[-1])
    before = trial.run.snapshot()
    trial.advance(1)
    require("COLLISION:/World/Crane/" in (trial.run.blocked or ""), "PARKED_CRANE_BYPASS")
    require(
        before["positions"] == trial.run.positions and before["elapsed"] == trial.run.elapsed,
        "REJECT_ADVANCED",
    )
    records.append(
        {"case": "parked_crane_old_route", "reason": trial.run.blocked, "legal_route": legal_route}
    )
    a.paths["QA1"] = legal_route
    trial.advance(a.seconds)
    require(trial.run.blocked is None, "PARKED_CRANE_RESUME")

    for name, label, device in (
        ("T3", "TEST HELD", "TEST1"),
        ("T3", "TWO INDEPENDENT", "SCN-WELD-J2"),
        ("T2", "EMPTY HOOK APPROACH", "CR1-HOOK"),
        ("T1", "EMPTY RETURN", "SCN-FORK-01"),
        ("T3", "EMPTY RETURN", "SCN-CART-01"),
    ):
        reach(name, label)
        trial.advance(0.1)
        try:
            trial.run.claim(device, "SECOND_REQUEST")
        except ValueError as exc:
            require(str(exc).startswith("RESOURCE_BUSY:"), "WRONG_REJECTION")
            records.append({"case": label, "reason": str(exc)})
        else:
            raise ValueError("DUPLICATE_DEVICE_ACCEPTED:" + device)

    for name, label, load, carrier, offset, fault in (
        ("T1", "CARRY S01", "SCN-STEEL-001", "SCN-FORK-01", 1.8, "FORK_LOAD_ALIGNMENT"),
        ("T3", "CARRY P01", "SCN-MEP-001", "SCN-CART-01", 1.1, "TRAY_LOAD_ALIGNMENT"),
    ):
        reach(name, label)
        a = trial.run.action
        maximum = 0
        for _ in range(101):
            trial.advance(a.seconds / 100)
            tick()
            actual = scene.readback()
            p, v = actual[load], actual[carrier]
            maximum = max(maximum, math.dist(p[:2], (v[0], v[1] + offset)))
            require(maximum < 0.001, "USD_ATTACHMENT_SLIP")
            if trial.run.action is not a:
                break
        # A coherent but wrong controller+USD coordinate must still fail the
        # independent load-to-carrier relationship, not only script readback.
        pos = trial.run.positions[load]
        trial.run.positions[load] = (pos[0] + 0.2, *pos[1:])
        scene.set_position(scene.mapping[load], trial.run.positions[load])
        try:
            scene.readback()
        except ValueError as exc:
            require(str(exc) == fault, "WRONG_SUPPORT_REJECTION")
            records.append({"case": label, "max_relative_error_m": maximum, "reason": str(exc)})
        else:
            raise ValueError("INDEPENDENT_ALIGNMENT_NOT_CHECKED")
    trial.load("T1")
    return records
