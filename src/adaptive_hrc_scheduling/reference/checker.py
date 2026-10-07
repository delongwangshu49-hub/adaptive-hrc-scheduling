"""Independent S16 half-open interval sweep, with no CP-SAT imports."""

from dataclasses import dataclass
from fractions import Fraction

from adaptive_hrc_scheduling.reference.domain import Entry, quantize, validate


@dataclass(frozen=True)
class Report:
    valid: bool
    findings: tuple[str, ...]
    objective: int | None
    ready: tuple[tuple[str, int], ...] = ()
    received: tuple[tuple[str, int], ...] = ()


def to_hours(instance, schedule):
    """Exact inverse projection; never fabricates a full production ExecutionSnapshot."""
    validate(instance)
    tick = Fraction(instance.tick_h)
    return tuple(
        (e.task_id, e.alternative_id, str(e.start * tick), str(e.end * tick)) for e in schedule
    )


def check_hours(instance, records):
    entries = tuple(
        Entry(task, alt, quantize(start, instance.tick_h)[0], quantize(end, instance.tick_h)[0])
        for task, alt, start, end in records
    )
    return check(instance, entries)


def check(instance, schedule, *, partial=False):
    validate(instance)
    tasks = {t.id: t for t in instance.tasks}
    people = {p.id: p for p in instance.people}
    capacity = {r.id: r.capacity for r in instance.resources} | {p.id: 1 for p in instance.people}
    entries, alternatives, findings = {}, {}, []
    for entry in schedule:
        if entry.task_id in entries or entry.task_id not in tasks:
            findings.append("TASK_ID:" + entry.task_id)
            continue
        entries[entry.task_id] = entry
        alt = next(
            (a for a in tasks[entry.task_id].alternatives if a.id == entry.alternative_id), None
        )
        if alt is None:
            findings.append("ALTERNATIVE:" + entry.task_id)
            continue
        alternatives[entry.task_id] = alt
        if (
            type(entry.start) is not int
            or type(entry.end) is not int
            or not 0 <= entry.start < entry.end <= instance.horizon
            or entry.end - entry.start != alt.duration
        ):
            findings.append("TIME:" + entry.task_id)
    if not partial and set(entries) != set(tasks):
        findings.append("INCOMPLETE")
    if findings:
        return Report(False, tuple(findings), None)
    usage = {r: [] for r in capacity}
    for task_id, entry in entries.items():
        task, alt = tasks[task_id], alternatives[task_id]
        if entry.start < task.release:
            findings.append("RELEASE:" + task_id)
        if task.latest_end is not None and entry.end > task.latest_end:
            findings.append("LATEST_END:" + task_id)
        for pred in task.predecessors:
            if pred not in entries or entries[pred].end > entry.start:
                findings.append("PRECEDENCE:" + task_id)
        for resource, demand in alt.resources:
            usage[resource].append((entry.start, entry.end, demand))
        for _, person in alt.roles:
            usage[person].append((entry.start, entry.end, 1))
            if not any(s <= entry.start and entry.end <= e for s, e in people[person].windows):
                findings.append("CALENDAR:" + task_id + ":" + person)
    ready, received = [], []
    for product in instance.products:
        if product.ready in entries:
            r = entries[product.ready].end
            ready.append((product.id, r))
            end = entries[product.store].end if product.store in entries else instance.horizon
            usage[product.output].append((r, end, 1))
        if product.store in entries:
            start = entries[product.store].start
            end = entries[product.receive].end if product.receive in entries else instance.horizon
            usage[product.buffer].append((start, end, 1))
        if product.receive in entries:
            received.append((product.id, entries[product.receive].end))
    for resource, intervals in usage.items():
        boundaries = sorted({t for start, end, _ in intervals for t in (start, end)})
        for time in boundaries:
            if sum(d for s, e, d in intervals if s <= time < e) > capacity[resource]:
                findings.append(f"CAPACITY:{resource}:{time}")
    if partial or findings:
        return Report(not findings, tuple(findings), None, tuple(ready), tuple(received))
    cost = sum(alternatives[t].cost for t in entries)
    completion = max(e.end for e in entries.values())
    tardiness = sum(p.weight * max(0, entries[p.receive].end - p.due) for p in instance.products)
    objective = (
        instance.tardiness_weight * tardiness
        + instance.makespan_weight * completion
        + instance.cost_weight * cost
    )
    return Report(True, (), objective, tuple(ready), tuple(received))
