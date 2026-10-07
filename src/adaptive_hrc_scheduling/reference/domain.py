"""Explicit synthetic projection, with exact decimal time conversion."""

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from fractions import Fraction

VERSION = "S16-STATIC-1.1"
LAYOUT_VERSION = "S16-ABSTRACT-GRAPH-1"
LIMIT = 1_000_000


@dataclass(frozen=True)
class Resource:
    id: str
    capacity: int = 1


@dataclass(frozen=True)
class Person:
    id: str
    qualifications: tuple[str, ...]
    windows: tuple[tuple[int, int], ...]


@dataclass(frozen=True)
class Alternative:
    id: str
    duration: int
    resources: tuple[tuple[str, int], ...] = ()
    roles: tuple[tuple[str, str], ...] = ()  # qualification, named person
    cost: int = 0
    kind: str = "H"


@dataclass(frozen=True)
class Task:
    id: str
    alternatives: tuple[Alternative, ...]
    predecessors: tuple[str, ...] = ()
    release: int = 0
    latest_end: int | None = None


@dataclass(frozen=True)
class Product:
    id: str
    ready: str
    store: str
    receive: str
    output: str
    buffer: str
    due: int
    weight: int = 1


@dataclass(frozen=True)
class Instance:
    id: str
    horizon: int
    tasks: tuple[Task, ...]
    resources: tuple[Resource, ...]
    people: tuple[Person, ...] = ()
    products: tuple[Product, ...] = ()
    tick_h: str = "1"
    tardiness_weight: int = 1
    makespan_weight: int = 1
    cost_weight: int = 1
    schema_version: str = VERSION
    purpose: str = "SYNTHETIC_STATIC_REFERENCE"
    layout_version: str = LAYOUT_VERSION


@dataclass(frozen=True)
class Entry:
    task_id: str
    alternative_id: str
    start: int
    end: int


def _integer(value, *, minimum=0):
    return type(value) is int and minimum <= value <= LIMIT


def grid_fraction(value):
    """One exact grid policy for validation, integerization and inverse projection."""
    if type(value) is not str:
        raise ValueError("tick_h must be a positive rational string")
    try:
        result = Fraction(value)
    except (ValueError, ZeroDivisionError) as error:
        raise ValueError("tick_h must be a positive rational string") from error
    if result <= 0:
        raise ValueError("tick_h must be positive")
    return result


def _tuple(value, label):
    if type(value) is not tuple:
        raise ValueError(label + ": expected immutable tuple")
    return value


def _array(value, label):
    if type(value) not in (list, tuple):
        raise ValueError(label + ": expected array")
    return tuple(value)


def _strings(value, label, *, immutable=False):
    sequence = _tuple(value, label) if immutable else _array(value, label)
    if any(type(element) is not str or not element for element in sequence):
        raise ValueError(label + ": expected atomic nonempty strings")
    return sequence


def _pairs(value, label, *, immutable=False):
    sequence = _tuple(value, label) if immutable else _array(value, label)
    result = []
    for element in sequence:
        pair = _tuple(element, label) if immutable else _array(element, label)
        if len(pair) != 2:
            raise ValueError(label + ": expected two-element arrays")
        result.append(pair)
    return tuple(result)


def _object(value, label):
    if type(value) is not dict:
        raise ValueError(label + ": expected object")
    return value


def _objects(value, label):
    return tuple(_object(element, label) for element in _array(value, label))


def _ids(records, label):
    _tuple(records, label)
    ids = [r.id for r in records]
    if len(set(ids)) != len(ids) or any(
        not isinstance(i, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_.-]{0,63}", i) for i in ids
    ):
        raise ValueError(f"{label}: invalid or duplicate ID")
    return {r.id: r for r in records}


def validate(instance):
    if not isinstance(instance, Instance):
        raise ValueError("explicit S16 Instance required; no full-world conversion")
    if (
        instance.schema_version != VERSION
        or instance.purpose != "SYNTHETIC_STATIC_REFERENCE"
        or instance.layout_version != LAYOUT_VERSION
    ):
        raise ValueError("version/purpose")
    _ids((instance,), "instance")
    if not _integer(instance.horizon, minimum=1):
        raise ValueError("horizon/tick")
    grid_fraction(instance.tick_h)
    for w in (instance.tardiness_weight, instance.makespan_weight, instance.cost_weight):
        if not _integer(w):
            raise ValueError("objective weight")
    tasks = _ids(instance.tasks, "tasks")
    resources = _ids(instance.resources, "resources")
    people = _ids(instance.people, "people")
    _ids(instance.products, "products")
    if not tasks or set(resources) & set(people):
        raise ValueError("empty tasks or ambiguous resource/person identity")
    for resource in resources.values():
        if not _integer(resource.capacity, minimum=1):
            raise ValueError("capacity")
    for person in people.values():
        _strings(person.qualifications, "qualifications", immutable=True)
        _pairs(person.windows, "windows", immutable=True)
        if len(set(person.qualifications)) != len(person.qualifications):
            raise ValueError("duplicate qualification")
        prior_end = -1
        for start, end in person.windows:
            if not _integer(start) or not _integer(end) or not prior_end <= start < end:
                raise ValueError("calendar")
            prior_end = end
    visited = set()
    pending = set(tasks)
    for task in tasks.values():
        _strings(task.predecessors, "predecessors", immutable=True)
    while pending:
        eligible = {t for t in pending if set(tasks[t].predecessors) <= visited}
        if not eligible:
            raise ValueError("cycle or unknown predecessor")
        visited |= eligible
        pending -= eligible
    for task in tasks.values():
        if not _integer(task.release) or not task.alternatives:
            raise ValueError("release/alternatives")
        if task.latest_end is not None and not _integer(task.latest_end):
            raise ValueError("latest end")
        if len(set(task.predecessors)) != len(task.predecessors):
            raise ValueError("duplicate predecessor")
        _ids(task.alternatives, "alternatives")
        for alt in task.alternatives:
            _pairs(alt.resources, "resources", immutable=True)
            _pairs(alt.roles, "roles", immutable=True)
            if alt.kind not in ("H", "H-team", "MOVE", "WAIT", "GATE"):
                raise ValueError("HR and unknown modes disabled")
            if not _integer(alt.duration, minimum=1) or not _integer(alt.cost):
                raise ValueError("duration/cost")
            if len({r for r, _ in alt.resources}) != len(alt.resources):
                raise ValueError("duplicate demand")
            if len({p for _, p in alt.roles}) != len(alt.roles):
                raise ValueError("roles require distinct named people")
            for resource, demand in alt.resources:
                if resource not in resources or not _integer(demand, minimum=1):
                    raise ValueError("unknown resource/demand")
            for qualification, person in alt.roles:
                if type(qualification) is not str or type(person) is not str:
                    raise ValueError("role IDs must be atomic strings")
                if person not in people or qualification not in people[person].qualifications:
                    raise ValueError("role qualification")
    markers = []
    for product in instance.products:
        if any(t not in tasks for t in (product.ready, product.store, product.receive)):
            raise ValueError("product task")
        markers.extend((product.ready, product.store, product.receive))
        if product.output not in resources or product.buffer not in resources:
            raise ValueError("product place")
        if product.output == product.buffer or resources[product.output].capacity != 1:
            raise ValueError("output must be distinct capacity-one station")
        if product.ready not in tasks[product.store].predecessors:
            raise ValueError("store must follow READY")
        if product.store not in tasks[product.receive].predecessors:
            raise ValueError("receive must follow store")
        if not _integer(product.due) or not _integer(product.weight, minimum=1):
            raise ValueError("due/weight")
        if any((product.output, 1) not in a.resources for a in tasks[product.ready].alternatives):
            raise ValueError("READY must occupy output")
        if any(
            r in (product.output, product.buffer)
            for t in (product.store, product.receive)
            for a in tasks[t].alternatives
            for r, _ in a.resources
        ):
            raise ValueError("residency places must not be double counted by transport")
    if len(set(markers)) != len(markers):
        raise ValueError("product markers must be distinct")
    # Bound all objective arithmetic well below int64 and exact double integers.
    bound = (
        instance.tardiness_weight * sum(p.weight * instance.horizon for p in instance.products)
        + instance.makespan_weight * instance.horizon
        + instance.cost_weight * sum(max(a.cost for a in t.alternatives) for t in instance.tasks)
    )
    if bound > 2**50:
        raise ValueError("objective overflow bound")
    return instance


def digest(instance):
    validate(instance)
    return hashlib.sha256(
        json.dumps(asdict(instance), sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def from_dict(data):
    data = dict(_object(data, "instance"))
    if not {"schema_version", "purpose", "layout_version"} <= data.keys():
        raise ValueError("explicit reference version, purpose and layout_version required")
    data["tasks"] = tuple(
        Task(
            **{
                **t,
                "predecessors": _strings(t.get("predecessors", ()), "predecessors"),
                "alternatives": tuple(
                    Alternative(
                        **{
                            **a,
                            "resources": _pairs(a.get("resources", ()), "resources"),
                            "roles": _pairs(a.get("roles", ()), "roles"),
                        }
                    )
                    for a in _objects(t["alternatives"], "alternatives")
                ),
            }
        )
        for t in _objects(data["tasks"], "tasks")
    )
    data["resources"] = tuple(Resource(**r) for r in _objects(data["resources"], "resources"))
    data["people"] = tuple(
        Person(
            **{
                **p,
                "qualifications": _strings(p["qualifications"], "qualifications"),
                "windows": _pairs(p["windows"], "windows"),
            }
        )
        for p in _objects(data.get("people", ()), "people")
    )
    data["products"] = tuple(Product(**p) for p in _objects(data.get("products", ()), "products"))
    return validate(Instance(**data))


def quantize(value_h, tick_h, direction="exact"):
    """Decimal strings avoid binary float rounding; conservative bounds are explicit."""
    if direction not in ("exact", "lower", "upper"):
        raise ValueError("rounding policy")
    value, tick = Fraction(str(value_h)), grid_fraction(tick_h)
    if value < 0 or tick <= 0:
        raise ValueError("time/grid")
    ratio = value / tick
    if direction == "exact" and ratio.denominator != 1:
        raise ValueError("off-grid time; explicit simplification required")
    integer = (
        -(-ratio.numerator // ratio.denominator)
        if direction == "lower"
        else ratio.numerator // ratio.denominator
    )
    if not _integer(integer):
        raise ValueError("time bound")
    return integer, str(integer * tick - value)
