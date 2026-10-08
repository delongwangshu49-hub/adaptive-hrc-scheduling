"""Independent SYNTHETIC_TEST_ONLY receiver with finite USD transport evidence."""

import math

from adaptive_hrc_scheduling.contracts.codec import require
from adaptive_hrc_scheduling.production_external import duration, is_external, path

from .model import key, sweep


def check_boundary_path(points, size, obstacles):
    sweep(tuple((x, y, z + size[2] / 2) for x, y, z in points), size, obstacles)


class SyntheticReceiver:
    def __init__(self, port):
        require(
            port.config.purpose in ("SYNTHETIC_TEST_ONLY", "SIMULATION_RESEARCH_ONLY"),
            "SYNTHETIC_RECEIVER_ONLY",
        )
        self.port = port
        self.runs = {}
        self.samples = []

    def step(self, run, now_h):
        port, scene = self.port, self.port.scene
        op = port.ops[run.command.operation_id]
        if not is_external(op):
            return
        ident = run.command.id
        if ident not in self.runs:
            points = path(port.config, op)
            require(math.dist(port.position(op.entity_id), points[0]) < 0.002, "RECEIVER_SOURCE")
            size = port.loads[op.entity_id].size_m
            check_boundary_path(points, size, scene.actual_obstacles((op.entity_id,)))
            self.runs[ident] = (run.started_h, points, size, 0.0)
            self.samples.append((ident, run.started_h, points[0], "ATTACHED"))
        started, points, size, previous = self.runs[ident]
        travel = (
            duration(port.config, op)
            - port.config.setup_h
            - port.config.load_h
            - port.config.unload_h
        )
        elapsed = max(0, min(travel, now_h - started - port.config.setup_h - port.config.load_h))
        fraction = elapsed / travel
        require(fraction >= previous, "RECEIVER_CLOCK_REVERSED")
        # Explicit finite samples, including intermediate readbacks even when
        # the event engine advances directly to the next completion time.
        steps = max(1, math.ceil((fraction - previous) * travel * 3600))
        obstacles = scene.actual_obstacles((op.entity_id,))
        fractions = {previous + (fraction - previous) * i / steps for i in range(1, steps + 1)}
        corner_seconds = 0
        for a, b in zip(points, points[1:]):
            corner_seconds += (abs(b[0] - a[0]) + abs(b[1] - a[1])) / 0.5 + abs(b[2] - a[2]) / 0.2
            corner = corner_seconds / (travel * 3600)
            if previous < corner < fraction:
                fractions.add(corner)
        for f in sorted(fractions):
            remaining = f * travel * 3600
            point = points[-1]
            for a, b in zip(points, points[1:]):
                seconds = (abs(b[0] - a[0]) + abs(b[1] - a[1])) / 0.5 + abs(b[2] - a[2]) / 0.2
                if remaining <= seconds and seconds:
                    point = tuple(x + (y - x) * remaining / seconds for x, y in zip(a, b))
                    break
                remaining -= seconds
            before = port.position(op.entity_id)
            check_boundary_path((before, point), size, obstacles)
            scene.set_position(port.mapping[op.entity_id], point)
            actual = port.position(op.entity_id)
            require(math.dist(actual, point) <= 0.002, "RECEIVER_ACTUAL_POSITION")
            port.expected[op.entity_id] = actual
            self.samples.append(
                (
                    ident,
                    started + port.config.setup_h + port.config.load_h + f * travel,
                    actual,
                    "MOVING",
                )
            )
        self.runs[ident] = (started, points, size, fraction)
        if now_h + 1e-10 < started + duration(port.config, op):
            return
        receiver_path = "/World/S15/Receiver/" + key(ident)
        receiver = scene.group(receiver_path).GetPrim()
        x, y, z = points[-1]
        scene.shape(
            receiver_path + "/Deck",
            (x, y, z / 2),
            (size[0] + 0.2, size[1] + 0.2, z),
            "blue",
            collision=True,
        )
        for field, value in {
            "runId": port.run_id,
            "epoch": port.epoch,
            "commandId": ident,
            "productId": op.product_id,
            "receiptId": "EXTERNAL-" + ident,
        }.items():
            scene.attr(receiver, field, value)
        self.samples.append((ident, now_h, port.position(op.entity_id), "RECEIVED"))
