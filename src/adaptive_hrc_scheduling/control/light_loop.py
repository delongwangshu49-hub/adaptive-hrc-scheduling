"""S12 causal one-action replanning on C05 feedback, with S10 actual-log audit.

The controller accepts only Feedback, never an executor, scenario or future order
catalogue. Proposed actions are disposable; acknowledged execution lives solely
in the actual backend. This is a greedy dispatch policy, not a complete schedule.
"""

import copy
import json
import math
from dataclasses import dataclass, fields, replace
from functools import lru_cache

from adaptive_hrc_scheduling.building_backend import BuildingBackend
from adaptive_hrc_scheduling.building_human import calendar_state
from adaptive_hrc_scheduling.checker import check_run
from adaptive_hrc_scheduling.contracts.building import validate
from adaptive_hrc_scheduling.domain import building as b
from adaptive_hrc_scheduling.planning.decoder import legal_candidates
from adaptive_hrc_scheduling.planning.rules import RULES, select


@dataclass(frozen=True)
class Options:
    rule: str = "EDD"
    horizon_h: float = 240.0
    poll_h: float = 1.0
    max_decisions: int = 5000
    max_bindings: int = 10000

    def validate(self):
        if (
            self.rule not in RULES
            or any(
                type(v) not in (int, float) or not math.isfinite(v) or v <= 0
                for v in (self.horizon_h, self.poll_h)
            )
            or any(type(v) is not int or v < 1 for v in (self.max_decisions, self.max_bindings))
        ):
            raise ValueError("INVALID_LOOP_OPTIONS")


@dataclass(frozen=True)
class ObservedState:
    """Explicit current-state whitelist; no scenario, cursors or future queue."""

    products: tuple[b.ProductState, ...]
    components: tuple[b.ComponentState, ...]
    materials: tuple[b.MaterialState, ...]
    attempts: tuple[b.Attempt, ...]
    running: tuple[b.Running, ...]
    residencies: tuple[b.Residency, ...]
    locks: tuple[b.Lock, ...]
    quality: tuple[b.QualityRecord, ...]
    failed_resources: tuple[str, ...]
    released_processes: tuple[str, ...]
    services: tuple[b.Service, ...]
    events: tuple[b.ExecutionEvent, ...]


@dataclass(frozen=True)
class Feedback:
    configuration: b.Configuration
    observation: b.PlanningObservation
    state: ObservedState


@dataclass(frozen=True)
class Decision:
    id: str
    observation_id: str
    revision: int
    time_h: float
    triggers: tuple[str, ...]
    action: str
    plan: b.Plan
    people: tuple[str, ...] = ()
    product_id: str | None = None
    until_h: float | None = None
    reason: str = ""


@dataclass(frozen=True)
class Turn:
    feedback: Feedback
    decision: Decision
    accepted: bool
    receipt: str
    actual_event_ids: tuple[str, ...]
    after_revision: int
    after_h: float
    before_event_count: int | None = None
    after_event_count: int | None = None


@dataclass(frozen=True)
class Result:
    status: str
    reason: str
    turns: tuple[Turn, ...]
    trace: b.ExecutionSnapshot
    report: object
    decision_findings: tuple[str, ...]


def capture(world):
    """Trusted adapter projects *already released* static data and current facts."""
    obs = world.observe()[0]
    visible = {p.product_id for p in obs.products}
    c, s = world.config, world.snapshot
    activities = tuple(a for a in c.activities if a.product_id in visible)
    aids = {a.id for a in activities}
    components = tuple(x for x in c.components if x.product_id in visible)
    materials = tuple(x for x in c.materials if x.product_id in visible)
    refs = visible | aids | {x.id for x in components + materials}
    refs |= {x.id for x in c.resources + c.people}
    evidence_ids = {"G1", "G2", "G4", "G5", "G6", "G7"}
    for a in activities:
        evidence_ids.update((a.quality_evidence, a.release_evidence))
        for m in a.modes:
            evidence_ids.update(m.qualification_ids)
            evidence_ids.update(u.checkpoint_id for u in m.units)
    projected = replace(
        c,
        products=tuple(p for p in c.products if p.id in visible),
        activities=activities,
        components=components,
        materials=materials,
        edges=tuple(e for e in c.edges if e.source in aids and e.target in aids),
        evidence=tuple(e for e in c.evidence if e.id in evidence_ids),
    )
    # Only actual events are exported. A material event for an unreleased order
    # must not expose that order through its payload or even through event_ids.
    events = tuple(
        e
        for e in s.events
        if (
            json.loads(e.reason)["entity_id"] in refs
            if e.kind == "EXTERNAL"
            else e.entity_id in refs or e.kind in ("REST_START", "PROTECTIVE_REST")
        )
    )
    obs = replace(obs, event_ids=tuple(e.id for e in events))
    state = ObservedState(
        tuple(p for p in s.products if p.product_id in visible),
        tuple(x for x in s.components if x.component_id in refs),
        tuple(x for x in s.materials if x.material_id in refs),
        tuple(x for x in s.attempts if x.activity_id in aids),
        tuple(x for x in s.running if x.activity_id in aids),
        tuple(x for x in s.residencies if x.owner in visible),
        s.locks,
        tuple(x for x in s.quality if x.product_id in visible),
        s.failed_resources,
        tuple(x for x in s.released_processes if x in aids),
        tuple(x for x in s.services if x.product_id in visible),
        events,
    )
    return Feedback(projected, obs, state)


@lru_cache(maxsize=32)
def _pristine_view(config):
    # Cached only by the complete immutable *visible* configuration. Never mutated.
    return BuildingBackend(config)


def _view(feedback):
    """Sandbox of observed facts used only for reversible admission probes."""
    c, o, s = feedback.configuration, feedback.observation, feedback.state
    world = copy.copy(_pristine_view(c))
    world.s = replace(
        world.snapshot,
        **{f.name: getattr(s, f.name) for f in fields(s)},
        time_h=o.observed_h,
        revision=o.state_revision,
        people=o.people,
        released_products=tuple(p.product_id for p in o.products),
    )
    return world


def choose(feedback, options=Options(), *, sequence=1, previous_event_ids=()):
    """Pure deterministic decision. No private scenario or wall-clock reads."""
    options.validate()
    c, o, s = feedback.configuration, feedback.observation, feedback.state
    if o.config_id != c.id or o.sampled_h != o.received_h or o.received_h != o.observed_h:
        raise ValueError("FRESH_OBSERVATION_REQUIRED")
    if {p.id for p in c.products} != {p.product_id for p in o.products}:
        raise ValueError("VISIBLE_PRODUCT_COVERAGE")
    previous = set(previous_event_ids)
    triggers = tuple(
        dict.fromkeys(
            "EXTERNAL:" + json.loads(e.reason)["kind"] if e.kind == "EXTERNAL" else e.kind
            for e in s.events
            if e.id not in previous
        )
    )
    triggers = triggers or (("INITIAL",) if sequence == 1 else ("POLL",))
    plan = b.Plan(
        "C04-1.0",
        c.id,
        o.id,
        (),
        tuple(b.Prediction(p.product_id, None) for p in o.products),
        "INCOMPLETE",
    )

    def decision(action, reason, **kwargs):
        return Decision(
            f"S12-D-{sequence}",
            o.id,
            o.state_revision,
            o.observed_h,
            triggers,
            action,
            kwargs.pop("plan", plan),
            reason=reason,
            **kwargs,
        )

    if any(x.state == "EMERGENCY_HOLD" for x in s.running + s.services):
        return decision("STOP", "EMERGENCY_HOLD_NO_SAFE_PATH")
    if o.observed_h > options.horizon_h:
        raise ValueError("OBSERVATION_BEYOND_HORIZON")
    at_end = o.observed_h == options.horizon_h
    blocked = ()
    if any(p.state not in ("READY", "RECEIVED", "QUARANTINED") for p in s.products):
        world = _view(feedback)
        # Cancellation cannot retract running work; cleanup is separately admitted
        # only after the executor says the committed tail and occupancy are safe.
        if not at_end:
            for p in sorted(s.products, key=lambda p: p.product_id):
                if p.cancelled and p.state != "QUARANTINED":
                    trial = copy.copy(world)
                    receipt = trial.cleanup(p.product_id)
                    if receipt.accepted:
                        return decision(
                            "CLEANUP",
                            "CANCELLED_PRODUCT_CLEARANCE",
                            product_id=p.product_id,
                            people=("Lop", "Lrig", "Lsig"),
                        )
        candidates, blocked, exhausted = legal_candidates(
            world, max_bindings=options.max_bindings, instant_only=at_end
        )
        if exhausted:
            return decision("STOP", "BINDING_BUDGET_EXHAUSTED")
        if candidates:
            command = replace(select(candidates, options.rule).command, id=f"S12-CMD-{sequence}")
            return decision(
                "DISPATCH", "CURRENT_LEGAL_RULE_CHOICE", plan=replace(plan, commands=(command,))
            )
        if not at_end:
            busy = {x.resource_id for x in s.locks}
            resting = {h.person_id for h in o.people if h.rest_until_h > o.observed_h}
            tired = tuple(
                sorted(
                    {pid for w in blocked if w.reason == "FATIGUE_PROTECTION" for pid in w.blockers}
                    - busy
                    - resting
                )
            )
            if tired and o.observed_h + c.min_rest_h <= options.horizon_h:
                return decision(
                    "REST",
                    "OBSERVED_FATIGUE_PROTECTION",
                    people=tired,
                    until_h=o.observed_h + c.min_rest_h,
                )
    if at_end:
        return decision("STOP", "HORIZON_REACHED")
    boundaries = [o.observed_h + options.poll_h, options.horizon_h]
    boundaries += [x.end_h for x in s.running + s.services if x.end_h > o.observed_h]
    boundaries += [
        x.wait_until_h
        for x in s.attempts
        if x.wait_until_h is not None and x.wait_until_h > o.observed_h
    ]
    boundaries += [h.rest_until_h for h in o.people if h.rest_until_h > o.observed_h]
    boundaries += [calendar_state(p, o.observed_h)[1] for p in c.people]
    return decision("WAIT", "WAIT_FOR_FEEDBACK_OR_KNOWN_BOUNDARY", until_h=min(boundaries))


def run_loop(config, scenario=None, options=Options(), *, feedback_source=None):
    """Trusted driver. feedback_source is an explicit test-only environment adapter.

    Wait deadlines come from the controller; C05 returns early on actual feedback.
    Future exogenous events can wake the loop, never influence its prior decision.
    """
    options.validate()
    validate(config)
    if feedback_source is not None and config.purpose != "SYNTHETIC_TEST_ONLY":
        raise ValueError("SYNTHETIC_FEEDBACK_REQUIRES_TEST_CONFIGURATION")
    world = BuildingBackend(config, scenario)
    turns = []
    previous_ids = ()
    reason = "DECISION_BUDGET_EXHAUSTED"
    for sequence in range(1, options.max_decisions + 1):
        if feedback_source is not None:
            feedback_source(world)
        feedback = capture(world)
        d = choose(feedback, options, sequence=sequence, previous_event_ids=previous_ids)
        previous_ids = feedback.observation.event_ids
        before = len(world.snapshot.events)
        if d.action == "STOP":
            accepted, receipt = True, d.reason
        elif d.action == "DISPATCH":
            result = world.dispatch(d.plan.commands[0])
            accepted, receipt = result.accepted, result.reason
        elif d.action == "REST":
            world.rest(d.people, d.until_h - world.time)
            accepted, receipt = True, "REST_COMMITTED"
        elif d.action == "CLEANUP":
            result = world.cleanup(d.product_id, roles=d.people)
            accepted, receipt = result.accepted, result.reason
        else:
            result = world.advance(d.until_h, stop_on_feedback=True)
            accepted, receipt = result.accepted, result.reason
        turns.append(
            Turn(
                feedback,
                d,
                accepted,
                receipt,
                tuple(e.id for e in world.snapshot.events[before:]),
                world.snapshot.revision,
                world.time,
                before,
                len(world.snapshot.events),
            )
        )
        if d.action == "STOP" or not accepted:
            reason = d.reason if d.action == "STOP" else receipt
            break
    if world.time == 0 and not any(
        x.state == "EMERGENCY_HOLD" for x in world.snapshot.running + world.snapshot.services
    ):
        # A zero-time budget exit cannot establish S10's positive common window.
        # Record one terminal observation wait, with no further dispatch/replanning.
        f = capture(world)
        d = Decision(
            f"S12-D-{len(turns) + 1}",
            f.observation.id,
            f.observation.state_revision,
            0,
            ("BUDGET_EXIT",),
            "WAIT",
            b.Plan(
                "C04-1.0",
                config.id,
                f.observation.id,
                (),
                tuple(b.Prediction(p.product_id, None) for p in f.observation.products),
                "INCOMPLETE",
            ),
            until_h=min(options.poll_h, options.horizon_h),
            reason="TERMINAL_OBSERVATION_WINDOW",
        )
        before = len(world.snapshot.events)
        receipt = world.advance(d.until_h, stop_on_feedback=True)
        turns.append(
            Turn(
                f,
                d,
                receipt.accepted,
                receipt.reason,
                tuple(e.id for e in world.snapshot.events[before:]),
                world.snapshot.revision,
                world.time,
                before,
                len(world.snapshot.events),
            )
        )
    report = check_run(config, world.snapshot)
    findings = audit_decisions(config, world.snapshot, tuple(turns))
    done = all(p.state in ("READY", "RECEIVED", "QUARANTINED") for p in world.snapshot.products)
    status = "COMPLETED" if done else "UNFINISHED"
    if done and any(p.cancelled for p in world.snapshot.products):
        status = "CLOSED_WITH_CANCELLATION"
    if report.status != "PASS" or findings:
        status = "INVALID_TRACE"
    return Result(status, reason, tuple(turns), world.snapshot, report, findings)


def audit_decisions(config, trace, turns):
    """Fail closed on missing or unreadable evidence; independent of admission."""
    from adaptive_hrc_scheduling.control.ledger import audit_prefixes

    try:
        return audit_prefixes(config, trace, turns) + _audit_decisions(config, trace, turns)
    except (ValueError, TypeError, KeyError, AttributeError, IndexError, StopIteration):
        return ("INCOMPLETE:UNREADABLE_DECISION_EVIDENCE",)


def _audit_decisions(config, trace, turns):
    """Independent ledger binding, in addition to S10's full physical replay.

    Checks observations against earlier actual event IDs, actions against actual
    starts, and command identities/revisions. Does not call choose/admission.
    Paired nonanticipation is tested separately; no optimality claim is made.
    """
    findings = []
    events = {e.id: e for e in trace.events}
    positions = {e.id: i for i, e in enumerate(trace.events)}
    commands = []
    prior_end = 0
    prior_revision = None
    used_starts = set()
    used_services = set()
    for i, turn in enumerate(turns, 1):
        d, f = turn.decision, turn.feedback
        o = f.observation

        def need(ok, code):
            if not ok:
                findings.append(f"{d.id}:{code}")

        need(d.action in ("STOP", "DISPATCH", "REST", "CLEANUP", "WAIT"), "ACTION_KIND")
        need(
            all(
                eid in events and d.time_h <= events[eid].time_h <= turn.after_h
                for eid in turn.actual_event_ids
            ),
            "ACTUAL_EVENT_INTERVAL",
        )
        next_action_positions = [
            positions[eid]
            for later in turns[i - 1 :]
            for eid in later.actual_event_ids
            if eid in positions
        ]
        if next_action_positions:
            need(
                all(
                    positions.get(eid, len(events)) < min(next_action_positions)
                    for eid in o.event_ids
                ),
                "OBSERVATION_PREFIX",
            )
        need(
            {p.id for p in f.configuration.products} == {p.product_id for p in o.products}
            and len(o.products) == len({p.product_id for p in o.products})
            and all(
                p in config.products and p.release_h <= d.time_h for p in f.configuration.products
            ),
            "VISIBLE_STATIC_PRODUCTS",
        )
        need(d.id == f"S12-D-{i}" and d.observation_id == o.id, "DECISION_ID")
        need(d.revision == o.state_revision and d.time_h == o.observed_h, "DECISION_VERSION")
        need(d.time_h >= prior_end and turn.after_h >= d.time_h, "TIME_ORDER")
        if prior_revision is not None:
            need(d.revision >= prior_revision, "REVISION_ORDER")
        need(o.sampled_h == o.received_h == o.observed_h, "FRESH_OBSERVATION")
        need(tuple(e.id for e in f.state.events) == o.event_ids, "OBSERVED_EVENT_COVERAGE")
        need(
            all(
                e.id in events and events[e.id] == e and e.time_h <= d.time_h
                for e in f.state.events
            ),
            "FUTURE_OR_CHANGED_EVENT",
        )
        need(not set(o.event_ids) & set(turn.actual_event_ids), "SAME_TICK_FUTURE_LEAK")
        need(
            d.plan.schema_version == o.schema_version == "C04-1.0"
            and d.plan.config_id == o.config_id == config.id
            and d.plan.observation_id == o.id
            and {p.product_id for p in d.plan.predicted_ready} == {p.product_id for p in o.products}
            and len(d.plan.predicted_ready) == len(o.products)
            and d.plan.status == "INCOMPLETE"
            and all(p.ready_h is None for p in d.plan.predicted_ready),
            "PLAN_IS_PROPOSAL",
        )
        if d.action == "DISPATCH":
            need(len(d.plan.commands) == 1, "ONE_COMMAND")
            if not d.plan.commands:
                continue
            cmd = d.plan.commands[0]
            commands.append(cmd.id)
            need(cmd.config_id == config.id and cmd.id == f"S12-CMD-{i}", "COMMAND_ID")
            need(
                cmd.expected_revision == d.revision and cmd.issued_h == d.time_h, "COMMAND_REVISION"
            )
            a = next((a for a in config.activities if a.id == cmd.activity_id), None)
            need(
                a is not None and a.product_id in {p.product_id for p in o.products},
                "UNOBSERVED_DISPATCH",
            )
            starts = [
                events[eid]
                for eid in turn.actual_event_ids
                if eid in events and events[eid].kind in ("UNIT_START", "READY", "COMPLETED")
            ]
            if turn.accepted:
                need(len(starts) == 1, "ACTUAL_START_COVERAGE")
                for e in starts:
                    need(e.id not in used_starts and e.time_h == cmd.issued_h, "START_ID_TIME")
                    used_starts.add(e.id)
                    if e.kind == "UNIT_START":
                        v = json.loads(e.reason)
                        need(
                            (
                                e.entity_id,
                                v["mode_id"],
                                v["attempt"],
                                v["unit_index"],
                                tuple((r["role_id"], r["person_id"]) for r in v["roles"]),
                            )
                            == (
                                cmd.activity_id,
                                cmd.mode_id,
                                cmd.attempt,
                                cmd.unit_index,
                                tuple((r.role_id, r.person_id) for r in cmd.roles),
                            ),
                            "START_BINDING",
                        )
                    else:
                        mode = (
                            next((m for m in a.modes if m.id == cmd.mode_id), None) if a else None
                        )
                        prior = next(
                            (
                                x
                                for x in reversed(f.state.attempts)
                                if x.activity_id == cmd.activity_id
                            ),
                            None,
                        )
                        need(
                            a is not None
                            and mode is not None
                            and not mode.units
                            and not cmd.roles
                            and cmd.attempt == (prior.number if prior else 0)
                            and cmd.unit_index == (prior.completed_units if prior else 0)
                            and (prior is None or prior.mode_id == cmd.mode_id)
                            and (
                                (
                                    e.kind == "READY"
                                    and a.code == "READY"
                                    and e.entity_id == a.product_id
                                    and cmd.mode_id == a.modes[0].id
                                )
                                or (
                                    e.kind == "COMPLETED"
                                    and a.code != "READY"
                                    and e.entity_id == a.id
                                    and e.attempt == cmd.attempt
                                )
                            ),
                            "INSTANT_BINDING",
                        )
        else:
            need(not d.plan.commands, "NON_DISPATCH_COMMANDS")
        action_events = [events[eid] for eid in turn.actual_event_ids if eid in events]
        for e in action_events:
            if e.kind in ("REST_START", "CLEANUP_START"):
                need(
                    turn.accepted is True
                    and d.action == ("REST" if e.kind == "REST_START" else "CLEANUP")
                    and e.time_h == d.time_h
                    and turn.after_h == d.time_h
                    and e.id not in used_services,
                    "SERVICE_ACTION_BINDING",
                )
                used_services.add(e.id)
        if d.action == "REST" and turn.accepted:
            rest = [e for e in action_events if e.kind == "REST_START"]
            need(
                turn.receipt == "REST_COMMITTED"
                and len(rest) == 1
                and json.loads(rest[0].reason) == {"people": list(d.people), "until": d.until_h},
                "REST_BINDING",
            )
        if d.action == "CLEANUP" and turn.accepted:
            cleanup = [e for e in action_events if e.kind == "CLEANUP_START"]
            need(
                turn.receipt == "ACCEPTED"
                and len(cleanup) == 1
                and cleanup[0].entity_id == d.product_id
                and tuple(json.loads(cleanup[0].reason)["people"]) == d.people,
                "CLEANUP_BINDING",
            )
        if d.action == "STOP":
            need(not action_events and turn.after_h == d.time_h, "STOP_MUTATION")
        if d.action == "WAIT":
            need(d.until_h > d.time_h and turn.after_h <= d.until_h, "WAIT_DEADLINE")
        prior_end, prior_revision = turn.after_h, turn.after_revision
    if tuple(commands) != trace.consumed_commands or len(set(commands)) != len(commands):
        findings.append("COMMAND_COVERAGE")
    actual = {e.id for e in trace.events if e.kind in ("UNIT_START", "READY", "COMPLETED")}
    if actual != used_starts:
        findings.append("UNBOUND_ACTUAL_START")
    services = {e.id for e in trace.events if e.kind in ("REST_START", "CLEANUP_START")}
    if services != used_services:
        findings.append("UNBOUND_ACTUAL_SERVICE")
    return tuple(findings)
