"""Execution truth records, deliberately separate from planning observations."""

from dataclasses import dataclass
from typing import Literal

from ..contracts.codec import ID, Count, Fraction, Index, Nonnegative, Positive
from .models import Activity, Units


@dataclass(frozen=True)
class WorkerState:
    worker_id: ID
    fatigue: Fraction
    exposure_min: Nonnegative
    activity: Activity


@dataclass(frozen=True)
class Preparation:
    robot_id: ID
    operation_id: ID | None
    group_id: ID | None
    station_id: ID | None
    valid: bool


@dataclass(frozen=True)
class Binding:
    operation_id: ID
    group_id: ID
    allocation_id: ID


@dataclass(frozen=True)
class PhaseState:
    operation_id: ID
    mode_id: ID
    allocation_id: ID
    group_id: ID
    phase_id: ID
    attempt: Count
    restore_sequence: Index
    status: Literal["running", "paused", "completed", "failed"]
    remaining_base_min: Nonnegative
    sampled_f: Fraction | None
    speed_multiplier: Positive
    started_min: Nonnegative
    completed_min: Nonnegative | None


@dataclass(frozen=True)
class Lock:
    resource_id: ID
    owner_group_id: ID
    purpose: Literal["active", "held", "reserved", "occupied"]


@dataclass(frozen=True)
class MaterialPosition:
    material_id: ID
    location_id: ID
    status: Literal["stored", "in_transit", "consumed", "scrapped", "finished"]
    slot: Index | None


@dataclass(frozen=True)
class Reservation:
    material_id: ID
    location_id: ID
    owner_group_id: ID
    slot: Index | None


@dataclass(frozen=True)
class ResourceState:
    resource_id: ID
    failed: bool
    release_allowed: bool | None


@dataclass(frozen=True)
class OrderState:
    order_id: ID
    released: bool
    cancelled: bool
    actual_completion_min: Nonnegative | None


@dataclass(frozen=True)
class ExecutionSnapshot:
    schema_version: Literal["S06-1.1"]
    kind: Literal["execution_snapshot"]
    run_id: ID
    configuration_id: ID
    units: Units
    sim_time_min: Nonnegative
    workers: tuple[WorkerState, ...]
    preparations: tuple[Preparation, ...]
    bindings: tuple[Binding, ...]
    phases: tuple[PhaseState, ...]
    locks: tuple[Lock, ...]
    materials: tuple[MaterialPosition, ...]
    reservations: tuple[Reservation, ...]
    resources: tuple[ResourceState, ...]
    orders: tuple[OrderState, ...]
