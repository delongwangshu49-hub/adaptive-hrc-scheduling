"""S16 matched-domain rules and deliberately bounded independent Cartesian oracle."""

import math
from dataclasses import dataclass
from itertools import product
from time import perf_counter

from adaptive_hrc_scheduling.reference.checker import check
from adaptive_hrc_scheduling.reference.domain import Entry, digest, validate


@dataclass(frozen=True)
class RuleResult:
    status: str
    schedule: tuple[Entry, ...]
    objective: int | None
    instance_sha256: str
    rule: str
    trials: int
    wall_seconds: float


def rule_schedule(instance, rule="EDD", *, max_trials=100_000, wall_seconds=10.0):
    validate(instance)
    if rule not in ("EDD", "SPT", "FASTEST_MODE"):
        raise ValueError("rule")
    if (
        type(max_trials) is not int
        or max_trials < 1
        or type(wall_seconds) not in (float, int)
        or not math.isfinite(wall_seconds)
        or wall_seconds < 0
    ):
        raise ValueError("budget")
    began = perf_counter()
    entries, trials = (), 0
    pending = {t.id: t for t in instance.tasks}
    due = {p.receive: p.due for p in instance.products}
    # The objective measures external receipt. Propagate its due date to every
    # ancestor, retaining dates beyond the horizon and the earliest shared due.
    for _ in instance.tasks:
        for task in instance.tasks:
            for pred in task.predecessors:
                if task.id in due:
                    due[pred] = min(due.get(pred, math.inf), due[task.id])
    while pending:
        assigned = {e.task_id: e for e in entries}
        eligible = [t for t in pending.values() if set(t.predecessors) <= set(assigned)]

        def priority(t):
            duration = min(a.duration for a in t.alternatives)
            return (duration if rule == "SPT" else due.get(t.id, math.inf), t.id)

        accepted = None
        for task in sorted(eligible, key=priority):
            lower = max([task.release] + [assigned[p].end for p in task.predecessors])
            candidates = sorted(
                task.alternatives,
                key=lambda a: (a.id,) if rule == "EDD" else (a.duration, a.cost, a.id),
            )
            for start in range(lower, instance.horizon):
                for alt in candidates:
                    trials += 1
                    if trials > max_trials or perf_counter() - began >= wall_seconds:
                        return RuleResult(
                            "BUDGET_EXHAUSTED",
                            entries,
                            None,
                            digest(instance),
                            rule,
                            trials,
                            perf_counter() - began,
                        )
                    entry = Entry(task.id, alt.id, start, start + alt.duration)
                    if check(instance, entries + (entry,), partial=True).valid:
                        accepted = entry
                        break
                if accepted:
                    break
            if accepted:
                break
        if accepted is None:
            return RuleResult(
                "NO_PLAN_FOUND",
                entries,
                None,
                digest(instance),
                rule,
                trials,
                perf_counter() - began,
            )
        entries += (accepted,)
        del pending[accepted.task_id]
    entries = tuple(
        sorted(
            entries,
            key=lambda e: next(i for i, t in enumerate(instance.tasks) if t.id == e.task_id),
        )
    )
    report = check(instance, entries)
    if not report.valid:
        raise RuntimeError("matched rule output failed independent check")
    return RuleResult(
        "FEASIBLE",
        entries,
        report.objective,
        digest(instance),
        rule,
        trials,
        perf_counter() - began,
    )


def enumerate_independent(instance, *, max_candidates=1_000_000):
    validate(instance)
    domains = [
        tuple(
            Entry(t.id, a.id, s, s + a.duration)
            for a in t.alternatives
            for s in range(instance.horizon - a.duration + 1)
        )
        for t in instance.tasks
    ]
    count = 1
    for domain in domains:
        count *= len(domain)
    if count > max_candidates:
        raise ValueError("oracle candidate budget exceeded; not an exhaustive proof")
    return {schedule for schedule in product(*domains) if check(instance, schedule).valid}
