"""S06 configuration objects. Times are minutes; rates are inverse minutes."""

from dataclasses import dataclass
from typing import Literal

from ..contracts.codec import ID, Count, Fraction, Index, Nonnegative, Positive

Kind = Literal["CUT", "BRACKET", "ASSEMBLE", "WELD", "INSPECT", "LIFT"]
Skill = Literal["CUT", "BRACKET", "ASSEMBLE", "WELD", "INSPECT", "TRANSFER"]
Activity = Literal["work", "collaborate", "carry", "supervise", "wait", "rest"]
Role = Literal["worker", "robot", "equipment", "station", "fixture", "crane", "route"]


@dataclass(frozen=True)
class Units:
    time: Literal["min"]
    rate: Literal["min^-1"]
    fatigue: Literal["dimensionless"]
    exposure: Literal["min"]
    capacity: Literal["count"]


@dataclass(frozen=True)
class WorkerParameters:
    initial_f: Fraction
    recovery_per_min: Positive
    speed_kappa: Nonnegative
    work_per_min: Nonnegative
    collaborate_per_min: Nonnegative
    carry_per_min: Nonnegative
    supervise_per_min: Nonnegative
    wait_per_min: Positive


@dataclass(frozen=True)
class Resource:
    id: ID
    kind: Literal[
        "worker", "robot", "equipment", "station", "fixture", "crane", "space", "buffer", "terminal"
    ]
    capacity: Count | None
    skills: tuple[Skill, ...]
    station_id: ID | None
    reachable_station_ids: tuple[ID, ...]
    accepted_materials: tuple[Literal["raw", "pipe", "bracket", "module", "finished", "scrap"], ...]
    receiving_slots: Index
    worker_parameters: WorkerParameters | None


@dataclass(frozen=True)
class Route:
    id: ID
    source_id: ID
    target_id: ID
    space_id: ID
    kind: Literal["feed", "crane"]
    preposition_min: Positive
    rig_min: Positive
    move_min: Positive
    unload_min: Positive
    reset_min: Positive


@dataclass(frozen=True)
class Allocation:
    id: ID
    skill: Skill
    worker_id: ID
    robot_id: ID | None
    equipment_id: ID | None
    station_id: ID | None
    fixture_id: ID | None
    crane_id: ID | None
    route_id: ID | None


@dataclass(frozen=True)
class Phase:
    id: ID
    predecessors: tuple[ID, ...]
    base_min: Positive
    active_roles: tuple[Role, ...]
    activity: Activity | None
    fatigue_sensitive: bool
    interruption: Literal["restart", "resume"]
    cancel_boundary: Literal["clear", "handoff_then_clear", "unload_reset", "reset"]
    establishes_preparation: bool
    requires_preparation: bool


@dataclass(frozen=True)
class Mode:
    id: ID
    operation_kind: Kind
    name: Literal["H", "R", "HR"]
    phases: tuple[Phase, ...]
    allocation_ids: tuple[ID, ...]
    switch_after: ID | None
    freeze_at: ID
    preparation_phase_id: ID | None
    held_roles: tuple[Role, ...]


@dataclass(frozen=True)
class DurationOverride:
    mode_id: ID
    phase_id: ID
    base_min: Positive


@dataclass(frozen=True)
class TransferGroup:
    id: ID
    material_id: ID
    allocation_ids: tuple[ID, ...]
    wait_for_reset: bool
    reserve_all_receiving_slots: bool


@dataclass(frozen=True)
class Operation:
    id: ID
    order_id: ID
    kind: Kind
    predecessors: tuple[ID, ...]
    mode_ids: tuple[ID, ...]
    input_ids: tuple[ID, ...]
    output_id: ID
    process_group_id: ID | None
    transfers: tuple[TransferGroup, ...]
    duration_overrides: tuple[DurationOverride, ...]
    feed_space_id: ID | None


@dataclass(frozen=True)
class Material:
    id: ID
    order_id: ID
    kind: Literal["raw", "pipe", "bracket", "module", "finished"]
    quantity: Count
    producer_id: ID | None
    consumer_id: ID | None
    storage_ids: tuple[ID, ...]
    movement: Literal["raw_at_release", "feed", "crane", "retained"]
    available_at: Literal["release", "handoff", "work", "unload"]


@dataclass(frozen=True)
class Order:
    id: ID
    family: ID
    release_min: Nonnegative
    due_min: Nonnegative
    weight: Positive
    required_finished_ids: tuple[ID, ...]


@dataclass(frozen=True)
class Configuration:
    schema_version: Literal["S06-1.0"]
    kind: Literal["configuration"]
    id: ID
    units: Units
    provenance: Literal["PROJECT_CHOICE_SYNTHETIC_UNCALIBRATED"]
    fatigue_cap: Fraction
    protective_rest_min: Positive
    observation_window_min: Positive
    cleanup_piece_min: Positive
    resources: tuple[Resource, ...]
    routes: tuple[Route, ...]
    allocations: tuple[Allocation, ...]
    modes: tuple[Mode, ...]
    orders: tuple[Order, ...]
    operations: tuple[Operation, ...]
    materials: tuple[Material, ...]
