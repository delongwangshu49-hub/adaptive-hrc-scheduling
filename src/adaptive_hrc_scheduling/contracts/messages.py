"""Planning, dispatch, execution, hidden-world and evaluation envelopes."""

import hashlib
import json
from dataclasses import dataclass
from typing import Literal

from ..domain.models import Configuration, Units
from ..domain.state import Binding, Lock, MaterialPosition, PhaseState, Preparation, Reservation
from .codec import ID, Count, Digest, Fraction, Index, Nonnegative, Positive


@dataclass(frozen=True)
class KnownOrder:
    order_id: ID
    released_observed_min: Nonnegative
    cancel_observed_min: Nonnegative | None
    completion_observed_min: Nonnegative | None
    actual_completion_min: Nonnegative | None


@dataclass(frozen=True)
class Estimate:
    resource_id: ID
    sampled_min: Nonnegative
    received_min: Nonnegative
    fatigue_estimate: Fraction | None
    exposure_estimate_min: Nonnegative | None
    available_estimate: bool | None


@dataclass(frozen=True)
class ObservedExecution:
    """Authorized, possibly partial state at sampled_min; absence means unknown."""

    sampled_min: Nonnegative
    received_min: Nonnegative
    bindings: tuple[Binding, ...]
    phases: tuple[PhaseState, ...]
    locks: tuple[Lock, ...]
    materials: tuple[MaterialPosition, ...]
    reservations: tuple[Reservation, ...]
    preparations: tuple[Preparation, ...]


@dataclass(frozen=True)
class PlanningObservation:
    schema_version: Literal["S06-1.1"]
    kind: Literal["planning_observation"]
    id: ID
    run_id: ID
    configuration_id: ID
    units: Units
    as_of_min: Nonnegative
    known_orders: tuple[KnownOrder, ...]
    estimates: tuple[Estimate, ...]
    observed_event_ids: tuple[ID, ...]
    execution: ObservedExecution | None


@dataclass(frozen=True)
class PlanningInput:
    schema_version: Literal["S06-1.1"]
    kind: Literal["planning_input"]
    configuration_id: ID
    observation: PlanningObservation
    visible_configuration: Configuration


@dataclass(frozen=True)
class Assignment:
    operation_id: ID
    mode_id: ID
    group_id: ID
    phase_id: ID
    allocation_id: ID
    attempt: Count
    restore_sequence: Index
    planned_start_min: Nonnegative
    planned_end_min: Nonnegative
    reason_code: ID


@dataclass(frozen=True)
class CompletionEstimate:
    order_id: ID
    predicted_completion_min: Nonnegative | None
    actual_completion_min: Nonnegative | None


@dataclass(frozen=True)
class ExposureEstimate:
    worker_id: ID
    predicted_window_exposure_min: Nonnegative


@dataclass(frozen=True)
class Plan:
    schema_version: Literal["S06-1.1"]
    kind: Literal["plan"]
    id: ID
    observation: PlanningObservation
    units: Units
    status: Literal["candidate", "incomplete"]
    assignments: tuple[Assignment, ...]
    completions: tuple[CompletionEstimate, ...]
    exposure_estimates: tuple[ExposureEstimate, ...]
    budget_kind: Literal["D0", "Dsum", "Dmax"]
    exposure_budget_min: Nonnegative | None
    reason_code: ID


@dataclass(frozen=True)
class DispatchCommand:
    schema_version: Literal["S06-1.1"]
    kind: Literal["dispatch"]
    id: ID
    run_id: ID
    configuration_id: ID
    observation_id: ID
    units: Units
    issued_min: Nonnegative
    action: Literal["start", "resume", "rest", "wait", "cleanup"]
    assignment: Assignment | None
    worker_id: ID | None
    duration_min: Positive | None
    cleanup_material_id: ID | None


@dataclass(frozen=True)
class WorldEvent:
    id: ID
    sim_time_min: Nonnegative
    type: Literal["release", "cancel", "failure", "repair"]
    entity_id: ID
    release_allowed: bool | None


@dataclass(frozen=True)
class HiddenScenario:
    schema_version: Literal["S06-1.1"]
    kind: Literal["hidden_scenario"]
    configuration_id: ID
    units: Units
    scenario_seed: Index
    events: tuple[WorldEvent, ...]


@dataclass(frozen=True)
class ExecutionEvent:
    schema_version: Literal["S06-1.1"]
    kind: Literal["execution_event"]
    run_id: ID
    configuration_id: ID
    event_id: ID
    units: Units
    sim_time_min: Nonnegative
    event_type: Literal[
        "started",
        "completed",
        "interrupted",
        "released",
        "arrived",
        "rejected",
        "cancelled",
        "restored",
    ]
    entity_id: ID
    phase_execution_id: ID | None
    old_state: ID
    new_state: ID
    cause: ID


@dataclass(frozen=True)
class RunManifest:
    schema_version: Literal["S06-1.1"]
    kind: Literal["run_manifest"]
    run_id: ID
    configuration_id: ID
    units: Units
    configuration_sha256: Digest
    scenario_sha256: Digest
    dependency_lock_sha256: Digest
    code_revision: str
    scenario_seed: Index
    decision_seed: Index
    algorithm_id: ID
    backend: Literal["event", "isaac"]
    decision_budget_ms: Positive
    observation_window_min: Positive
    fatigue_cap: Fraction
    status: Literal["planned", "completed", "deadlock", "truncated", "failed"]
    solver_pauses_simulation: bool
    termination_reason: ID | None


@dataclass(frozen=True)
class ActualCompletion:
    order_id: ID
    actual_completion_min: Nonnegative | None


@dataclass(frozen=True)
class WorkerExposure:
    worker_id: ID
    actual_exposure_min: Nonnegative
    actual_peak: Fraction


@dataclass(frozen=True)
class OfflineEvaluation:
    schema_version: Literal["S06-1.1"]
    kind: Literal["offline_evaluation"]
    run_id: ID
    configuration_id: ID
    units: Units
    observation_window_min: Positive
    scenario: HiddenScenario
    evaluation_order_ids: tuple[ID, ...]
    completions: tuple[ActualCompletion, ...]
    workers: tuple[WorkerExposure, ...]
    drained_at_min: Nonnegative | None
    truncated: bool
    budget_violated: bool


def phase_execution_id(operation_id, group_id, phase_id, attempt, restore_sequence=0):
    """Stable across resume; restart changes attempt, a new restore changes sequence."""
    from .codec import decode, require

    for value in (operation_id, group_id, phase_id):
        decode(ID, value)
    decode(Count, attempt)
    decode(Index, restore_sequence)
    require((phase_id == "restore") == (restore_sequence > 0), "restore sequence mismatch")
    payload = json.dumps(
        [operation_id, group_id, phase_id, attempt, restore_sequence], separators=(",", ":")
    )
    return "phase." + hashlib.sha256(payload.encode("utf-8")).hexdigest()
