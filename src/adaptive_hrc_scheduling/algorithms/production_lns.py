"""S17 current-window production repair, using only the delivered event prefix.

The candidate is one next dispatch or a WAIT, not a fabricated full-factory
schedule. Preview starts are isolated and independently audited. Subsequent
external arrivals/quality/receipt permissions are never forecast as facts.
"""

from copy import deepcopy
from dataclasses import replace
from time import perf_counter
from types import SimpleNamespace

from adaptive_hrc_scheduling.algorithms.lns import Repair, Verification
from adaptive_hrc_scheduling.contracts.codec import ContractError, require
from adaptive_hrc_scheduling.contracts.production import digest, validate
from adaptive_hrc_scheduling.control.production_decisions import check_decisions, record
from adaptive_hrc_scheduling.domain import production as m
from adaptive_hrc_scheduling.planning.production import choose
from adaptive_hrc_scheduling.production_backend import ProductionBackend
from adaptive_hrc_scheduling.production_checker import check_run


def parent(plan):
    if not plan.commands:
        return None
    return (
        plan.reason.removeprefix("PREPARE:")
        if plan.reason.startswith("PREPARE:")
        else plan.commands[0].operation_id
    )


class ProductionProblem:
    def __init__(self, config, value, prefix, *, decisions=(), sequence=0, rejected=(), rule="EDD"):
        validate(value, config=config)
        obs = value.observation
        require(
            (prefix.config_id, prefix.config_sha256, prefix.run_id, prefix.epoch)
            == (config.id, digest(config), obs.run_id, obs.epoch)
            and replace(prefix.state, intervals=()) == obs.state
            and tuple(e.id for e in prefix.events) == obs.event_ids
            and obs.sampled_h == obs.received_h == obs.state.time_h,
            "CURRENT_DELIVERED_PREFIX_REQUIRED",
        )
        decisions = deepcopy(tuple(decisions))
        require(check_run(config, prefix).status == "PASS", "INVALID_S10_PREFIX")
        # S15 audits a closed history. Append a validation-only terminal WAIT at
        # this delivered observation to close the prefix; it is not an executed
        # decision or a forecast fact, and is never added to the caller's ledger.
        terminal = self._terminal(obs)
        require(
            check_decisions(config, prefix, decisions + (record(terminal),)).status == "PASS",
            "INVALID_DECISION_PREFIX",
        )
        self.config, self.value, self.prefix = config, value, prefix
        self.decisions = tuple(decisions)
        self.sequence, self.rejected, self.rule = sequence, tuple(sorted(rejected)), rule
        self.held = {r.command.operation_id for r in obs.state.running}

    @staticmethod
    def _terminal(obs):
        return SimpleNamespace(
            observation=obs,
            plan=m.Plan("S15-PROD-1.0", obs.config_id, obs.id, (), "WAIT", "S17_AUDIT_PREFIX"),
            rejected_parents=(),
            receipt_id=None,
        )

    def _world(self):
        obs = self.value.observation
        world = ProductionBackend(self.config, run_id=obs.run_id, epoch=obs.epoch)
        world.s, world.events = self.prefix.state, list(self.prefix.events)
        for event in self.prefix.events:
            command = event.command
            if command:
                if command.service:
                    world.operations[command.operation_id] = command.service.operation
                    if command.service.route:
                        world.routes[command.service.route.id] = command.service.route
                if event.kind in ("STARTED", "REJECTED", "DEFERRED"):
                    world.commands[command.id] = (digest(command), event)
            if event.world:
                world.world_ids[event.world.id] = digest(event.world)
        return world

    def _choose(self, excluded, deadline):
        # Banning a pending parent changes search order only. It neither changes
        # the config nor declares that the execution backend rejected that parent.
        excluded = set(excluded) - self.held
        budget = min(self.value.budget_ms, max(0.001, (deadline - perf_counter()) * 1000))
        value = replace(
            self.value,
            budget_ms=budget,
            operations=tuple(o for o in self.value.operations if o.id not in excluded),
        )
        return choose(
            self.config,
            value,
            rule=self.rule,
            sequence=self.sequence,
            excluded_operations=tuple(sorted(excluded)),
        )

    def initial(self, deadline):
        # Even a zero search budget retains a normally budgeted, audited baseline.
        plan = choose(
            self.config,
            replace(
                self.value,
                operations=tuple(o for o in self.value.operations if o.id not in self.rejected),
            ),
            rule=self.rule,
            sequence=self.sequence,
            excluded_operations=self.rejected,
        )
        return Repair(plan, 1, (plan.reason,))

    def mutable(self, candidate):
        ident = parent(candidate)
        return () if ident is None or ident in self.held else ("NEXT_DISPATCH",)

    def verify(self, candidate):
        try:
            validate(candidate, config=self.config)
            obs = self.value.observation
            require(
                candidate.observation_id == obs.id and len(candidate.commands) <= 1,
                "PLAN_OBSERVATION_OR_CARDINALITY",
            )
            world = self._world()
            receipt = None
            score = (2, obs.sampled_h)
            if candidate.commands:
                cmd = candidate.commands[0]
                require(candidate.status == "CANDIDATE", "PLAN_STATUS")
                require(
                    cmd.operation_id not in self.rejected
                    and parent(candidate) not in self.rejected,
                    "REJECTED_PARENT",
                )
                held = next(
                    (r for r in obs.state.running if r.command.operation_id == cmd.operation_id),
                    None,
                )
                if held:
                    require(
                        cmd.resume_of == held.command.id and cmd.roles == held.command.roles,
                        "EXECUTION_COMMITMENT_CHANGED",
                    )
                receipt = world.dispatch(cmd)
                require(receipt.kind == "STARTED", "PREVIEW:" + receipt.reason)
                running = next(r for r in world.s.running if r.command.id == cmd.id)
                # Lexicographic current-window objective: production before
                # preparation, then estimated finish. No delivery-optimal claim.
                score = (1 if cmd.service else 0, running.earliest_end_h)
            else:
                require(candidate.status == "WAIT", "NO_PLAN_FOUND_IS_NOT_LEGAL_WAIT")
            preview = world.snapshot()
            audit = check_run(self.config, preview)
            require(
                audit.status == "PASS", "S10_PREVIEW:" + ";".join(f.reason for f in audit.findings)
            )
            decision = SimpleNamespace(
                observation=obs,
                plan=candidate,
                rejected_parents=self.rejected,
                receipt_id=receipt.id if receipt else None,
            )
            rows = self.decisions + (record(decision),)
            if receipt:
                rows += (record(self._terminal(world.observe())),)
            causal = check_decisions(self.config, preview, rows)
            require(
                causal.status == "PASS",
                "DECISION_PREVIEW:" + ";".join(f.reason for f in causal.findings),
            )
            return Verification(True, score)
        except (
            ContractError,
            ValueError,
            TypeError,
            KeyError,
            AttributeError,
            StopIteration,
        ) as exc:
            return Verification(False, None, (str(exc),))

    def repair(self, candidate, removed, rng, trials, deadline):
        require(removed == ("NEXT_DISPATCH",), "UNKNOWN_NEIGHBORHOOD")
        best, best_score, reasons = None, None, set()
        excluded = set(self.rejected)
        # Destroy the incumbent's pending priority first; do not destroy a
        # running command, its owner, material reservation, or transport motion.
        excluded.add(parent(candidate))
        tried = 0
        termination = "REPAIR_TRIAL_BUDGET"
        while tried < trials:
            if perf_counter() >= deadline:
                termination = "WALL_BUDGET"
                break
            proposed = self._choose(excluded, deadline)
            tried += 1
            checked = self.verify(proposed)
            reasons.add(proposed.reason)
            if checked.valid and (best_score is None or checked.score < best_score):
                best, best_score = proposed, checked.score
            elif not checked.valid:
                reasons.update(checked.reasons)
            ident = parent(proposed)
            if ident is None or ident in excluded or ident in self.held:
                termination = "NEIGHBORHOOD_EXHAUSTED"
                break
            excluded.add(ident)
        return Repair(best, tried, tuple(sorted(reasons)), termination)
