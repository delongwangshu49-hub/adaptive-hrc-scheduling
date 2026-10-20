"""Explicit S20 objectives; the S18 lexicographic default remains unchanged."""

import math
from dataclasses import dataclass

from adaptive_hrc_scheduling.contracts.codec import require


@dataclass(frozen=True)
class WeightedObjective:
    weight: float
    horizon_h: float = 720
    version: str = "D_WEIGHTED_r1"

    def validate(self):
        require(self.version == "D_WEIGHTED_r1", "D_OBJECTIVE_VERSION")
        require(
            type(self.weight) in (int, float)
            and math.isfinite(self.weight)
            and 0 <= self.weight <= 1,
            "D_OBJECTIVE_WEIGHT",
        )
        require(
            type(self.horizon_h) in (int, float)
            and math.isfinite(self.horizon_h)
            and self.horizon_h > 0,
            "D_OBJECTIVE_HORIZON",
        )

    def score(self, config, completed, exposure, max_exposure, candidate_sha256):
        self.validate()
        total = len(config.core_activities)
        require(type(completed) is int and 0 <= completed <= total, "D_PROGRESS")
        require(
            all(
                type(v) in (int, float) and math.isfinite(v) and v >= 0
                for v in (exposure, max_exposure)
            ),
            "D_EXPOSURE",
        )
        require(
            type(candidate_sha256) is str
            and len(candidate_sha256) == 64
            and all(c in "0123456789abcdef" for c in candidate_sha256),
            "D_FINGERPRINT",
        )
        require(total > 0 and config.people and config.cap > 0, "D_NORMALIZATION")
        value = self.weight * (1 - completed / total) + (1 - self.weight) * exposure / (
            len(config.people) * config.cap * self.horizon_h
        )
        # LNS requires numeric scores. An integer retains the complete stable hash.
        return value, max_exposure, int(candidate_sha256, 16)
