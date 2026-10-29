"""P051 fixed-hour scenario and event-boundary full production schedules.

The configuration identity opts into fixed active hours. Historical configurations
and their serialized schema/digests stay unchanged. Fatigue integration and all
admission checks remain active.
"""

import copy
import gzip
import json
from dataclasses import replace
from time import perf_counter

from .contracts.codec import as_data, require
from .contracts.production import digest
from .domain import production as m

FIXED_PREFIX = "P051-FIXED-r1:"


def is_fixed(config):
    return config.id.startswith(FIXED_PREFIX)


def configuration(config):
    from .contracts.production import validate

    return (
        validate(replace(config, id=FIXED_PREFIX + config.id)) if not is_fixed(config) else config
    )


class RulePolicy:
    """Constructive common-rule baseline, with no periodic search."""

    method = "P051_FULL_CONSTRUCTIVE"

    def __init__(self, session, modes=(), order=()):
        self.session = session
        self.config = session.world.config
        self.modes, self.order = modes, order
        self.pending = self.committed = ()
        self.candidates, self.journal = [], []
        self.cache_hash = None
        self.budget = self

    def decide(self, value, snapshot, decisions, *, sequence, rejected):
        from .planning.production import choose

        priority = dict(self.order)
        # Urgent class precedes stable order, while dependencies remain guarded.
        for aid, urgency in self.session.history.priority_bias():
            priority[aid] = priority.get(aid, 0) + urgency * 100000
        return choose(
            self.config,
            value,
            sequence=sequence,
            excluded_operations=rejected,
            mode_choices=self.modes,
            order_bias=tuple(priority.items()),
        )

    def next_tick(self, now_h):
        return self.session.spec["clock"]["session_until_h"]

    def report(self):
        return dict(used_calls=0, kind="CONSTRUCTIVE_SHARED_RULES")

    def begin_cycle(self):
        pass

    def end_cycle(self, plan, receipt):
        pass


def preview(session, decisions, *, modes=(), order=()):
    """Isolated executor and catalog; future facts never enter the live session."""
    from .control.production_loop import run

    clone = copy.copy(session)
    for key, value in session.__dict__.items():
        if isinstance(value, (dict, list, set)):
            setattr(clone, key, copy.deepcopy(value))
    clone.world = copy.deepcopy(session.world)
    # Runtime timing subclasses contain callbacks bound to the live recorder.
    # A hypothetical replay must never emit into that live timing ledger.
    from .production_backend import ProductionBackend

    clone.world.__class__ = ProductionBackend
    clone.world.backend = "logistics-event"
    clone.backend = clone.world
    clone.history = session.history.fork()
    clone.active_products = set(session.active_products)
    clone.world.dispatch_products = clone.active_products
    clone.history.active_products = clone.active_products
    clone.policy = RulePolicy(clone, modes, order)
    clone.lifecycle = clone.projection = None
    clone.closed, clone.stopped, clone.terminal = True, False, False
    clone.boundary = lambda: None
    clone.bind_observation = lambda observation: None
    clone.bind_dispatch = lambda *args: None
    clone.persist = lambda: None
    clone.request_boundaries = lambda: [
        t for t in clone.material_due.values() if t > clone.world.s.time_h
    ]
    from .control.session_lifecycle import Lifecycle

    obligations = Lifecycle(clone)
    result = run(
        clone.backend,
        clone.scenario(),
        joint_policy=clone.policy,
        session=clone,
        continuation=True,
        planning_preview=True,
        prefix_decisions=decisions,
        stop_condition=lambda world: obligations.clear(),
    )
    require(
        result.audit.status == result.decision_audit.status == "PASS",
        "FULL_REPLAY_AUDIT:"
        + str(
            (
                result.manifest["termination"],
                result.snapshot.state.time_h,
                result.audit.findings,
                result.decision_audit.findings,
            )
        ),
    )
    require(
        result.manifest["termination"] in ("OPERATIONS_COMPLETE", "DECLARED_CHECKPOINT")
        and obligations.clear(),
        "FULL_NO_FEASIBLE_SCHEDULE:"
        + str(
            (
                result.manifest["termination"],
                result.snapshot.state.time_h,
                result.decisions[-2].plan.reason if len(result.decisions) > 1 else "",
            )
        ),
    )
    return result


def mode_proposal(config, seconds=1.0):
    """Bounded CP resource relaxation proposes modes; replay is the acceptance gate.

    Transport, buffer geometry, fatigue and calendars are checked by full replay,
    never inferred from this lower-bound model. A solver result is not a plan.
    """
    try:
        from ortools.sat.python import cp_model
    except ImportError:
        # Kit uses its own interpreter; reuse the project's locked solver in an
        # isolated process, without installing into or changing Kit's runtime.
        import os
        import subprocess
        from pathlib import Path

        root = Path(__file__).resolve().parents[2]
        if os.environ.get("P051_SOLVER_WORKER") == "1":
            return (), dict(
                status="SOLVER_IMPORT_FAILED",
                budget_s=seconds,
                bound_scope="CORE_RESOURCE_RELAXATION_REQUIRES_FULL_REPLAY",
            )
        try:
            completed = subprocess.run(
                [
                    str(root / ".venv/Scripts/python.exe"),
                    "-m",
                    "adaptive_hrc_scheduling.full_schedule_solver",
                ],
                input=json.dumps(dict(configuration=as_data(config), seconds=seconds)),
                text=True,
                encoding="utf-8",
                capture_output=True,
                timeout=15,
                env=dict(
                    os.environ, PYTHONPATH=str(root / "src"), PYTHONUTF8="1", P051_SOLVER_WORKER="1"
                ),
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            require(completed.returncode == 0, "SOLVER_PROCESS:" + completed.stderr[-400:])
            result = json.loads(completed.stdout)
            return tuple(tuple(x) for x in result["modes"]), dict(
                result["report"], runtime="LOCKED_PROJECT_SUBPROCESS"
            )
        except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
            return (), dict(
                status="IMPROVEMENT_UNAVAILABLE",
                reason=str(exc),
                budget_s=seconds,
                bound_scope="CORE_RESOURCE_RELAXATION_REQUIRES_FULL_REPLAY",
            )

    model = cp_model.CpModel()
    starts, ends, choices, resources = {}, {}, {}, {}
    horizon = 720 * 3600
    for a in config.core_activities:
        start = model.new_int_var(0, horizon, a.id + ":s")
        end = model.new_int_var(0, horizon, a.id + ":e")
        starts[a.id], ends[a.id] = start, end
        options = []
        for mode in a.modes:
            if not mode.enabled:
                continue
            selected = model.new_bool_var(mode.id)
            duration = round(sum(u.base_h for u in mode.units) * 3600)
            interval = model.new_optional_interval_var(start, duration, end, selected, mode.id)
            options.append(selected)
            choices[a.id, mode.kind] = selected
            equipment = {e for u in mode.units for e in u.equipment}
            for resource in equipment:
                resources.setdefault(resource, []).append(interval)
        if options:
            model.add_exactly_one(options)
        else:
            model.add(end == start)
    for edge in config.core_edges:
        if edge.source in ends and edge.target in starts:
            model.add(starts[edge.target] >= ends[edge.source])
    for intervals in resources.values():
        model.add_no_overlap(intervals)
    makespan = model.new_int_var(0, horizon, "makespan")
    model.add_max_equality(makespan, list(ends.values()))
    model.minimize(makespan)
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = seconds
    solver.parameters.num_search_workers = 1
    solver.parameters.random_seed = 0
    status = solver.solve(model)
    modes = ()
    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        modes = tuple((aid, kind) for (aid, kind), v in choices.items() if solver.value(v))
    return modes, dict(
        status=solver.status_name(status),
        wall_s=solver.wall_time,
        bound_scope="CORE_RESOURCE_RELAXATION_REQUIRES_FULL_REPLAY",
        branches=solver.num_branches,
        budget_s=seconds,
    )


def intervals(result):
    """All successful production and service intervals, with explicit actual ends."""
    ended = {
        e.command_id: e.occurred_sim_h for e in result.snapshot.events if e.kind == "COMPLETED"
    }
    interrupted = {
        e.command_id: e.occurred_sim_h for e in result.snapshot.events if e.kind == "EXCEPTION"
    }
    return [
        dict(
            command=as_data(e.command),
            start_h=e.occurred_sim_h,
            end_h=ended.get(e.command.id, interrupted.get(e.command.id)),
            **(
                {"end_status": "INTERRUPTED"}
                if e.command.id not in ended and e.command.id in interrupted
                else {}
            ),
            operation_id=e.command.operation_id,
            activity_id=e.command.activity_id,
            product_id=e.command.product_id,
            roles=as_data(e.command.roles),
            command_id=e.command.id,
        )
        for e in result.snapshot.events
        if e.kind == "STARTED"
    ]


class FullSchedulePolicy(RulePolicy):
    """Atomically adopt a verified complete schedule and consume it without solving."""

    method = "P051_FULL_FIXED_HOURS"

    def __init__(self, session):
        super().__init__(session)
        self.calls = 0
        self.version = 0
        self.plan = None
        self.queue = []
        self.dirty = "INITIAL"
        self.failure = None
        self.history = []
        self.bindings = []
        self.checked_events = 0
        self.paused = self.cancelled = False

    def catalog_changed(self, affected_ids, operations, event_ids=(), protected_commands=()):
        self.dirty = "CATALOG_CHANGE"
        return []

    def recovery_boundary(self):
        """Only already accepted future repair/return requests can unlock a pause."""
        s = self.session
        pending = s.lifecycle.pending() if s.lifecycle else ()
        times = [
            s.requests[key]["requested_sim_h"]
            for key in pending
            if s.requests[key]["kind"] in ("DEVICE_REPAIR", "PERSON_RETURN")
            and s.requests[key].get("requested_sim_h", 0) > s.world.s.time_h
            and s.requests[key]["expires_sim_h"] >= s.requests[key]["requested_sim_h"]
        ]
        return min(times, default=None)

    def ensure_schedule(self, decisions):
        if self.plan:
            expected = {r["command_id"]: r for r in self.plan["intervals"]}
            for event in self.session.world.events[self.checked_events :]:
                if event.command_id in expected and (
                    event.kind == "EXCEPTION"
                    or event.kind == "COMPLETED"
                    and abs(event.occurred_sim_h - expected[event.command_id]["end_h"]) > 1e-8
                ):
                    self.dirty = "EXECUTION_DEVIATION"
        self.checked_events = len(self.session.world.events)
        if not self.dirty:
            return
        from .contracts.session import digest as wire_digest
        from .control.session import save_atomic

        s, w = self.session, self.session.world
        began = perf_counter()
        anchor = (s.version, w.s.revision, len(w.events), w.s.time_h)
        reason, self.dirty = self.dirty, None
        self.calls += 1
        entry = dict(call=self.calls, reason=reason, at_h=w.s.time_h, anchor=anchor)
        try:
            stable = ()
            if self.plan:
                interrupted = {e.command_id for e in w.events if e.kind == "EXCEPTION"}
                activities = list(dict.fromkeys(r["activity_id"] for r in self.plan["intervals"]))
                stable = tuple((aid, i - len(activities) - 1) for i, aid in enumerate(activities))
            try:
                baseline = preview(s, decisions, order=stable)
            except ValueError as exc:
                if not stable:
                    raise
                entry["stable_insertion_failure"] = str(exc)
                baseline = preview(s, decisions)
                stable = ()
            chosen = baseline
            modes, solver = mode_proposal(w.config)
            entry["solver"] = solver
            actual_modes = {
                e.command.activity_id: e.command.mode_id
                for e in baseline.snapshot.events
                if e.kind == "STARTED" and e.command.branch
            }
            different = any(
                actual_modes.get(aid) and kind != actual_modes[aid] for aid, kind in modes
            )
            entry["optimization"] = "FEASIBLE_BASELINE_NO_DISTINCT_MODE_PROPOSAL"
            if different:
                try:
                    candidate = preview(s, decisions, modes=modes, order=stable)
                    if candidate.snapshot.state.time_h < baseline.snapshot.state.time_h - 1e-9:
                        chosen = candidate
                        entry["optimization"] = "VERIFIED_MAKESPAN_IMPROVEMENT"
                    else:
                        entry["optimization"] = "NO_MAKESPAN_IMPROVEMENT"
                except ValueError as exc:
                    entry["optimization"] = "CANDIDATE_REJECTED:" + str(exc)
            require(
                anchor == (s.version, w.s.revision, len(w.events), w.s.time_h),
                "FULL_OBSOLETE_RESULT",
            )
            rows = intervals(chosen)
            started = {e.command.id for e in w.events if e.kind == "STARTED"}
            successful_receipts = {e.id for e in chosen.snapshot.events if e.kind == "STARTED"}
            planned = [
                d
                for d in chosen.decisions
                if d.receipt_id in successful_receipts
                and d.plan.commands
                and d.plan.commands[0].id not in started
            ]
            # Completed and running commands are inherited from the exact prefix.
            if self.plan:
                old = {
                    r["command_id"]: r for r in self.plan["intervals"] if r["command_id"] in started
                }
                new = {r["command_id"]: r for r in rows}
                require(
                    all(
                        k in new
                        and all(new[k][f] == v[f] for f in ("start_h", "operation_id", "roles"))
                        and (k in interrupted or new[k]["end_h"] == v["end_h"])
                        for k, v in old.items()
                    ),
                    "FULL_FROZEN_PREFIX_CHANGED",
                )
            version = self.version + 1
            plan = dict(
                format="P051-FULL-SCHEDULE-1",
                plan_id=s.spec["run_id"] + ":FULL",
                version=version,
                scenario="FIXED_HOURS_IDEAL-r1",
                configuration_sha256=digest(w.config),
                anchor_h=w.s.time_h,
                anchor_events=len(w.events),
                event_prefix_sha256=s.event_prefix_hash(),
                catalog_version=s.version,
                completion_h=chosen.snapshot.state.time_h,
                intervals=rows,
                covered_operations=sorted({r["operation_id"] for r in rows}),
                active_static_operations=chosen.manifest["active_static_operations"],
                completed_static_operations=chosen.manifest["completed_static_operations"],
                execution_audit="PASS",
                causal_audit="PASS",
                future_facts="DECLARED_DETERMINISTIC_RULES_NOT_ACTUAL_FACTS",
            )
            checksum = wire_digest(plan)
            folder = s.output / "full-schedules"
            folder.mkdir(exist_ok=True)
            save_atomic(folder / (checksum + ".json"), plan)
            # The proof retains its hypothetical identity, separate from actual events.
            with gzip.open(
                folder / (checksum + ".proof.json.gz"), "wt", encoding="utf-8", compresslevel=1
            ) as stream:
                from .control.production_decisions import record
                from .schedule_proof import encode

                json.dump(
                    dict(
                        scope="HYPOTHETICAL_FULL_REPLAY",
                        configuration=as_data(w.config),
                        initial=as_data(s.history.initial),
                        generations=s.history.generations,
                        snapshot_graph=encode(chosen.snapshot),
                        decisions=[record(d) for d in chosen.decisions],
                    ),
                    stream,
                    separators=(",", ":"),
                )
            self.plan, self.version, self.queue = plan, version, planned
            self.cache_hash = checksum
            self.failure = None
            entry.update(
                status="ADOPTED",
                version=version,
                plan_sha256=checksum,
                baseline_h=baseline.snapshot.state.time_h,
                chosen_h=chosen.snapshot.state.time_h,
            )
        except (ValueError, KeyError) as exc:
            self.failure = str(exc)
            entry.update(
                status="NO_FEASIBLE_PLAN", reason_detail=self.failure, retained_version=self.version
            )
        entry["wall_s"] = perf_counter() - began
        self.history.append(entry)
        charge = dict(
            sequence=-(2**31) + self.calls,
            phase="FULL_PLAN_BUILD",
            trigger="INITIAL" if self.calls == 1 else "CATALOG_CHANGED",
            search_call=True,
            decision_seconds=entry["wall_s"],
            plan_version=self.version,
            status=entry["status"],
        )
        s.account.charge(charge)
        self.journal.append(charge)
        save_atomic(s.output / "full-schedule-state.json", self.report())

    def decide(self, value, snapshot, decisions, *, sequence, rejected):
        obs = value.observation
        self.config = self.session.world.config
        reason = "FULL_PLAN_WAIT"
        command = None
        if self.failure:
            reason = "FULL_PLAN_BLOCKED:" + self.failure[:300]
        elif self.queue:
            scheduled = self.queue[0]
            source = scheduled.plan.commands[0]
            if abs(source.issued_sim_h - obs.sampled_h) <= 1e-8:
                command = replace(
                    source,
                    expected_revision=obs.state.revision,
                    config_sha256=obs.config_sha256,
                    schema_version=self.config.schema_version,
                    research=self.config.research,
                )
                guard = copy.copy(self.session.world)
                guard.s = obs.state
                guard.operations = dict(guard.operations)
                guard.routes = dict(guard.routes)
                if command.service:
                    guard.operations[command.operation_id] = command.service.operation
                    if command.service.route:
                        guard.routes[command.service.route.id] = command.service.route
                try:
                    guard._admit(command)
                    reason = scheduled.plan.reason
                except (ValueError, KeyError) as exc:
                    command = None
                    self.dirty = "EXECUTION_DEVIATION"
                    reason = "FULL_DEVIATION:" + str(exc)
            elif source.issued_sim_h < obs.sampled_h - 1e-8:
                self.dirty = "EXECUTION_DEVIATION"
                reason = "FULL_DEVIATION:MISSED_START"
        self.journal.append(
            dict(
                sequence=sequence,
                selected_source="VERIFIED_FULL_PLAN",
                plan_version=self.version,
                plan_sha256=self.cache_hash,
                reason=reason,
                sim_h=obs.sampled_h,
            )
        )
        return m.Plan(
            self.config.schema_version,
            self.config.id,
            obs.id,
            (command,) if command else (),
            "CANDIDATE" if command else "WAIT",
            reason,
            self.config.research,
        )

    def end_cycle(self, plan, receipt):
        if receipt and receipt.kind == "STARTED":
            require(
                self.queue and receipt.command.id == self.queue[0].plan.commands[0].id,
                "FULL_DISPATCH_MISMATCH",
            )
            self.queue.pop(0)
            self.bindings.append(
                dict(
                    plan_id=self.plan["plan_id"],
                    version=self.version,
                    command_id=receipt.command.id,
                    receipt_id=receipt.id,
                    start_h=receipt.occurred_sim_h,
                )
            )
        elif receipt:
            self.dirty = "EXECUTION_DEVIATION"

    def next_tick(self, now_h):
        future = [
            d.plan.commands[0].issued_sim_h
            for d in self.queue
            if d.plan.commands[0].issued_sim_h > now_h + 1e-10
        ]
        return min(future, default=self.session.spec["clock"]["session_until_h"])

    def report(self):
        return dict(
            format="P051-FULL-SCHEDULE-1",
            used_calls=self.calls,
            version=self.version,
            plan_sha256=self.cache_hash,
            failure=self.failure,
            history=self.history,
            actual_bindings=self.bindings,
        )

    def reference(self):
        return dict(
            format="P051-FULL-SCHEDULE-1",
            plan_id=self.plan["plan_id"] if self.plan else None,
            version=self.version,
            artifact_sha256=self.cache_hash,
            failure=self.failure,
            solve_calls=self.calls,
            planning=self.calls > len(self.history),
            completion_h=self.plan["completion_h"] if self.plan else None,
            anchor_events=self.plan["anchor_events"] if self.plan else 0,
        )


def verify_saved(directory, reference, *, initial, events):
    """Independent process: reconstruct both audits and the immutable plan rows."""
    import re
    from pathlib import Path
    from types import SimpleNamespace

    from .contracts.codec import decode
    from .contracts.session import digest as wire_digest
    from .control.production_decisions import check_decisions
    from .dynamic_workforce import WorkforceHistory
    from .production_checker import check_run

    key = reference["artifact_sha256"]
    require(bool(re.fullmatch(r"[a-f0-9]{64}", key)), "FULL_ARTIFACT_PATH")
    folder = Path(directory) / "full-schedules"
    plan = json.loads((folder / (key + ".json")).read_bytes())
    require(
        wire_digest(plan) == key
        and plan["version"] == reference["version"]
        and plan["plan_id"] == reference["plan_id"],
        "FULL_ARTIFACT_DIGEST",
    )
    with gzip.open(folder / (key + ".proof.json.gz"), "rt", encoding="utf-8") as stream:
        proof = json.load(stream)
    require(
        proof["scope"] == "HYPOTHETICAL_FULL_REPLAY" and proof["initial"] == initial,
        "FULL_PROOF_BASIS",
    )
    require(
        plan["anchor_events"] <= len(events)
        and wire_digest(events[: plan["anchor_events"]]) == plan["event_prefix_sha256"],
        "FULL_PROOF_ANCHOR",
    )
    history = WorkforceHistory(decode(m.Configuration, initial), proof["generations"])
    require(as_data(history.current) == proof["configuration"], "FULL_PROOF_CONFIGURATION")
    if "snapshot_graph" in proof:
        from .schedule_proof import decode as decode_graph

        snapshot = decode_graph(proof["snapshot_graph"])
    else:
        snapshot = decode(m.ExecutionSnapshot, proof["snapshot"])
    require(
        as_data(snapshot.events[: plan["anchor_events"]]) == events[: plan["anchor_events"]],
        "FULL_PROOF_PREFIX",
    )
    audit = check_run(history.current, snapshot, catalog=history)
    causal = check_decisions(history.current, snapshot, proof["decisions"], catalog=history)
    require(audit.status == causal.status == "PASS", "FULL_PROOF_AUDITS")
    require(
        intervals(SimpleNamespace(snapshot=snapshot)) == plan["intervals"], "FULL_PROOF_INTERVALS"
    )
    from . import production_rework
    from .production_admission import applicable

    completed = sum(o.id in snapshot.state.completed for o in history.current.operations)
    active = sum(
        production_rework.active(history.current, snapshot.state.gates, o)
        and applicable(o, snapshot.state.mode_attempts)
        for o in history.current.operations
    )
    require(
        plan["configuration_sha256"] == digest(history.current)
        and plan["plan_id"] == snapshot.run_id + ":FULL"
        and is_fixed(history.current)
        and plan["completion_h"] == snapshot.state.time_h
        and plan["covered_operations"] == sorted({r["operation_id"] for r in plan["intervals"]})
        and all(r["end_h"] is not None for r in plan["intervals"])
        and not snapshot.state.running,
        "FULL_PROOF_COVERAGE",
    )
    require(
        plan["active_static_operations"] == active
        and plan["completed_static_operations"] == completed
        and all(p.cancelled or p.received_h is not None for p in snapshot.state.products),
        "FULL_PROOF_COMPLETION",
    )
    return plan
