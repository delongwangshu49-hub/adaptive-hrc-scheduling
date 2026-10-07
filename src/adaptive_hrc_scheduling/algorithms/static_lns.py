"""S17 bounded time-slot neighborhoods on the explicit S16 reference domain."""

from dataclasses import replace
from itertools import product
from time import perf_counter

from adaptive_hrc_scheduling.algorithms.lns import Repair, Verification
from adaptive_hrc_scheduling.reference.baselines import rule_schedule
from adaptive_hrc_scheduling.reference.checker import check
from adaptive_hrc_scheduling.reference.domain import Entry, validate


class StaticProblem:
    def __init__(self, instance, fixed_modes, *, initial=None, committed=(), rule="EDD"):
        validate(instance)
        if set(fixed_modes) != {t.id for t in instance.tasks}:
            raise ValueError("explicit fixed mode required for every task")
        for task in instance.tasks:
            if fixed_modes[task.id] not in {a.id for a in task.alternatives}:
                raise ValueError("unknown fixed mode")
        self.instance = instance
        self.fixed_modes = dict(fixed_modes)
        self.fixed_instance = replace(
            instance,
            tasks=tuple(
                replace(
                    t, alternatives=tuple(a for a in t.alternatives if a.id == fixed_modes[t.id])
                )
                for t in instance.tasks
            ),
        )
        self.initial_schedule = initial
        self.committed = tuple(committed)
        if len({e.task_id for e in self.committed}) != len(self.committed):
            raise ValueError("duplicate commitment")
        if any(e.task_id not in self.fixed_modes for e in self.committed):
            raise ValueError("unknown commitment")
        self.rule = rule

    def initial(self, deadline):
        if self.initial_schedule is not None:
            return Repair(tuple(self.initial_schedule))
        result = rule_schedule(
            self.fixed_instance, self.rule, wall_seconds=max(0, deadline - perf_counter())
        )
        return Repair(
            result.schedule if result.status == "FEASIBLE" else None,
            result.trials,
            (result.status,),
        )

    def mutable(self, candidate):
        locked = {e.task_id for e in self.committed}
        return tuple(e.task_id for e in candidate if e.task_id not in locked)

    def verify(self, candidate):
        try:
            report = check(self.instance, candidate)
            reasons = report.findings
            if any(e.alternative_id != self.fixed_modes[e.task_id] for e in candidate):
                reasons += ("FIXED_MODE_CHANGED",)
            by_id = {e.task_id: e for e in candidate}
            if any(by_id.get(e.task_id) != e for e in self.committed):
                reasons += ("COMMITMENT_CHANGED",)
            return Verification(not reasons, (report.objective,) if not reasons else None, reasons)
        except (ValueError, TypeError, KeyError, AttributeError) as exc:
            return Verification(False, None, ("MALFORMED_CANDIDATE:" + str(exc),))

    def repair(self, candidate, removed, rng, trials, deadline):
        by_id = {e.task_id: e for e in candidate}
        tasks = {t.id: t for t in self.fixed_instance.tasks}
        domains = []
        for ident in removed:
            task = tasks[ident]
            alt = task.alternatives[0]
            upper = min(self.instance.horizon, task.latest_end or self.instance.horizon)
            starts = list(range(task.release, upper - alt.duration + 1))
            rng.shuffle(starts)
            domains.append(tuple(Entry(ident, alt.id, s, s + alt.duration) for s in starts))
        best, score, tried, failures = None, None, 0, set()
        termination = "NEIGHBORHOOD_EXHAUSTED"
        for replacements in product(*domains):
            if perf_counter() >= deadline:
                termination = "WALL_BUDGET"
                break
            if tried >= trials:
                termination = "REPAIR_TRIAL_BUDGET"
                break
            tried += 1
            entries = by_id | {e.task_id: e for e in replacements}
            proposed = tuple(entries[t.id] for t in self.instance.tasks)
            checked = self.verify(proposed)
            if checked.valid and (score is None or checked.score < score):
                best, score = proposed, checked.score
            elif not checked.valid:
                failures.update(checked.reasons)
        return Repair(best, tried, tuple(sorted(failures)), termination)
