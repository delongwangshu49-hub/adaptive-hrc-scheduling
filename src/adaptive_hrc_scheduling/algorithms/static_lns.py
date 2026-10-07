"""S17 bounded time-slot neighborhoods on the explicit S16 reference domain."""

from dataclasses import replace
from itertools import product
from time import perf_counter

from adaptive_hrc_scheduling.algorithms.lns import Repair, Verification
from adaptive_hrc_scheduling.reference.baselines import rule_schedule
from adaptive_hrc_scheduling.reference.checker import check
from adaptive_hrc_scheduling.reference.domain import Entry, validate


class StaticProblem:
    def __init__(
        self,
        instance,
        fixed_modes,
        *,
        initial=None,
        committed=(),
        rule="EDD",
        initial_trials=100_000,
    ):
        validate(instance)
        if type(initial_trials) is not int or initial_trials < 1:
            raise ValueError("initial_trials")
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
        self.initial_trials = initial_trials

    def initial(self, deadline):
        if self.initial_schedule is not None:
            return Repair(tuple(self.initial_schedule))
        if self.committed:
            return self._committed_initial(deadline)
        result = rule_schedule(
            self.fixed_instance,
            self.rule,
            max_trials=self.initial_trials,
            wall_seconds=max(0, deadline - perf_counter()),
        )
        return Repair(
            result.schedule if result.status == "FEASIBLE" else None,
            result.trials,
            (result.status,),
        )

    def _partial_findings(self, entries):
        """Safe pruning of a partial assignment with all locked slots present.

        Missing ancestors and unfinished residency suffixes may still be filled.
        Ignore only those optimistic partial findings; no partial assignment is
        returned or ranked as a feasible plan. Complete output uses verify().
        """
        report = check(self.fixed_instance, entries, partial=True)
        assigned = {e.task_id: e for e in entries}
        tasks = {t.id: t for t in self.fixed_instance.tasks}
        open_resources = set()
        for p in self.fixed_instance.products:
            if p.ready in assigned and p.store not in assigned:
                open_resources.add(p.output)
            if p.store in assigned and p.receive not in assigned:
                open_resources.add(p.buffer)
        findings = []
        for finding in report.findings:
            if finding.startswith("PRECEDENCE:"):
                ident = finding.split(":", 1)[1]
                predecessors = tasks[ident].predecessors
                if any(p not in assigned for p in predecessors) and all(
                    p not in assigned or assigned[p].end <= assigned[ident].start
                    for p in predecessors
                ):
                    continue
            if finding.startswith("CAPACITY:") and finding.split(":", 2)[1] in open_resources:
                continue
            findings.append(finding)
        return tuple(findings)

    def _committed_initial(self, deadline):
        if self.rule not in ("EDD", "SPT", "FASTEST_MODE"):
            raise ValueError("rule")
        tasks = {t.id: t for t in self.fixed_instance.tasks}
        assigned = {e.task_id: e for e in self.committed}
        failures = self._partial_findings(tuple(assigned.values()))
        if failures:
            return Repair(None, 0, ("INVALID_COMMITMENT",) + failures, "INVALID_COMMITMENT")
        due = {p.receive: p.due for p in self.fixed_instance.products}
        for _ in tasks:
            for task in tasks.values():
                for predecessor in task.predecessors:
                    if task.id in due:
                        due[predecessor] = min(due.get(predecessor, float("inf")), due[task.id])
        tried = 0
        stopped = None

        answer = None
        frames = []
        while True:
            if len(assigned) == len(tasks):
                proposed = tuple(assigned[t.id] for t in self.fixed_instance.tasks)
                if self.verify(proposed).valid:
                    answer = proposed
                    break
            if perf_counter() >= deadline:
                stopped = "WALL_BUDGET"
                break
            eligible = [
                t
                for t in tasks.values()
                if t.id not in assigned and set(t.predecessors) <= assigned.keys()
            ]
            if eligible:
                task = min(
                    eligible,
                    key=lambda t: (
                        t.alternatives[0].duration
                        if self.rule == "SPT"
                        else due.get(t.id, float("inf")),
                        t.id,
                    ),
                )
                alt = task.alternatives[0]
                lower = max([task.release] + [assigned[p].end for p in task.predecessors])
                upper = (
                    min(
                        self.instance.horizon,
                        task.latest_end if task.latest_end is not None else self.instance.horizon,
                    )
                    - alt.duration
                )
                frames.append((task, alt, iter(range(lower, upper + 1))))
            # An explicit stack keeps the trial/wall limits independent of
            # Python's recursion depth, without allocating a Cartesian product.
            while frames:
                task, alt, starts = frames[-1]
                assigned.pop(task.id, None)
                start = next(starts, None)
                if start is None:
                    frames.pop()
                    continue
                if perf_counter() >= deadline:
                    stopped = "WALL_BUDGET"
                    break
                if tried >= self.initial_trials:
                    stopped = "INITIAL_TRIAL_BUDGET"
                    break
                tried += 1
                assigned[task.id] = Entry(task.id, alt.id, start, start + alt.duration)
                if not self._partial_findings(tuple(assigned.values())):
                    break
            if stopped or not frames:
                break
        reason = stopped or ("FEASIBLE" if answer is not None else "NO_PLAN_FOUND")
        return Repair(
            answer, tried, (reason,), "COMMITTED_INITIAL" if answer is not None else reason
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
