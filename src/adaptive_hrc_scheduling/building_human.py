"""Hour-domain adapter of the tested minute-domain linear integrator."""

import math
from dataclasses import replace

from adaptive_hrc_scheduling.contracts.codec import require
from adaptive_hrc_scheduling.domain.building import HumanInterval
from adaptive_hrc_scheduling.domain.models import WorkerParameters
from adaptive_hrc_scheduling.domain.state import WorkerState
from adaptive_hrc_scheduling.human_state import evolve


def calendar_state(person, time_h):
    phase = time_h % person.calendar.period_h
    for window in person.calendar.windows:
        if window.start_h <= phase < window.end_h:
            return "WAIT", time_h + (window.end_h - phase)
        if phase < window.start_h:
            kind = "REST" if phase >= person.calendar.windows[0].end_h else "OFF_SHIFT"
            return kind, time_h + (window.start_h - phase)
    return "OFF_SHIFT", time_h + (person.calendar.period_h - phase) + person.calendar.windows[
        0
    ].start_h


def can_work(person, start, end):
    state, bound = calendar_state(person, start)
    return state == "WAIT" and start <= end <= bound and end <= person.valid_until_h


def integrate(person, state, activity, start, end, cap, *, rate=None):
    require(
        math.isfinite(start) and math.isfinite(end) and end >= start, "human interval: invalid time"
    )
    a = person.work_rate if rate is None else rate
    if activity == "WAIT":
        a = person.wait_rate
    recovering = activity in ("REST", "OFF_SHIFT")
    parameters = WorkerParameters(
        person.initial_f,
        person.recovery_rate / 60,
        0,
        a / 60,
        a / 60,
        a / 60,
        a / 60,
        person.wait_rate / 60,
    )
    old = WorkerState(
        person.id, state.fatigue, state.exposure * 60, "rest" if recovering else "work"
    )
    result = evolve(old, parameters, "rest" if recovering else "work", (end - start) * 60, cap)
    new = replace(
        state,
        fatigue=result.state.fatigue,
        exposure=result.state.exposure_min / 60,
        peak=max(state.peak, result.peak_f),
    )
    interval = HumanInterval(
        person.id,
        start,
        end,
        activity,
        person.recovery_rate if recovering else a,
        state.fatigue,
        new.fatigue,
        result.exposure_increment_min / 60,
    )
    return new, interval
