"""Real USD scene checks and scripted synthetic transfers; no dispatch integration."""

import math

from pxr import Gf, UsdGeom, UsdPhysics

from .layout import local
from .model import POSES, Box, Transfer, fk, require, robot_check, sweep


def obstacles(scene, excluded=()):
    cache = UsdGeom.BBoxCache(0, ["default", "render", "proxy"], False, True)
    result = []
    for prim in scene.stage.Traverse():
        path = str(prim.GetPath())
        if not prim.HasAPI(UsdPhysics.CollisionAPI):
            continue
        if path in ("/World/Factory/Ground", "/World/ContactProbe") or any(
            path.startswith(p) for p in excluded
        ):
            continue
        bound = cache.ComputeWorldBound(prim).ComputeAlignedRange()
        result.append(Box(path, local(bound.GetMidpoint()), tuple(bound.GetSize())))
    return result


def sync_entities(scene):
    ids = [r["id"] for g in ("products", "components") for r in scene.config[g]]
    for name in ids:
        scene.mapping.pop(name, None)
    scene.stage.RemovePrim("/World/Entities")
    scene.group("/World/Entities")
    scene.entities()
    scene.mapping_check()


def run_inspection(scene, app, capture, checkpoint=lambda report: None):
    report = {"routes": [], "negative_cases": [], "robot_poses": [], "screenshots": []}

    def reject(name, operation, expected):
        try:
            operation()
        except ValueError as exc:
            require(expected in str(exc), "UNEXPECTED_REJECTION:" + str(exc))
            report["negative_cases"].append({"case": name, "reason": str(exc)})
        else:
            raise ValueError("NEGATIVE_ACCEPTED:" + name)

    def transfer(name, entity, equipment, target, target_zone, size, mass, rigging=0):
        path = scene.mapping[entity]
        source = scene.scene_position(path)
        ignored = [path, scene.mapping[equipment]]
        if equipment == "CR1":
            # Wheels contact their own rails; foreign obstacles on rails remain checked.
            ignored += ["/World/Factory/Rail0", "/World/Factory/Rail1"]
        # Separate geometry fixture, never continue an active welding phase.
        scene.state.phase = None
        scene.state.owners = {}
        for i, person in enumerate(scene.config["people"]):
            scene.set_position(scene.mapping[person["id"]], (2 + i * 1.5, 33, 0))
        # Operator/rigging/signal are separate people outside the load envelope.
        people = ("Lop", "Lrig", "Lsig") if equipment == "CR1" else ("P1", "Lrig", "Lsig")
        for i, person in enumerate(people):
            pp = scene.mapping[person]
            scene.set_position(
                pp, (39 + i, 33, 0) if equipment == "CR1" else (target[0] - 1 + i * 1.5, 15.4, 0)
            )
            scene.attr(scene.stage.GetPrimAtPath(pp), "laborState", "MOVE_ROLE_SYNTHETIC")
        obs = obstacles(scene, ignored)
        move = Transfer(equipment, source, target, size, mass, rigging, obs)
        reject(name + "_unattached", lambda: move.sample(0.1), "NOT_ATTACHED")
        move.attach()
        reject(name + "_early_unhook", move.detach, "NOT_LANDED")
        # Per-support sweeps retain the HST full 6.6 x 3.7 functional footprint.
        if equipment == "HST1":
            planar = [(p[0], p[1], 0) for p in move.points]
            for dx in (-3.25, 3.25):
                for dy in (-1.7, 1.7):
                    sweep([(x + dx, y + dy, 2.75) for x, y, _ in planar], (0.12, 0.12, 5.5), obs)
            sweep([(p[0], p[1], 5.5) for p in move.points], (6.6, 3.7, 0.2), obs)
        samples = []
        for i in range(241):
            position = move.sample(i / 240)
            scene.set_position(path, position)
            if equipment == "CR1":
                scene.set_crane(position, size[2] - 0.6, size[:2])
            else:
                hp = scene.mapping["HST1"]
                scene.set_position(hp, (position[0], position[1], 0))
                scene.set_position(hp + "/Spreader", (0, 0, position[2] + size[2] - 0.2))
                end = position[2] + size[2] - 0.2
                ops = UsdGeom.Xformable(
                    scene.stage.GetPrimAtPath(hp + "/Rope")
                ).GetOrderedXformOps()
                ops[0].Set(Gf.Vec3d(0, 0, (5.4 + end) / 2))
                ops[-1].Set(Gf.Vec3f(0.04, 0.04, 5.4 - end))
            actual = scene.scene_position(path)
            require(math.dist(actual, position) <= 0.01, "USD_TRANSFER_READBACK")
            samples.append(actual)
            if i % 12 == 0:
                app.update()
        scene.set_position(path, (target[0] + 0.02, target[1], target[2]))
        reject(name + "_wrong_endpoint", lambda: move.land(scene.scene_position(path)), "ARRIVAL")
        scene.set_position(path, target)
        move.land(scene.scene_position(path))
        move.detach()
        scene.state.place(entity, target_zone, target)
        scene.attr(scene.stage.GetPrimAtPath(path), "location", target_zone)
        report["routes"].append(
            {
                "name": name,
                "equipment": equipment,
                "entity": entity,
                "source": source,
                "target": target,
                "mass_t": mass,
                "rigging_t": rigging,
                "sample_count": len(samples),
                "readback_endpoint": samples[-1],
                "obstacles_checked": len(obs),
                "roles": people,
                "reservation": move.reservation,
                "duration_seconds": move.duration_seconds,
                "peak_speed_m_s": move.peak_speed_m_s,
                "speed_limits_m_s": move.speed_limits_m_s,
                "state": move.state,
                "samples": samples,
            }
        )
        checkpoint(report)

    scene.reset("initial")
    for suffix, y in (("BOTTOM", 7.5), ("TOP", 12.5)):
        transfer(
            "MV-IN-" + suffix, "PRODUCT-1." + suffix, "HST1", (16, y, 0.6), "J2", (6, 0.8, 0.8), 2
        )
    scene.reset("dual_frame")
    for suffix, y in (("BOTTOM", 7.5), ("TOP", 12.5)):
        transfer("MV-" + suffix, "PRODUCT-1." + suffix, "HST1", (26, y, 0.6), "BUF", (6, 3, 0.8), 2)
    # Each JOIN-IN component has exactly one source. Columns remain at PRE until move 3.
    for suffix, target, size, mass in (
        ("BOTTOM", (36, 7.5, 0.6), (6, 3, 0.8), 2),
        ("TOP", (36, 12.5, 0.6), (6, 3, 0.8), 2),
        ("COLUMNS", (36, 10, 0.6), (1.6, 1.6, 3.4), 4),
    ):
        transfer("JOIN-IN-" + suffix, "PRODUCT-1." + suffix, "CR1", target, "J3", size, mass)
        report["screenshots"].append(capture("join_" + suffix.lower(), "J3"))
    scene.state.merge()
    scene.fixture = "structure"
    sync_entities(scene)
    require(len(scene.state.entities) == 1, "MERGE_BODY_COUNT")
    for suffix in ("BOTTOM", "TOP", "COLUMNS"):
        prim = scene.stage.GetPrimAtPath(scene.mapping["PRODUCT-1." + suffix])
        require(prim.GetAttribute("s13:consumedInto").Get() == "PRODUCT-1", "MERGE_USD_LINEAGE")
    transfer("J3-F1", "PRODUCT-1", "CR1", (36, 24, 0.6), "F1", (6, 3, 3.8), 8, 1)
    transfer("F1-OUT1", "PRODUCT-1", "CR1", (16, 24, 0.6), "OUT1", (6, 3, 3.8), 8, 1)
    scene.reset("structure")
    scene.state.place("PRODUCT-1", "F1", (36, 24, 0.6))
    sync_entities(scene)
    transfer("F1-Q1_GEOMETRY_ONLY", "PRODUCT-1", "CR1", (26, 24, 0.6), "Q1", (6, 3, 3.8), 8, 1)
    # Fault injection against real registered dimensions.
    scene.shape("/World/InjectedRailObstacle", (25, 0.75, 1), (0.2, 0.2, 2), "red", collision=True)
    rail_box = [b for b in obstacles(scene) if b.name == "/World/InjectedRailObstacle"]
    reject(
        "track_obstacle",
        lambda: Transfer(
            "CR1",
            (36, 10, 0.6),
            (16, 24, 0.6),
            (6, 3, 3.8),
            8,
            1,
            rail_box,
        ),
        "COLLISION",
    )
    scene.stage.RemovePrim("/World/InjectedRailObstacle")
    scene.shape("/World/InjectedLoadObstacle", (36, 17, 2), (0.1, 0.1, 0.1), "red", collision=True)
    load_box = [b for b in obstacles(scene) if b.name == "/World/InjectedLoadObstacle"]
    reject(
        "load_obstacle",
        lambda: Transfer(
            "CR1",
            (36, 10, 0.6),
            (36, 24, 0.6),
            (6, 3, 3.8),
            8,
            1,
            load_box,
        ),
        "COLLISION",
    )
    scene.stage.RemovePrim("/World/InjectedLoadObstacle")
    scene.reset("robot_demo")
    obs = obstacles(scene, [scene.mapping["R1"]])
    for pose in POSES:
        robot_check(pose, obs)
        scene.set_joints(pose)
        expected, _ = fk(pose)
        actual = scene.scene_matrix(scene.tcp_path)
        err = math.dist([expected[k][3] for k in range(3)], actual.ExtractTranslation())
        require(err <= 0.001, "TCP_READBACK")
        report["robot_poses"].append({"angles": pose, "error_m": err, "obstacles": len(obs)})
    tcp = scene.scene_position(scene.tcp_path)
    reject(
        "robot_workpiece_collision",
        lambda: robot_check(POSES[-1], [Box("workpiece", tcp, (0.4, 0.4, 0.4))]),
        "ROBOT_COLLISION",
    )
    continuous_error = 0.0
    for i in range(241):
        q = [a + (b - a) * i / 240 for a, b in zip(POSES[0], POSES[1])]
        expected = robot_check(q, obs)
        scene.set_joints(q)
        err = math.dist([expected[k][3] for k in range(3)], scene.scene_position(scene.tcp_path))
        continuous_error = max(continuous_error, err)
        require(err <= 0.001, "CONTINUOUS_TCP")
        if i % 12 == 0:
            app.update()
    report["robot_continuous"] = {
        "samples": 241,
        "max_position_error_m": continuous_error,
        "obstacles_checked_per_sample": len(obs),
    }
    # Visibility is never a collision or production permission control.
    scene.reset("mep_wait")
    product = scene.mapping["PRODUCT-1"]
    collider = scene.stage.GetPrimAtPath(product + "/Occupancy")
    require(collider.HasAPI(UsdPhysics.CollisionAPI), "HIDDEN_WALL_LOST_COLLISION")
    before = (
        UsdGeom.BBoxCache(0, ["default"], False, True)
        .ComputeWorldBound(collider)
        .ComputeAlignedRange()
    )
    envelope = tuple(before.GetSize())
    require(max(abs(a - b) for a, b in zip(envelope, (6, 3, 3.2))) <= 0.001, "USD_ENVELOPE")
    report["module_envelope_m"] = envelope
    UsdGeom.Imageable(scene.stage.GetPrimAtPath(product + "/B_EN")).MakeInvisible()
    after = (
        UsdGeom.BBoxCache(0, ["default"], False, True)
        .ComputeWorldBound(collider)
        .ComputeAlignedRange()
    )
    require(Gf.IsClose(before.GetSize(), after.GetSize(), 1e-8), "VISIBILITY_CHANGED_OCCUPANCY")
    require(
        scene.state.owners["TEST1"] == "PRODUCT-1" and scene.state.faces == ["WET"],
        "WAIT_OCCUPANCY",
    )
    report["hidden_wall_collision"] = True
    # Mutate the actual USD mappings, then restore before returning the evidence.
    bad = scene.group("/World/Resources/Duplicate")
    scene.attr(bad.GetPrim(), "domainId", "WELD1")
    reject("duplicate_welder_USD", scene.mapping_check, "USD_MAPPING")
    scene.stage.RemovePrim("/World/Resources/Duplicate")
    welder = scene.stage.GetPrimAtPath(scene.mapping["WELD1"])
    scene.attr(welder, "classification", "ROBOT")
    reject("manual_machine_robot_USD", scene.mapping_check, "USD_EQUIPMENT_CLASSIFICATION")
    scene.attr(welder, "classification", "MANUAL_WELDER")
    scene.mapping_check()
    return report
