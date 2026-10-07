"""S17 fixed-mode LNS, with independently gated candidates and cooperative budgets.

Adapters own feasibility and objective evaluation. Search never ranks an unchecked
candidate, and never replaces execution facts. Wall time is measured, not replayed.
"""

import hashlib
import json
import math
import random
from dataclasses import asdict, dataclass, is_dataclass
from time import perf_counter
from typing import Protocol


def fingerprint(value):
    def encode(item):
        if is_dataclass(item):
            return asdict(item)
        raise TypeError(type(item).__name__)

    return hashlib.sha256(
        json.dumps(
            value, default=encode, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode("utf-8")
    ).hexdigest()


@dataclass(frozen=True)
class Options:
    seed: int = 0
    iterations: int = 20
    destroy_size: int = 2
    repair_trials: int = 1000
    wall_seconds: float = 10.0
    stagnation: int = 20
    accept_equal: bool = True

    def validate(self):
        for name, minimum in (
            ("seed", 0),
            ("iterations", 0),
            ("destroy_size", 1),
            ("repair_trials", 1),
            ("stagnation", 1),
        ):
            if type(getattr(self, name)) is not int or getattr(self, name) < minimum:
                raise ValueError(name)
        if (
            type(self.wall_seconds) not in (int, float)
            or not math.isfinite(self.wall_seconds)
            or self.wall_seconds < 0
            or type(self.accept_equal) is not bool
        ):
            raise ValueError("wall_seconds/accept_equal")


@dataclass(frozen=True)
class Verification:
    valid: bool
    score: tuple[float, ...] | None
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class Repair:
    candidate: object | None
    trials: int = 0
    reasons: tuple[str, ...] = ()
    termination: str = "REPAIRED"


class Problem(Protocol):
    def initial(self, deadline: float) -> Repair: ...
    def mutable(self, candidate: object) -> tuple[str, ...]: ...
    def repair(self, candidate, removed, rng, trials, deadline) -> Repair: ...
    def verify(self, candidate: object) -> Verification: ...


@dataclass(frozen=True)
class Iteration:
    index: int
    removed: tuple[str, ...]
    candidate: object | None
    candidate_sha256: str | None
    score: tuple[float, ...] | None
    accepted: bool
    improved: bool
    reasons: tuple[str, ...]
    repair_termination: str
    trials: int
    wall_seconds: float


@dataclass(frozen=True)
class Result:
    status: str
    termination: str
    initial: object | None
    initial_score: tuple[float, ...] | None
    best: object | None
    best_score: tuple[float, ...] | None
    history: tuple[Iteration, ...]
    seed: int
    options: Options
    initial_reasons: tuple[str, ...]
    wall_seconds: float


def _gate(problem, candidate):
    report = problem.verify(candidate)
    if report.valid and (
        not isinstance(report.score, tuple)
        or not report.score
        or any(type(x) not in (int, float) or not math.isfinite(x) for x in report.score)
    ):
        return Verification(False, None, ("INVALID_OBJECTIVE",))
    if report.valid:
        try:
            fingerprint(candidate)
        except (TypeError, ValueError):
            return Verification(False, None, ("INVALID_CANDIDATE_ENCODING",))
    return report


def search(problem: Problem, options=Options()):
    options.validate()
    began = perf_counter()
    deadline = began + options.wall_seconds
    rng = random.Random(options.seed)
    start = problem.initial(deadline)
    report = _gate(problem, start.candidate) if start.candidate is not None else None
    if report is None or not report.valid:
        return Result(
            "WAIT",
            "NO_LEGAL_INITIAL",
            None,
            None,
            None,
            None,
            (),
            options.seed,
            options,
            start.reasons + (() if report is None else report.reasons),
            perf_counter() - began,
        )
    current = best = initial = start.candidate
    current_score = best_score = initial_score = report.score
    history, stale = [], 0
    termination = "ITERATION_BUDGET"
    for index in range(options.iterations):
        if perf_counter() >= deadline:
            termination = "WALL_BUDGET"
            break
        mutable = tuple(sorted(problem.mutable(current)))
        if len(set(mutable)) != len(mutable):
            raise ValueError("duplicate mutable decision")
        if not mutable:
            termination = "EMPTY_NEIGHBORHOOD"
            break
        removed = tuple(sorted(rng.sample(mutable, min(options.destroy_size, len(mutable)))))
        tick = perf_counter()
        repaired = problem.repair(current, removed, rng, options.repair_trials, deadline)
        candidate = repaired.candidate
        checked = _gate(problem, candidate) if candidate is not None else None
        reasons = repaired.reasons
        accepted = improved = False
        if checked is not None and checked.valid:
            if len(checked.score) != len(best_score):
                raise ValueError("objective dimension changed")
            if perf_counter() >= deadline:
                reasons += ("WALL_BUDGET_CANDIDATE_DISCARDED",)
            else:
                improved = checked.score < best_score
                accepted = checked.score < current_score or (
                    options.accept_equal and checked.score == current_score
                )
                if accepted:
                    current, current_score = candidate, checked.score
                else:
                    reasons += ("WORSE_OR_EQUAL_REJECTED",)
                if improved:
                    best, best_score = candidate, checked.score
        elif checked is not None:
            reasons += checked.reasons
        else:
            reasons += ("REPAIR_FAILED_KEEP_LEGAL_INCUMBENT",)
        try:
            candidate_hash = fingerprint(candidate) if candidate is not None else None
            recorded_candidate = candidate
        except (TypeError, ValueError):
            candidate_hash, recorded_candidate = None, None
            reasons += ("UNENCODABLE_CANDIDATE",)
        history.append(
            Iteration(
                index,
                removed,
                recorded_candidate,
                candidate_hash,
                checked.score if checked and checked.valid else None,
                accepted,
                improved,
                reasons,
                repaired.termination,
                repaired.trials,
                perf_counter() - tick,
            )
        )
        stale = 0 if improved else stale + 1
        if perf_counter() >= deadline:
            termination = "WALL_BUDGET"
            break
        if stale >= options.stagnation:
            termination = "NO_IMPROVEMENT"
            break
    # Required final audit may exceed the cooperative wall budget. Never silently
    # skip verification to meet a hard real-time claim that this step does not make.
    final = _gate(problem, best)
    if not final.valid or final.score != best_score:
        raise RuntimeError("best feasible cache failed final independent verification")
    return Result(
        "FEASIBLE",
        termination,
        initial,
        initial_score,
        best,
        best_score,
        tuple(history),
        options.seed,
        options,
        start.reasons,
        perf_counter() - began,
    )
