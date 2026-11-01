"""S15 synthetic environment driver. Future releases stay outside the planner."""

from dataclasses import dataclass, replace

from adaptive_hrc_scheduling import production_rework as rework
from adaptive_hrc_scheduling.building_human import calendar_state
from adaptive_hrc_scheduling.contracts.codec import ContractError, require
from adaptive_hrc_scheduling.contracts.production import digest
from adaptive_hrc_scheduling.control.production_decisions import check_decisions, record
from adaptive_hrc_scheduling.domain import production as m
from adaptive_hrc_scheduling.planning.production import choose, planning_input
from adaptive_hrc_scheduling.production_admission import applicable, completed_activity
from adaptive_hrc_scheduling.production_checker import check_run


@dataclass(frozen=True)
class Scenario:
    id: str = "NORMAL"
    until_h: float = 720
    receive_after_h: float = 0
    delayed_lot: str | None = None
    arrival_after_h: float = 0
    cancel_product: str | None = None
    cancel_stage: str | None = None
    quality_fail: str | None = None
    rework_fail: bool = False
    loaded_failure: bool = False
    actual_device_failure: bool = False
    actual_path_obstruction: bool = False


@dataclass(frozen=True)
class Decision:
    observation: m.PlanningObservation
    plan: m.Plan
    rejected_parents: tuple[str, ...]
    receipt_id: str | None


@dataclass(frozen=True)
class Result:
    snapshot: m.ExecutionSnapshot
    decisions: tuple[Decision, ...]
    manifest: dict
    audit: object
    decision_audit: object


def validate_scenario(config, scenario):
    """WV01 is one exact supplemental case, not a general window extension."""
    require(
        sum(
            (
                scenario.loaded_failure,
                scenario.actual_device_failure,
                scenario.actual_path_obstruction,
            )
        )
        <= 1,
        "ONE_FAILURE_INTERVENTION_PER_SCENARIO",
    )
    if config.id.startswith("P051-FIXED-r1:P052-E20-r1:"):
        require(
            scenario == Scenario(id="INTERACTIVE", until_h=scenario.until_h)
            and 0 < scenario.until_h <= 3000,
            "E20_EXACT_SCENARIO_REQUIRED",
        )
    elif scenario.id == "B2_SUPPLEMENTAL_960" or scenario.until_h > 720:
        require(
            scenario == Scenario(id="B2_SUPPLEMENTAL_960", until_h=960, receive_after_h=840)
            and config.rework_enabled
            and len(config.products) == 3
            and all(p.variant == "SR-W1" and p.release_h == 0 for p in config.products),
            "WV01_EXACT_SCENARIO_REQUIRED",
        )
    else:
        require(0 < scenario.until_h <= 720, "FIXED_S15_WINDOW")


def run(*args, **kwargs):
    """Persist failure without inventing application acknowledgements or exit codes."""
    try:
        return _run(*args, **kwargs)
    except Exception:
        session = kwargs.get("session")
        life = getattr(session, "lifecycle", None)
        if life is not None and not session.terminal:
            life.finish("FAILED")
        raise


def _run(
    backend,
    scenario=Scenario(),
    *,
    rule="EDD",
    max_turns=20000,
    execution_hook=None,
    joint_policy=None,
    stop_condition=None,
    warmup_only=False,
    prefix_decisions=(),
    continuation=False,
    fixed_mode=None,
    handover_after_setup=False,
    orderly_stop=None,
    session=None,
    planning_preview=False,
):
    life = getattr(session, "lifecycle", None)
    world = getattr(backend, "world", backend)
    isaac = hasattr(backend, "world")
    if session is not None:
        require(
            session.backend is backend and scenario == session.scenario(), "SESSION_RUN_BINDING"
        )
        require(joint_policy is session.policy, "SESSION_POLICY_BINDING")
    if continuation:
        history = dict(catalog=session.history) if session is not None else {}
        require(
            check_run(world.config, world.snapshot(), **history).status == "PASS"
            and (
                planning_preview
                or check_decisions(
                    world.config,
                    world.snapshot(),
                    tuple(record(d) for d in prefix_decisions),
                    **history,
                ).status
                == "PASS"
            ),
            "VERIFIED_CONTINUATION_PREFIX_REQUIRED",
        )
    else:
        require(world.s.time_h == 0 and not world.events, "FRESH_RUN_REQUIRED")
    c = world.config
    validate_scenario(c, scenario)
    require(
        c.purpose in ("SYNTHETIC_TEST_ONLY", "SIMULATION_RESEARCH_ONLY"), "SYNTHETIC_DRIVER_ONLY"
    )
    places = {p.id: p for p in c.places}
    lots = {lot.id: lot for lot in c.lots}
    incoming = {
        lot.id: next(o for o in c.operations if o.entity_id == lot.id and o.action == "TRANSFER")
        for lot in c.lots
        if not lot.parent_ids
    }
    rejected = set()
    decisions = list(prefix_decisions)
    checkpoint_wait_replaced = bool(
        continuation
        and decisions
        and decisions[-1].receipt_id is None
        and not decisions[-1].plan.commands
        and decisions[-1].observation.event_ids == tuple(e.id for e in world.events)
    )
    if checkpoint_wait_replaced:
        decisions.pop()
    last_revision = -1
    last_changed = 0
    termination = "TURN_LIMIT"
    seen_preparation_states = {}
    static_ids = {o.id for o in c.operations}
    failure_done = False
    repair_at = None
    failure_product = None
    failure_resource = "FORK-01"
    obstruction_path = "/World/Static/S15_TEST_PATH_OBSTRUCTION"
    preparation_steps = 0
    stop_facts = None

    def fact(kind, entity, pid, evidence="ML-METHOD", result="PASS", attempt=0):
        ident = f"{scenario.id}-{kind}-{entity}" + (f"-A{attempt}" if attempt else "")
        return backend.apply_world(
            m.WorldEvent(
                ident,
                world.run_id,
                world.epoch,
                world.s.time_h,
                kind,
                entity,
                pid,
                attempt,
                result,
                evidence,
            )
        )

    def ingress_group(lot):
        steel = lot.bom_id == "B-ST" and lot.material == "STEEL"
        corridor = (
            ("RECEIVE", "STEEL", "PRE-IN")
            if steel
            else ("MEP-RECEIVE", "MEP-STORE", "KIT", "F1-KIT", "J3", "F1")
        )
        for stock in world.s.lots:
            other = lots[stock.id]
            if not stock.arrived or world._mass(stock.id) <= 1e-9:
                continue
            loc = stock.location
            root = places[loc].parent or loc if loc in places else loc
            belongs = (other.material == "STEEL") if steel else (other.material != "STEEL")
            if (
                belongs
                and (root in corridor or loc == "IN_TRANSIT")
                and other.group_id != lot.group_id
            ):
                return False
        return True

    if life is not None:
        life.driver = dict(turn_limit=max_turns, turns_entered=0, checkpoint_reached=False)
    for sequence in range(len(decisions), len(decisions) + max_turns):
        if life is not None:
            life.driver["turns_entered"] += 1
        if execution_hook:
            execution_hook(backend, "before_decision")
        if session is not None:
            session.boundary()
            session.refresh_capacity()
            c = world.config
            places = {p.id: p for p in c.places}
            lots = {lot.id: lot for lot in c.lots}
            incoming = {
                lot.id: next(
                    o for o in c.operations if o.entity_id == lot.id and o.action == "TRANSFER"
                )
                for lot in c.lots
                if not lot.parent_ids
            }
            static_ids = {o.id for o in c.operations}
        stop_requested = bool(
            (session is not None and session.stopped) or (orderly_stop and orderly_stop(world))
        )
        if life is not None:
            limit = life.limit()
            if limit:
                termination = limit
                break
            if life.clear() and not stop_requested:
                if session.closed or not life.continuous:
                    termination = "OPERATIONS_COMPLETE"
                    break
                life.change("WAITING_INPUT", "NO_OPEN_OBLIGATIONS")
                observed = world.observe()
                world.deliver()
                session.bind_observation(observed)
                session.projection.publish(observed)
                blocked = life.advance(scenario.until_h, idle=True)
                if blocked:
                    termination = blocked
                    break
                continue
            obligations = life.obligations()
            if not stop_requested and not any(
                obligations[k]
                for k in (
                    "open_products",
                    "physical_residuals",
                    "running",
                    "holds",
                    "reservations",
                    "commitments",
                )
            ):
                life.change(life.waiting_phase(), "PENDING_REQUESTS")
                observed = world.observe()
                world.deliver()
                session.bind_observation(observed)
                session.projection.publish(observed)
                blocked = life.advance(scenario.until_h, idle=True)
                if blocked:
                    termination = blocked
                    break
                continue
            life.change("DRAINING" if session.closed else "RUNNING_OPEN", "BOUNDARY")
            if (
                not stop_requested
                and decisions
                and decisions[-1].receipt_id is None
                and decisions[-1].observation.event_ids == tuple(e.id for e in world.events)
            ):
                # A control-only receipt (or input wake) does not create a new
                # execution observation. Retain the prior WAIT decision and
                # meter to the next boundary instead of auditing it twice.
                blocked = life.advance(scenario.until_h, idle=not world.s.running)
                if blocked:
                    termination = blocked
                    break
                continue
        if stop_requested:
            # Control is outside planning. Admit no new production, world inputs,
            # or service dispatches; finish only already STARTED work using the
            # same execution/readback path. HOLDs and reservations stay factual.
            stop_facts = {
                "accepted_h": world.s.time_h,
                "accepted_revision": world.s.revision,
                "started_commands": [
                    r.command.id for r in world.s.running if r.status == "STARTED"
                ],
                "event_count_at_boundary": len(world.events),
                "future_commitments": "PRESERVED_IN_JOURNAL_NOT_DISPATCHED",
            }
            if life is not None:
                life.stop_intake = True
                life.stop_control = dict(
                    stop_facts,
                    source="REQUEST" if session.stopped else "WORKER_ORDERLY_STOP_CALLBACK",
                )
            while pending := [r for r in world.s.running if r.status == "STARTED"]:
                if life is not None:
                    # Retry/query ingress is not an execution stall. The stop
                    # fence rejects new business while preserving idempotency.
                    session.boundary()
                before = world.s.revision
                tick = max(world.s.time_h, min(r.earliest_end_h for r in pending))
                if execution_hook:
                    execution_hook(backend, "before_stop_advance")
                if life is not None:
                    blocked = life.limit() or life.advance(tick)
                    if blocked:
                        break
                elif isaac:
                    backend.advance_to(tick)
                    backend.deliver()
                else:
                    world.advance(tick)
                if execution_hook:
                    execution_hook(backend, "after_stop_advance")
                if world.s.revision == before:
                    if life is not None and life.last_advance == "INPUT_WAKE":
                        continue
                    break
            if isaac:
                backend.deliver()
            observed = world.observe()
            world.deliver()
            decisions.append(
                Decision(
                    observed,
                    m.Plan(
                        c.schema_version, c.id, observed.id, (), "WAIT", "ORDERLY_STOP", c.research
                    ),
                    tuple(sorted(rejected)),
                    None,
                )
            )
            termination = "ORDERLY_STOPPED" if not world.s.running else "ORDERLY_STOP_BLOCKED"
            stop_facts["remaining_commands"] = [r.command.id for r in world.s.running]
            stop_facts["final_h"] = world.s.time_h
            break
        if stop_condition and stop_condition(world):
            if life is not None:
                life.driver["checkpoint_reached"] = True
            if isaac:
                backend.deliver()
            observed = world.observe()
            world.deliver()
            decisions.append(
                Decision(
                    observed,
                    m.Plan(
                        c.schema_version,
                        c.id,
                        observed.id,
                        (),
                        "WAIT",
                        "DECLARED_CHECKPOINT",
                        c.research,
                    ),
                    tuple(sorted(rejected)),
                    None,
                )
            )
            termination = "DECLARED_CHECKPOINT"
            break
        if any(
            r.status == "STARTED" and r.earliest_end_h <= world.s.time_h + 1e-10
            for r in world.s.running
        ):
            before_due = world.s.revision
            if isaac:
                backend.advance_to(world.s.time_h)
            else:
                world.advance(world.s.time_h)
            if world.s.revision != before_due:
                continue
        if world.s.revision != last_revision:
            # Keep actual rejections through the current decision epoch. A clock
            # or completion can release the rejected constraint.
            # Replay changes in order: a repair/return after an exception must
            # clear that exception too when a continuation reads a whole prefix.
            for event in world.events[last_changed:]:
                if event.kind == "WORLD" or (
                    event.kind == "COMPLETED"
                    and (
                        not event.command.service
                        or event.command.service.operation.action in ("TRANSFER", "RETURN")
                    )
                ):
                    rejected.clear()
                    preparation_steps = 0
                elif event.kind == "COMPLETED" and event.command.service is not None:
                    preparation_steps += 1
                if event.kind == "EXCEPTION" and event.command:
                    rejected.add(event.command.operation_id)
            last_revision = world.s.revision
            last_changed = len(world.events)
        if preparation_steps >= 128:
            termination = "PREPARATION_BUDGET"
            break
        if repair_at is not None and world.s.time_h >= repair_at:
            if scenario.actual_path_obstruction and isaac:
                backend.port.scene.stage.RemovePrim(obstruction_path)
            fact("REPAIR", failure_resource, failure_product)
            repair_at = None
        for product in c.products:
            state = world._product(product.id)
            if not state.released and world.s.time_h >= product.release_h:
                fact("ORDER_ARRIVAL", product.id, product.id)
            if (
                state.received_h is None
                and product.id not in world.s.receive_permits
                and world.s.time_h >= scenario.receive_after_h
            ):
                fact("RECEIVE_PERMIT", product.id, product.id)
            if scenario.cancel_product == product.id and not state.cancelled:
                triggered = (
                    scenario.cancel_stage == "UNSTARTED"
                    and world.s.time_h == 0
                    or scenario.cancel_stage == "STOCK"
                    and any(
                        lot.product_id == product.id
                        and not lot.parent_ids
                        and world._lot(lot.id).arrived
                        and world._lot(lot.id).location.startswith("STEEL.")
                        for lot in c.lots
                    )
                    or scenario.cancel_stage == "WIP"
                    and world._mass(product.id) > 0
                    or scenario.cancel_stage == "READY"
                    and state.ready_h is not None
                )
                if triggered:
                    fact("CANCEL", product.id, product.id)
        delivery_order = list(incoming.items())
        if session is not None and session.history.generations:
            deadlines = {p.id: p.due_h for p in c.products}
            delivery_order.sort(
                key=lambda pair: (
                    session.history.priorities.get(lots[pair[0]].product_id) != "URGENT",
                    deadlines[lots[pair[0]].product_id],
                    pair[0],
                )
            )
        for ident, delivery in delivery_order:
            lot = lots[ident]
            if session is not None and not session.material_ready(lot.product_id):
                continue
            if not rework.active(c, world.s.gates, delivery):
                continue
            if any(
                not (
                    records := rework.quality_records(
                        c, world.s.gates, gate, lot.product_id, delivery.attempt_index
                    )
                )
                or records[-1].result != "PASS"
                for gate in delivery.quality_gates
            ):
                continue
            if world._lot(ident).arrived or world._product(lot.product_id).cancelled:
                continue
            if not world._product(lot.product_id).released:
                continue
            if ident == scenario.delayed_lot and world.s.time_h < scenario.arrival_after_h:
                continue
            raw_steel = lot.bom_id == "B-ST" and lot.material == "STEEL"
            fork_location = world._position("FORK-01").location
            if raw_steel and (
                fork_location not in places
                or (places[fork_location].parent or fork_location) == "RECEIVE"
            ):
                continue
            if (
                not raw_steel and not all(i in world.s.completed for i in delivery.prerequisites)
            ) or not ingress_group(lot):
                continue
            try:
                fact("ARRIVAL", ident, lot.product_id, delivery.location)
            except ContractError as exc:
                if not str(exc).startswith(
                    ("CAPACITY", "GROUP_", "ACTUAL_WORLD_OCCUPIED", "SUPPORT_")
                ):
                    raise
                continue
            fact("IDENTIFY", ident, lot.product_id)
            fact("RELEASE", ident, lot.product_id)
        for activity in c.core_activities:
            bound = [i for b in c.bindings if b.activity_id == activity.id for i in b.operation_ids]
            if bound and completed_activity(c, world.s.completed, activity.id):
                for kind, gate in [
                    ("QUALITY", activity.quality_evidence),
                    ("PROCESS_RELEASE", activity.release_evidence),
                ]:
                    if gate and not any(
                        g.id == gate and g.product_id == activity.product_id for g in world.s.gates
                    ):
                        fact(
                            kind,
                            gate,
                            activity.product_id,
                            gate,
                            "FAIL" if activity.code == scenario.quality_fail else "PASS",
                        )
        if c.rework_enabled:
            for product in c.products:
                for code, kind in (
                    ("WAIT-W", "PROCESS_RELEASE"),
                    ("WAIT-TEST", "PROCESS_RELEASE"),
                    ("Q-POND", "QUALITY"),
                ):
                    if product.id + ".REPAIR." + code not in world.s.completed:
                        continue
                    activity = next(
                        a
                        for a in c.core_activities
                        if a.product_id == product.id and a.code == code
                    )
                    gate = (
                        activity.quality_evidence
                        if kind == "QUALITY"
                        else activity.release_evidence
                    )
                    if not any(
                        g.id == gate and g.product_id == product.id and g.attempt == 1
                        for g in world.s.gates
                    ):
                        fact(
                            kind,
                            gate,
                            product.id,
                            gate,
                            "FAIL" if code == "Q-POND" and scenario.rework_fail else "PASS",
                            attempt=1,
                        )
        if isaac:
            backend.deliver()
        if any(e.kind == "WORLD" for e in world.events[last_changed:]):
            # A just-observed repair/arrival must unlock this decision too;
            # waiting for another turn can otherwise falsely declare STALLED.
            rejected.clear()
        # Detect repeated physical states at the same simulation time. Service
        # identifiers and revision counters are deliberately excluded: changing
        # those is not physical or production progress.
        if not world.s.running:
            cycle_key = (
                world.s.time_h,
                tuple(sorted(static_ids.intersection(world.s.completed))),
                world.s.positions,
                world.s.lots,
                world.s.products,
                world.s.humans,
                world.s.gates,
                world.s.supports,
                tuple(sorted(rejected)),
            )
            seen_preparation_states[cycle_key] = seen_preparation_states.get(cycle_key, 0) + 1
            if seen_preparation_states[cycle_key] > 3:
                termination = "DECISION_CYCLE"
                break
        if joint_policy and hasattr(joint_policy, "ensure_schedule"):
            if joint_policy.failure:
                # Waiting for a business/resource correction is not a repeated
                # preparation decision; preserve the paused failure boundary.
                seen_preparation_states.clear()
            if execution_hook and joint_policy.dirty:
                from concurrent.futures import ThreadPoolExecutor
                from time import sleep

                with ThreadPoolExecutor(max_workers=1, thread_name_prefix="full-schedule") as pool:
                    future = pool.submit(joint_policy.ensure_schedule, tuple(decisions))
                    while not future.done():
                        execution_hook(backend, "planning")
                        sleep(0.05)
                    future.result()
            else:
                joint_policy.ensure_schedule(tuple(decisions))
            if joint_policy.failure:
                if life is None:
                    termination = "FULL_PLAN_BLOCKED"
                    break
                from time import sleep

                life.change("WAITING_BOUNDARY", "FULL_PLAN_BLOCKED:" + joint_policy.failure[:200])
                observed = world.observe()
                world.deliver()
                session.bind_observation(observed)
                session.projection.publish(observed)
                recovery = joint_policy.recovery_boundary()
                if recovery is not None:
                    # Solve time is paused. Once infeasibility is established,
                    # meter safely to an accepted recovery event without dispatch.
                    blocked = life.advance(recovery, idle=not world.s.running)
                    if blocked:
                        termination = blocked
                        break
                    continue
                sleep(0.1)
                continue
        if joint_policy and hasattr(joint_policy, "begin_cycle"):
            joint_policy.begin_cycle()
        observation = world.observe()
        require(observation in world.deliver(), "OBSERVATION_NOT_DELIVERED")
        catalog_observation = session.bind_observation(observation) if session is not None else None
        if isaac:
            require(
                backend.ledger.status == "CONTIGUOUS"
                and tuple(e.id for e in backend.ledger.events) == observation.event_ids
                and (not observation.event_ids or backend.ledger.state == observation.state),
                "OBSERVATION_NOT_DELIVERED_EXECUTION_PREFIX",
            )
        value = planning_input(c, observation, 10000)
        value = replace(
            value,
            operations=tuple(
                o
                for o in value.operations
                if o.id not in rejected
                and (not warmup_only or not o.branch)
                and (
                    session is None
                    or o.product_id in session.active_products
                    or world._product(o.product_id).cancelled
                )
            ),
        )
        plan = (
            joint_policy.decide(
                value,
                world.snapshot(),
                (record(d) for d in decisions),
                sequence=sequence,
                rejected=rejected,
            )
            if joint_policy
            else choose(
                c,
                value,
                rule=rule,
                sequence=sequence,
                excluded_operations=rejected,
                mode_choices=tuple((s.activity_id, fixed_mode) for s in c.research.scope_bindings)
                if fixed_mode
                else (),
                crew_choices=tuple(
                    (a.activity_id, "W2")
                    for a in world.s.mode_attempts
                    if a.completed_units and a.definition_id.endswith(".H-SIM-v1")
                )
                if handover_after_setup
                else (),
            )
        )
        if joint_policy and hasattr(joint_policy, "guard"):
            current = world.observe()
            plan = joint_policy.guard(plan, current)
            if current != observation:
                observation = current
                require(observation in world.deliver(), "OBSERVATION_NOT_DELIVERED")
        if life is not None:
            session.projection.publish(observation, plan)
        receipt = backend.dispatch(plan.commands[0]) if plan.commands else None
        if session is not None:
            session.bind_dispatch(plan, receipt, catalog_observation)
        if joint_policy and hasattr(joint_policy, "end_cycle"):
            joint_policy.end_cycle(plan, receipt)
        decisions.append(
            Decision(observation, plan, tuple(sorted(rejected)), receipt.id if receipt else None)
        )
        if getattr(joint_policy, "dirty", None):
            continue
        if receipt:
            op = world.operations[receipt.command.operation_id]
            if (
                (
                    scenario.loaded_failure
                    or scenario.actual_device_failure
                    or scenario.actual_path_obstruction
                )
                and not failure_done
                and receipt.kind == "STARTED"
                and not receipt.command.service
                and op.action == "TRANSFER"
                and op.entity_id in lots
                and world.routes[op.route_id].device_id == "FORK-01"
            ):
                from adaptive_hrc_scheduling.production_backend import route_hours

                target_time = (
                    world.s.time_h
                    + c.setup_h
                    + c.load_h
                    + route_hours(world.routes[op.route_id]) / 2
                )
                if isaac:
                    backend.advance_to(target_time)
                else:
                    world.advance(target_time)
                require(
                    any(
                        p.command_id == receipt.command.id and 0 < p.progress < 1
                        for p in world.s.motions
                    ),
                    "LOADED_FAILURE_REQUIRES_MOTION_SAMPLE",
                )
                if scenario.actual_device_failure or scenario.actual_path_obstruction:
                    reason = (
                        "ACTUAL_EXECUTION:COLLISION:" + obstruction_path
                        if scenario.actual_path_obstruction
                        else "ACTUAL_EXECUTION:ACTUAL_DEVICE_FAILED:FORK-01"
                    )
                    if scenario.actual_path_obstruction:
                        failure_resource = world.routes[op.route_id].segments[0]
                    if isaac:
                        # Perturb only USD. Full-route preflight detects the
                        # obstacle ahead without moving the last verified load.
                        # The planner receives notice only after that readback.
                        if scenario.actual_path_obstruction:
                            point = world.routes[op.route_id].points[-1]
                            backend.port.scene.shape(
                                obstruction_path,
                                (point.x, point.y, point.z + 0.1),
                                (0.2, 0.2, 0.2),
                                "red",
                                collision=True,
                            )
                        else:
                            backend.port.scene.attr(
                                backend.port.prim("FORK-01"), "s15Available", False
                            )
                        backend.advance_to(world.s.time_h)
                        require(
                            world.events[-1].kind == "EXCEPTION"
                            and world.events[-1].reason == reason,
                            "ACTUAL_FAILURE_MUST_PRECEDE_WORLD_NOTICE",
                        )
                    else:
                        # Reference symptom for paired replay, not a claim of
                        # physical observation on the lightweight backend.
                        world.exception(receipt.command.id, reason)
                fact("FAILURE", failure_resource, op.product_id)
                failure_done, failure_product = True, op.product_id
                repair_at = world.s.time_h + 0.25
            if receipt.reason.startswith("ACTUAL_PREFLIGHT:ACTUAL_DEVICE_FAILED:"):
                resource = receipt.reason.rsplit(":", 1)[-1]
                if resource in world.devices and resource not in world.s.failed_resources:
                    fact("FAILURE", resource, op.product_id)
            if receipt.kind != "STARTED":
                parent = (
                    plan.reason.removeprefix("PREPARE:")
                    if plan.reason.startswith("PREPARE:")
                    else receipt.command.operation_id
                )
                rejected.add(parent)
            if execution_hook:
                execution_hook(backend, "after_dispatch")
            continue
        if all(
            o.id in world.s.completed
            for o in c.operations
            if rework.active(c, world.s.gates, o) and applicable(o, world.s.mode_attempts)
        ):
            if life is None:
                termination = "OPERATIONS_COMPLETE"
                break
        if plan.status == "NO_PLAN_FOUND" and life is None:
            termination = "DECISION_BUDGET" if plan.reason == "DECISION_BUDGET" else "NO_PLAN_FOUND"
            break
        if world.s.time_h >= scenario.until_h:
            termination = "WINDOW_CENSORED"
            break
        pending = [r.earliest_end_h for r in world.s.running if r.status == "STARTED"]
        if joint_policy:
            pending.append(joint_policy.next_tick(world.s.time_h))
        if session is not None:
            pending.extend(session.request_boundaries())
        pending += [
            t.time_h + o.wait_h
            for o in c.operations
            if o.wait_after
            for t in world.s.completion_times
            if t.operation_id == o.wait_after and t.time_h + o.wait_h > world.s.time_h + 1e-10
        ]
        pending += [
            p.release_h
            for p in c.products
            if not world._product(p.id).released and p.release_h > world.s.time_h
        ]
        pending += [
            t for t in (scenario.receive_after_h, scenario.arrival_after_h) if t > world.s.time_h
        ]
        if repair_at is not None:
            pending.append(repair_at)
        if "CALENDAR" in plan.reason or "HUMAN_CAP" in plan.reason:
            pending += [calendar_state(p, world.s.time_h)[1] for p in c.people]
        if life is not None:
            pending.append(scenario.until_h)
        if not pending:
            termination = "STALLED"
            break
        tick = min(scenario.until_h, min(pending))
        if (
            session is not None
            and session.workforce_enabled
            and tick <= world.s.time_h
            and any(r.status == "EXCEPTION" for r in world.s.running)
        ):
            termination = "WORKFORCE_HOLD_PROTECTION"
            break
        before = world.s.revision
        if life is not None:
            life.change(life.waiting_phase(), plan.reason)
            blocked = life.advance(tick, idle=not world.s.running)
            if blocked:
                termination = blocked
                break
            continue
        if isaac:
            backend.advance_to(tick)
        else:
            world.advance(tick)
        if world.s.revision == before:
            termination = "NO_PROGRESS"
            break
    if life is not None or planning_preview or hasattr(joint_policy, "ensure_schedule"):
        if isaac:
            backend.deliver()
        observed = world.observe()
        world.deliver()
        if not decisions or decisions[-1].observation.event_ids != observed.event_ids:
            decisions.append(
                Decision(
                    observed,
                    m.Plan(
                        c.schema_version, c.id, observed.id, (), "WAIT", termination, c.research
                    ),
                    tuple(sorted(rejected)),
                    None,
                )
            )
    snapshot = world.snapshot()
    if execution_hook:
        execution_hook(backend, "before_audit")
    dynamic = (
        dict(catalog=session.history)
        if session is not None and (session.history.generations or session.workforce_enabled)
        else {}
    )
    audit = check_run(c, snapshot, **dynamic)
    decision_audit = check_decisions(c, snapshot, (record(d) for d in decisions), **dynamic)
    manifest = {
        "protocol": "S15-PARITY-1",
        "scenario": scenario.__dict__,
        "config_sha256": digest(c),
        "backend": world.backend,
        "termination": termination,
        "time_h": world.s.time_h,
        "static_operations": len(c.operations),
        "completed_static_operations": sum(o.id in world.s.completed for o in c.operations),
        "active_static_operations": sum(
            rework.active(c, world.s.gates, o) and applicable(o, world.s.mode_attempts)
            for o in c.operations
        ),
        "ready": sum(p.ready_h is not None for p in world.s.products),
        "received": sum(p.received_h is not None for p in world.s.products),
        "audit": audit.status,
        "decision_audit": decision_audit.status,
        "decision_protocol": "S15-DECISION-1",
        "observation_delivery": "CURRENT_EVENT_PREFIX_ZERO_DELAY",
        "S15_complete": False,
        "industrial_qualification": "NOT_ESTABLISHED" if c.research else "UNKNOWN",
        "schema_version": c.schema_version,
        "warmup_only": warmup_only,
        "continuation": continuation,
        "checkpoint_wait_replaced_in_extended_journal": checkpoint_wait_replaced,
        "fixed_phase_witness_mode": fixed_mode,
        "handover_after_setup_witness": handover_after_setup,
        "research": __import__(
            "adaptive_hrc_scheduling.contracts.codec", fromlist=["as_data"]
        ).as_data(c.research),
        "loaded_failure_injected": failure_done and not scenario.actual_path_obstruction,
        "actual_path_obstruction_injected": failure_done and scenario.actual_path_obstruction,
        "preparation_steps_since_progress": preparation_steps,
    }
    if joint_policy:
        manifest["method"] = joint_policy.method
        manifest["search_budget"] = joint_policy.budget.report()
        manifest["joint_journal"] = joint_policy.journal
    if stop_facts is not None:
        manifest["orderly_stop"] = stop_facts
    if session is not None:
        manifest["launch_binding"] = session.binding
        manifest["catalog_version"] = session.version
        if life is not None:
            observed = world.observe()
            world.deliver()
            session.bind_observation(observed)
            session.projection.publish(observed)
            life.finish(
                termination, "PASS" if audit.status == decision_audit.status == "PASS" else "FAIL"
            )
            manifest["session_final"] = life.final
            manifest["lifecycle"] = life.data()
        else:
            session.persist()
    return Result(snapshot, tuple(decisions), manifest, audit, decision_audit)
