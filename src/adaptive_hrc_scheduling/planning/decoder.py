"""S11 bounded static schedule generation on an isolated C05 candidate world.

No HiddenScenario or execution snapshot is accepted. Initial observations must
be complete at t=0. Synthetic gate assumptions are opt-in and are recorded as
candidate facts, never asserted to be future factory observations.
"""

import copy
import json
import math
from dataclasses import dataclass, replace
from time import perf_counter

from adaptive_hrc_scheduling.building_backend import BuildingBackend
from adaptive_hrc_scheduling.building_human import calendar_state
from adaptive_hrc_scheduling.checker import check_run
from adaptive_hrc_scheduling.contracts.building import evidence_pass, validate
from adaptive_hrc_scheduling.contracts.codec import ContractError
from adaptive_hrc_scheduling.domain import building as b
from adaptive_hrc_scheduling.planning.rules import RULES, Candidate, select


@dataclass(frozen=True)
class Options:
    rule: str = "EDD"
    horizon_h: float = 480.0
    max_decisions: int = 5000
    max_bindings: int = 10000
    synthetic_gate_assumptions: bool = False


@dataclass(frozen=True)
class Wait:
    time_h: float
    activity_id: str
    mode_id: str
    reason: str
    blockers: tuple[str, ...] = ()


@dataclass
class Result:
    status: str
    reason: str
    configuration: b.Configuration | None
    observation: b.PlanningObservation | None
    plan: b.Plan | None
    trace: b.ExecutionSnapshot | None
    report: object | None
    waits: tuple[Wait, ...]
    assumptions: tuple[str, ...]
    decisions: int
    wall_ms: float


def _latest(world):
    return {a.activity_id: a for a in sorted(world.snapshot.attempts, key=lambda a: a.number)}


def _bindings(world, activity, mode, index, previous):
    roles = mode.units[index].roles if mode.units else ()
    committed = {}
    if previous and previous.completed_units and previous.prepared:
        starts = [
            e
            for e in world.snapshot.events
            if e.kind == "UNIT_START"
            and e.entity_id == activity.id
            and e.attempt == previous.number
        ]
        if starts:
            committed = {
                r["role_id"]: r["person_id"] for r in json.loads(starts[-1].reason)["roles"]
            }

    def visit(i, assigned):
        if i == len(roles):
            yield tuple(assigned)
            return
        role = roles[i]
        for person in sorted(world.config.people, key=lambda p: p.id):
            if (
                role.qualification in person.qualifications
                and person.valid_until_h > world.time
                and person.id not in {r.person_id for r in assigned}
                and (role.id not in committed or committed[role.id] == person.id)
            ):
                yield from visit(i + 1, assigned + [b.RoleBinding(role.id, person.id)])

    yield from visit(0, [])


def legal_candidates(world, *, max_bindings=10000):
    """Probe immutable snapshot copies; rejected probes never alter the trace.

    Return all admitted candidates in the bounded enumeration, rejection/wait
    reasons and exhaustion flag. The caller must not rank a truncated set.
    """
    latest = _latest(world)
    humans = {h.person_id: h for h in world.snapshot.people}
    candidates, waits = [], []
    probes = 0
    for a in sorted(world.config.activities, key=lambda a: a.id):
        prior = latest.get(a.id)
        if prior and prior.state in ("COMPLETED", "RUNNING", "CANCELLED", "FAILED"):
            continue
        unfinished = tuple(
            sorted(
                e.source
                for e in world.config.edges
                if e.target == a.id
                and (e.source not in latest or latest[e.source].state != "COMPLETED")
            )
        )
        if unfinished:
            waits.append(Wait(world.time, a.id, "", "PREDECESSOR", unfinished))
            continue
        for mode in sorted(a.modes, key=lambda m: m.id):
            if prior and prior.mode_id != mode.id:
                continue
            if not mode.enabled or not evidence_pass(world.config, mode.qualification_ids):
                waits.append(Wait(world.time, a.id, mode.id, "MODE_DISABLED_OR_UNQUALIFIED"))
                continue
            index = prior.completed_units if prior else 0
            found = False
            for roles in _bindings(world, a, mode, index, prior):
                found = True
                probes += 1
                if probes > max_bindings:
                    return (), tuple(waits), True
                c = b.DispatchCommand(
                    "C04-1.0",
                    world.config.id,
                    f"S11-CMD-{len(world.snapshot.consumed_commands) + 1}",
                    world.time,
                    world.snapshot.revision,
                    a.id,
                    mode.id,
                    prior.number if prior else 0,
                    index,
                    roles,
                )
                trial = copy.copy(world)
                try:
                    receipt = trial.dispatch(c)
                    reason = None if receipt.accepted else receipt.reason
                except ContractError as error:
                    reason = str(error)
                if reason is None:
                    # Remaining-unit estimate freezes current assigned fatigue. For
                    # later roles, use the highest fatigue of qualified pool members.
                    bound = {r.role_id: r.person_id for r in roles}
                    estimate = 0.0
                    for unit in mode.units[index:]:
                        fatigue = max(
                            (
                                humans[bound[r.id]].fatigue
                                if r.id in bound
                                else max(
                                    (
                                        humans[p.id].fatigue
                                        for p in world.config.people
                                        if r.qualification in p.qualifications
                                    ),
                                    default=world.config.cap,
                                )
                                for r in unit.roles
                            ),
                            default=0.0,
                        )
                        estimate += unit.base_h * (1 + unit.kappa * fatigue)
                    candidates.append(
                        Candidate(c, a.product_id, world.products[a.product_id].due_h, estimate)
                    )
                else:
                    blockers = ()
                    if reason.startswith("RESOURCE_BUSY:"):
                        rid = reason.split(":", 1)[1]
                        blockers = tuple(
                            sorted(
                                {rid}
                                | {
                                    lock.owner
                                    for lock in world.snapshot.locks
                                    if lock.resource_id == rid
                                }
                            )
                        )
                    elif reason.startswith("DESTINATION_CAPACITY:"):
                        rid = reason.split(":", 1)[1]
                        blockers = tuple(
                            sorted(
                                {rid}
                                | {r.owner for r in world.snapshot.residencies if r.location == rid}
                            )
                        )
                    elif reason in (
                        "CALENDAR_OR_QUALIFICATION",
                        "FATIGUE_PROTECTION",
                        "REST_COMMITTED",
                    ):
                        blockers = tuple(r.person_id for r in roles)
                    elif reason == "WORK_FACE_CONFLICT":
                        blockers = tuple(
                            sorted(
                                {r.activity_id for r in world.snapshot.running}
                                | {
                                    x.activity_id
                                    for x in world.snapshot.attempts
                                    if x.state == "WAITING_RELEASE"
                                }
                            )
                        )
                    waits.append(Wait(world.time, a.id, mode.id, reason, blockers))
            if not found:
                waits.append(Wait(world.time, a.id, mode.id, "NO_QUALIFIED_DISTINCT_BINDING"))
    return tuple(candidates), tuple(dict.fromkeys(waits)), False


def _proof(config):
    """Only a necessary fixed load inequality is a certified infeasibility proof."""
    resources = {r.id: r for r in config.resources}
    products = {p.id: p for p in config.products}
    components = {c.id: c for c in config.components}
    for a in sorted(config.activities, key=lambda a: a.id):
        if a.move:
            p = products[a.product_id]
            for entity in a.move.entity_ids:
                mass = products[entity].mass_t if entity in products else components[entity].mass_t
                capacity = resources[a.move.equipment].load_t
                if mass + p.rigging_t > capacity:
                    return (
                        f"MANDATORY_MOVE_OVERLOAD:{a.id}:{entity}:{mass}+{p.rigging_t}>{capacity}"
                    )
    return None


def _synthetic_facts(world):
    """Conditional all-pass candidate model, never a source of industrial evidence."""
    for aid, attempt in sorted(_latest(world).items()):
        a = world.activities[aid]
        kind = None
        if (
            a.quality_evidence
            and attempt.state == "COMPLETED"
            and not any(
                q.activity_id == aid and q.attempt == attempt.number for q in world.snapshot.quality
            )
            and evidence_pass(world.config, (a.quality_evidence,))
        ):
            kind = "QUALITY_RESULT"
        elif (
            attempt.state == "WAITING_RELEASE"
            and world.time >= attempt.wait_until_h
            and aid not in world.snapshot.released_processes
            and evidence_pass(world.config, (a.release_evidence, "G4"))
        ):
            kind = "PROCESS_RELEASE"
        if kind:
            world.apply_event(
                b.WorldEvent(
                    f"S11-ASSUMPTION-{len(world.snapshot.events) + 1}",
                    world.time,
                    kind,
                    aid,
                    "PASS" if kind == "QUALITY_RESULT" else None,
                    attempt.number if kind == "QUALITY_RESULT" else None,
                )
            )


def generate_plan(config, observation, options=Options()):
    """Return FEASIBLE only for a nonempty, complete, independently checked trace.

    NO_PLAN_FOUND is bounded greedy failure, including unresolved qualification or
    quality facts. INFEASIBLE is reserved for an explicit fixed-model load proof.
    Future products are projected out before generation; no scenario is read.
    """
    started = perf_counter()
    world = None
    projected = None
    waits, commands = [], []
    decisions = 0
    assumptions = (
        ("SYNTHETIC_ALL_PASS_QUALITY_AND_PROCESS_RELEASE",)
        if options.synthetic_gate_assumptions
        else ()
    )

    def result(status, reason, plan=None, report=None):
        return Result(
            status,
            reason,
            projected,
            observation,
            plan,
            world.snapshot if world else None,
            report,
            tuple(waits),
            assumptions,
            decisions,
            (perf_counter() - started) * 1000,
        )

    try:
        if (
            options.rule not in RULES
            or type(options.max_decisions) is not int
            or options.max_decisions < 1
            or type(options.max_bindings) is not int
            or options.max_bindings < 1
            or type(options.horizon_h) not in (int, float)
            or not math.isfinite(options.horizon_h)
            or options.horizon_h <= 0
            or type(options.synthetic_gate_assumptions) is not bool
        ):
            return result("INVALID_INPUT", "INVALID_OPTIONS")
        validate(config)
        validate(observation, config=config)
        visible = {p.product_id for p in observation.products}
        if not visible:
            return result("NO_PLAN_FOUND", "NO_VISIBLE_PRODUCTS")
        visible_orders = {p.order_id for p in config.products if p.id in visible}
        if any(p.order_id in visible_orders and p.id not in visible for p in config.products):
            return result("NO_PLAN_FOUND", "CURRENT_WINDOW_HAS_UNRELEASED_ORDER_MEMBERS")
        projected = replace(
            config,
            products=tuple(p for p in config.products if p.id in visible),
            activities=tuple(a for a in config.activities if a.product_id in visible),
            components=tuple(c for c in config.components if c.product_id in visible),
            materials=tuple(m for m in config.materials if m.product_id in visible),
        )
        ids = {a.id for a in projected.activities}
        projected = replace(
            projected, edges=tuple(e for e in config.edges if e.source in ids and e.target in ids)
        )
        world = BuildingBackend(projected)
        expected = world.observe()[0]
        if replace(observation, id=expected.id) != expected:
            return result("INVALID_INPUT", "COMPLETE_PRISTINE_T0_OBSERVATION_REQUIRED")
        if options.synthetic_gate_assumptions and projected.purpose != "SYNTHETIC_TEST_ONLY":
            return result("INVALID_INPUT", "SYNTHETIC_ASSUMPTIONS_REQUIRE_TEST_CONFIGURATION")
        proof = _proof(projected)
        if proof:
            return result("INFEASIBLE", proof)
        for decisions in range(1, options.max_decisions + 1):
            if options.synthetic_gate_assumptions:
                _synthetic_facts(world)
            if all(p.state == "READY" for p in world.snapshot.products):
                plan = b.Plan(
                    "C04-1.0",
                    projected.id,
                    observation.id,
                    tuple(commands),
                    tuple(b.Prediction(p.product_id, p.ready_h) for p in world.snapshot.products),
                    "CANDIDATE",
                )
                report = check_run(
                    projected,
                    world.snapshot,
                    plan=plan,
                    observation=observation,
                    candidate_trace=True,
                )
                if commands and report.status == "PASS":
                    return result("FEASIBLE", "COMPLETE_VERIFIED_CANDIDATE", plan, report)
                return result("NO_PLAN_FOUND", "INDEPENDENT_CHECK_REJECTED", report=report)
            if world.time >= options.horizon_h:
                return result("NO_PLAN_FOUND", "HORIZON_EXHAUSTED")
            candidates, blocked, exhausted = legal_candidates(
                world, max_bindings=options.max_bindings
            )
            waits.extend(blocked)
            if exhausted:
                return result("NO_PLAN_FOUND", "BINDING_BUDGET_EXHAUSTED")
            if candidates:
                chosen = select(candidates, options.rule).command
                receipt = world.dispatch(chosen)
                if not receipt.accepted:
                    return result("NO_PLAN_FOUND", "ADMISSION_CHANGED:" + receipt.reason)
                commands.append(chosen)
                continue
            # Rest is an explicit charged action at an idle point. No locks or
            # residencies are cleared to make a candidate feasible.
            busy = {lock.resource_id for lock in world.snapshot.locks}
            resting = {h.person_id for h in world.snapshot.people if h.rest_until_h > world.time}
            tired = sorted(
                {pid for w in blocked if w.reason == "FATIGUE_PROTECTION" for pid in w.blockers}
                - busy
                - resting
            )
            if tired:
                world.rest(tuple(tired), projected.min_rest_h)
            boundaries = [r.end_h for r in world.snapshot.running]
            boundaries += [
                a.wait_until_h
                for a in world.snapshot.attempts
                if a.state == "WAITING_RELEASE" and a.wait_until_h > world.time
            ]
            boundaries += [
                h.rest_until_h for h in world.snapshot.people if h.rest_until_h > world.time
            ]
            temporal = tired or any(
                w.reason in ("CALENDAR_OR_QUALIFICATION", "REST_COMMITTED", "FATIGUE_PROTECTION")
                for w in blocked
            )
            if temporal:
                boundaries += [calendar_state(p, world.time)[1] for p in projected.people]
            boundaries = [t for t in boundaries if t > world.time]
            if not boundaries:
                return result("NO_PLAN_FOUND", "BLOCKED_WITHOUT_KNOWN_PROGRESS_EVENT")
            world.advance(min(min(boundaries), options.horizon_h))
        return result("NO_PLAN_FOUND", "DECISION_BUDGET_EXHAUSTED")
    except (ContractError, ValueError, TypeError, AttributeError, IndexError, KeyError) as error:
        # Errors after initialization remain failures, never infeasibility proofs.
        return result("INVALID_INPUT" if not commands else "NO_PLAN_FOUND", str(error))
