"""S19 cooperative online scheduling for the approved simulation domain.

Deadlines include input construction and verification. Individual Python calls
are not preempted: overruns are reported and late proposals are not dispatched.
Only delivered observations are available to search; the live executor remains
the final authority for acceptance and physical readback.
"""

import math
import random
from dataclasses import asdict, dataclass, replace
from time import perf_counter

from adaptive_hrc_scheduling.algorithms.lns import _gate, fingerprint
from adaptive_hrc_scheduling.algorithms.simulation_joint import SimulationJointProblem, terminal
from adaptive_hrc_scheduling.contracts.codec import ContractError, as_data, require
from adaptive_hrc_scheduling.contracts.production import digest, validate
from adaptive_hrc_scheduling.control.audit_cache import DecisionCheckpoint, ExecutionCheckpoint
from adaptive_hrc_scheduling.control.production_decisions import record
from adaptive_hrc_scheduling.domain import production as m
from adaptive_hrc_scheduling.planning.production import choose
from adaptive_hrc_scheduling.production_backend import ProductionBackend


class Interrupted(RuntimeError):
    """Cooperative interruption, deliberately not a candidate validation error."""


@dataclass(frozen=True)
class Limits:
    decision_seconds: float = 1.0
    search_seconds: float = 0.25
    period_h: float = 0.25
    horizon_h: float = 2.0
    iterations: int = 1
    repair_trials: int = 1
    max_search_calls: int = 4
    # Future commitments constrain choices, without creating execution ownership.
    future_commitment_h: float = 0.0

    def validate(self):
        for name in ("decision_seconds", "search_seconds", "period_h", "horizon_h"):
            value = getattr(self, name)
            require(type(value) in (int, float) and math.isfinite(value), "ONLINE_LIMIT_TYPE")
            require(value >= 0, "ONLINE_NEGATIVE_LIMIT")
        require(self.period_h > 0 and self.horizon_h > 0, "ONLINE_WINDOW")
        require(self.search_seconds <= self.decision_seconds, "ONLINE_SEARCH_ALLOCATION")
        require(
            type(self.future_commitment_h) in (int, float)
            and math.isfinite(self.future_commitment_h)
            and 0 <= self.future_commitment_h <= self.horizon_h,
            "ONLINE_COMMITMENT_WINDOW",
        )
        for name in ("iterations", "repair_trials", "max_search_calls"):
            value = getattr(self, name)
            require(type(value) is int and value >= 0, "ONLINE_COUNT")


def version(observation):
    """Bind run, epoch, configuration, time, delivered events and observed state."""
    return digest(observation)


def protected(state):
    return {
        name: as_data(getattr(state, name))
        for name in (
            "running",
            "owners",
            "reservations",
            "positions",
            "lots",
            "motions",
            "supports",
            "mode_attempts",
            "activity_crews",
        )
    }


def plan_rows(commands):
    return [
        dict(
            operation=c.operation_id,
            product=c.product_id,
            attempt=c.attempt,
            mode=c.mode_id,
            roles=as_data(c.roles),
            start_h=c.issued_sim_h,
        )
        for c in commands
    ]


def plan_change(before, after):
    """Counts use only the same not-started operation/attempt pairs in both plans."""

    def indexed(rows):
        result = {}
        for row in rows:
            key = (row["operation"], row["attempt"])
            require(key not in result, "DUPLICATE_PLAN_OPERATION")
            result[key] = row
        return result

    old, new = indexed(before), indexed(after)
    common = old.keys() & new.keys()
    a, b = [k for k in old if k in common], [k for k in new if k in common]
    ranks = {k: i for i, k in enumerate(b)}
    inversions = sum(ranks[x] > ranks[y] for i, x in enumerate(a) for y in a[i + 1 :])
    return dict(
        comparable=len(common),
        added=len(new.keys() - old.keys()),
        removed=len(old.keys() - new.keys()),
        order_inversions=inversions,
        mode_changes=sum(old[k]["mode"] != new[k]["mode"] for k in common),
        crew_changes=sum(old[k]["roles"] != new[k]["roles"] for k in common),
        start_changes=sum(old[k]["start_h"] != new[k]["start_h"] for k in common),
        total_start_shift_h=sum(abs(old[k]["start_h"] - new[k]["start_h"]) for k in common),
    )


class OnlinePolicy:
    method = "S19_ONLINE_JOINT"

    def __init__(self, config, limits=Limits(), *, end_h, problem_factory=SimulationJointProblem):
        validate(config)
        require(config.research is not None, "SIMULATION_ONLINE_ADMISSION_REQUIRED")
        limits.validate()
        require(math.isfinite(end_h) and end_h > 0, "ONLINE_END")
        self.config, self.limits, self.end_h = config, limits, end_h
        self.problem_factory = problem_factory
        self.budget = self  # production-loop manifest protocol
        self.journal, self.candidates = [], []
        self.pending = ()
        self.pending_reasons = {}
        self.committed = ()
        self.commitment_reasons = {}
        self.cache_origin = self.cache_hash = self.identity = None
        self.last_search_h = None
        self.last_event_count = 0
        self.calls = 0
        self.paused = self.cancelled = False
        self._cycle_start = None
        self._proposal_version = None
        self._force_trigger = None
        self._execution_checkpoint = ExecutionCheckpoint()
        self._decision_checkpoint = DecisionCheckpoint()

    def pause(self):
        self.paused = True
        self.cancelled = True
        self._force_trigger = "PAUSE"

    def resume(self):
        self.paused = self.cancelled = False
        self._force_trigger = "RESUME"

    def interrupt(self):
        self.cancelled = True

    def begin_cycle(self):
        self._cycle_start = perf_counter()

    def wait(self, obs, reason):
        c = self.config
        return m.Plan(c.schema_version, c.id, obs.id, (), "WAIT", "S19:" + reason, c.research)

    def _admit(self, command, obs, rejected):
        require(
            (command.run_id, command.epoch, command.config_sha256)
            == (obs.run_id, obs.epoch, obs.config_sha256),
            "STALE_COMMAND_IDENTITY",
        )
        require(command.operation_id not in rejected, "OBSERVED_REJECTION")
        require(command.expected_revision == obs.state.revision, "STALE_REVISION")
        require(command.issued_sim_h == obs.sampled_h, "STALE_CLOCK")
        validate(command, config=self.config)
        w = ProductionBackend(self.config, run_id=obs.run_id, epoch=obs.epoch)
        w.s = obs.state
        for running in obs.state.running:
            if running.command.service:
                service = running.command.service
                w.operations[service.operation.id] = service.operation
                if service.route:
                    w.routes[service.route.id] = service.route
        if command.service:
            w.operations[command.operation_id] = command.service.operation
            if command.service.route:
                w.routes[command.service.route.id] = command.service.route
        w._admit(command)

    def _search(self, obs, prefix, decisions, rejected, deadline, row):
        self.calls += 1
        row["search_call"] = self.calls
        began = perf_counter()
        best = score = problem = None

        def measured(label, function, *args, **kwargs):
            start = perf_counter()
            try:
                return function(*args, **kwargs)
            finally:
                row[label] = row.get(label, 0.0) + perf_counter() - start

        def checkpoint():
            if self.cancelled or self.paused:
                raise Interrupted("CANCELLED")
            if perf_counter() >= deadline:
                raise Interrupted("SEARCH_DEADLINE")

        def evaluate(candidate):
            nonlocal best, score
            checkpoint()
            if candidate is None:
                return
            report = measured(
                "candidate_gate_seconds",
                _gate,
                problem,
                candidate,
                dimensions=len(score) if score else None,
            )
            checkpoint()  # no partly checked or late candidate enters the cache
            if report.valid and (score is None or report.score < score):
                commands = tuple(c for s in candidate.steps for c in s.plan.commands)
                by_key = {(c.operation_id, c.attempt): c for c in commands}
                locked = {(c.operation_id, c.attempt): c for c in self.committed}
                # A candidate cannot silently replace a promise with an alternative.
                require(
                    all(
                        k in by_key and self._promise(by_key[k]) == self._promise(c)
                        for k, c in locked.items()
                    ),
                    "FUTURE_COMMITMENT_CHANGED",
                )
                require(
                    [k for k in by_key if k in locked] == list(locked), "FUTURE_COMMITMENT_ORDER"
                )
                best, score = candidate, report.score
                row.setdefault("candidate_acceptance_seconds", []).append(perf_counter() - began)
            elif not report.valid:
                row["failures"].extend(report.reasons)

        try:
            checkpoint()
            problem = measured(
                "construction_seconds",
                self.problem_factory,
                self.config,
                obs,
                prefix,
                decisions=decisions,
                end_h=min(self.end_h, obs.sampled_h + self.limits.horizon_h),
                rejected=tuple(rejected),
                checkpoint=checkpoint,
                **(
                    {
                        "execution_checkpoint": self._execution_checkpoint,
                        "decision_checkpoint": self._decision_checkpoint,
                        "initial_action_only": self.limits.search_seconds <= 0.05,
                    }
                    if self.problem_factory is SimulationJointProblem
                    else {}
                ),
                **(
                    {
                        "committed": tuple(
                            (c, self.commitment_reasons[(c.operation_id, c.attempt)])
                            for c in self.committed
                        )
                    }
                    if self.committed
                    else {}
                ),
            )
            initial = measured("initial_seconds", problem.initial, deadline)
            row["initial_strategy"] = (
                "INITIAL_ACTION_THEN_FULL_WINDOW_HOLD"
                if getattr(problem, "initial_action_only", False)
                else "FULL_JOINT_ROLLOUT"
            )
            row["failures"].extend(initial.reasons)
            evaluate(initial.candidate)
            rng = random.Random(self.calls - 1)
            for _ in range(self.limits.iterations):
                checkpoint()
                if best is None or self.limits.repair_trials == 0:
                    break
                # Do not begin another indivisible rollout when even the just
                # measured generation + full gate no longer fits. This is a
                # measured reserve, not a prediction or hard-time guarantee.
                reserve = row.get("initial_seconds", 0) + row.get("candidate_gate_seconds", 0)
                if perf_counter() + reserve >= deadline:
                    row["termination"] = "INSUFFICIENT_REPAIR_RESERVE"
                    break
                mutable = tuple(sorted(problem.mutable(best)))
                if not mutable:
                    break
                removed = tuple(sorted(rng.sample(mutable, min(2, len(mutable)))))
                repaired = measured(
                    "repair_seconds",
                    problem.repair,
                    best,
                    removed,
                    rng,
                    self.limits.repair_trials,
                    deadline,
                )
                row["failures"].extend(repaired.reasons)
                evaluate(repaired.candidate)
            if row["termination"] != "INSUFFICIENT_REPAIR_RESERVE":
                row["termination"] = "ITERATION_LIMIT"
        except Interrupted as exc:
            row["termination"] = str(exc)
        except (ContractError, ValueError, TypeError, KeyError, StopIteration, RuntimeError) as exc:
            row["termination"] = "SEARCH_ERROR"
            row["failures"].append(type(exc).__name__ + ":" + str(exc))
        finally:
            row.update(
                search_seconds=perf_counter() - began,
                verification_seconds=getattr(problem, "validation_seconds", 0),
                verification_calls=getattr(problem, "validation_calls", 0),
                iterations=getattr(problem, "search_iterations", 0),
                trials=getattr(problem, "search_trials", 0),
            )
        if best is not None:
            self.candidates.append((problem, best))
            row["score"] = score
            # Preserve the identity even if the current head is unusable and
            # fallback later clears the active cache. Hashing is bookkeeping
            # inside the total decision cycle, after the timed search gate.
            row["verified_candidate_sha256"] = fingerprint(best)
        return best

    def decide(self, value, prefix, decisions, *, sequence=0, rejected=()):
        began = self._cycle_start if self._cycle_start is not None else perf_counter()
        self._cycle_start = None
        deadline = began + self.limits.decision_seconds
        self._active_start = began
        obs = value.observation
        current_version = version(obs)
        self._proposal_version = current_version
        self._deadline = deadline
        self._rejected = tuple(rejected)
        identity = (obs.config_sha256, obs.run_id, obs.epoch)
        require(obs.config_sha256 == digest(self.config), "ONLINE_CONFIGURATION")
        require(
            obs.state == replace(prefix.state, intervals=())
            and obs.event_ids == tuple(e.id for e in prefix.events)
            and obs.received_h == obs.sampled_h
            and (prefix.run_id, prefix.epoch, prefix.config_sha256)
            == (obs.run_id, obs.epoch, obs.config_sha256),
            "ONLINE_DELIVERED_PREFIX",
        )
        identity_changed = self.identity is not None and identity != self.identity
        if identity_changed:
            self.pending = ()
            self.cache_origin = self.cache_hash = None
            self.last_search_h = None
            self.last_event_count = 0
            self.committed = ()
            self.commitment_reasons = {}
        self.identity = identity
        require(len(prefix.events) >= self.last_event_count, "ONLINE_PREFIX_REWIND")
        started = set(obs.state.completed) | {r.command.operation_id for r in obs.state.running}
        prior_commitments = self.committed
        cancelled_products = {p.product_id for p in obs.state.products if p.cancelled}
        self.committed = tuple(
            c
            for c in self.committed
            if c.operation_id not in started and c.product_id not in cancelled_products
        )
        self.pending = tuple(c for c in self.pending if c.operation_id not in started)
        old = plan_rows(self.pending)
        facts = prefix.events[self.last_event_count :]
        disruptive = any(e.kind in ("WORLD", "EXCEPTION", "REJECTED") for e in facts)
        trigger = self._force_trigger or (
            "IDENTITY_CHANGED"
            if identity_changed
            else "INITIAL"
            if self.last_search_h is None
            else "FEEDBACK"
            if disruptive
            else "PERIODIC"
            if obs.sampled_h >= self.last_search_h + self.limits.period_h - 1e-10
            else None
        )
        self._force_trigger = None
        self.last_event_count = len(prefix.events)
        row = dict(
            sequence=sequence,
            event_count=len(obs.event_ids),
            observation_id=obs.id,
            run_id=obs.run_id,
            epoch=obs.epoch,
            time_h=obs.sampled_h,
            observation_sha256=current_version,
            trigger=trigger,
            before=old,
            failures=[],
            termination="NO_SEARCH",
            search_seconds=0.0,
            verification_seconds=0.0,
            verification_calls=0,
            iterations=0,
            trials=0,
            protected_sha256=fingerprint(protected(obs.state)),
            completed_or_running=sorted(started),
            cache_invalidated=False,
            commitments_before=plan_rows(prior_commitments),
            commitment_releases=[
                dict(
                    operation=c.operation_id,
                    attempt=c.attempt,
                    reason="STARTED_OR_COMPLETED"
                    if c.operation_id in started
                    else "OBSERVED_CANCELLATION",
                )
                for c in prior_commitments
                if c not in self.committed
            ],
        )
        self.journal.append(row)
        if disruptive:
            # A changed feasibility domain invalidates the whole old suffix.
            self.pending = self.committed
            row["cache_invalidated"] = bool(old)
        ingest_failure = False
        if (
            not self.paused
            and not self.cancelled
            and perf_counter() < deadline
            and self.calls < self.limits.max_search_calls
            and self.limits.search_seconds > 0
            and self.problem_factory is SimulationJointProblem
        ):
            feedback_start = perf_counter()
            try:
                decisions = tuple(decisions)
                closed = decisions
                if not (
                    closed
                    and closed[-1]["event_count"] == len(prefix.events)
                    and closed[-1]["receipt_id"] is None
                    and not closed[-1]["plan"]["commands"]
                ):
                    closed += (record(terminal(self.config, obs)),)
                require(
                    self._execution_checkpoint.verify(self.config, prefix).status == "PASS",
                    "INVALID_EXECUTION_PREFIX",
                )
                require(
                    self._decision_checkpoint.verify(self.config, prefix, closed).status == "PASS",
                    "INVALID_CAUSAL_PREFIX",
                )
            except ContractError as exc:
                row["failures"].append(str(exc))
                ingest_failure = True
            finally:
                row["feedback_verification_seconds"] = perf_counter() - feedback_start
        if self.paused or self.cancelled or obs.sampled_h >= self.end_h or ingest_failure:
            plan = self.wait(
                obs,
                "INVALID_PREFIX"
                if ingest_failure
                else "PAUSED"
                if self.paused
                else "CANCELLED"
                if self.cancelled
                else "WINDOW_END",
            )
        else:
            if trigger:
                self.last_search_h = obs.sampled_h
                if self.calls < self.limits.max_search_calls and self.limits.search_seconds > 0:
                    candidate = self._search(
                        obs,
                        prefix,
                        tuple(decisions),
                        rejected,
                        min(deadline, perf_counter() + self.limits.search_seconds),
                        row,
                    )
                    if candidate is not None:
                        self.pending = tuple(c for s in candidate.steps for c in s.plan.commands)
                        self.pending_reasons = {
                            (c.operation_id, c.attempt): s.plan.reason
                            for s in candidate.steps
                            for c in s.plan.commands
                        }
                        self.cache_origin = current_version
                        self.cache_hash = row["verified_candidate_sha256"]
                        if self.limits.future_commitment_h:
                            locked = {(c.operation_id, c.attempt) for c in self.committed}
                            additions = tuple(
                                c
                                for c in self.pending
                                if (c.operation_id, c.attempt) not in locked
                                and c.issued_sim_h
                                <= obs.sampled_h + self.limits.future_commitment_h
                            )
                            self.committed += additions
                            self.commitment_reasons.update(self.pending_reasons)
                else:
                    row["termination"] = "SEARCH_DISABLED_OR_CALL_LIMIT"
            plan = None
            held = {r.command.id for r in obs.state.running if r.status == "EXCEPTION"}
            if (
                self.committed
                and held
                and not self.cancelled
                and not self.paused
                and perf_counter() < deadline
            ):
                recovery = choose(
                    self.config, value, sequence=sequence, excluded_operations=rejected
                )
                if recovery.commands and recovery.commands[0].resume_of in held:
                    plan = recovery
                    row["selected_source"] = "ACTUAL_RECOVERY"
            if self.committed:
                locked = {(c.operation_id, c.attempt) for c in self.committed}
                self.pending = self.committed + tuple(
                    c for c in self.pending if (c.operation_id, c.attempt) not in locked
                )
                self.pending_reasons.update(self.commitment_reasons)
            if (
                plan is None
                and not self.cancelled
                and not self.paused
                and perf_counter() < deadline
                and self.pending
            ):
                head = self.pending[0]
                if head.issued_sim_h > obs.sampled_h + 1e-10:
                    plan = self.wait(obs, "CACHED_FUTURE_START")
                else:
                    head = replace(
                        head,
                        # Actual dispatch identity belongs to the observation /
                        # decision, not to the wall-clock-dependent solve path.
                        # Candidate provenance stays in cache_sha256 and origin.
                        id=f"PLAN-{obs.state.revision}-{sequence}-{head.operation_id}",
                        issued_sim_h=obs.sampled_h,
                        expected_revision=obs.state.revision,
                    )
                    try:
                        self._admit(head, obs, rejected)
                        plan = m.Plan(
                            self.config.schema_version,
                            self.config.id,
                            obs.id,
                            (head,),
                            "CANDIDATE",
                            self.pending_reasons.get(
                                (head.operation_id, head.attempt), "S19:CACHE_CURRENT_HEAD"
                            ),
                            self.config.research,
                        )
                        row["selected_source"] = (
                            "VERIFIED_CACHE" if self.cache_hash is not None else "RULE_RETRY"
                        )
                    except (ContractError, ValueError, KeyError) as exc:
                        row["failures"].append("CACHE_INVALID:" + str(exc))
                        row["cache_invalidated"] = True
                        self.pending = self.committed
                        if self.committed:
                            plan = self.wait(obs, "COMMITMENT_BLOCKED:" + str(exc))
            if (
                plan is None
                and not self.cancelled
                and not self.paused
                and perf_counter() < deadline
            ):
                fallback_start = perf_counter()
                try:
                    plan = choose(
                        self.config,
                        replace(value, budget_ms=max(0.000001, (deadline - perf_counter()) * 1000)),
                        sequence=sequence,
                        excluded_operations=rejected,
                    )
                    if plan.status == "NO_PLAN_FOUND":
                        plan = self.wait(obs, plan.reason)
                    # These are actual chosen commands, not a verified future schedule.
                    self.pending = plan.commands
                    self.pending_reasons = {
                        (c.operation_id, c.attempt): plan.reason for c in plan.commands
                    }
                    row["selected_source"] = "RULE"
                    self.cache_origin = self.cache_hash = None
                except (ContractError, ValueError, KeyError, StopIteration) as exc:
                    row["failures"].append("RULE_ERROR:" + str(exc))
                    plan = self.wait(obs, "RULE_ERROR")
                row["fallback_seconds"] = perf_counter() - fallback_start
            if plan is None:
                plan = self.wait(obs, "CANCELLED" if self.cancelled else "DECISION_DEADLINE")
        if self.cancelled or self.paused:
            plan = self.wait(obs, "PAUSED" if self.paused else "CANCELLED")
        # Final current-state shield is mandatory, even for a verified cache.
        plan = self.guard(plan, obs)
        row.update(
            after=plan_rows(self.pending),
            cache_origin=self.cache_origin,
            cache_sha256=self.cache_hash,
            plan_reason=plan.reason,
            plan_operation=plan.commands[0].operation_id if plan.commands else None,
            decision_seconds=perf_counter() - began,
            commitments_after=plan_rows(self.committed),
            selected_proposal=next(
                (
                    r
                    for r in plan_rows(self.pending)
                    if plan.commands
                    and r["operation"] == plan.commands[0].operation_id
                    and r["attempt"] == plan.commands[0].attempt
                ),
                plan_rows(plan.commands)[0] if plan.commands else None,
            ),
        )
        row["change"] = plan_change(row["before"], row["after"])
        row["budget_exceeded"] = row["decision_seconds"] > self.limits.decision_seconds
        return plan

    @staticmethod
    def _promise(command):
        return (
            command.operation_id,
            command.attempt,
            command.mode_id,
            command.roles,
            command.service,
            command.branch,
        )

    def guard(self, plan, current):
        """Called again immediately before dispatch; stale candidates are never rebased here."""
        if version(current) != self._proposal_version:
            if self.journal:
                self.journal[-1]["stale_dispatch_rejected"] = True
            self.pending = ()
            return self.wait(current, "STALE_OBSERVATION")
        if self.paused or self.cancelled:
            return self.wait(current, "PAUSED" if self.paused else "CANCELLED")
        if plan.commands:
            try:
                require(len(plan.commands) == 1, "ONLINE_SINGLE_DISPATCH")
                validate(plan, config=self.config)
                require(plan.observation_id == current.id, "STALE_PLAN")
                self._admit(plan.commands[0], current, self._rejected)
            except (ContractError, ValueError, KeyError) as exc:
                self.pending = ()
                return self.wait(current, "DISPATCH_SHIELD:" + str(exc))
        if perf_counter() >= self._deadline:
            return self.wait(current, "DECISION_DEADLINE")
        return plan

    def next_tick(self, now_h):
        times = [self.end_h]
        # Once the declared search allowance is exhausted, ordinary execution
        # and external events drive rule fallback. Deadline WAIT still retries.
        if (
            self.calls < self.limits.max_search_calls
            and self.limits.search_seconds > 0
            or self.paused
            or self.cancelled
            or self.journal
            and "DEADLINE" in self.journal[-1].get("plan_reason", "")
        ):
            times.append(now_h + self.limits.period_h)
        times += [c.issued_sim_h for c in self.pending if c.issued_sim_h > now_h + 1e-10]
        return min(times)

    def end_cycle(self, plan, receipt):
        row = self.journal[-1]
        row.update(
            cycle_seconds=perf_counter() - self._active_start,
            dispatched=bool(plan.commands),
            receipt_kind=receipt.kind if receipt else None,
            receipt_id=receipt.id if receipt else None,
            final_reason=plan.reason,
        )
        row["cycle_budget_exceeded"] = row["cycle_seconds"] > self.limits.decision_seconds
        proposal = row.get("selected_proposal")
        row["actual_start"] = (
            dict(
                operation=receipt.command.operation_id,
                attempt=receipt.command.attempt,
                proposed_h=proposal["start_h"],
                actual_h=receipt.occurred_sim_h,
                delay_h=receipt.occurred_sim_h - proposal["start_h"],
            )
            if receipt is not None and receipt.kind == "STARTED" and proposal is not None
            else None
        )

    def report(self):
        return dict(
            declared=asdict(self.limits),
            used_calls=self.calls,
            decision_count=len(self.journal),
            decision_seconds=sum(r.get("decision_seconds", 0) for r in self.journal),
            search_seconds=sum(r["search_seconds"] for r in self.journal),
            validation_seconds=sum(r["verification_seconds"] for r in self.journal),
            budget_exceeded=sum(r.get("budget_exceeded", False) for r in self.journal),
            cycle_seconds=sum(r.get("cycle_seconds", 0) for r in self.journal),
            cycle_budget_exceeded=sum(r.get("cycle_budget_exceeded", False) for r in self.journal),
            deadline_kind="COOPERATIVE_MEASURED_NOT_HARD_REAL_TIME",
            commitment="FUTURE_CHOICES_AND_ACCEPTED_UNTIL_RELEASE_NO_SPECULATIVE_OWNERSHIP"
            if self.limits.future_commitment_h
            else "ACCEPTED_UNTIL_ACTUAL_RELEASE_NO_FUTURE_RESERVATIONS",
        )
