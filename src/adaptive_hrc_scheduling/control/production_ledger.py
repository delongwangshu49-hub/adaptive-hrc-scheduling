"""Ordered observation delivery, separate from execution time and hidden scenarios."""

import math
from dataclasses import replace

from adaptive_hrc_scheduling.contracts.codec import require
from adaptive_hrc_scheduling.contracts.production import digest, validate


class EventLedger:
    def __init__(self, config, run_id, epoch=0):
        self.config = config
        self.run_id = run_id
        self.epoch = epoch
        self.next_sequence = 1
        self.pending = {}
        self.seen = {}
        self.events = []
        self.stale = []
        self.state = None

    def accept(self, event, *, received_sim_h, wall_elapsed_s):
        validate(event, config=self.config)
        require(
            math.isfinite(received_sim_h)
            and math.isfinite(wall_elapsed_s)
            and received_sim_h >= event.occurred_sim_h
            and wall_elapsed_s >= 0,
            "ARRIVAL_CLOCK",
        )
        if (event.run_id, event.epoch) != (self.run_id, self.epoch):
            self.stale.append((event.id, event.run_id, event.epoch))
            return "STALE_EPOCH"
        fingerprint = digest(event)
        if event.id in self.seen:
            require(self.seen[event.id] == fingerprint, "EVENT_ID_PAYLOAD_CONFLICT")
            return "DUPLICATE"
        require(
            event.sequence >= self.next_sequence and event.sequence not in self.pending,
            "SEQUENCE_REUSE",
        )
        self.seen[event.id] = fingerprint
        self.pending[event.sequence] = replace(
            event, received_sim_h=received_sim_h, wall_elapsed_s=wall_elapsed_s
        )
        while self.next_sequence in self.pending:
            following = self.pending.pop(self.next_sequence)
            require(
                self.state is None
                or following.state.time_h >= self.state.time_h
                and following.state.revision > self.state.revision,
                "STATE_REGRESSION",
            )
            self.events.append(following)
            self.state = following.state
            self.next_sequence += 1
        return "BUFFERED" if self.pending else "APPLIED"

    @property
    def status(self):
        return "INCOMPLETE" if self.pending else "CONTIGUOUS"

    def reset(self, epoch):
        require(epoch > self.epoch, "EPOCH_NOT_ADVANCED")
        self.__init__(self.config, self.run_id, epoch)
