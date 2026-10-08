"""S18 production joint suffix search over a delivered prefix and an entire future window.

Rollouts contain only already delivered external facts. Unobserved arrivals,
quality and receipt permissions remain unknown; they are not forecast as PASS.
"""

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
    ):
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
        require(check_run(config, prefix).status == "PASS", "INVALID_EXECUTION_PREFIX")
        self.config, self.observation, self.prefix = config, observation, prefix
        supplied = deepcopy(tuple(decisions))
        terminal_row = record(terminal(config, observation))
        already_closed = bool(
            supplied
            and supplied[-1]["event_count"] == len(prefix.events)
            and supplied[-1]["receipt_id"] is None
            and not supplied[-1]["plan"]["commands"]
        )
        closed = supplied if already_closed else supplied + (terminal_row,)
        require(check_decisions(config, prefix, closed).status == "PASS", "INVALID_CAUSAL_PREFIX")
        # Preserve the source journal separately. A non-dispatch terminal WAIT
        # closes an archived checkpoint; the extended journal uses the next
        # proposal at that same observation instead of duplicating its prefix.
        self.decisions = supplied[:-1] if already_closed else supplied
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
        self.validation_seconds = 0.0
        self.validation_calls = 0

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

    def genes(self, rng=None):
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
                else self.fixed_mode
                or (
                    rng.choice(("H", "HR-seq"))
                    if rng
                    else "H"
                    if "R1" in self.observation.state.failed_resources
                    else "HR-seq"
                )
            )
            who = (
                (
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
            if perf_counter() >= deadline:
                return Repair(None, reasons=("WALL_BUDGET",), termination="WALL_BUDGET")
            obs = w.observe()
            value = planning_input(
                self.config, obs, min(10000, max(1, (deadline - perf_counter()) * 1000))
            )
            value = replace(
                value, operations=tuple(o for o in value.operations if o.id not in rejected)
            )
            plan = choose(
                self.config,
                value,
                sequence=len(steps),
                excluded_operations=rejected,
                mode_choices=genes.modes,
                crew_choices=genes.crews,
                order_bias=genes.order,
                start_slots=genes.slots,
                rest_people=tuple(rests),
            )
            if plan.commands:
                c = plan.commands[0]
                receipt = w.dispatch(c)
                if receipt.kind != "STARTED":
                    return Repair(None, reasons=("NOMINAL_DISPATCH:" + receipt.reason,))
                if plan.reason == "PROPOSED_REST":
                    rests.remove(c.service.operation.entity_id)
                steps.append(Step(plan, None))
                continue
            if plan.status == "NO_PLAN_FOUND":
                return Repair(None, reasons=(plan.reason,))
            ticks = [self.end_h]
            ticks += [r.earliest_end_h for r in w.s.running if r.status == "STARTED"]
            ticks += [t for _, t in genes.slots if t > w.s.time_h + 1e-10]
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
        return self.rollout(self.genes(), deadline)

    def mutable(self, candidate):
        return ("MODE", "CREW", "ORDER", "START_SLOT", "REST")

    def repair(self, candidate, removed, rng, trials, deadline):
        require(set(removed) <= set(self.mutable(candidate)), "UNKNOWN_JOINT_NEIGHBORHOOD")
        reasons = set()
        for n in range(trials):
            proposed = self.genes(rng)
            # Only destroyed genes change; actual attempts are already protected in genes().
            fields = dict(
                MODE="modes", CREW="crews", ORDER="order", START_SLOT="slots", REST="rests"
            )
            genes = replace(
                candidate.genes, **{fields[k]: getattr(proposed, fields[k]) for k in removed}
            )
            # A changed mode requires its own eligible role pool.
            if "MODE" in removed:
                genes = replace(genes, crews=proposed.crews)
            result = self.rollout(genes, deadline)
            reasons.update(result.reasons)
            if result.candidate is not None:
                return Repair(result.candidate, n + 1, tuple(sorted(reasons)))
            if perf_counter() >= deadline:
                break
        return Repair(None, n + 1, tuple(sorted(reasons)), "REPAIR_BUDGET")

    def preview(self, candidate):
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
                type(v) in (int, float) and v >= self.observation.sampled_h
                for _, v in candidate.genes.slots
            ),
            "CANDIDATE_GENE_SLOTS",
        )
        require(
            set(candidate.genes.rests) <= {p.id for p in self.config.people}, "CANDIDATE_GENE_REST"
        )
        if self.fixed_mode:
            committed = {a.activity_id for a in self.observation.state.mode_attempts}
            require(
                all(v == self.fixed_mode for a, v in candidate.genes.modes if a not in committed),
                "FIXED_MODE_CHANGED",
            )
        for step in candidate.steps:
            for command in step.plan.commands:
                if command.branch:
                    require(
                        command.mode_id == modes[command.activity_id], "CANDIDATE_MODE_METADATA"
                    )
        require(
            candidate.anchor_sha256 == self.anchor and candidate.end_h == self.end_h,
            "CANDIDATE_WINDOW_OR_ANCHOR",
        )
        w, rows = self.world(), list(self.decisions)
        for step in candidate.steps:
            obs = w.observe()
            require(step.plan.observation_id == obs.id, "SCHEDULE_OBSERVATION")
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
        require(abs(w.s.time_h - self.end_h) <= 1e-8, "FULL_WINDOW_NOT_REACHED")
        rows.append(record(terminal(self.config, w.observe())))
        return w.snapshot(), tuple(rows)

    def verify(self, candidate):
        start = perf_counter()
        self.validation_calls += 1
        try:
            snapshot, rows = self.preview(candidate)
            audit = check_run(self.config, snapshot)
            require(audit.status == "PASS", "S10:" + ";".join(f.reason for f in audit.findings))
            causal = check_decisions(self.config, snapshot, rows)
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
