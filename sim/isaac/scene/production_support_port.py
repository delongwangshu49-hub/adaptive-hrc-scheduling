"""Persistent USD support attachments; every change is timed and read back."""

import math
from dataclasses import replace

from pxr import UsdGeom, UsdPhysics

from adaptive_hrc_scheduling import production_supports as support
from adaptive_hrc_scheduling.contracts.codec import require
from adaptive_hrc_scheduling.domain import production as m

from .model import Box, key, sweep


class SupportPort:
    def __init__(self, parent):
        self.parent = parent
        self.scene, self.config = parent.scene, parent.config
        self.layouts = {x.id: x for x in self.config.support_layouts}
        self.states = {s.root: s for s in support.initial(self.config)}
        self.previous = {}
        for state in self.states.values():
            for beam in state.beams:
                ident = self.ident(state.root, beam.index)
                path = "/World/S15/Supports/" + key(ident)
                self.scene.ident(ident, path, beam.position)
                self.scene.shape(
                    path + "/Body", (0, 0, 0), support.BEAM_SIZE, "light", collision=True
                )
                parent.expected[ident] = beam.position
                x, y, z = beam.position
                name = "SC-HOLDER-" + state.root + "-" + str(beam.index)
                self.scene.shape(
                    "/World/Static/" + key(name),
                    (x, y, z - 0.0225),
                    (0.06, 0.5, 0.005),
                    "light",
                    collision=True,
                )
                self.scene.attr(
                    self.scene.stage.GetPrimAtPath("/World/Static/" + key(name)), "obstacleId", name
                )

    @staticmethod
    def ident(root, index):
        return f"SC-{root}-{index}"

    def read(self, root):
        rows = []
        for index in range(22):
            ident = self.ident(root, index)
            prim = self.parent.prim(ident)
            body = self.scene.stage.GetPrimAtPath(self.parent.mapping[ident] + "/Body")
            rows.append(
                m.BeamReadback(
                    index,
                    self.parent.position(ident),
                    UsdGeom.Imageable(body).ComputeVisibility() != UsdGeom.Tokens.invisible,
                    bool(
                        body.HasAPI(UsdPhysics.CollisionAPI)
                        and UsdPhysics.CollisionAPI(body).GetCollisionEnabledAttr().Get()
                    ),
                )
            )
            require(prim.GetAttribute("s13:sceneId").Get() == ident, "ACTUAL_SUPPORT_IDENTITY")
        return tuple(rows)

    def expected(self, root):
        samples = self.read(root)
        for sample in samples:
            self.parent.check_actual(self.ident(root, sample.index))
            require(sample.visible and sample.collision_enabled, "ACTUAL_SUPPORT_DISABLED")
        return samples

    @staticmethod
    def suffix(points, distance):
        for index, (a, b) in enumerate(zip(points, points[1:])):
            length = math.dist(a, b)
            if distance <= length:
                ratio = distance / length if length else 1
                p = tuple(v + ratio * (w - v) for v, w in zip(a, b))
                return (p, *points[index + 1 :])
            distance -= length
        return (points[-1], points[-1])

    def check_paths(self, command, elapsed=0):
        op = self.parent.ops[command.operation_id]
        layout = self.layouts[op.support_layout_id]
        old = self.previous.get(
            command.id,
            self.previous.get(
                command.resume_of, self.layouts.get(self.states[layout.root].layout_id)
            ),
        )
        actual = self.expected(layout.root)
        expected = support.sample(self.config, old, layout, elapsed)
        require(
            all(math.dist(a.position, b.position) <= 0.002 for a, b in zip(actual, expected)),
            "ACTUAL_SUPPORT_PROGRESS_DRIFT",
        )
        ids = tuple(self.ident(layout.root, i) for i in range(22))
        fixed = self.scene.actual_obstacles(ids)
        positions = {b.index: b.position for b in actual}
        for move in support.movements(self.config, old, layout):
            if elapsed >= move.end_h - 1e-12:
                continue
            moving = {2 * move.pair_index, 2 * move.pair_index + 1}
            obstacles = fixed + [
                Box(self.ident(layout.root, i), p, support.BEAM_SIZE)
                for i, p in positions.items()
                if i not in moving
            ]
            for side, path in enumerate(move.paths):
                remaining = self.suffix(
                    path, max(0, elapsed - move.start_h) * 3600 * support.SPEED_M_S
                )
                sweep(remaining, support.BEAM_SIZE, obstacles)
                positions[2 * move.pair_index + side] = path[-1]

    def start(self, run):
        layout = self.layouts[self.parent.ops[run.command.operation_id].support_layout_id]
        self.previous[run.command.id] = self.previous.get(
            run.command.resume_of, self.layouts.get(self.states[layout.root].layout_id)
        )

    def step(self, run, now):
        op = self.parent.ops[run.command.operation_id]
        layout = self.layouts[op.support_layout_id]
        old = self.previous[run.command.id]
        elapsed = run.active_before_h + now - run.started_h
        # Check the remaining interval against actual current occupancy, including
        # every other beam. The moving pair remains explicitly represented.
        prior_elapsed = getattr(self, "sampled", {}).get(run.command.id, run.active_before_h)
        self.check_paths(run.command, prior_elapsed)
        for pose in support.sample(self.config, old, layout, elapsed):
            self.parent.put(self.ident(layout.root, pose.index), pose.position)
        rows = self.expected(layout.root)
        done = now + 1e-10 >= run.earliest_end_h
        self.states[layout.root] = replace(
            self.states[layout.root],
            layout_id=layout.id if done else self.states[layout.root].layout_id,
            beams=tuple(m.BeamPose(p.index, p.position) for p in rows),
        )
        if not hasattr(self, "sampled"):
            self.sampled = {}
        self.sampled[run.command.id] = elapsed
        proof = m.Readback(
            "ISAAC_USD",
            self.parent.run_id,
            self.parent.epoch,
            run.command.id,
            now,
            None,
            layout.root if done else "IN_TRANSIT",
            layout.root,
            self.parent.places[layout.root],
            op.role_locations,
            True,
            True,
            True,
            done,
            done,
            False,
            "USD-SUPPORT-" + run.command.id + "-" + str(len(self.parent.samples)),
            1 if done else min(elapsed / support.duration(self.config, old, layout), 1 - 1e-12),
            beams=rows,
        )
        self.parent.samples.append(proof)
        return proof

    def for_location(self, location):
        point = self.parent.places[location]
        for state in self.states.values():
            layout = self.layouts.get(state.layout_id)
            if layout:
                contact = next((c for c in layout.contacts if c.position == point), None)
                if contact:
                    self.expected(layout.root)
                    return [
                        self.scene.stage.GetPrimAtPath(
                            self.parent.mapping[
                                self.ident(layout.root, 2 * contact.pair_index + side)
                            ]
                            + "/Body"
                        )
                        for side in range(2)
                    ]
        return []
