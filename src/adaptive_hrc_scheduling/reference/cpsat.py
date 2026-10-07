"""S16 optional OR-Tools model, explicit statuses and independently checked output."""

import math
from dataclasses import dataclass
from importlib.metadata import version
from time import perf_counter

from adaptive_hrc_scheduling.reference.checker import check
from adaptive_hrc_scheduling.reference.domain import Entry, digest, validate

ORTOOLS_VERSION = "9.15.6755"


def _api():
    try:
        from ortools.sat.python import cp_model
    except ImportError as error:
        raise RuntimeError("Install the locked reference group to run S16 CP-SAT") from error
    if version("ortools") != ORTOOLS_VERSION:
        raise RuntimeError("S16 requires locked OR-Tools " + ORTOOLS_VERSION)
    return cp_model


@dataclass(frozen=True)
class Options:
    wall_seconds: float = 10.0
    seed: int = 0
    stop_after_solutions: int | None = None
    presolve: bool = True


@dataclass(frozen=True)
class Result:
    status: str
    termination: str
    schedule: tuple[Entry, ...]
    objective: int | None
    best_bound: float | None
    relative_gap: float | None
    budget_seconds: float
    solver_wall_seconds: float
    total_wall_seconds: float
    seed: int
    workers: int
    solver_version: str
    instance_sha256: str
    checker: str


def _build(instance, *, objective=True):
    validate(instance)
    cp = _api()
    model = cp.CpModel()
    starts, ends, choices = {}, {}, {}
    resources = {r.id: r.capacity for r in instance.resources} | {p.id: 1 for p in instance.people}
    people = {p.id: p for p in instance.people}
    occupancy = {r: [] for r in resources}
    demands = {r: [] for r in resources}
    cost_terms = []
    for task in instance.tasks:
        start = model.new_int_var(task.release, max(task.release, instance.horizon), task.id + ":s")
        end = model.new_int_var(0, instance.horizon, task.id + ":e")
        starts[task.id], ends[task.id] = start, end
        if task.latest_end is not None:
            model.add(end <= task.latest_end)
        choices[task.id] = []
        for alt in task.alternatives:
            selected = model.new_bool_var(task.id + ":" + alt.id)
            choices[task.id].append(selected)
            interval = model.new_optional_interval_var(
                start, alt.duration, end, selected, task.id + ":" + alt.id + ":i"
            )
            for resource, demand in alt.resources:
                occupancy[resource].append(interval)
                demands[resource].append(demand)
            for _, person in alt.roles:
                occupancy[person].append(interval)
                demands[person].append(1)
                windows = []
                for index, (lo, hi) in enumerate(people[person].windows):
                    window = model.new_bool_var(f"{task.id}:{alt.id}:{person}:{index}")
                    model.add(start >= lo).only_enforce_if(window)
                    model.add(end <= hi).only_enforce_if(window)
                    windows.append(window)
                model.add(sum(windows) == selected)
            cost_terms.append(alt.cost * selected)
        model.add_exactly_one(choices[task.id])
    for task in instance.tasks:
        for pred in task.predecessors:
            model.add(starts[task.id] >= ends[pred])
    tardiness_terms = []
    for product in instance.products:
        for place, start, end, name in (
            (product.output, ends[product.ready], ends[product.store], "out"),
            (product.buffer, starts[product.store], ends[product.receive], "fg"),
        ):
            size = model.new_int_var(0, instance.horizon, product.id + ":" + name + ":d")
            interval = model.new_interval_var(start, size, end, product.id + ":" + name)
            occupancy[place].append(interval)
            demands[place].append(1)
        tardy = model.new_int_var(0, instance.horizon, product.id + ":tardy")
        model.add_max_equality(tardy, [0, ends[product.receive] - product.due])
        tardiness_terms.append(product.weight * tardy)
    for resource, capacity in resources.items():
        if occupancy[resource]:
            model.add_cumulative(occupancy[resource], demands[resource], capacity)
    if objective:
        makespan = model.new_int_var(0, instance.horizon, "makespan")
        model.add_max_equality(makespan, list(ends.values()))
        model.minimize(
            instance.tardiness_weight * sum(tardiness_terms)
            + instance.makespan_weight * makespan
            + instance.cost_weight * sum(cost_terms)
        )
    diagnostic = model.validate()
    if diagnostic:
        raise ValueError("MODEL_INVALID: " + diagnostic)
    return cp, model, starts, ends, choices


def _extract(instance, getter, starts, ends, choices):
    return tuple(
        Entry(
            t.id,
            next(a.id for a, c in zip(t.alternatives, choices[t.id]) if getter(c)),
            getter(starts[t.id]),
            getter(ends[t.id]),
        )
        for t in instance.tasks
    )


def _options(options):
    if (
        type(options.wall_seconds) not in (float, int)
        or not math.isfinite(options.wall_seconds)
        or options.wall_seconds < 0
        or type(options.seed) is not int
        or not 0 <= options.seed <= 2**31 - 1
        or type(options.presolve) is not bool
        or (
            options.stop_after_solutions is not None
            and (type(options.stop_after_solutions) is not int or options.stop_after_solutions < 1)
        )
    ):
        raise ValueError("solver options")


def solve(instance, options=Options()):
    _options(options)
    began = perf_counter()
    cp, model, starts, ends, choices = _build(instance)
    solver = cp.CpSolver()
    solver.parameters.max_time_in_seconds = options.wall_seconds
    solver.parameters.num_search_workers = 1
    solver.parameters.random_seed = options.seed
    solver.parameters.cp_model_presolve = options.presolve

    class Stop(cp.CpSolverSolutionCallback):
        def __init__(self):
            super().__init__()
            self.count = 0
            self.stopped = False

        def on_solution_callback(self):
            self.count += 1
            if options.stop_after_solutions and self.count >= options.stop_after_solutions:
                self.stopped = True
                self.stop_search()

    callback = Stop()
    code = solver.solve(model, callback)
    status = solver.status_name(code)
    schedule, value, bound, gap = (), None, None, None
    checker = "NO_INCUMBENT"
    if code in (cp.OPTIMAL, cp.FEASIBLE):
        schedule = _extract(instance, solver.value, starts, ends, choices)
        report = check(instance, schedule)
        if not report.valid or report.objective != round(solver.objective_value):
            raise RuntimeError("CP-SAT output failed independent check: " + repr(report))
        value = report.objective
        bound = solver.best_objective_bound
        if not math.isfinite(bound) or bound > value + 1e-6:
            raise RuntimeError("invalid objective bound")
        gap = max(0.0, value - bound) / max(1, abs(value))
        checker = "PASS_S16_STATIC"
    if status == "OPTIMAL":
        termination = "PROVEN_OPTIMAL"
    elif status == "INFEASIBLE":
        termination = "PROVEN_INFEASIBLE"
    elif callback.stopped:
        termination = "SOLUTION_LIMIT"
    else:
        termination = "BUDGET_OR_SOLVER_STOP"
    return Result(
        status,
        termination,
        schedule,
        value,
        bound,
        gap,
        options.wall_seconds,
        solver.wall_time,
        perf_counter() - began,
        options.seed,
        1,
        ORTOOLS_VERSION,
        digest(instance),
        checker,
    )


def enumerate_cp(instance, *, wall_seconds=10.0, max_solutions=100_000):
    """Satisfaction enumeration; complete means proved exhaustion, never a capped prefix."""
    _options(Options(wall_seconds=wall_seconds, stop_after_solutions=max_solutions))
    cp, model, starts, ends, choices = _build(instance, objective=False)
    solver = cp.CpSolver()
    solver.parameters.enumerate_all_solutions = True
    solver.parameters.num_search_workers = 1
    solver.parameters.max_time_in_seconds = wall_seconds
    schedules = set()

    class Collect(cp.CpSolverSolutionCallback):
        def __init__(self):
            super().__init__()
            self.stopped = False

        def on_solution_callback(self):
            schedule = _extract(instance, self.value, starts, ends, choices)
            if not check(instance, schedule).valid:
                raise RuntimeError("enumerated solution failed independent check")
            schedules.add(schedule)
            if len(schedules) >= max_solutions:
                self.stopped = True
                self.stop_search()

    callback = Collect()
    code = solver.solve(model, callback)
    return schedules, code in (cp.OPTIMAL, cp.INFEASIBLE) and not callback.stopped
