"""Execution-side port for S14. Kit imports stay outside the installable CPU package.

The port owns motion and reads USD. A returned dispatch receipt never completes
work. Only correlated readback or an explicit exception can end a running unit.
"""

import math
import time

from adaptive_hrc_scheduling.contracts.codec import ContractError, require
from adaptive_hrc_scheduling.control.logistics_ledger import EventLedger
from adaptive_hrc_scheduling.logistics_backend import LogisticsBackend


class IsaacAdapter:
    def __init__(self, config, port, *, run_id="RUN-S14-ISAAC", epoch=0):
        self.world = LogisticsBackend(config, run_id=run_id, epoch=epoch, backend="isaac-usd")
        self.port = port
        self.ledger = EventLedger(config, run_id, epoch)
        self.sim_seconds = 0.0
        self.wall_start = time.monotonic()
        self.stale_callbacks = []
        self.published = 0
        self.delivery_queue = []
        self.world_port_error = None
        self.port.reset(config, run_id, epoch)

    def dispatch(self, command):
        require(self.world_port_error is None, "WORLD_PORT_FAILURE_RESET_REQUIRED")
        duplicate = command.id in self.world.commands

        def preflight(command):
            try:
                self.port.preflight(command)
            except Exception as exc:
                raise ContractError("ACTUAL_PREFLIGHT:" + str(exc)) from exc

        receipt = self.world.dispatch(command, preflight=preflight)
        if receipt.kind == "STARTED" and not duplicate:
            run = next(r for r in self.world.s.running if r.command.id == command.id)
            try:
                self.port.start(run)
            except Exception as exc:
                receipt = self.world.exception(command.id, "PORT_START:" + str(exc))
        return receipt

    def advance(self, seconds, *, playing=True):
        require(self.world_port_error is None, "WORLD_PORT_FAILURE_RESET_REQUIRED")
        require(math.isfinite(seconds) and seconds >= 0, "INVALID_SIMULATION_DELTA")
        if not playing:
            return ()
        self.sim_seconds += seconds
        self.world.advance(self.sim_seconds / 3600, auto_complete=False)
        results = []
        for run in tuple(self.world.s.running):
            if run.status != "STARTED":
                continue
            try:
                proof = self.port.step(run.command.id, self.world.s.time_h)
                if proof is not None:
                    results.append(self.feedback(proof))
            except Exception as exc:
                results.append(self.world.exception(run.command.id, "ACTUAL_EXECUTION:" + str(exc)))
        return tuple(results)

    def feedback(self, proof):
        if (proof.run_id, proof.epoch) != (self.world.run_id, self.world.epoch):
            self.stale_callbacks.append(proof)
            return "STALE_EPOCH"
        run = next((r for r in self.world.s.running if r.command.id == proof.command_id), None)
        if run is None:
            receipt = self.world.commands.get(proof.command_id)
            require(
                receipt is not None
                and receipt[1].kind == "COMPLETED"
                and receipt[1].readback == proof,
                "UNEXPECTED_CALLBACK",
            )
            return receipt[1]
        if proof.location == "IN_TRANSIT":
            return self.world.progress(proof.command_id, proof)
        return self.world.complete(proof.command_id, proof)

    def apply_world(self, event):
        require(self.world_port_error is None, "WORLD_PORT_FAILURE_RESET_REQUIRED")
        receipt = self.world.apply_world(event)
        if receipt is not None:
            try:
                self.port.world_event(event)
            except Exception as exc:
                # A partially applied external effect cannot safely be replayed.
                self.world_port_error = str(exc)
                raise ContractError("WORLD_PORT_FAILURE_RESET_REQUIRED") from exc
        return receipt

    def deliver(self, *, delay_h=0):
        require(math.isfinite(delay_h) and delay_h >= 0, "OBSERVATION_DELAY")
        for event in self.world.events[self.published :]:
            self.delivery_queue.append((self.world.s.time_h + delay_h, event))
        self.published = len(self.world.events)
        waiting = []
        for due, event in self.delivery_queue:
            if due <= self.world.s.time_h:
                self.ledger.accept(
                    event,
                    received_sim_h=self.world.s.time_h,
                    wall_elapsed_s=time.monotonic() - self.wall_start,
                )
            else:
                waiting.append((due, event))
        self.delivery_queue = waiting
        return self.ledger.state

    def reset(self):
        config, run_id, epoch = self.world.config, self.world.run_id, self.world.epoch + 1
        self.__init__(config, self.port, run_id=run_id, epoch=epoch)
