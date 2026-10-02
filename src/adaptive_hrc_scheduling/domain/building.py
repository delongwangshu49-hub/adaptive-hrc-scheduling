"""Building-domain C04-1.0 records. Hours, tonnes and explicit unknown evidence.

These immutable records describe research fixtures, not industrial qualification.
The historical pipe domain stays in models.py/state.py without implicit conversion.
"""

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

Version = Literal["C04-1.0"]
Status = Literal["PASS", "FAIL", "UNKNOWN"]


@dataclass(frozen=True)
class Units:
    time: Literal["h"]
    rate: Literal["h^-1"]
    exposure: Literal["F.h"]
    mass: Literal["t"]
    length: Literal["m"]


@dataclass(frozen=True)
class Evidence:
    id: ID
    status: Status
    basis: Literal["INDUSTRIAL", "SYNTHETIC_TEST", "UNRESOLVED"]
    reference: str
    revision: ID


@dataclass(frozen=True)
class Parameter:
    id: ID
    value: Nonnegative
    unit: str
    classification: Literal["F", "A", "E", "U"]
    source: str
    validity: str


@dataclass(frozen=True)
class Calendar:
    period_h: Positive
    windows: tuple["Window", ...]


@dataclass(frozen=True)
class Window:
    start_h: Nonnegative
    end_h: Positive


@dataclass(frozen=True)
class Person:
    id: ID
    qualifications: tuple[ID, ...]
    valid_until_h: Positive
    initial_f: Fraction
    work_rate: Nonnegative
    wait_rate: Positive
    recovery_rate: Positive
    calendar: Calendar


@dataclass(frozen=True)
class Resource:
    id: ID
    kind: Literal["BAY", "BUFFER", "EQUIPMENT", "FIXTURE", "ROUTE"]
    capacity: Count
    load_t: Nonnegative


@dataclass(frozen=True)
class Role:
    id: ID
    qualification: ID


@dataclass(frozen=True)
class BOMItem:
    id: ID
    quantity: Positive
    unit: str


@dataclass(frozen=True)
class Product:
    id: ID
    order_id: ID
    variant: Literal["SR-W1", "SR-W2"]
    revision: ID
    bom: tuple[BOMItem, ...]
    mass_t: Positive
    rigging_t: Positive
    release_h: Nonnegative
    due_h: Positive


@dataclass(frozen=True)
class Component:
    id: ID
    product_id: ID
    kind: Literal["BOTTOM", "TOP", "COLUMNS"]
    quantity: Count
    initial_location: ID
    mass_t: Positive


@dataclass(frozen=True)
class Material:
    id: ID
    product_id: ID
    activity_id: ID
    bom_ids: tuple[ID, ...]
    quantity: Positive
    arrived: bool
    identified: bool
    released: bool


@dataclass(frozen=True)
class WorkUnit:
    id: ID
    base_h: Positive
    checkpoint_id: ID
    phase: Literal["SETUP", "WORK", "ROBOT", "UNLOAD", "CHECK", "MOVE"]
    roles: tuple[Role, ...]
    equipment: tuple[ID, ...]
    kappa: Nonnegative
    resumable: bool


@dataclass(frozen=True)
class Mode:
    id: ID
    kind: Literal["H", "H-team", "HR-seq", "MOVE", "WAIT", "GATE"]
    output_revision: ID
    qualification_ids: tuple[ID, ...]
    qualification_revisions: tuple[ID, ...]
    units: tuple[WorkUnit, ...]
    enabled: bool


@dataclass(frozen=True)
class Move:
    source: ID
    target: ID
    route: ID
    equipment: ID
    entity_ids: tuple[ID, ...]
    landing_h: tuple[Positive, ...]
    qualification_ids: tuple[ID, ...]
    qualification_revisions: tuple[ID, ...]


@dataclass(frozen=True)
class Activity:
    id: ID
    product_id: ID
    code: ID
    location: ID
    face: str
    modes: tuple[Mode, ...]
    material_ids: tuple[ID, ...]
    wait_h: Nonnegative
    release_evidence: ID | None
    quality_evidence: ID | None
    move: Move | None


@dataclass(frozen=True)
class Edge:
    source: ID
    target: ID
    relation: Literal["material", "precedence", "quality", "wait_release"]


@dataclass(frozen=True)
class FacePair:
    first: str
    second: str
    qualification_id: ID


@dataclass(frozen=True)
class Configuration:
    schema_version: Version
    id: ID
    specification: Literal["C03-0.3"]
    units: Units
    purpose: Literal["RESEARCH_BLOCKED", "SYNTHETIC_TEST_ONLY"]
    cap: Fraction
    min_rest_h: Positive
    observation_window_h: Positive
    people: tuple[Person, ...]
    resources: tuple[Resource, ...]
    products: tuple[Product, ...]
    components: tuple[Component, ...]
    materials: tuple[Material, ...]
    activities: tuple[Activity, ...]
    edges: tuple[Edge, ...]
    evidence: tuple[Evidence, ...]
    face_pairs: tuple[FacePair, ...]
    parameters: tuple[Parameter, ...]


@dataclass(frozen=True)
class RoleBinding:
    role_id: ID
    person_id: ID


@dataclass(frozen=True)
class Attempt:
    activity_id: ID
    number: Index
    mode_id: ID
    completed_units: Index
    state: Literal[
        "NOT_READY",
        "RUNNING",
        "PAUSED_AT_CHECKPOINT",
        "WAITING_RELEASE",
        "FAILED",
        "COMPLETED",
        "CANCELLED",
    ]
    wait_until_h: Nonnegative | None
    prepared: bool


@dataclass(frozen=True)
class Residency:
    entity_id: ID
    location: ID
    owner: ID
    reserved: bool


@dataclass(frozen=True)
class Lock:
    resource_id: ID
    owner: ID


@dataclass(frozen=True)
class QualityRecord:
    id: ID
    product_id: ID
    activity_id: ID
    attempt: Index
    product_revision: ID
    criterion_revision: ID
    inspector_id: ID
    time_h: Nonnegative
    result: Status
    valid: bool


@dataclass(frozen=True)
class HumanState:
    person_id: ID
    fatigue: Fraction
    exposure: Nonnegative
    peak: Fraction
    rest_until_h: Nonnegative


@dataclass(frozen=True)
class ProductState:
    product_id: ID
    location: ID
    state: Literal[
        "RELEASED",
        "IN_PROCESS",
        "BLOCKED",
        "QUALITY_HOLD",
        "CANCEL_PENDING",
        "QUARANTINED",
        "READY",
        "RECEIVED",
    ]
    cancelled: bool
    ready_h: Nonnegative | None
    installed_bom: tuple[ID, ...]
    water_present: bool


@dataclass(frozen=True)
class ComponentState:
    component_id: ID
    location: ID
    incorporated: bool


@dataclass(frozen=True)
class MaterialState:
    material_id: ID
    arrived: bool
    identified: bool
    released: bool
    consumed_by: ID | None


@dataclass(frozen=True)
class Running:
    activity_id: ID
    attempt: Index
    unit_index: Index
    mode_id: ID
    start_h: Nonnegative
    end_h: Nonnegative
    sampled_max_f: Fraction
    multiplier: Positive
    roles: tuple[RoleBinding, ...]
    equipment: tuple[ID, ...]
    state: Literal["ACTIVE", "EMERGENCY_HOLD"]
    landings_done: Index


@dataclass(frozen=True)
class WorldEvent:
    id: ID
    time_h: Nonnegative
    kind: Literal[
        "MATERIAL_ARRIVAL",
        "MATERIAL_IDENTIFY",
        "MATERIAL_RELEASE",
        "PROCESS_RELEASE",
        "QUALITY_RESULT",
        "INVALIDATE",
        "FAILURE",
        "REPAIR",
        "ORDER_ARRIVAL",
        "CANCEL",
        "RECEIVED",
    ]
    entity_id: ID
    value: Status | None
    attempt: Index | None


@dataclass(frozen=True)
class ObservedProduct:
    product_id: ID
    state: str | None
    location: str | None
    completed_activity_ids: tuple[ID, ...]
    cancelled: bool | None


@dataclass(frozen=True)
class PlanningObservation:
    schema_version: Version
    config_id: ID
    id: ID
    sampled_h: Nonnegative
    received_h: Nonnegative
    observed_h: Nonnegative
    state_revision: Index
    products: tuple[ObservedProduct, ...]
    people: tuple[HumanState, ...]
    unavailable_resources: tuple[ID, ...]
    event_ids: tuple[ID, ...]


@dataclass(frozen=True)
class PlanningInput:
    schema_version: Version
    config_id: ID
    observation: PlanningObservation
    products: tuple[Product, ...]
    activities: tuple[Activity, ...]
    decision_budget_ms: Positive


@dataclass(frozen=True)
class DispatchCommand:
    schema_version: Version
    config_id: ID
    id: ID
    issued_h: Nonnegative
    expected_revision: Index
    activity_id: ID
    mode_id: ID
    attempt: Index
    unit_index: Index
    roles: tuple[RoleBinding, ...]


@dataclass(frozen=True)
class Plan:
    schema_version: Version
    config_id: ID
    observation_id: ID
    commands: tuple[DispatchCommand, ...]
    predicted_ready: tuple["Prediction", ...]
    status: Literal["INCOMPLETE", "CANDIDATE"]


@dataclass(frozen=True)
class Prediction:
    product_id: ID
    ready_h: Nonnegative | None


@dataclass(frozen=True)
class ExecutionEvent:
    schema_version: Version
    config_id: ID
    id: ID
    time_h: Nonnegative
    kind: str
    entity_id: ID
    attempt: Index | None
    reason: str


@dataclass(frozen=True)
class HiddenScenario:
    schema_version: Version
    config_id: ID
    seed: Index
    events: tuple[WorldEvent, ...]


@dataclass(frozen=True)
class ExecutionSnapshot:
    schema_version: Version
    config_id: ID
    config_sha256: Digest
    time_h: Nonnegative
    revision: Index
    products: tuple[ProductState, ...]
    components: tuple[ComponentState, ...]
    materials: tuple[MaterialState, ...]
    attempts: tuple[Attempt, ...]
    running: tuple[Running, ...]
    people: tuple[HumanState, ...]
    residencies: tuple[Residency, ...]
    locks: tuple[Lock, ...]
    quality: tuple[QualityRecord, ...]
    failed_resources: tuple[ID, ...]
    released_processes: tuple[ID, ...]
    released_products: tuple[ID, ...]
    consumed_commands: tuple[ID, ...]
    event_cursor: Index
    random_cursor: Index
    scenario: HiddenScenario
    observation_queue: tuple[PlanningObservation, ...]
    events: tuple[ExecutionEvent, ...]
    intervals: tuple["HumanInterval", ...]
    services: tuple["Service", ...]


@dataclass(frozen=True)
class HumanInterval:
    person_id: ID
    start_h: Nonnegative
    end_h: Nonnegative
    activity: Literal[
        "WORK", "SUPERVISE", "WAIT", "REST", "OFF_SHIFT", "HANDOVER", "RESTORE", "EMERGENCY_HOLD"
    ]
    rate: Nonnegative
    start_f: Fraction
    end_f: Fraction
    exposure: Nonnegative


@dataclass(frozen=True)
class OfflineEvaluation:
    schema_version: Version
    config_id: ID
    window_h: Positive
    products: tuple[ProductState, ...]
    people: tuple[HumanState, ...]
    incomplete_count: Index
    cancelled_count: Index
    scope: Literal["EXECUTOR_SUMMARY_NOT_S10"]


@dataclass(frozen=True)
class RunManifest:
    schema_version: Version
    config_id: ID
    configuration_sha256: Digest
    specification: Literal["C03-0.3"]
    code_revision: str
    seed: Index
    backend: Literal["building-event"]
    status: Literal["PLANNED", "HOLD", "SYNTHETIC_TEST_COMPLETE"]
    gaps: tuple[ID, ...]
    industrial_qualification: Literal["NOT_ESTABLISHED"]


@dataclass(frozen=True)
class Service:
    id: ID
    kind: Literal["HANDOVER", "RESTORE", "REPAIR", "CLEANUP"]
    activity_id: ID
    product_id: ID
    people: tuple[ID, ...]
    start_h: Nonnegative
    end_h: Nonnegative
    source: ID | None
    target: ID | None
    state: Literal["ACTIVE", "EMERGENCY_HOLD"]
    replacement_person: ID | None
    outgoing_person: ID | None


# Frozen C03 DAG, identified by public activity codes; do not infer edges at runtime.
STEEL_EDGES = (
    ("KIT", "CUT", "material"),
    ("CUT", "MV-IN-B", "material"),
    ("MV-IN-B", "W-B", "precedence"),
    ("W-B", "MV-B", "precedence"),
    ("CUT", "MV-IN-T", "material"),
    ("MV-IN-T", "W-T", "precedence"),
    ("W-T", "MV-T", "precedence"),
    ("MV-B", "JOIN-IN", "material"),
    ("MV-T", "JOIN-IN", "material"),
    ("KIT", "JOIN-IN", "material"),
    ("JOIN-IN", "W-3D", "precedence"),
    ("W-3D", "Q-STR", "precedence"),
    ("Q-STR", "COAT", "quality"),
    ("COAT", "WAIT-COAT", "precedence"),
    ("WAIT-COAT", "MOVE-F", "wait_release"),
    ("MOVE-F", "FLOOR", "precedence"),
    ("KIT", "FLOOR", "material"),
    ("FLOOR", "MEP-E", "precedence"),
    ("FLOOR", "MEP-P", "precedence"),
    ("MEP-E", "Q-MEP", "precedence"),
    ("MEP-P", "Q-MEP", "precedence"),
    ("Q-MEP", "LINING", "quality"),
    ("LINING", "Q-LIN", "precedence"),
    ("Q-LIN", "WPROOF", "quality"),
    ("WPROOF", "WAIT-W", "precedence"),
    ("WAIT-W", "TEST-SET", "wait_release"),
    ("TEST-SET", "WAIT-TEST", "precedence"),
    ("WAIT-TEST", "Q-POND", "wait_release"),
    ("Q-POND", "TILE", "quality"),
    ("TILE", "WAIT-TILE", "precedence"),
    ("WAIT-TILE", "EXT", "wait_release"),
    ("EXT", "Q-EXT", "precedence"),
    ("Q-EXT", "PAINT", "quality"),
    ("PAINT", "WAIT-PAINT", "precedence"),
    ("WAIT-PAINT", "FIT", "wait_release"),
    ("FIT", "Q-FIN", "precedence"),
    ("Q-FIN", "PACK", "quality"),
    ("PACK", "Q-PACK", "precedence"),
    ("Q-PACK", "MOVE-OUT", "quality"),
    ("MOVE-OUT", "READY", "precedence"),
)
