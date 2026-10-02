"""Deterministic priorities applied only after dispatch admission."""

from dataclasses import dataclass

from adaptive_hrc_scheduling.domain.building import DispatchCommand

RULES = ("EDD", "SPT", "FASTEST_MODE")


@dataclass(frozen=True)
class Candidate:
    command: DispatchCommand
    product_id: str
    due_h: float
    estimated_remaining_h: float

    @property
    def tie(self):
        c = self.command
        return (
            self.product_id,
            c.activity_id,
            c.mode_id,
            tuple((r.role_id, r.person_id) for r in c.roles),
        )


def select(candidates, rule):
    """SPT uses remaining activity work at current fatigue, excluding passive waits.

    FASTEST_MODE first chooses the fastest currently admissible mode/binding per
    activity, then EDD across activities. Estimates never certify completion.
    """
    if rule not in RULES:
        raise ValueError("unknown rule")
    if not candidates:
        raise ValueError("no legal candidates")
    if rule == "FASTEST_MODE":
        best = {}
        for c in sorted(candidates, key=lambda c: (c.estimated_remaining_h, c.tie)):
            best.setdefault(c.command.activity_id, c)
        candidates = tuple(best.values())
    return min(
        candidates, key=lambda c: (c.estimated_remaining_h if rule == "SPT" else c.due_h, c.tie)
    )
