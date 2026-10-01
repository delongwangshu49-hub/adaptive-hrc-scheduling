"""S07 pure fatigue arithmetic; no clock, dispatch or observation generation."""

import math
from dataclasses import dataclass, replace
from fractions import Fraction as Rational

from .contracts.codec import (
    ContractError,
    Fraction,
    Nonnegative,
    Positive,
    as_data,
    decode,
    require,
)
from .domain.models import Activity, Configuration, Phase, WorkerParameters
from .domain.phases import resolve_process_phase
from .domain.state import PhaseState, WorkerState


class FatigueLimitError(ContractError):
    """The requested interval would exceed the common cap; no state is returned."""


@dataclass(frozen=True)
class Evolution:
    state: WorkerState
    exposure_increment_min: float
    peak_f: float


@dataclass(frozen=True)
class ActivityInterval:
    start_min: float
    end_min: float
    activity: Activity


@dataclass(frozen=True)
class WorkerTrajectory:
    worker_id: str
    intervals: tuple[ActivityInterval, ...]
    results: tuple[Evolution, ...]
    peak_f: float


@dataclass(frozen=True)
class WindowExposure:
    trajectories: tuple[WorkerTrajectory, ...]
    total_min: float
    max_individual_min: float
    peak_f: float
    censored: bool


@dataclass(frozen=True)
class PhaseTiming:
    sampled_f: float | None
    speed_multiplier: float
    duration_min: float


@dataclass(frozen=True)
class ProtectionDecision:
    allowed: bool
    reason: str


def _parameters(parameters, cap):
    parameters = decode(WorkerParameters, as_data(parameters))
    cap = decode(Fraction, cap)
    require(cap > 0, "positive fatigue cap")
    require(parameters.initial_f <= cap, "initial fatigue above cap")
    return parameters, cap


def _fatigue(fatigue, cap):
    fatigue = decode(Fraction, fatigue)
    require(fatigue <= cap, "state exceeds fatigue cap")
    return fatigue


def _rate(parameters, activity):
    decode(Activity, activity)
    require(activity != "rest", "rest has recovery, not accumulation")
    return getattr(parameters, f"{activity}_per_min")


def _beyond_cap(start, rate, duration, cap):
    # Compare the supplied binary numbers exactly: a rounded endpoint must
    # not erase a sub-ULP excess. This is validation, not state clipping.
    return Rational(start) + Rational(rate) * Rational(duration) > Rational(cap)


def _phase(phase):
    phase = decode(Phase, as_data(phase))
    require((phase.activity is not None) == ("worker" in phase.active_roles), "phase worker")
    require(phase.activity not in {"rest", "wait"}, "process activity")
    require(
        not phase.fatigue_sensitive or (phase.id == "work" and phase.activity is not None),
        "phase speed sensitivity",
    )
    return phase


def evolve(state, parameters, activity, duration_min, cap):
    """Integrate one constant activity in minutes, preserving prior exposure.

    Zero duration is an identity on state. Cap checks are strict (no epsilon,
    saturation or recovery used to hide an earlier violation). Rest alone may
    reach zero. The returned peak is for this interval, including its start.
    """
    parameters, cap = _parameters(parameters, cap)
    state = decode(WorkerState, as_data(state))
    start = _fatigue(state.fatigue, cap)
    decode(Activity, activity)
    duration = decode(Nonnegative, duration_min)
    if duration == 0:
        return Evolution(state, 0.0, start)
    if activity == "rest":
        # Use only the positive triangle/trapezoid, never a trapezoid over
        # the entire interval after recovery reaches zero.
        recovery = parameters.recovery_per_min
        to_zero = start / recovery
        active = min(duration, to_zero)
        end = 0.0 if duration >= to_zero else start - recovery * duration
        area = active * (start / 2 + end / 2)
    else:
        rate = _rate(parameters, activity)
        end = start + rate * duration
        if end > cap or _beyond_cap(start, rate, duration, cap):
            raise FatigueLimitError("FATIGUE_PROTECTION")
        area = duration * (start / 2 + end / 2)
    area = decode(Nonnegative, area)
    exposure = decode(Nonnegative, state.exposure_min + area)
    final = replace(state, fatigue=end, exposure_min=exposure, activity=activity)
    return Evolution(final, area, max(start, end))


def time_to_cap(fatigue, parameters, activity, cap):
    """Earliest cap contact under unchanged activity; None means no contact.

    At cap return zero, including for rest. This is a numeric event horizon,
    not a timer or an automatic rest transition.
    """
    parameters, cap = _parameters(parameters, cap)
    fatigue = _fatigue(fatigue, cap)
    decode(Activity, activity)
    if fatigue == cap:
        return 0.0
    if activity == "rest":
        return None
    rate = _rate(parameters, activity)
    if rate == 0:
        return None
    try:
        horizon = decode(Nonnegative, float((Rational(cap) - Rational(fatigue)) / Rational(rate)))
    except OverflowError as error:
        raise ContractError("cap horizon overflow") from error
    if _beyond_cap(fatigue, rate, horizon, cap):
        horizon = math.nextafter(horizon, 0.0)
    return horizon


def protective_rest(state, parameters, cap, minimum_min):
    """Apply a declared positive minimum rest; caller must then recheck work."""
    minimum = decode(Positive, minimum_min)
    return evolve(state, parameters, "rest", minimum, cap)


def sample_phase(phase, parameters, fatigue, cap):
    """Sample at a first start or a new restart attempt, never on resume.

    The one duration applies to the whole HR phase. No machine duration is
    added. This function does not create attempt IDs or permit a restart.
    """
    parameters, cap = _parameters(parameters, cap)
    fatigue = _fatigue(fatigue, cap)
    phase = _phase(phase)
    sample = fatigue if phase.fatigue_sensitive else None
    multiplier = 1 + parameters.speed_kappa * fatigue if sample is not None else 1.0
    multiplier = decode(Positive, multiplier)
    duration = decode(Positive, phase.base_min * multiplier)
    return PhaseTiming(sample, multiplier, duration)


def remaining_duration(phase, parameters, progress, cap):
    """Use stored sample/multiplier and remaining *base* work after a pause.

    No current fatigue is accepted: waiting/rest/restore cannot resample a
    continuation. Validity of the interruption itself belongs to S08/S09.
    """
    parameters, cap = _parameters(parameters, cap)
    phase = _phase(phase)
    progress = decode(PhaseState, as_data(progress))
    require(progress.phase_id == phase.id, "progress phase mismatch")
    require(progress.status in {"running", "paused"}, "progress is not resumable")
    require(progress.completed_min is None, "unfinished phase has completion time")
    require(0 < progress.remaining_base_min <= phase.base_min, "remaining base work")
    if phase.fatigue_sensitive:
        require(progress.sampled_f is not None, "missing fatigue sample")
        sample = _fatigue(progress.sampled_f, cap)
        expected = sample_phase(phase, parameters, sample, cap).speed_multiplier
    else:
        require(progress.sampled_f is None, "unexpected fatigue sample")
        expected = 1.0
    require(progress.speed_multiplier == expected, "stored speed multiplier mismatch")
    return decode(Positive, progress.remaining_base_min * expected)


def process_start_allowed(
    config: Configuration,
    operation_id: str,
    mode_id: str,
    phase_id: str,
    state: WorkerState,
    *,
    progress: PhaseState | None = None,
    restore_required: bool = False,
):
    """Numeric process protection for an already validated configuration.

    Include the declared necessary handoff automatically. If required, include
    restore before robot work; resample work afterwards only for a new attempt.
    Robot-only time is conservatively explicit wait for the bound worker.
    No resource/preparation/qualification/visibility permission is conferred.
    Unknown blocking time, transfers and cleanup must be checked separately by
    the future executor; this is not a complete dispatch or event engine.
    """
    require(type(restore_required) is bool, "restore flag must be bool")
    state = decode(WorkerState, as_data(state))
    worker = next((r for r in config.resources if r.id == state.worker_id), None)
    require(worker is not None and worker.kind == "worker", "unknown worker")
    parameters, cap = _parameters(worker.worker_parameters, config.fatigue_cap)
    _fatigue(state.fatigue, cap)
    phase = resolve_process_phase(config, operation_id, mode_id, phase_id)
    if progress is not None:
        progress = decode(PhaseState, as_data(progress))
        require(
            (progress.operation_id, progress.mode_id, progress.phase_id)
            == (operation_id, mode_id, phase_id),
            "progress identity mismatch",
        )
        q = next((q for q in config.allocations if q.id == progress.allocation_id), None)
        mode = next(m for m in config.modes if m.id == mode_id)
        operation = next(o for o in config.operations if o.id == operation_id)
        require(
            q is not None
            and q.worker_id == state.worker_id
            and q.id in mode.allocation_ids
            and progress.group_id == operation.process_group_id,
            "progress binding mismatch",
        )
        remaining_duration(phase, parameters, progress, cap)
    phases = []
    if restore_required:
        require(phase.id == "work" and phase.requires_preparation, "restore before robot work")
        phases.append(resolve_process_phase(config, operation_id, mode_id, "restore"))
    phases.append(phase)
    if phase.cancel_boundary == "handoff_then_clear":
        phases.append(resolve_process_phase(config, operation_id, mode_id, "handoff"))
    else:
        require(phase.cancel_boundary == "clear", "not a process release boundary")
    try:
        for item in phases:
            duration = (
                remaining_duration(item, parameters, progress, cap)
                if item is phase and progress is not None
                else sample_phase(item, parameters, state.fatigue, cap).duration_min
            )
            state = evolve(state, parameters, item.activity or "wait", duration, cap).state
    except FatigueLimitError:
        return ProtectionDecision(False, "FATIGUE_PROTECTION")
    return ProtectionDecision(True, "WITHIN_FATIGUE_CAP")


def evaluate_window(config: Configuration, timelines, *, drained_min):
    """Integrate supplied complete [0,T_obs] activity histories for all workers.

    Configuration must already pass the S06 boundary. No implicit gaps or tails:
    every activity, including wait and post-drain rest, is supplied explicitly.
    drained_min=None denotes not drained by the horizon (censored); otherwise
    it is an externally established drain time, not one inferred by this API.
    """
    window = decode(Positive, config.observation_window_min)
    if drained_min is not None:
        drained_min = decode(Nonnegative, drained_min)
        require(drained_min <= window, "drain outside observation window")
    workers = [r for r in config.resources if r.kind == "worker"]
    require(bool(workers), "window requires workers")
    require(set(timelines) == {r.id for r in workers}, "complete worker coverage required")
    trajectories = []
    for worker in workers:
        parameters, cap = _parameters(worker.worker_parameters, config.fatigue_cap)
        state = WorkerState(worker.id, parameters.initial_f, 0.0, "wait")
        cursor = 0.0
        results, intervals = [], []
        peak = state.fatigue
        for interval in timelines[worker.id]:
            interval = decode(ActivityInterval, as_data(interval))
            start = decode(Nonnegative, interval.start_min)
            end = decode(Positive, interval.end_min)
            require(start == cursor and start < end <= window, "gap, overlap or window mismatch")
            if drained_min is not None and end > drained_min:
                require(interval.activity == "rest", "post-drain tail must be explicit rest")
            result = evolve(state, parameters, interval.activity, end - start, cap)
            results.append(result)
            intervals.append(interval)
            peak = max(peak, result.peak_f)
            state, cursor = result.state, end
        require(cursor == window, "missing observation-window tail")
        trajectories.append(WorkerTrajectory(worker.id, tuple(intervals), tuple(results), peak))
    exposures = [t.results[-1].state.exposure_min for t in trajectories]
    try:
        total = decode(Nonnegative, math.fsum(exposures))
    except OverflowError as error:
        raise ContractError("exposure total overflow") from error
    return WindowExposure(
        tuple(trajectories),
        total,
        max(exposures),
        max(t.peak_f for t in trajectories),
        drained_min is None,
    )
