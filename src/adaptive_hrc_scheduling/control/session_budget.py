"""A measured total account with reserved complete-search slots for changes."""

import math
from dataclasses import asdict, dataclass

from adaptive_hrc_scheduling.contracts.codec import require
from adaptive_hrc_scheduling.contracts.session import digest
from adaptive_hrc_scheduling.control.online import Limits


@dataclass(frozen=True)
class Profile:
    id: str
    limits: Limits
    total_seconds: float
    change_reserve_calls: int
    objective: str = "S18_PROGRESS_THEN_EXPOSURE_LEXICOGRAPHIC"

    def validate(self):
        self.limits.validate()
        require(
            type(self.total_seconds) in (float, int) and math.isfinite(self.total_seconds),
            "TOTAL_BUDGET_INVALID",
        )
        require(self.limits.search_seconds > 0.05, "FULL_JOINT_PROFILE_REQUIRED")
        require(
            type(self.change_reserve_calls) is int and self.change_reserve_calls >= 1,
            "CHANGE_RESERVE_REQUIRED",
        )
        require(
            self.total_seconds >= (self.change_reserve_calls + 1) * self.limits.decision_seconds,
            "TOTAL_RESERVE_TOO_SMALL",
        )
        require(
            self.objective
            in (
                "S18_PROGRESS_THEN_EXPOSURE_LEXICOGRAPHIC",
                "P042_URGENCY_DUE_PROGRESS_EXPOSURE-r1",
            ),
            "OBJECTIVE_UNKNOWN",
        )

    @property
    def sha256(self):
        return digest(asdict(self))


class BudgetAccount:
    def __init__(self, profile):
        profile.validate()
        self.profile = profile
        self.used = 0.0
        self.change_calls = 0
        self.entries = []

    def allowance(self, trigger):
        remaining = max(0.0, self.profile.total_seconds - self.used)
        reserve = max(0, self.profile.change_reserve_calls - self.change_calls)
        if trigger not in ("FEEDBACK", "CATALOG_CHANGED"):
            remaining = max(0.0, remaining - reserve * self.profile.limits.decision_seconds)
        return min(self.profile.limits.decision_seconds, remaining)

    def can_search(self, trigger):
        # Do not spend a protected slot on a rollout that cannot fit a complete slice.
        return self.allowance(trigger) >= self.profile.limits.decision_seconds - 1e-9

    def charge(self, row):
        elapsed = row.get("cycle_seconds", row["decision_seconds"])
        if row.get("search_call") and row.get("trigger") in ("FEEDBACK", "CATALOG_CHANGED"):
            self.change_calls += 1
        self.used += elapsed
        entry = dict(
            sequence=row["sequence"],
            trigger=row["trigger"],
            elapsed_s=elapsed,
            used_s=self.used,
            remaining_s=max(0.0, self.profile.total_seconds - self.used),
            overrun_s=max(0.0, self.used - self.profile.total_seconds),
        )
        self.entries.append(entry)
        row["total_budget"] = entry

    def report(self):
        return dict(
            profile=asdict(self.profile),
            profile_sha256=self.profile.sha256,
            used_s=self.used,
            change_searches=self.change_calls,
            entries=self.entries,
        )


def load_profile(data):
    require(
        type(data) is dict
        and set(data) == {"id", "limits", "total_seconds", "change_reserve_calls", "objective"},
        "PROFILE_FIELDS",
    )
    profile = Profile(**{**data, "limits": Limits(**data["limits"])})
    profile.validate()
    return profile
