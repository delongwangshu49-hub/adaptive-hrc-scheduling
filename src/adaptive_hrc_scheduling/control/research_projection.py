"""Source-bound S20 planning observations, kept separate from real execution.

Only this adapter sees the real sampling history. Search receives a declared
hypothetical model, with historical human measurements redacted, and the live
state is used afterwards solely to admit or refuse an unchanged proposal.
"""

import hashlib
import json
import math
from dataclasses import asdict, dataclass, fields, is_dataclass, replace
from types import SimpleNamespace

from adaptive_hrc_scheduling.algorithms.lns import fingerprint
from adaptive_hrc_scheduling.algorithms.simulation_joint import (
    Genes,
    Schedule,
    SimulationJointProblem,
    Step,
    terminal,
)
from adaptive_hrc_scheduling.contracts.codec import as_data, decode, require
from adaptive_hrc_scheduling.contracts.production import digest, validate, wire
from adaptive_hrc_scheduling.control.audit_cache import (
    DecisionCheckpoint,
    ExecutionCheckpoint,
    clone,
)
from adaptive_hrc_scheduling.control.production_decisions import check_decisions, record
from adaptive_hrc_scheduling.control.simulation_joint_policy import Budget, SimulationJointPolicy
from adaptive_hrc_scheduling.domain import production as m
from adaptive_hrc_scheduling.planning.production import planning_input
from adaptive_hrc_scheduling.production_checker import check_run
from adaptive_hrc_scheduling.research_objective import WeightedObjective

METHODS = ("ADAPTIVE_JOINT", "FIXED_H", "FIXED_HR", "NO_OBSERVATION_UPDATE")


def uniform(seed, stream, entity, ordinal):
    wire = json.dumps(
        ["S20-DESIGN-r1", seed, stream, entity, ordinal],
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    raw = hashlib.sha256(wire.encode()).digest()
    return (int.from_bytes(raw[:8], "big") >> 11) / 2**53


@dataclass(frozen=True)
class ObservationSettings:
    delay_h: float = 0
    fatigue_noise: float = 0
    missing_probability: float = 0
    seed: str = "B-DEV-00"
    period_h: float = 0.25
    version: str = "S20-OBS-r1"

    def validate(self):
        require(
            self.version == "S20-OBS-r1" and type(self.seed) is str and self.seed,
            "PROJECTION_VERSION",
        )
        require(
            all(
                type(v) in (int, float) and math.isfinite(v)
                for v in (self.delay_h, self.fatigue_noise, self.missing_probability, self.period_h)
            ),
            "PROJECTION_NUMERIC_TYPE",
        )
        require(
            self.delay_h >= 0
            and 0 <= self.fatigue_noise <= 0.05
            and 0 <= self.missing_probability <= 1
            and self.period_h == 0.25,
            "PROJECTION_SETTINGS",
        )


@dataclass(frozen=True)
class ProjectionContract:
    """Caller-supplied run identity, independent of the saved evidence being checked."""

    config_sha256: str
    method: str
    settings: ObservationSettings
    budget: Budget
    objective: WeightedObjective | None = None
    version: str = "S20-PROJECTION-CONTRACT-r1"

    @classmethod
    def create(cls, config, budget, *, settings, method, objective=None):
        require(type(budget) is Budget, "PROJECTION_CONTRACT_BUDGET")
        result = cls(
            digest(config),
            method,
            settings,
            replace(budget, opportunities_h=tuple(budget.opportunities_h)),
            objective,
        )
        result.validate(config)
        return result

    def validate(self, config):
        require(
            self.version == "S20-PROJECTION-CONTRACT-r1" and self.config_sha256 == digest(config),
            "PROJECTION_CONTRACT_CONFIG",
        )
        require(self.method in METHODS, "PROJECTION_METHOD")
        require(type(self.settings) is ObservationSettings, "PROJECTION_CONTRACT_SETTINGS")
        require(type(self.budget) is Budget, "PROJECTION_CONTRACT_BUDGET")
        self.settings.validate()
        self.budget.validate()
        require(
            self.objective is None or type(self.objective) is WeightedObjective,
            "PROJECTION_CONTRACT_OBJECTIVE",
        )
        if self.objective is not None:
            self.objective.validate()


def check_contract(config, expected, method, settings, budget):
    require(type(expected) is ProjectionContract, "PROJECTION_TRUSTED_CONTRACT_REQUIRED")
    expected.validate(config)
    require(method in METHODS, "PROJECTION_METHOD")
    require(method == expected.method, "PROJECTION_METHOD_BINDING")
    settings.validate()
    require(
        fingerprint(asdict(settings)) == fingerprint(asdict(expected.settings)),
        "PROJECTION_SETTINGS_BINDING",
    )
    require(
        fingerprint(asdict(budget)) == fingerprint(asdict(expected.budget)),
        "PROJECTION_BUDGET_BINDING",
    )


def restore_world(config, snapshot):
    # Same reconstruction as the existing problem, without creating a planner.
    from types import SimpleNamespace

    return SimulationJointProblem.world(SimpleNamespace(config=config, prefix=snapshot))


@dataclass(frozen=True)
class ObservationFrame:
    snapshot: m.ExecutionSnapshot
    decisions: tuple
    ordinal: int
    received_h: float
    dropped: bool
    settings_sha256: str

    def identity(self):
        return fingerprint(
            dict(
                source=digest(self.snapshot),
                decisions=fingerprint(self.decisions),
                ordinal=self.ordinal,
                received_h=self.received_h,
                dropped=self.dropped,
                settings_sha256=self.settings_sha256,
            )
        )


def close_rows(config, snapshot, rows):
    rows = tuple(rows)
    obs = restore_world(config, snapshot).observe()
    closed = record(terminal(config, obs))
    if rows and rows[-1]["event_count"] == len(snapshot.events) and rows[-1]["receipt_id"] is None:
        require(rows[-1] == closed, "PROJECTION_TERMINAL_CONTEXT")
        return rows
    return rows + (closed,)


def check_frame(config, frame, settings, now_h):
    settings.validate()
    require(type(frame.ordinal) is int and frame.ordinal >= 0, "PROJECTION_ORDINAL")
    require(
        frame.settings_sha256 == fingerprint(asdict(settings))
        and math.isclose(
            frame.snapshot.state.time_h, frame.ordinal * settings.period_h, abs_tol=1e-9, rel_tol=0
        )
        and frame.received_h == frame.snapshot.state.time_h + settings.delay_h,
        "PROJECTION_SAMPLE_CLOCK",
    )
    require(
        frame.received_h <= now_h and frame.snapshot.state.time_h <= now_h,
        "PROJECTION_FUTURE_OR_UNDELIVERED",
    )
    expected_drop = (
        uniform(settings.seed, "missing", "snapshot", frame.ordinal) < settings.missing_probability
    )
    require(type(frame.dropped) is bool and frame.dropped == expected_drop, "PROJECTION_DROP_MASK")
    require(check_run(config, frame.snapshot).status == "PASS", "PROJECTION_SOURCE_EXECUTION")
    require(
        check_decisions(config, frame.snapshot, frame.decisions).status == "PASS",
        "PROJECTION_SOURCE_CAUSAL",
    )


class ModelAnchor:
    """A certified model boundary, never an actual execution certificate.

    Independent checkers first reconstruct the real source. Their private ledgers
    then start the hypothetical suffix at the declared fatigue measurement. The
    public execution checker without these scoped checkpoints rejects that model.
    """

    def __init__(self, config, frame, settings, now_h):
        check_frame(config, frame, settings, now_h)
        require(not frame.dropped, "PROJECTION_DROPPED_FRAME")
        self.config, self.frame, self.settings = config, frame, settings
        source = frame.snapshot
        execution, causal = ExecutionCheckpoint(), DecisionCheckpoint()
        require(
            check_run(config, source, checkpoint=execution).status == "PASS",
            "PROJECTION_SOURCE_EXECUTION",
        )
        require(
            check_decisions(config, source, frame.decisions, checkpoint=causal).status == "PASS",
            "PROJECTION_SOURCE_CAUSAL",
        )
        humans, noise = [], []
        for h in source.state.humans:
            epsilon = settings.fatigue_noise * (
                2 * uniform(settings.seed, "noise", h.person_id, frame.ordinal) - 1
            )
            measured = min(1, max(0, h.fatigue + epsilon))
            humans.append(replace(h, fatigue=measured, peak=max(h.peak, measured)))
            noise.append(
                dict(
                    person_id=h.person_id,
                    epsilon=epsilon,
                    measured=measured,
                    clipped=measured != h.fatigue + epsilon,
                )
            )
        state = replace(source.state, humans=tuple(humans), revision=source.state.revision + 1)
        boundary = m.ExecutionEvent(
            config.schema_version,
            config.id,
            digest(config),
            source.run_id,
            source.epoch,
            "S20-MODEL-BOUNDARY",
            len(source.events) + 1,
            None,
            None,
            None,
            None,
            "CLOCK",
            state.time_h,
            state.time_h,
            0,
            "S20_AUTHORIZED_MODEL_NOT_ACTUAL_EVENT",
            None,
            None,
            None,
            None,
            replace(state, intervals=()),
        )
        # Past commands/events remain traceable; past raw human measurements are
        # audit-only and are not made available through the search object's history.
        redacted = tuple(replace(e, state=replace(e.state, humans=())) for e in source.events)
        self.snapshot = replace(source, state=state, events=redacted + (boundary,))
        _, execution_ledger = execution.restore(config, source)
        execution_ledger["humans"] = {h.person_id: [h.fatigue, h.exposure, h.peak] for h in humans}
        execution_ledger["revision"] = state.revision
        execution_ledger["event_ids"].add(boundary.id)
        execution.save(config, self.snapshot, execution_ledger)
        execution._certified = execution._report = None
        _, causal_ledger = causal.restore(config, source)
        causal_ledger["state"] = replace(state, intervals=())
        causal_ledger["prefix"] = [e.id for e in self.snapshot.events]
        causal.save(config, self.snapshot, causal_ledger)
        causal._records = clone(frame.decisions)
        causal._certified = causal._report = None
        self.execution, self.causal = execution, causal
        self.source_rows = frame.decisions
        self.proof = dict(
            version="S20-PROJECTED-MODEL-r1",
            frame_id=frame.identity(),
            config_sha256=digest(config),
            source_sha256=digest(source),
            sample_h=source.state.time_h,
            received_h=frame.received_h,
            ordinal=frame.ordinal,
            settings=asdict(settings),
            noise=noise,
            model_anchor_sha256=digest(self.snapshot),
            scope="HYPOTHETICAL_SUFFIX_NOT_ACTUAL_EXECUTION",
        )

    def at(self, now_h):
        require(now_h >= self.frame.received_h, "PROJECTION_FUTURE_OR_UNDELIVERED")
        world = restore_world(self.config, self.snapshot)
        rows = self.source_rows + (record(terminal(self.config, world.observe())),)
        if now_h > world.s.time_h:
            world.advance(now_h)
            rows += (record(terminal(self.config, world.observe())),)
        return world.observe(), world.snapshot(), rows

    def check_prefix(self, observation, prefix, decisions):
        """Replay only recorded nominal commands and endogenous time advancement."""
        require(
            tuple(prefix.events[: len(self.snapshot.events)]) == self.snapshot.events,
            "PROJECTION_MODEL_PREFIX",
        )
        rows = tuple(decisions)
        require(
            rows[: len(self.source_rows)] == self.source_rows,
            "PROJECTION_MODEL_SOURCE_DECISIONS",
        )
        world = restore_world(self.config, self.snapshot)
        for row in rows[len(self.source_rows) :]:
            at = row["sampled_h"]
            require(
                world.s.time_h <= at <= prefix.state.time_h,
                "PROJECTION_NOMINAL_CLOCK",
            )
            if at > world.s.time_h:
                world.advance(at)
            obs = world.observe()
            plan = decode_exact(m.Plan, row["plan"])
            require(len(plan.commands) <= 1, "PROJECTION_NOMINAL_COMMAND_COUNT")
            receipt = world.dispatch(plan.commands[0]) if plan.commands else None
            replayed = record(
                SimpleNamespace(
                    observation=obs,
                    plan=plan,
                    rejected_parents=row["rejected_parents"],
                    receipt_id=receipt.id if receipt else None,
                )
            )
            require(replayed == row, "PROJECTION_NOMINAL_DECISION_REPLAY")
        require(prefix.state.time_h >= world.s.time_h, "PROJECTION_NOMINAL_CLOCK")
        if prefix.state.time_h > world.s.time_h:
            world.advance(prefix.state.time_h)
        require(
            world.snapshot() == prefix and world.observe() == observation,
            "PROJECTION_UNAUTHORIZED_MODEL_EVOLUTION",
        )

    def problem(self, config, observation, prefix, **kwargs):
        require(config is self.config, "PROJECTION_CONFIG_CONTEXT")
        self.check_prefix(observation, prefix, kwargs.get("decisions", ()))
        return SimulationJointProblem(
            config,
            observation,
            prefix,
            execution_checkpoint=self.execution.fork(),
            decision_checkpoint=self.causal.fork(),
            **kwargs,
        )

    def audit_candidate(self, problem, schedule):
        require(
            problem.config is self.config
            and problem.prefix.events[: len(self.snapshot.events)] == self.snapshot.events,
            "PROJECTION_CANDIDATE_CONTEXT",
        )
        self.check_prefix(problem.observation, problem.prefix, problem.decisions)
        snapshot, rows = problem.preview(schedule)
        a = check_run(self.config, snapshot, checkpoint=self.execution.fork())
        b = check_decisions(self.config, snapshot, rows, checkpoint=self.causal.fork())
        require(a.status == b.status == "PASS", "PROJECTION_CANDIDATE_AUDIT")
        return dict(
            scope="HYPOTHETICAL_SUFFIX_NOT_ACTUAL_EXECUTION",
            execution=a.status,
            causal=b.status,
            schedule_sha256=fingerprint(schedule),
            proof=clone(self.proof),
        )


class ProjectedPolicy:
    def __init__(
        self,
        config,
        budget,
        *,
        end_h,
        settings=ObservationSettings(),
        method="ADAPTIVE_JOINT",
        objective=None,
    ):
        settings.validate()
        self.config, self.settings, self.end_h, self.method = config, settings, end_h, method
        self.contract = ProjectionContract.create(
            config, budget, method=method, settings=settings, objective=objective
        )
        self.inner = SimulationJointPolicy(
            config, budget, method=method, end_h=end_h, objective=objective
        )
        self.budget = self.inner.budget
        self.frames, self.trace, self.candidate_proofs = [], [], []
        self.latest = self.anchor = None
        self.sample_ordinal = -1
        self.context = None

    @property
    def journal(self):
        return [
            dict(
                projection=self.settings.version, proposals=self.inner.journal, delivery=self.trace
            )
        ]

    @property
    def candidates(self):
        return self.inner.candidates

    def decide(self, value, prefix, decisions, *, sequence=0, rejected=()):
        now = prefix.state.time_h
        context = prefix.run_id, prefix.epoch, prefix.config_sha256
        require(self.context in (None, context), "PROJECTION_RUN_CONTEXT")
        self.context = context
        ordinal = round(now / self.settings.period_h)
        if (
            math.isclose(now, ordinal * self.settings.period_h, abs_tol=1e-9, rel_tol=0)
            and ordinal > self.sample_ordinal
        ):
            require(ordinal == self.sample_ordinal + 1, "PROJECTION_MISSED_PUBLIC_SAMPLE")
            frame = ObservationFrame(
                prefix,
                close_rows(self.config, prefix, decisions),
                ordinal,
                now + self.settings.delay_h,
                uniform(self.settings.seed, "missing", "snapshot", ordinal)
                < self.settings.missing_probability,
                fingerprint(asdict(self.settings)),
            )
            self.frames.append(frame)
            self.sample_ordinal = ordinal
        delivered = [f for f in self.frames if not f.dropped and f.received_h <= now]
        newest = delivered[-1] if delivered else None
        if newest is not None and (self.latest is None or newest.ordinal > self.latest.ordinal):
            if self.method != "NO_OBSERVATION_UPDATE" or self.anchor is None:
                self.anchor = ModelAnchor(self.config, newest, self.settings, now)
                self.inner.problem_factory = self.anchor.problem
            self.latest = newest
        if self.anchor is None:
            self.trace.append(
                dict(time_h=now, sequence=sequence, frame_id=None, result="WAIT_UNKNOWN")
            )
            return m.Plan(
                self.config.schema_version,
                self.config.id,
                value.observation.id,
                (),
                "WAIT",
                "S20_NO_DELIVERED_OBSERVATION",
                self.config.research,
            )
        observation, model, rows = self.anchor.at(now)
        model_value = planning_input(self.config, observation, 10000)
        before = len(self.inner.candidates)
        proposal = self.inner.decide(model_value, model, rows, sequence=sequence, rejected=())
        for problem, schedule in self.inner.candidates[before:]:
            self.candidate_proofs.append((self.anchor, problem, schedule))
        entry = dict(
            time_h=now,
            sequence=sequence,
            frame_id=self.anchor.frame.identity(),
            model_observation_sha256=digest(observation),
            proposal=wire(proposal),
            calls_after_proposal=self.budget.calls,
        )
        command = None
        if proposal.commands:
            command = replace(
                proposal.commands[0], issued_sim_h=now, expected_revision=prefix.state.revision
            )
            # No search, ranking or fallback receives the outcome of this check.
            safety = restore_world(self.config, prefix)
            if command.service:
                safety.operations[command.operation_id] = command.service.operation
                if command.service.route:
                    safety.routes[command.service.route.id] = command.service.route
            try:
                require(command.operation_id not in rejected, "S20_ACTUAL_REJECTION_SHIELD")
                validate(command, config=self.config)
                safety._admit(command)
                entry["result"] = "ADMITTED"
            except ValueError as exc:
                command = None
                entry["result"], entry["refusal"] = "SAFETY_WAIT", str(exc)
        else:
            entry["result"] = "MODEL_WAIT"
        plan = m.Plan(
            self.config.schema_version,
            self.config.id,
            value.observation.id,
            (command,) if command else (),
            "CANDIDATE" if command else "WAIT",
            "S20_PROJECTED_PROPOSAL" if command else "S20_PROJECTED_WAIT",
            self.config.research,
        )
        entry["actual_plan"] = wire(plan)
        self.trace.append(entry)
        return plan

    def next_tick(self, now_h):
        grid = (self.sample_ordinal + 1) * self.settings.period_h
        arrivals = [f.received_h for f in self.frames if not f.dropped and f.received_h > now_h]
        ticks = [self.end_h, self.inner.next_tick(now_h), grid, *arrivals]
        return min(t for t in ticks if t > now_h + 1e-10) if now_h < self.end_h else self.end_h


def audit_projection_history(config, snapshot, decisions, policy):
    """Independent source/delivery/nominal-candidate and unchanged-dispatch checks."""
    decisions = tuple(decisions)
    check_contract(config, policy.contract, policy.method, policy.settings, policy.budget.declared)
    require(
        check_run(config, snapshot).status == "PASS"
        and check_decisions(config, snapshot, decisions).status == "PASS",
        "PROJECTION_ACTUAL_AUDIT",
    )
    expected_count = math.floor((snapshot.state.time_h + 1e-9) / policy.settings.period_h) + 1
    require(len(policy.frames) == expected_count, "PROJECTION_PUBLIC_SAMPLE_COVERAGE")
    for expected, frame in enumerate(policy.frames):
        require(
            frame.ordinal == expected
            and frame.snapshot.run_id == snapshot.run_id
            and frame.snapshot.epoch == snapshot.epoch
            and tuple(snapshot.events[: len(frame.snapshot.events)]) == frame.snapshot.events,
            "PROJECTION_FRAME_SOURCE_PREFIX",
        )
        check_frame(config, frame, policy.settings, frame.received_h)
    by_id = {f.identity(): f for f in policy.frames}
    anchors = {}

    def rebuilt_anchor(frame):
        identity = frame.identity()
        if identity not in anchors:
            anchors[identity] = ModelAnchor(config, frame, policy.settings, snapshot.state.time_h)
        return anchors[identity]

    require(
        [entry["sequence"] for entry in policy.trace] == list(range(len(decisions))),
        "PROJECTION_MISSING_OR_DUPLICATE_DECISION_PROOF",
    )
    for entry in policy.trace:
        require(
            type(entry["sequence"]) is int and 0 <= entry["sequence"] < len(decisions),
            "PROJECTION_ACTUAL_ROW",
        )
        actual_row = decisions[entry["sequence"]]
        require(actual_row["sampled_h"] == entry["time_h"], "PROJECTION_ACTUAL_CLOCK")
        if entry["frame_id"] is None:
            require(
                not any(not f.dropped and f.received_h <= entry["time_h"] for f in policy.frames),
                "PROJECTION_FALSE_UNKNOWN",
            )
            require(
                not actual_row["plan"]["commands"]
                and actual_row["plan"]["reason"] == "S20_NO_DELIVERED_OBSERVATION",
                "PROJECTION_UNKNOWN_DISPATCH",
            )
            continue
        frame = by_id[entry["frame_id"]]
        require(
            not frame.dropped and frame.received_h <= entry["time_h"], "PROJECTION_EARLY_DELIVERY"
        )
        eligible_frames = [
            f for f in policy.frames if not f.dropped and f.received_h <= entry["time_h"]
        ]
        expected_frame = (
            eligible_frames[0] if policy.method == "NO_OBSERVATION_UPDATE" else eligible_frames[-1]
        )
        require(frame.identity() == expected_frame.identity(), "PROJECTION_WRONG_DELIVERED_FRAME")
        model_observation, _, _ = rebuilt_anchor(frame).at(entry["time_h"])
        require(
            entry["model_observation_sha256"] == digest(model_observation),
            "PROJECTION_MODEL_OBSERVATION_BINDING",
        )
        nominal, actual = entry["proposal"], entry["actual_plan"]
        require(as_data(actual) == actual_row["plan"], "PROJECTION_ACTUAL_PLAN_BINDING")
        if nominal["commands"]:
            eligible_candidates = [
                (p, s) for p, s in policy.candidates if p.observation.sampled_h <= entry["time_h"]
            ]
            require(eligible_candidates, "PROJECTION_UNCERTIFIED_PROPOSAL")
            _, schedule = eligible_candidates[-1]
            proposal_command = nominal["commands"][0]
            source = None
            for step in schedule.steps:
                if (
                    step.plan.commands
                    and proposal_command["id"]
                    == step.plan.commands[0].id + f"-ACTUAL-{entry['sequence']}"
                ):
                    source = wire(step.plan.commands[0])
                    break
            require(source is not None, "PROJECTION_PROPOSAL_NOT_IN_SCHEDULE")
            amended = clone(proposal_command)
            for field in ("id", "issued_sim_h", "expected_revision"):
                source.pop(field), amended.pop(field)
            require(source == amended, "PROJECTION_PROPOSAL_MUTATION")
            n = actual_row["event_count"]
            visible_state = snapshot.events[n - 1].state if n else policy.frames[0].snapshot.state
            actual_prefix = replace(snapshot, state=visible_state, events=snapshot.events[:n])
            safety = restore_world(config, actual_prefix)
            command = replace(
                decode(m.DispatchCommand, as_data(proposal_command)),
                issued_sim_h=actual_row["sampled_h"],
                expected_revision=actual_row["state_revision"],
            )
            if command.service:
                safety.operations[command.operation_id] = command.service.operation
                if command.service.route:
                    safety.routes[command.service.route.id] = command.service.route
            refusal = None
            try:
                require(
                    command.operation_id not in actual_row["rejected_parents"],
                    "S20_ACTUAL_REJECTION_SHIELD",
                )
                validate(command, config=config)
                safety._admit(command)
            except ValueError as exc:
                refusal = str(exc)
            require(bool(actual["commands"]) == (refusal is None), "PROJECTION_SHIELD_VERDICT")
            if refusal:
                require(
                    entry["result"] == "SAFETY_WAIT" and entry["refusal"] == refusal,
                    "PROJECTION_REFUSAL_PROOF",
                )
        if actual["commands"]:
            require(
                entry["result"] == "ADMITTED" and len(nominal["commands"]) == 1,
                "PROJECTION_DISPATCH_SOURCE",
            )
            a, b = clone(nominal["commands"][0]), clone(actual["commands"][0])
            for field in ("issued_sim_h", "expected_revision"):
                a.pop(field), b.pop(field)
            require(a == b, "PROJECTION_COMMAND_CHANGED_AFTER_SEARCH")
        require(
            entry["calls_after_proposal"] <= policy.budget.declared.max_calls,
            "PROJECTION_EXTRA_SEARCH",
        )
    require(
        len(policy.candidate_proofs) == len(policy.candidates), "PROJECTION_MISSING_CANDIDATE_PROOF"
    )
    for anchor, problem, schedule in policy.candidate_proofs:
        check_frame(config, anchor.frame, policy.settings, snapshot.state.time_h)
        rebuilt = rebuilt_anchor(anchor.frame)
        require(
            rebuilt.proof == anchor.proof and rebuilt.snapshot == anchor.snapshot,
            "PROJECTION_MODEL_PROOF_MUTATION",
        )
        expected_mode = {"FIXED_H": "H", "FIXED_HR": "HR-seq"}.get(policy.method)
        require(problem.fixed_mode == expected_mode, "PROJECTION_FIXED_MODE_BINDING")
        require(
            fingerprint(asdict(problem.objective) if problem.objective else None)
            == fingerprint(
                asdict(policy.contract.objective) if policy.contract.objective else None
            ),
            "PROJECTION_OBJECTIVE_BINDING",
        )
        # Rebind immutable, content-checked event objects to the independent cache.
        events = problem.prefix.events[: len(rebuilt.snapshot.events)]
        require(events == rebuilt.snapshot.events, "PROJECTION_MODEL_PREFIX")
        rebuilt.execution._events = events
        rebuilt.causal._events = events
        rebuilt.audit_candidate(problem, schedule)
    return dict(
        status="PASS",
        scope="S20_AUTHORIZED_PROJECTION_AND_REAL_EXECUTION",
        frames=len(policy.frames),
        decisions=len(policy.trace),
        candidates=len(policy.candidate_proofs),
    )


def decode_exact(kind, raw):
    """Validate JSON, retaining its integer/float spelling for exact source hashes."""
    if kind is Schedule:
        # The general production codec handles homogeneous tuples. Genes also
        # contain (ID, int/float) pairs, which require their explicit schema.
        require(set(raw) == {f.name for f in fields(Schedule)}, "PROJECTION_SCHEDULE_FIELDS")
        genes = raw["genes"]
        require(set(genes) == {f.name for f in fields(Genes)}, "PROJECTION_GENE_FIELDS")
        pairs = {}
        for name in ("modes", "crews", "order", "slots"):
            require(
                type(genes[name]) is list
                and all(type(p) is list and len(p) == 2 and type(p[0]) is str for p in genes[name]),
                "PROJECTION_GENE_PAIRS",
            )
            pairs[name] = tuple(tuple(p) for p in genes[name])
        require(
            type(genes["rests"]) is list
            and all(type(x) is str for x in genes["rests"])
            and type(genes["initial_action_only"]) is bool,
            "PROJECTION_GENE_TYPES",
        )
        steps = []
        for step in raw["steps"]:
            require(set(step) == {"plan", "advance_to_h"}, "PROJECTION_STEP_FIELDS")
            t = step["advance_to_h"]
            require(
                t is None or type(t) in (int, float) and math.isfinite(t) and t >= 0,
                "PROJECTION_STEP_CLOCK",
            )
            steps.append(Step(decode_exact(m.Plan, step["plan"]), t))
        parsed = Schedule(
            raw["anchor_sha256"],
            raw["end_h"],
            Genes(
                **pairs,
                rests=tuple(genes["rests"]),
                initial_action_only=genes["initial_action_only"],
            ),
            tuple(steps),
            raw["scope"],
        )
    else:
        parsed = decode(kind, raw)

    def preserve(value, saved):
        if is_dataclass(value):
            return replace(
                value,
                **{f.name: preserve(getattr(value, f.name), saved[f.name]) for f in fields(value)},
            )
        if isinstance(value, tuple):
            return tuple(preserve(v, s) for v, s in zip(value, saved))
        return saved if type(value) is float else value

    return preserve(parsed, raw)


def export_projection(policy):
    return dict(
        version="S20-PROJECTION-EVIDENCE-r2",
        contract=as_data(policy.contract),
        settings=asdict(policy.settings),
        method=policy.method,
        budget=policy.budget.report(),
        trace=clone(policy.trace),
        frames=[
            dict(
                snapshot=as_data(f.snapshot),
                decisions=clone(f.decisions),
                ordinal=f.ordinal,
                received_h=f.received_h,
                dropped=f.dropped,
                settings_sha256=f.settings_sha256,
            )
            for f in policy.frames
        ],
        candidates=[
            dict(
                frame_id=a.frame.identity(),
                proof=clone(a.proof),
                prefix=as_data(p.prefix),
                decisions=p.decisions,
                schedule=as_data(s),
                fixed_mode=p.fixed_mode,
                objective=asdict(p.objective) if p.objective else None,
            )
            for a, p, s in policy.candidate_proofs
        ],
    )


def audit_saved_projection(config, snapshot, decisions, data, *, expected):
    """Rebuild scoped model certificates from saved sources, with no new search."""
    require(
        data["version"] in ("S20-PROJECTION-EVIDENCE-r1", "S20-PROJECTION-EVIDENCE-r2"),
        "PROJECTION_EVIDENCE_VERSION",
    )
    settings = ObservationSettings(**data["settings"])
    declared = Budget(**data["budget"]["declared"])
    check_contract(config, expected, data["method"], settings, declared)
    if data["version"] == "S20-PROJECTION-EVIDENCE-r2":
        require(
            fingerprint(data["contract"]) == fingerprint(as_data(expected)),
            "PROJECTION_SAVED_CONTRACT_BINDING",
        )
    frames = [
        ObservationFrame(
            decode_exact(m.ExecutionSnapshot, r["snapshot"]),
            tuple(r["decisions"]),
            r["ordinal"],
            r["received_h"],
            r["dropped"],
            r["settings_sha256"],
        )
        for r in data["frames"]
    ]
    by_id = {f.identity(): f for f in frames}
    candidates, proofs = [], []
    for row in data["candidates"]:
        anchor = ModelAnchor(config, by_id[row["frame_id"]], settings, snapshot.state.time_h)
        require(anchor.proof == row["proof"], "PROJECTION_SAVED_PROOF")
        prefix = decode_exact(m.ExecutionSnapshot, row["prefix"])
        root = prefix.events[: len(anchor.snapshot.events)]
        require(root == anchor.snapshot.events, "PROJECTION_SAVED_PREFIX")
        anchor.execution._events = root
        anchor.causal._events = root
        schedule = decode_exact(Schedule, row["schedule"])
        problem = anchor.problem(
            config,
            restore_world(config, prefix).observe(),
            prefix,
            decisions=tuple(row["decisions"]),
            end_h=schedule.end_h,
            fixed_mode=row["fixed_mode"],
            objective=WeightedObjective(**row["objective"]) if row["objective"] else None,
        )
        candidates.append((problem, schedule))
        proofs.append((anchor, problem, schedule))
    policy = SimpleNamespace(
        contract=expected,
        frames=frames,
        trace=data["trace"],
        settings=settings,
        method=data["method"],
        candidates=candidates,
        candidate_proofs=proofs,
        budget=SimpleNamespace(declared=declared),
    )
    return audit_projection_history(config, snapshot, decisions, policy)
