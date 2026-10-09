"""S18 production joint suffix search over a delivered prefix and an entire future window.

Rollouts contain only already delivered external facts. Unobserved arrivals,
quality and receipt permissions remain unknown; they are not forecast as PASS.
"""

import math
from copy import deepcopy
from dataclasses import dataclass, replace
from time import perf_counter
from types import SimpleNamespace

from adaptive_hrc_scheduling.algorithms.lns import Repair, Verification
from adaptive_hrc_scheduling.building_human import calendar_state
from adaptive_hrc_scheduling.contracts.codec import ContractError, require
from adaptive_hrc_scheduling.contracts.production import digest, validate
from adaptive_hrc_scheduling.control.production_decisions import check_decisions, record
from adaptive_hrc_scheduling.domain import production as m
from adaptive_hrc_scheduling.planning.production import choose, planning_input
from adaptive_hrc_scheduling.production_admission import completed_activity
from adaptive_hrc_scheduling.production_backend import ProductionBackend
from adaptive_hrc_scheduling.production_checker import check_run


@dataclass(frozen=True)
class Genes:
    modes: tuple[tuple[str, str], ...]
    crews: tuple[tuple[str, str], ...]
    order: tuple[tuple[str, int], ...]
    slots: tuple[tuple[str, float], ...]
    rests: tuple[str, ...] = ()
    initial_action_only: bool = False


@dataclass(frozen=True)
class Step:
    plan: m.Plan
    advance_to_h: float | None


@dataclass(frozen=True)
class Schedule:
    anchor_sha256: str
    end_h: float
    genes: Genes
    steps: tuple[Step, ...]
    scope: str = "COMPLETE_NOMINAL_WINDOW_NO_UNKNOWN_EXTERNAL_FACTS"


def terminal(config, observation):
    return SimpleNamespace(
        observation=observation,
        plan=m.Plan(
            config.schema_version,
            config.id,
            observation.id,
            (),
            "WAIT",
            "S18_WINDOW_END",
            config.research,
        ),
        rejected_parents=(),
        receipt_id=None,
    )


class SimulationJointProblem:
    def __init__(
        self,
        config,
        observation,
        prefix,
        *,
        decisions=(),
        end_h,
        fixed_mode=None,
        max_steps=4096,
        rejected=(),
        checkpoint=None,
        committed=(),
        execution_checkpoint=None,
        decision_checkpoint=None,
        initial_action_only=False,
    ):
        self.checkpoint = checkpoint or (lambda: None)
        self.checkpoint()
        validate(config)
        require(config.research is not None, "SIMULATION_JOINT_ADMISSION_REQUIRED")
        validate(observation, config=config)
        require(
            observation.state == replace(prefix.state, intervals=())
            and observation.event_ids == tuple(e.id for e in prefix.events)
            and observation.received_h == observation.sampled_h
            and prefix.config_sha256 == digest(config),
            "DELIVERED_PREFIX_REQUIRED",
        )
        require(
            end_h > observation.sampled_h and fixed_mode in (None, "H", "HR-seq"),
            "COMMON_WINDOW_OR_MODE",
        )
        require(
            check_run(config, prefix, checkpoint=execution_checkpoint).status == "PASS",
            "INVALID_EXECUTION_PREFIX",
        )
        self.execution_checkpoint = (
            execution_checkpoint.fork() if execution_checkpoint is not None else None
        )
        self.checkpoint()
        self.config, self.observation, self.prefix = config, observation, prefix
        supplied = (
            decision_checkpoint._capture_rows(tuple(decisions))
            if decision_checkpoint is not None
            else deepcopy(tuple(decisions))
        )
        terminal_row = record(terminal(config, observation))
        already_closed = bool(
            supplied
            and supplied[-1]["event_count"] == len(prefix.events)
            and supplied[-1]["receipt_id"] is None
            and not supplied[-1]["plan"]["commands"]
        )
        closed = supplied if already_closed else supplied + (terminal_row,)
        require(
            check_decisions(config, prefix, closed, checkpoint=decision_checkpoint).status
            == "PASS",
            "INVALID_CAUSAL_PREFIX",
        )
        self.decision_checkpoint = (
            decision_checkpoint.fork() if decision_checkpoint is not None else None
        )
        self.checkpoint()
        # Preserve the source journal separately. A non-dispatch terminal WAIT
        # closes an archived checkpoint; the extended journal uses the next
        # proposal at that same observation instead of duplicating its prefix.
        self._decisions = supplied[:-1] if already_closed else supplied
        self.end_h, self.fixed_mode, self.max_steps = end_h, fixed_mode, max_steps
        self.anchor = digest(observation)
        self.scope = tuple(s.activity_id for s in config.research.scope_bindings)
        self.activities = tuple(a.id for a in config.core_activities)
        self.crew_specs = tuple(
            (a.id + ":" + r.id, r.qualification, r.id, a.id)
            for a in config.core_activities
            if a.id not in self.scope
            for mode in a.modes
            if mode.enabled
            for u in mode.units[:1]
            for r in u.roles
        )
        self.crew_keys = (*self.scope, *(key for key, _, _, _ in self.crew_specs))
        self.rejected = tuple(rejected)
        self.committed = tuple(committed)
        self.validation_seconds = 0.0
        self.validation_calls = 0
        self.search_iterations = 0
        self.search_trials = 0
        self._plan_reference = {}
        require(type(initial_action_only) is bool, "INITIAL_POLICY_TYPE")
        self.initial_action_only = initial_action_only

    @property
    def decisions(self):
        # Exported journals cannot mutate the private certified history.
        return deepcopy(self._decisions)

    def input_for(self, w, genes, index, budget_ms):
        # The conservative seed may choose its first action, then deliberately
        # hold all uncommitted new work. Actual holds and promises still pass
        # through the regular recovery/commitment choice and physical replay.
        if (
            genes.initial_action_only
            and index > 0
            and not self.committed
            and not any(r.status == "EXCEPTION" for r in w.s.running)
        ):
            return m.PlanningInput(
                self.config.schema_version, self.config.id, w.observe(), (), budget_ms
            )
        return planning_input(self.config, w.observe(), budget_ms)

    def planned(self, w, value, genes, rejected, rests, index):
        key = (value.observation, value.operations, genes, tuple(sorted(rejected)), tuple(rests))
        prior = self._plan_reference.get(index)
        if prior is not None and prior[0] == key:
            return prior[1]
        result = self._planned(w, value, genes, rejected, rests, index)
        # Only a completed deterministic choice is reusable. A time-limited
        # planner failure cannot certify a future reference choice. Physical
        # replay and both independent audits still run for every candidate.
        if result.status != "NO_PLAN_FOUND":
            self._plan_reference[index] = (key, result)
        return result

    def _planned(self, w, value, genes, rejected, rests, index):
        held = {r.command.id for r in w.s.running if r.status == "EXCEPTION"}
        if held:
            recovery = choose(
                self.config,
                value,
                sequence=index,
                excluded_operations=rejected,
                mode_choices=genes.modes,
                crew_choices=genes.crews,
                order_bias=genes.order,
                start_slots=genes.slots,
                rest_people=tuple(rests),
            )
            if recovery.commands and recovery.commands[0].resume_of in held:
                return recovery
        started = set(w.s.completed) | {r.command.operation_id for r in w.s.running}
        outstanding = [(c, reason) for c, reason in self.committed if c.operation_id not in started]
        if outstanding:
            head, reason = outstanding[0]
            obs = value.observation
            if head.issued_sim_h > obs.sampled_h + 1e-10:
                return m.Plan(
                    self.config.schema_version,
                    self.config.id,
                    obs.id,
                    (),
                    "WAIT",
                    "S19_COMMITTED_FUTURE_START",
                    self.config.research,
                )
            command = replace(
                head,
                id=f"LOCKED-{w.s.revision}-{index}-{head.operation_id}",
                expected_revision=w.s.revision,
                issued_sim_h=obs.sampled_h,
            )
            return m.Plan(
                self.config.schema_version,
                self.config.id,
                obs.id,
                (command,),
                "CANDIDATE",
                reason,
                self.config.research,
            )
        if genes.initial_action_only and index > 0:
            return replace(terminal(self.config, value.observation).plan, reason="S19_SEED_HOLD")
        return choose(
            self.config,
            value,
            sequence=index,
            excluded_operations=rejected,
            mode_choices=genes.modes,
            crew_choices=genes.crews,
            order_bias=genes.order,
            start_slots=genes.slots,
            rest_people=tuple(rests),
        )

    def world(self):
        w = ProductionBackend(self.config, run_id=self.prefix.run_id, epoch=self.prefix.epoch)
        w.s, w.events = self.prefix.state, list(self.prefix.events)
        for e in self.prefix.events:
            if e.command:
                c = e.command
                if c.service:
                    w.operations[c.operation_id] = c.service.operation
                    if c.service.route:
                        w.routes[c.service.route.id] = c.service.route
                if e.kind in ("STARTED", "DEFERRED", "REJECTED", "COMPLETED", "EXCEPTION"):
                    w.commands[c.id] = (digest(c), e)
            if e.world:
                w.world_ids[e.world.id] = digest(e.world)
        return w

    def genes(self, rng=None, *, retained_modes=()):
        retained_modes = dict(retained_modes)
        attempts = {a.activity_id: a for a in self.observation.state.mode_attempts}
        modes, crews, order, slots = [], [], [], []
        for n, aid in enumerate(self.scope):
            a = next(a for a in self.config.core_activities if a.id == aid)
            held = attempts.get(aid)
            mode = (
                next(
                    m.kind
                    for m in a.modes
                    if held
                    and any(
                        o.branch
                        and o.branch.definition_id == held.definition_id
                        and o.production_mode == m.kind
                        for o in self.config.operations
                    )
                )
                if held
                else retained_modes.get(aid)
                or self.fixed_mode
                or (
                    rng.choice(("H", "HR-seq"))
                    if rng
                    else "H"
                    if "R1" in self.observation.state.failed_resources
                    else "HR-seq"
                )
            )
            who = (
                held.handover.incoming
                if held and held.handover
                else (
                    rng.choice(("W1", "W2"))
                    if rng
                    and mode == "H"
                    and held.completed_units
                    and not any(
                        r.command.activity_id == aid for r in self.observation.state.running
                    )
                    else held.crew[0].person_id
                )
                if held and held.crew
                else "OP1"
                if mode == "HR-seq"
                else (rng.choice(("W1", "W2")) if rng else "W1")
            )
            modes.append((aid, mode))
            crews.append((aid, who))
            order.append((aid, rng.randrange(len(self.scope)) if rng else n))
            slots.append(
                (
                    aid,
                    self.observation.sampled_h
                    + (rng.choice((0, 0.25, 0.5)) if rng and not held else 0),
                )
            )
        committed = {
            a.activity_id: {r.role_id: r.person_id for r in a.roles}
            for a in self.observation.state.activity_crews
        }
        used = {}
        for key, qualification, default, aid in self.crew_specs:
            used.setdefault(aid, set())
            candidates = [
                p.id
                for p in self.config.people
                if qualification in p.qualifications and p.id not in used[aid]
            ]
            who = committed.get(aid, {}).get(default) or (
                rng.choice(candidates) if rng else default
            )
            crews.append((key, who))
            used[aid].add(who)
        for n, aid in enumerate(self.activities):
            if aid in self.scope:
                continue
            started = aid in committed or any(
                r.command.activity_id == aid for r in self.observation.state.running
            )
            order.append((aid, rng.randrange(len(self.activities)) if rng else n))
            slots.append(
                (
                    aid,
                    self.observation.sampled_h
                    + (rng.choice((0, 0.25, 0.5)) if rng and not started else 0),
                )
            )
        rests = (rng.choice(("W1", "W2", "OP1")),) if rng and rng.randrange(2) else ()
        return Genes(tuple(modes), tuple(crews), tuple(order), tuple(slots), rests)

    def rollout(self, genes, deadline):
        w, steps = self.world(), []
        rests = list(genes.rests)
        rejected = set(self.rejected)
        while w.s.time_h < self.end_h - 1e-10 and len(steps) < self.max_steps:
            self.checkpoint()
            if perf_counter() >= deadline:
                return Repair(None, reasons=("WALL_BUDGET",), termination="WALL_BUDGET")
            value = self.input_for(
                w, genes, len(steps), min(10000, max(1, (deadline - perf_counter()) * 1000))
            )
            value = replace(
                value, operations=tuple(o for o in value.operations if o.id not in rejected)
            )
            plan = self.planned(w, value, genes, rejected, rests, len(steps))
            if plan.commands:
                c = plan.commands[0]
                receipt = w.dispatch(c)
                if receipt.kind != "STARTED":
                    return Repair(None, reasons=("NOMINAL_DISPATCH:" + receipt.reason,))
                if plan.reason == "PROPOSED_REST" and c.service.operation.entity_id in rests:
                    rests.remove(c.service.operation.entity_id)
                steps.append(Step(plan, None))
                continue
            if plan.status == "NO_PLAN_FOUND":
                return Repair(None, reasons=(plan.reason,))
            if plan.reason == "S19_SEED_HOLD":
                # advance() still integrates every completion and calendar
                # boundary. No new dispatch is proposed inside this interval.
                steps.append(Step(plan, self.end_h))
                w.advance(self.end_h)
                continue
            ticks = [self.end_h]
            ticks += [r.earliest_end_h for r in w.s.running if r.status == "STARTED"]
            ticks += [t for _, t in genes.slots if t > w.s.time_h + 1e-10]
            ticks += [
                c.issued_sim_h for c, _ in self.committed if c.issued_sim_h > w.s.time_h + 1e-10
            ]
            ticks += [calendar_state(p, w.s.time_h)[1] for p in self.config.people]
            ticks += [
                t.time_h + o.wait_h
                for o in self.config.operations
                if o.wait_after
                for t in w.s.completion_times
                if t.operation_id == o.wait_after and t.time_h + o.wait_h > w.s.time_h + 1e-10
            ]
            tick = min(t for t in ticks if t > w.s.time_h + 1e-10)
            steps.append(Step(plan, tick))
            w.advance(tick)
            rejected.clear()
        if abs(w.s.time_h - self.end_h) > 1e-8:
            return Repair(None, reasons=("FULL_WINDOW_NOT_REACHED",))
        return Repair(Schedule(self.anchor, self.end_h, genes, tuple(steps)), 1)

    def initial(self, deadline):
        self.search_trials += 1
        return self.rollout(
            replace(self.genes(), initial_action_only=self.initial_action_only), deadline
        )

    def mutable(self, candidate):
        return ("MODE", "CREW", "ORDER", "START_SLOT", "REST")

    def repair(self, candidate, removed, rng, trials, deadline):
        require(set(removed) <= set(self.mutable(candidate)), "UNKNOWN_JOINT_NEIGHBORHOOD")
        require(type(trials) is int and trials > 0, "REPAIR_TRIALS")
        self.search_iterations += 1
        reasons = set()
        attempted = 0
        for n in range(trials):
            self.checkpoint()
            if perf_counter() >= deadline:
                return Repair(None, attempted, tuple(sorted(reasons)), "WALL_BUDGET")
            attempted += 1
            self.search_trials += 1
            proposed = self.genes(
                rng, retained_modes=() if "MODE" in removed else candidate.genes.modes
            )
            # Only destroyed genes change; actual attempts are already protected in genes().
            fields = dict(
                MODE="modes", CREW="crews", ORDER="order", START_SLOT="slots", REST="rests"
            )
            genes = replace(
                candidate.genes,
                initial_action_only=False,
                **{fields[k]: getattr(proposed, fields[k]) for k in removed},
            )
            # A changed mode requires its own eligible role pool.
            if "MODE" in removed and "CREW" not in removed:
                old_modes, new_modes = dict(candidate.genes.modes), dict(genes.modes)
                proposed_crews = dict(proposed.crews)
                genes = replace(
                    genes,
                    crews=tuple(
                        (
                            key,
                            proposed_crews[key]
                            if key in new_modes and new_modes[key] != old_modes[key]
                            else who,
                        )
                        for key, who in genes.crews
                    ),
                )
            try:
                # Reject a bad local proposal without losing the verified incumbent.
                result = self.rollout(genes, deadline)
            except (ContractError, ValueError, KeyError, TypeError, StopIteration) as exc:
                reasons.add("REPAIR_REJECTED:" + type(exc).__name__ + ":" + str(exc))
                continue
            reasons.update(result.reasons)
            if result.candidate is not None:
                return Repair(result.candidate, n + 1, tuple(sorted(reasons)))
            if perf_counter() >= deadline:
                break
        return Repair(None, attempted, tuple(sorted(reasons)), "REPAIR_BUDGET")

    def preview(self, candidate):
        require(type(candidate.genes.initial_action_only) is bool, "CANDIDATE_INITIAL_POLICY")
        require(
            candidate.scope == "COMPLETE_NOMINAL_WINDOW_NO_UNKNOWN_EXTERNAL_FACTS",
            "CANDIDATE_SCOPE",
        )
        for name, keys in (
            ("modes", self.scope),
            ("crews", self.crew_keys),
            ("order", self.activities),
            ("slots", self.activities),
        ):
            entries = getattr(candidate.genes, name)
            require(
                len(entries) == len(keys) and {a for a, _ in entries} == set(keys),
                "CANDIDATE_GENE_SCOPE",
            )
        modes, crews = dict(candidate.genes.modes), dict(candidate.genes.crews)
        require(all(v in ("H", "HR-seq") for v in modes.values()), "CANDIDATE_GENE_MODE")
        require(
            all(crews[a] in (("W1", "W2") if modes[a] == "H" else ("OP1",)) for a in self.scope),
            "CANDIDATE_GENE_CREW",
        )
        people = {p.id: p for p in self.config.people}
        require(
            all(
                crews[key] in people and qual in people[crews[key]].qualifications
                for key, qual, _, _ in self.crew_specs
            ),
            "CANDIDATE_GENE_QUALIFICATION",
        )
        for aid in self.activities:
            selected = [crews[key] for key, _, _, a in self.crew_specs if a == aid]
            require(len(selected) == len(set(selected)), "CANDIDATE_GENE_DOUBLE_ROLE")
        require(
            all(type(v) is int and v >= 0 for _, v in candidate.genes.order), "CANDIDATE_GENE_ORDER"
        )
        require(
            all(
                type(v) in (int, float) and math.isfinite(v) and v >= self.observation.sampled_h
                for _, v in candidate.genes.slots
            ),
            "CANDIDATE_GENE_SLOTS",
        )
        require(
            len(candidate.genes.rests) == len(set(candidate.genes.rests))
            and set(candidate.genes.rests) <= {p.id for p in self.config.people},
            "CANDIDATE_GENE_REST",
        )
        if self.fixed_mode:
            committed = {a.activity_id for a in self.observation.state.mode_attempts}
            require(
                all(v == self.fixed_mode for a, v in candidate.genes.modes if a not in committed),
                "FIXED_MODE_CHANGED",
            )
        for attempt in self.observation.state.mode_attempts:
            expected = next(
                o.production_mode
                for o in self.config.operations
                if o.branch and o.branch.definition_id == attempt.definition_id
            )
            require(modes[attempt.activity_id] == expected, "CANDIDATE_COMMITTED_MODE")
            if attempt.handover:
                require(
                    crews[attempt.activity_id] == attempt.handover.incoming,
                    "CANDIDATE_COMMITTED_HANDOVER",
                )
            elif attempt.crew and (
                not attempt.completed_units
                or any(
                    r.command.activity_id == attempt.activity_id
                    for r in self.observation.state.running
                )
            ):
                require(
                    crews[attempt.activity_id] == attempt.crew[0].person_id,
                    "CANDIDATE_COMMITTED_CREW",
                )
        for committed in self.observation.state.activity_crews:
            for role in committed.roles:
                require(
                    crews[committed.activity_id + ":" + role.role_id] == role.person_id,
                    "CANDIDATE_COMMITTED_CREW",
                )
        require(
            candidate.anchor_sha256 == self.anchor and candidate.end_h == self.end_h,
            "CANDIDATE_WINDOW_OR_ANCHOR",
        )
        w, rows = self.world(), list(self._decisions)
        slots = dict(candidate.genes.slots)
        rests, rejected = list(candidate.genes.rests), set(self.rejected)
        for index, step in enumerate(candidate.steps):
            self.checkpoint()
            obs = w.observe()
            require(step.plan.observation_id == obs.id, "SCHEDULE_OBSERVATION")
            require(len(step.plan.commands) <= 1, "SCHEDULE_COMMAND_COUNT")
            for command in step.plan.commands:
                if any(
                    (command.operation_id, command.attempt) == (c.operation_id, c.attempt)
                    for c, _ in self.committed
                ):
                    # Bound to the exact promise by planned() equality below;
                    # mutable genes govern only the remaining uncommitted work.
                    continue
                # Independent declaration/trace checks, before dispatch or planner replay.
                if command.activity_id in slots:
                    require(
                        command.issued_sim_h + 1e-10 >= slots[command.activity_id],
                        "CANDIDATE_SLOT_METADATA",
                    )
                if command.branch:
                    require(
                        command.mode_id == modes[command.activity_id], "CANDIDATE_MODE_METADATA"
                    )
                    require(
                        all(r.person_id == crews[command.activity_id] for r in command.roles),
                        "CANDIDATE_CREW_METADATA",
                    )
                elif command.service and command.service.operation.handover:
                    change = command.service.operation.handover
                    require(
                        change.incoming == crews[change.activity_id]
                        and modes[change.activity_id] == "H",
                        "CANDIDATE_HANDOVER_METADATA",
                    )
                elif command.service is None and command.activity_id in self.activities:
                    require(
                        all(
                            crews.get(command.activity_id + ":" + r.role_id) == r.person_id
                            for r in command.roles
                        ),
                        "CANDIDATE_CREW_METADATA",
                    )
            # ORDER is a dispatch priority, not a forced total order. REST is a
            # consumable optional request, not every protective rest in the trace.
            # Replay these choices at each reconstructed observation, while S10
            # and the causal audit below independently check execution legality.
            value = self.input_for(w, candidate.genes, index, 10000)
            value = replace(
                value, operations=tuple(o for o in value.operations if o.id not in rejected)
            )
            expected = self.planned(w, value, candidate.genes, rejected, rests, index)
            require(expected == step.plan, "CANDIDATE_DISPATCH_METADATA")
            if (
                step.plan.reason == "PROPOSED_REST"
                and step.plan.commands[0].service.operation.entity_id in rests
            ):
                rests.remove(step.plan.commands[0].service.operation.entity_id)
            receipt = w.dispatch(step.plan.commands[0]) if step.plan.commands else None
            require(receipt is None or receipt.kind == "STARTED", "SCHEDULE_DISPATCH")
            rows.append(
                record(
                    SimpleNamespace(
                        observation=obs,
                        plan=step.plan,
                        rejected_parents=(),
                        receipt_id=receipt.id if receipt else None,
                    )
                )
            )
            if step.advance_to_h is not None:
                require(
                    not step.plan.commands and w.s.time_h < step.advance_to_h <= self.end_h,
                    "SCHEDULE_CLOCK",
                )
                w.advance(step.advance_to_h)
                rejected.clear()
        require(abs(w.s.time_h - self.end_h) <= 1e-8, "FULL_WINDOW_NOT_REACHED")
        rows.append(record(terminal(self.config, w.observe())))
        return w.snapshot(), tuple(rows)

    def verify(self, candidate):
        start = perf_counter()
        self.validation_calls += 1
        try:
            snapshot, rows = self.preview(candidate)
            self.checkpoint()
            audit = check_run(
                self.config,
                snapshot,
                checkpoint=self.execution_checkpoint.fork()
                if self.execution_checkpoint is not None
                else None,
            )
            self.checkpoint()
            require(audit.status == "PASS", "S10:" + ";".join(f.reason for f in audit.findings))
            causal = check_decisions(
                self.config,
                snapshot,
                rows,
                checkpoint=self.decision_checkpoint.fork()
                if self.decision_checkpoint is not None
                else None,
            )
            self.checkpoint()
            require(causal.status == "PASS", "CAUSE:" + ";".join(f.reason for f in causal.findings))
            # Completed facts/exposure in the whole nominal window; no score for
            # assumed future QUALITY, receipts, or unfinished makespan.
            score = (
                -sum(
                    completed_activity(self.config, snapshot.state.completed, a.id)
                    and not completed_activity(self.config, self.prefix.state.completed, a.id)
                    for a in self.config.core_activities
                ),
                sum(h.exposure for h in snapshot.state.humans),
                max(h.exposure for h in snapshot.state.humans),
            )
            return Verification(True, score)
        except (
            ContractError,
            KeyError,
            ValueError,
            TypeError,
            StopIteration,
            AttributeError,
        ) as exc:
            return Verification(False, None, (str(exc),))
        finally:
            self.validation_seconds += perf_counter() - start
