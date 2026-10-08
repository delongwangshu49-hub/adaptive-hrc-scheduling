"""Predeclared paired budgets and complete-window S18 production proposals."""

import math
from dataclasses import asdict, dataclass, replace
from time import perf_counter
from types import SimpleNamespace

from adaptive_hrc_scheduling.algorithms.lns import Options, fingerprint, search
from adaptive_hrc_scheduling.algorithms.simulation_joint import SimulationJointProblem, terminal
from adaptive_hrc_scheduling.contracts.codec import ContractError, require
from adaptive_hrc_scheduling.contracts.production import digest, validate
from adaptive_hrc_scheduling.control.production_decisions import record
from adaptive_hrc_scheduling.domain import production as m


@dataclass(frozen=True)
class Budget:
    max_calls: int
    max_iterations: int
    max_repair_trials: int
    max_wall_seconds: float
    per_call_iterations: int
    per_call_trials: int
    per_call_wall_seconds: float
    opportunities_h: tuple[float, ...]
    future_window_h: float

    def validate(self):
        require(
            all(
                type(v) is int and v > 0
                for v in (
                    self.max_calls,
                    self.max_iterations,
                    self.max_repair_trials,
                    self.per_call_iterations,
                    self.per_call_trials,
                )
            ),
            "SEARCH_BUDGET_COUNTS",
        )
        require(
            math.isfinite(self.max_wall_seconds)
            and math.isfinite(self.per_call_wall_seconds)
            and math.isfinite(self.future_window_h)
            and self.max_wall_seconds > 0
            and self.per_call_wall_seconds > 0
            and self.future_window_h > 0
            and self.opportunities_h
            and all(type(t) in (int, float) and math.isfinite(t) for t in self.opportunities_h)
            and self.opportunities_h[0] >= 0
            and all(a < b for a, b in zip(self.opportunities_h, self.opportunities_h[1:])),
            "SEARCH_BUDGET_WINDOWS",
        )


class BudgetLedger:
    def __init__(self, budget):
        budget.validate()
        self.declared = budget
        self.calls = self.iterations = self.trials = self.validation_calls = 0
        self.wall_seconds = self.validation_seconds = 0.0
        self.records = []

    def allocation(self):
        b = self.declared
        trials = b.max_repair_trials - self.trials - 1
        iterations = min(
            b.per_call_iterations, b.max_iterations - self.iterations, trials // b.per_call_trials
        )
        wall = min(b.per_call_wall_seconds, b.max_wall_seconds - self.wall_seconds)
        if self.calls >= b.max_calls or trials < 0 or iterations < 0 or wall <= 0:
            return None
        return Options(
            seed=self.calls,
            iterations=iterations,
            destroy_size=2,
            repair_trials=b.per_call_trials,
            wall_seconds=wall,
            stagnation=max(1, iterations),
            accept_equal=True,
        )

    def consume(self, result, elapsed, problem):
        self.calls += 1
        iterations = len(result.history) if result is not None else 0
        trials = 1 + sum(h.trials for h in result.history) if result is not None else 1
        # Started work remains chargeable even if search returns no Result.
        iterations = max(iterations, getattr(problem, "search_iterations", 0))
        trials = max(trials, getattr(problem, "search_trials", 0))
        self.iterations += iterations
        self.trials += trials
        self.wall_seconds += elapsed
        validations = getattr(problem, "validation_calls", 0)
        seconds = getattr(problem, "validation_seconds", 0)
        self.validation_calls += validations
        self.validation_seconds += seconds
        b = self.declared
        within = (
            self.calls <= b.max_calls
            and self.iterations <= b.max_iterations
            and self.trials <= b.max_repair_trials
            and self.wall_seconds <= b.max_wall_seconds
            and elapsed <= b.per_call_wall_seconds
        )
        self.records.append(
            dict(
                call=self.calls,
                iterations=iterations,
                repair_trials=trials,
                wall_seconds=elapsed,
                validation_calls=validations,
                validation_seconds=seconds,
                cumulative_iterations=self.iterations,
                cumulative_repair_trials=self.trials,
                cumulative_wall_seconds=self.wall_seconds,
                within_budget=within,
            )
        )
        return within

    def report(self):
        return dict(
            declared=asdict(self.declared),
            used_calls=self.calls,
            used_iterations=self.iterations,
            used_repair_trials=self.trials,
            used_wall_seconds=self.wall_seconds,
            validation_calls=self.validation_calls,
            validation_seconds=self.validation_seconds,
            records=self.records,
        )


class SimulationJointPolicy:
    def __init__(self, config, budget, *, method="ADAPTIVE_JOINT", end_h):
        require(
            method in ("ADAPTIVE_JOINT", "FIXED_H", "FIXED_HR", "NO_OBSERVATION_UPDATE"),
            "SIM_METHOD",
        )
        self.config, self.budget, self.method, self.end_h = (
            config,
            BudgetLedger(budget),
            method,
            end_h,
        )
        self.anchor = self.problem = self.schedule = None
        self.next_step = 0
        self.next_opportunity = 0
        self.journal = []
        self.candidates = []

    def nominal_prefix(self, at_h):
        p = self.problem or self.anchor
        w, rows = p.world(), list(p.decisions)
        if self.schedule is None:
            return p.observation, p.prefix, p.decisions
        for step in self.schedule.steps:
            if w.s.time_h >= at_h - 1e-10:
                break
            obs = w.observe()
            receipt = w.dispatch(step.plan.commands[0]) if step.plan.commands else None
            rows.append(
                record(
                    SimpleNamespace(
                        observation=obs,
                        plan=step.plan,
                        rejected_parents=(),
                        receipt_id=receipt.id if receipt else None,
                    )
                )
            )
            if step.advance_to_h is not None:
                w.advance(min(at_h, step.advance_to_h))
        if w.s.time_h < at_h:
            obs = w.observe()
            rows.append(record(terminal(self.config, obs)))
            w.advance(at_h)
        return w.observe(), w.snapshot(), tuple(rows)

    def decide(self, value, prefix, decisions, *, sequence=0, rejected=()):
        decisions = tuple(decisions)
        c, current = self.config, value.observation
        opportunities = self.budget.declared.opportunities_h
        if current.sampled_h >= self.end_h - 1e-10:
            return m.Plan(
                c.schema_version, c.id, current.id, (), "WAIT", "S18_WINDOW_END", c.research
            )
        due = (
            self.next_opportunity < len(opportunities)
            and opportunities[self.next_opportunity] <= current.sampled_h + 1e-10
        )
        nominal = self.method == "NO_OBSERVATION_UPDATE"
        if due:
            while (
                self.next_opportunity < len(opportunities)
                and opportunities[self.next_opportunity] <= current.sampled_h + 1e-10
            ):
                self.next_opportunity += 1
            options = self.budget.allocation()
            began = perf_counter()
            result = problem = None
            error = None
            if options is not None:
                try:
                    obs, base, rows = (
                        self.nominal_prefix(current.sampled_h)
                        if nominal and self.anchor
                        else (current, prefix, tuple(decisions))
                    )
                    problem = SimulationJointProblem(
                        c,
                        obs,
                        base,
                        decisions=rows,
                        end_h=min(
                            self.end_h, current.sampled_h + self.budget.declared.future_window_h
                        ),
                        rejected=() if nominal else tuple(rejected),
                        fixed_mode="H"
                        if self.method == "FIXED_H"
                        else "HR-seq"
                        if self.method == "FIXED_HR"
                        else None,
                    )
                    if self.anchor is None:
                        self.anchor = problem
                    remaining = max(0, options.wall_seconds - (perf_counter() - began))
                    result = search(problem, replace(options, wall_seconds=remaining))
                except (ContractError, ValueError, KeyError, TypeError, StopIteration) as exc:
                    error = str(exc)
                within = self.budget.consume(result, perf_counter() - began, problem)
                self.problem = problem
                self.schedule = result.best if result and within else None
                self.next_step = 0
                if self.schedule is not None:
                    self.candidates.append((problem, self.schedule))
            else:
                error = "CUMULATIVE_BUDGET_EXHAUSTED"
            self.journal.append(
                dict(
                    time_h=current.sampled_h,
                    proposal_source="RETAINED_ANCHOR_NOMINAL_EVOLUTION"
                    if nominal
                    else "DELIVERED_CURRENT_PREFIX",
                    anchor_sha256=self.anchor.anchor if self.anchor else None,
                    current_sha256=digest(current),
                    actual_event_count=len(prefix.events),
                    actual_decision_count=len(tuple(decisions)),
                    schedule_sha256=fingerprint(self.schedule) if self.schedule else None,
                    score_scope="NOMINAL_COMPLETE_WINDOW",
                    score=result.best_score if result else None,
                    termination=result.termination if result else error,
                )
            )
        while self.schedule is not None and self.next_step < len(self.schedule.steps):
            step = self.schedule.steps[self.next_step]
            if not step.plan.commands:
                if step.advance_to_h is not None and step.advance_to_h > current.sampled_h + 1e-10:
                    break
                self.next_step += 1
                continue
            original = step.plan.commands[0]
            if original.issued_sim_h > current.sampled_h + 1e-10:
                break
            self.next_step += 1
            command = replace(
                original,
                id=original.id + f"-ACTUAL-{sequence}",
                issued_sim_h=current.sampled_h,
                expected_revision=current.state.revision,
            )
            # Current data is used only in this safety shield for the no-update
            # channel. A refusal never starts another search or ranks a proposal.
            w = self.problem.world()
            w.s = prefix.state
            for e in prefix.events:
                if e.command and e.command.service:
                    w.operations[e.command.operation_id] = e.command.service.operation
                    if e.command.service.route:
                        w.routes[e.command.service.route.id] = e.command.service.route
            if command.service:
                w.operations[command.operation_id] = command.service.operation
                if command.service.route:
                    w.routes[command.service.route.id] = command.service.route
            try:
                require(command.operation_id not in rejected, "ACTUAL_REJECTION_SHIELD")
                validate(command, config=c)
                w._admit(command)
            except ContractError as exc:
                self.journal.append(
                    dict(
                        time_h=current.sampled_h,
                        shield="WAIT",
                        reason=str(exc),
                        proposal_operation=command.operation_id,
                    )
                )
                return m.Plan(
                    c.schema_version,
                    c.id,
                    current.id,
                    (),
                    "WAIT",
                    "S18_SHIELD:" + str(exc),
                    c.research,
                )
            return m.Plan(
                c.schema_version,
                c.id,
                current.id,
                (command,),
                "CANDIDATE",
                "S18_FULL_WINDOW",
                c.research,
            )
        return m.Plan(
            c.schema_version, c.id, current.id, (), "WAIT", "S18_NOMINAL_WAIT", c.research
        )

    def next_tick(self, now_h):
        candidates = [t for t in self.budget.declared.opportunities_h if t > now_h + 1e-10]
        if self.schedule is not None:
            candidates += [
                s.advance_to_h
                for s in self.schedule.steps
                if s.advance_to_h is not None and s.advance_to_h > now_h + 1e-10
            ]
        return min(candidates, default=self.end_h)
