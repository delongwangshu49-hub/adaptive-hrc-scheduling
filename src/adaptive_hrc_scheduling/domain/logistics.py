"""S14-ML-1.0 shared records. Research hours/metres/tonnes, never certification."""

from dataclasses import dataclass
from typing import Literal

from adaptive_hrc_scheduling.contracts.codec import (
    ID,
    Count,
    Digest,
    Fraction,
    Index,
    Nonnegative,
    Positive,
)
from adaptive_hrc_scheduling.domain.building import (
    Activity,
    Edge,
    Evidence,
    HumanState,
    Person,
    Product,
    Role,
    RoleBinding,
)

Version = Literal["S14-ML-1.0"]
Action = Literal[
    "WALK",
    "TRANSFER",
    "EMPTY_RETURN",
    "RESERVE",
    "RELEASE_RESERVATION",
    "CONVERT",
    "WORK",
    "READY",
    "RECEIVE_EXTERNAL",
    "RETURN",
    "SCRAP",
    "REST",
    "DEPLOY_TOOL",
    "RETRIEVE_TOOL",
]


@dataclass(frozen=True)
class Place:
    id: ID
    kind: Literal["BAY", "MATERIAL", "COMPONENT", "FINISHED", "INTERFACE", "CONTROL"]
    capacity: Count
    position: tuple[float, ...]


@dataclass(frozen=True)
class Device:
    id: ID
    kind: Literal["FIXED", "CRANE", "VEHICLE", "TOOL", "FIXTURE"]
    initial_location: ID
    capacity_t: Nonnegative
    qualification: ID


@dataclass(frozen=True)
class PersonPosition:
    person_id: ID
    location: ID


@dataclass(frozen=True)
class Route:
    id: ID
    source: ID
    target: ID
    device_id: ID | None
    segments: tuple[ID, ...]
    points: tuple["Point", ...]
    speed_m_s: Positive
    vertical_speed_m_s: Positive
    qualification: ID
    max_size_m: tuple[Positive, ...]


@dataclass(frozen=True)
class Point:
    x: float
    y: float
    z: float


@dataclass(frozen=True)
class Lot:
    id: ID
    product_id: ID
    material: ID
    unit: Literal["piece", "set", "m2", "t"]
    quantity: Positive
    mass_t: Nonnegative
    size_m: tuple[Positive, ...]
    initial_location: ID
    parent_ids: tuple[ID, ...]
    arrived: bool
    identified: bool
    released: bool


@dataclass(frozen=True)
class Entity:
    id: ID
    product_id: ID
    kind: Literal["COMPONENT", "PRODUCT"]
    initial_location: ID
    mass_t: Positive
    size_m: tuple[Positive, ...]


@dataclass(frozen=True)
class Amount:
    lot_id: ID
    quantity: Positive


@dataclass(frozen=True)
class Operation:
    id: ID
    product_id: ID
    activity_id: ID
    action: Action
    phase: Literal["WALK", "DRIVE", "PUSH", "SETUP", "WORK", "SUPERVISE", "REST"]
    prerequisites: tuple[ID, ...]
    roles: tuple[Role, ...]
    role_locations: tuple[PersonPosition, ...]
    equipment: tuple[ID, ...]
    location: ID
    target: ID | None
    route_id: ID | None
    entity_id: ID | None
    material_inputs: tuple[Amount, ...]
    material_outputs: tuple[Amount, ...]
    scrap_quantity: Nonnegative
    base_h: Nonnegative
    kappa: Nonnegative
    qualification_ids: tuple[ID, ...]
    quality_gates: tuple[ID, ...]
    wait_gate: ID | None
    hold_device: ID | None
    release_device: ID | None
    component_inputs: tuple[ID, ...] = ()
    component_outputs: tuple[ID, ...] = ()
    attempt_index: Index = 0
    unit_index: Index = 0


@dataclass(frozen=True)
class Configuration:
    schema_version: Version
    specification: Literal["S14-ML-SPEC-1.0"]
    layout_version: Literal["S13-TARGET-R5-2"]
    id: ID
    purpose: Literal["RESEARCH_BLOCKED", "SYNTHETIC_TEST_ONLY"]
    scope: Literal["PRODUCTION", "WITNESS_FRAGMENT"]
    products: tuple[Product, ...]
    core_activities: tuple[Activity, ...]
    core_edges: tuple[Edge, ...]
    people: tuple[Person, ...]
    person_positions: tuple[PersonPosition, ...]
    places: tuple[Place, ...]
    devices: tuple[Device, ...]
    routes: tuple[Route, ...]
    lots: tuple[Lot, ...]
    entities: tuple[Entity, ...]
    operations: tuple[Operation, ...]
    evidence: tuple[Evidence, ...]
    cap: Fraction
    min_rest_h: Positive
    setup_h: Nonnegative
    load_h: Nonnegative
    unload_h: Nonnegative
    rigging_t: Nonnegative
    initial_ready_products: tuple[ID, ...]
    initial_ready_evidence: tuple[ID, ...]


@dataclass(frozen=True)
class LotState:
    id: ID
    location: ID
    available: Nonnegative
    consumed: Nonnegative
    converted: Nonnegative
    scrapped: Nonnegative
    returned: Nonnegative
    arrived: bool
    identified: bool
    released: bool


@dataclass(frozen=True)
class Reservation:
    lot_id: ID
    product_id: ID
    activity_id: ID
    attempt: Index
    quantity: Positive


@dataclass(frozen=True)
class Position:
    id: ID
    location: ID
    support: ID


@dataclass(frozen=True)
class Ownership:
    resource_id: ID
    command_id: ID


@dataclass(frozen=True)
class Gate:
    id: ID
    product_id: ID
    attempt: Index
    result: Literal["PASS", "FAIL", "UNKNOWN"]
    occurred_sim_h: Nonnegative
    revision: ID


@dataclass(frozen=True)
class ProductState:
    product_id: ID
    released: bool
    cancelled: bool
    ready_h: Nonnegative | None
    received_h: Nonnegative | None


@dataclass(frozen=True)
class HumanInterval:
    person_id: ID
    command_id: ID | None
    start_h: Nonnegative
    end_h: Nonnegative
    phase: Literal[
        "WALK",
        "DRIVE",
        "PUSH",
        "SETUP",
        "WORK",
        "SUPERVISE",
        "WAIT",
        "REST",
        "OFF_SHIFT",
        "EMERGENCY_HOLD",
    ]
    rate: Nonnegative
    start_f: Fraction
    end_f: Nonnegative
    exposure: Nonnegative


@dataclass(frozen=True)
class DispatchCommand:
    schema_version: Version
    config_id: ID
    config_sha256: Digest
    run_id: ID
    epoch: Index
    id: ID
    product_id: ID
    activity_id: ID
    operation_id: ID
    attempt: Index
    unit_index: Index
    mode_id: Literal["H", "H-team", "MOVE", "WAIT", "GATE"]
    issued_sim_h: Nonnegative
    expected_revision: Index
    roles: tuple[RoleBinding, ...]
    resume_of: ID | None = None


@dataclass(frozen=True)
class Running:
    command: DispatchCommand
    started_h: Nonnegative
    earliest_end_h: Nonnegative
    status: Literal["STARTED", "EXCEPTION"]
    held_at_h: Nonnegative | None = None
    start_progress: Nonnegative = 0
    active_before_h: Nonnegative = 0


@dataclass(frozen=True)
class State:
    time_h: Nonnegative
    revision: Index
    lots: tuple[LotState, ...]
    reservations: tuple[Reservation, ...]
    positions: tuple[Position, ...]
    owners: tuple[Ownership, ...]
    products: tuple[ProductState, ...]
    humans: tuple[HumanState, ...]
    completed: tuple[ID, ...]
    running: tuple[Running, ...]
    gates: tuple[Gate, ...]
    failed_resources: tuple[ID, ...]
    intervals: tuple[HumanInterval, ...]
    receive_permits: tuple[ID, ...]
    motions: tuple["Readback", ...] = ()


@dataclass(frozen=True)
class InputReadback:
    entity_id: ID
    position_m: tuple[float, ...]
    quantity: Nonnegative | None
    visible: bool
    supported: bool


@dataclass(frozen=True)
class Readback:
    """Execution evidence, never accepted as part of a planner command."""

    source: Literal["LIGHT_EXECUTOR", "ISAAC_USD"]
    run_id: ID
    epoch: Index
    command_id: ID
    sample_sim_h: Nonnegative
    entity_id: ID | None
    location: ID
    support: ID
    position_m: tuple[float, ...]
    role_positions: tuple[PersonPosition, ...]
    device_ok: bool
    path_clear: bool
    attached: bool
    landed: bool
    detached: bool
    departed_boundary: bool
    evidence_id: ID
    progress: Nonnegative = 0
    inputs: tuple[InputReadback, ...] = ()


@dataclass(frozen=True)
class ExecutionEvent:
    schema_version: Version
    config_id: ID
    config_sha256: Digest
    run_id: ID
    epoch: Index
    id: ID
    sequence: Index
    command_id: ID | None
    product_id: ID | None
    activity_id: ID | None
    attempt: Index | None
    kind: Literal[
        "ACCEPTED",
        "REJECTED",
        "DEFERRED",
        "STARTED",
        "COMPLETED",
        "EXCEPTION",
        "WORLD",
        "CLOCK",
        "PROGRESS",
    ]
    occurred_sim_h: Nonnegative
    received_sim_h: Nonnegative
    wall_elapsed_s: Nonnegative
    reason: str
    command: DispatchCommand | None
    command_sha256: Digest | None
    world: "WorldEvent | None"
    readback: Readback | None
    state: State


@dataclass(frozen=True)
class WorldEvent:
    id: ID
    run_id: ID
    epoch: Index
    occurred_sim_h: Nonnegative
    kind: Literal[
        "ARRIVAL",
        "IDENTIFY",
        "RELEASE",
        "QUALITY",
        "PROCESS_RELEASE",
        "FAILURE",
        "REPAIR",
        "CANCEL",
        "ORDER_ARRIVAL",
        "RECEIVE_PERMIT",
    ]
    entity_id: ID
    product_id: ID
    attempt: Index
    result: Literal["PASS", "FAIL", "UNKNOWN"]
    evidence_id: ID


@dataclass(frozen=True)
class ExecutionSnapshot:
    schema_version: Version
    config_id: ID
    config_sha256: Digest
    run_id: ID
    epoch: Index
    state: State
    events: tuple[ExecutionEvent, ...]


@dataclass(frozen=True)
class PlanningObservation:
    schema_version: Version
    config_id: ID
    config_sha256: Digest
    run_id: ID
    epoch: Index
    id: ID
    sampled_h: Nonnegative
    received_h: Nonnegative
    state: State
    event_ids: tuple[ID, ...]


@dataclass(frozen=True)
class PlanningInput:
    schema_version: Version
    config_id: ID
    observation: PlanningObservation
    operations: tuple[Operation, ...]
    budget_ms: Positive


@dataclass(frozen=True)
class Plan:
    schema_version: Version
    config_id: ID
    observation_id: ID
    commands: tuple[DispatchCommand, ...]
    status: Literal["CANDIDATE", "WAIT", "NO_PLAN_FOUND"]
    reason: str


@dataclass(frozen=True)
class HiddenScenario:
    schema_version: Version
    config_id: ID
    events: tuple[WorldEvent, ...]


@dataclass(frozen=True)
class OfflineEvaluation:
    schema_version: Version
    config_id: ID
    window_h: Nonnegative
    ready_count: Index
    received_count: Index
    internal_finished_count: Index
    cancelled_count: Index
    incomplete_count: Index
    total_exposure: Nonnegative
    max_exposure: Nonnegative
    scope: Literal["INDEPENDENT_EVENT_RECONSTRUCTION"]


@dataclass(frozen=True)
class RunManifest:
    schema_version: Version
    config_id: ID
    config_sha256: Digest
    specification: Literal["S14-ML-SPEC-1.0"]
    layout_version: Literal["S13-TARGET-R5-2"]
    backend: Literal["logistics-event", "isaac-usd"]
    run_id: ID
    epoch: Index
    code_revision: str
    status: Literal["PLANNED", "HOLD", "SYNTHETIC_TEST_COMPLETE"]
    industrial_qualification: Literal["NOT_ESTABLISHED"]
