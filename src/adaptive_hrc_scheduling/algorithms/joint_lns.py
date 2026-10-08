"""S18 conditional C04 joint branches; current S15 research admission is closed.

This module never changes qualification, execution facts, times or load rates.
The bounded branch adapter accepts only delivered Feedback and actual intervals.
It has no future scenario, quality oracle or external receipt forecast.
"""

import copy
import math
from dataclasses import dataclass, replace
from time import perf_counter

from adaptive_hrc_scheduling.algorithms.lns import Repair, Verification, fingerprint, search
from adaptive_hrc_scheduling.building_human import calendar_state
from adaptive_hrc_scheduling.checker import check_run
from adaptive_hrc_scheduling.contracts.building import evidence_pass, validate
from adaptive_hrc_scheduling.contracts.codec import ContractError, require
from adaptive_hrc_scheduling.control.light_loop import Feedback, _view, capture
from adaptive_hrc_scheduling.domain import building as b
from adaptive_hrc_scheduling.domain import production as p
from adaptive_hrc_scheduling.planning.decoder import legal_candidates

G2 = (
    "G2-JOINT",
    "G2-WPS",
    "G2-PROGRAM",
    "G2-FIXTURE",
    "G2-PEOPLE",
    "G2-ISOLATION",
    "G2-INSPECTION",
    "G2-OUTPUT",
)


@dataclass(frozen=True)
class Admission:
    status: str
    reasons: tuple[str, ...]
    references: tuple[tuple[str, str, str, str], ...] = ()


def admission(config):
    """Fail closed: an Industrial PASS label alone is not a scoped G2 dossier.

    Conditional C04 fixtures can test branches. S15 lacks an HR-seq mapping;
    real research requires separately reviewed scope/evidence and contract work.
    """
    if type(config) is p.Configuration and config.schema_version == "S18-PROD-2.0":
        from adaptive_hrc_scheduling.contracts.production import validate as validate_production

        try:
            validate_production(config)
        except ContractError as exc:
            return Admission("BLOCKED", ("INVALID_SIMULATION_ADMISSION", str(exc)))
        return Admission(
            "APPROVED_ASSUMPTION_SET",
            (),
            tuple(
                (
                    s.activity_id,
                    s.process_revision,
                    "SIMULATION_ASSUMPTION",
                    config.research.assumption_sha256,
                )
                for s in config.research.scope_bindings
            ),
        )
    if type(config) is p.Configuration:
        return Admission("BLOCKED", ("G2_OPEN_HR_DISABLED", "S15_HR_SEQUENCE_MAPPING_ABSENT"))
    if type(config) is not b.Configuration:
        return Admission("BLOCKED", ("UNSUPPORTED_JOINT_DOMAIN",))
    try:
        validate(config)
    except (ContractError, ValueError, TypeError, AttributeError) as exc:
        return Admission("BLOCKED", ("INVALID_QUALIFICATION_INPUT", str(exc)))
    evidence = {e.id: e for e in config.evidence}
    refs = tuple(
        (i, evidence[i].revision, evidence[i].basis, evidence[i].reference)
        for i in G2
        if i in evidence
    )
    reasons = []
    if not evidence_pass(config, G2):
        reasons.append("G2_OPEN")
    for activity in config.activities:
        if activity.code not in ("W-B", "W-T"):
            continue
        modes = {m.kind: m for m in activity.modes}
        if set(modes) != {"H", "HR-seq"}:
            reasons.append("COMMON_OUTPUT_MODES_ABSENT:" + activity.id)
            continue
        if len({m.output_revision for m in modes.values()}) != 1:
            reasons.append("COMMON_OUTPUT_REVISION:" + activity.id)
        if any(
            not m.enabled or not evidence_pass(config, m.qualification_ids) for m in modes.values()
        ):
            reasons.append("MODE_DISABLED_OR_UNQUALIFIED:" + activity.id)
    if config.purpose != "SYNTHETIC_TEST_ONLY":
        reasons.append("REVIEWED_PRODUCT_JOINT_DOSSIER_REQUIRED")
    if any(evidence[i].basis != "SYNTHETIC_TEST" for i in G2 if i in evidence):
        reasons.append("CONDITIONAL_FIXTURE_REQUIRED")
    return Admission("BLOCKED" if reasons else "CONDITIONAL_BRANCH_ONLY", tuple(reasons), refs)


@dataclass(frozen=True)
class Switches:
    fixed_modes: tuple[tuple[str, str], ...] = ()
    state_ranking: bool = True


@dataclass(frozen=True)
class Action:
    kind: str
    command: b.DispatchCommand | None = None
    people: tuple[str, ...] = ()
    until_h: float | None = None


@dataclass(frozen=True)
class Candidate:
    observation_sha256: str
    actions: tuple[Action, ...]


class JointProblem:
    """Finite visible work-package tail in the legacy C04 conditional domain.

    Completion of explicit targets is required, not full-module readiness.
    Repair destroys only proposed suffixes; actual prefix and prepared/active
    modes/crews are immutable. The S10 audit independently replays the whole
    observed prefix plus hypothetical suffix over the same comparison window.
    """

    def __init__(
        self,
        feedback,
        intervals,
        targets,
        *,
        switches=Switches(),
        window_h=8.0,
        max_steps=120,
        max_bindings=10000,
    ):
        require(type(feedback) is Feedback, "DELIVERED_FEEDBACK_REQUIRED")
        gate = admission(feedback.configuration)
        require(gate.status == "CONDITIONAL_BRANCH_ONLY", ";".join(gate.reasons))
        require(
            type(switches) is Switches and type(switches.state_ranking) is bool, "INVALID_SWITCHES"
        )
        require(
            type(window_h) in (int, float)
            and math.isfinite(window_h)
            and window_h > 0
            and type(max_steps) is int
            and max_steps > 0
            and type(max_bindings) is int
            and max_bindings > 0,
            "INVALID_BOUNDS",
        )
        c, o = feedback.configuration, feedback.observation
        validate(o, config=c)
        require(o.sampled_h == o.received_h == o.observed_h, "FRESH_OBSERVATION_REQUIRED")
        world = _view(feedback)
        world.s = replace(world.s, intervals=tuple(intervals))
        require(
            tuple(e.id for e in feedback.state.events) == o.event_ids
            and all(e.time_h <= o.observed_h for e in feedback.state.events)
            and all(i.end_h <= o.observed_h for i in intervals),
            "CURRENT_PREFIX_REQUIRED",
        )
        require(world.observe()[0] == o, "OBSERVATION_STATE_MISMATCH")
        if o.observed_h > 0:
            report = check_run(c, world.snapshot)
            require(
                report.status == "PASS",
                "INVALID_S10_PREFIX:" + ";".join(f.code for f in report.findings),
            )
        else:
            from adaptive_hrc_scheduling.building_backend import BuildingBackend

            require(
                feedback == capture(BuildingBackend(c)) and not intervals, "PRISTINE_T0_REQUIRED"
            )
        require(
            type(targets) is tuple
            and targets
            and len(set(targets)) == len(targets)
            and set(targets) <= world.activities.keys(),
            "EXPLICIT_TARGETS_REQUIRED",
        )
        scope = set(targets)
        while True:
            more = {e.source for e in c.edges if e.target in scope} - scope
            if not more:
                break
            scope |= more
        fixed = dict(switches.fixed_modes)
        require(len(fixed) == len(switches.fixed_modes), "DUPLICATE_FIXED_MODE")
        if fixed:
            require(set(fixed) == scope, "FIXED_MODE_COVERAGE")
            require(
                all(fixed[a] in {m.id for m in world.activities[a].modes} for a in scope),
                "UNKNOWN_FIXED_MODE",
            )
        for attempt in feedback.state.attempts:
            if attempt.activity_id in fixed:
                require(fixed[attempt.activity_id] == attempt.mode_id, "FIXED_COMMITMENT_CHANGED")
        self.feedback, self.world, self.targets, self.scope = feedback, world, targets, scope
        self.switches, self.fixed = switches, fixed
        self.end = o.observed_h + window_h
        self.max_steps, self.max_bindings = max_steps, max_bindings
        self.observation_hash = fingerprint((feedback, tuple(intervals)))

    def _done(self, world):
        done = {a.activity_id for a in world.s.attempts if a.state == "COMPLETED"}
        return set(self.targets) <= done

    def _apply(self, world, action):
        require(type(action) is Action, "ACTION_SHAPE")
        if action.kind == "DISPATCH":
            cmd = action.command
            require(
                not action.people and action.until_h is None and cmd is not None, "DISPATCH_SHAPE"
            )
            require(cmd.activity_id in self.scope, "OUTSIDE_VISIBLE_TARGET_CLOSURE")
            require(
                not self.fixed or self.fixed[cmd.activity_id] == cmd.mode_id, "FIXED_MODE_CHANGED"
            )
            require(
                cmd.issued_h == world.time and cmd.expected_revision == world.s.revision,
                "STALE_PROPOSED_COMMAND",
            )
            receipt = world.dispatch(cmd)
            require(receipt.accepted, receipt.reason)
        elif action.kind == "REST":
            require(
                action.command is None
                and action.people
                and action.until_h is not None
                and world.time < action.until_h <= self.end,
                "REST_SHAPE",
            )
            world.rest(action.people, action.until_h - world.time)
        elif action.kind == "ADVANCE":
            require(
                action.command is None
                and not action.people
                and action.until_h is not None
                and world.time < action.until_h <= self.end,
                "ADVANCE_SHAPE",
            )
            receipt = world.advance(action.until_h)
            require(receipt.accepted, receipt.reason)
        else:
            raise ValueError("UNKNOWN_ACTION")

    def _menu(self, world):
        candidates, waits, exhausted = legal_candidates(world, max_bindings=self.max_bindings)
        require(not exhausted, "BINDING_BUDGET_EXHAUSTED")
        candidates = [
            x
            for x in candidates
            if x.command.activity_id in self.scope
            and (not self.fixed or self.fixed[x.command.activity_id] == x.command.mode_id)
        ]

        def rank(x):
            estimate = x.estimated_remaining_h
            if not self.switches.state_ranking:
                mode = next(
                    m
                    for m in world.activities[x.command.activity_id].modes
                    if m.id == x.command.mode_id
                )
                estimate = sum(u.base_h for u in mode.units[x.command.unit_index :])
            return (
                estimate,
                x.command.activity_id,
                x.command.mode_id,
                tuple((r.role_id, r.person_id) for r in x.command.roles),
            )

        candidates.sort(key=rank)
        menu = [
            Action("DISPATCH", replace(x.command, id=f"S18-CMD-{len(world.s.events) + 1}"))
            for x in candidates
        ]
        busy = {x.resource_id for x in world.s.locks}
        relevant = {
            r.qualification
            for a in self.scope
            for m in world.activities[a].modes
            for u in m.units
            for r in u.roles
        }
        idle = tuple(
            sorted(
                h.person_id
                for h in world.s.people
                if h.person_id not in busy
                and h.rest_until_h <= world.time
                and h.fatigue > 0
                and relevant.intersection(world.people[h.person_id].qualifications)
            )
        )
        if world.time + world.config.min_rest_h <= self.end:
            menu.extend(
                Action("REST", people=(pid,), until_h=world.time + world.config.min_rest_h)
                for pid in idle
            )
        bounds = [r.end_h for r in world.s.running + world.s.services if r.end_h > world.time]
        bounds += [h.rest_until_h for h in world.s.people if h.rest_until_h > world.time]
        bounds += [calendar_state(p, world.time)[1] for p in world.config.people]
        bounds += [world.time + world.config.min_rest_h, self.end]
        menu.append(Action("ADVANCE", until_h=min(t for t in bounds if t > world.time)))
        return menu, waits

    def _rollout(self, prefix, rng, deadline):
        world = copy.copy(self.world)
        actions = list(prefix)
        for action in prefix:
            self._apply(world, action)
        reasons = set()
        while not self._done(world) and len(actions) < self.max_steps and world.time < self.end:
            if perf_counter() >= deadline:
                return Repair(None, reasons=("WALL_BUDGET",), termination="WALL_BUDGET")
            menu, waits = self._menu(world)
            reasons.update(w.reason for w in waits if w.activity_id in self.scope)
            # Deterministic initial takes the ranked dispatch; stochastic suffixes
            # also propose actual rest and delayed starts without altering facts.
            action = menu[0] if rng is None else rng.choice(menu)
            if rng is None and action.kind == "REST":
                tired = {p for w in waits if w.reason == "FATIGUE_PROTECTION" for p in w.blockers}
                action = next(
                    (x for x in menu if x.kind == "REST" and set(x.people) <= tired), menu[-1]
                )
            self._apply(world, action)
            actions.append(action)
        if not self._done(world):
            return Repair(
                None,
                reasons=tuple(sorted(reasons | {"VISIBLE_TAIL_NOT_COMPLETED"})),
                termination="BOUNDED_NO_PLAN",
            )
        if world.time < self.end:
            actions.append(Action("ADVANCE", until_h=self.end))
        return Repair(
            Candidate(self.observation_hash, tuple(actions)), reasons=("CONDITIONAL_BRANCH_ONLY",)
        )

    def initial(self, deadline):
        try:
            return self._rollout((), None, deadline)
        except (ContractError, ValueError, TypeError, KeyError, AttributeError) as exc:
            return Repair(None, reasons=(str(exc),), termination="INITIAL_FAILED")

    def mutable(self, candidate):
        return tuple(f"STEP:{i}" for i in range(len(candidate.actions)))

    def repair(self, candidate, removed, rng, trials, deadline):
        cut = min(int(i.split(":")[1]) for i in removed)
        best, score, reasons = None, None, set()
        tried = 0
        branch_world = copy.copy(self.world)
        for action in candidate.actions[:cut]:
            self._apply(branch_world, action)
        branches, _ = self._menu(branch_world)
        while tried < trials and perf_counter() < deadline:
            tried += 1
            try:
                # Try each next branch before random suffixes. This includes mode,
                # crew, real rest and delay alternatives under identical trial caps.
                if tried <= len(branches):
                    prefix = candidate.actions[:cut] + (branches[tried - 1],)
                    proposal = self._rollout(prefix, None, deadline)
                else:
                    proposal = self._rollout(candidate.actions[:cut], rng, deadline)
                reasons.update(proposal.reasons)
                if proposal.candidate is not None:
                    report = self.verify(proposal.candidate)
                    reasons.update(report.reasons)
                    if report.valid and (score is None or report.score < score):
                        best, score = proposal.candidate, report.score
            except (ContractError, ValueError, TypeError, KeyError, AttributeError) as exc:
                reasons.add(str(exc))
        return Repair(
            best,
            tried,
            tuple(sorted(reasons)),
            "WALL_BUDGET" if perf_counter() >= deadline else "REPAIR_TRIAL_BUDGET",
        )

    def preview(self, candidate):
        require(
            type(candidate) is Candidate
            and candidate.observation_sha256 == self.observation_hash
            and type(candidate.actions) is tuple
            and len(candidate.actions) <= self.max_steps + 1,
            "CANDIDATE_BINDING_OR_BUDGET",
        )
        world = copy.copy(self.world)
        for action in candidate.actions:
            self._apply(world, action)
        require(self._done(world), "VISIBLE_TAIL_NOT_COMPLETED")
        require(world.time == self.end, "COMMON_WINDOW_REQUIRED")
        return world.snapshot

    def verify(self, candidate):
        try:
            trace = self.preview(candidate)
            report = check_run(self.feedback.configuration, trace)
            require(report.status == "PASS", "S10:" + ";".join(f.code for f in report.findings))
            finish = max(
                e.time_h
                for e in trace.events
                if e.kind in ("COMPLETED", "ACTIVITY_COMPLETE") and e.entity_id in self.targets
            )
            # Removing state information affects ranking only; safety and the
            # actual independent audit always consume the full delivered state.
            score = (
                finish,
                sum(h.exposure for h in trace.people),
                max(h.exposure for h in trace.people),
            )
            if not self.switches.state_ranking:
                score = (round(finish, 9), 0.0, 0.0)
            return Verification(
                True, tuple(round(x, 9) for x in score), ("CONDITIONAL_C04_BRANCH_ONLY",)
            )
        except (ContractError, ValueError, TypeError, KeyError, AttributeError) as exc:
            return Verification(False, None, (str(exc),))


def joint_search(problem, options):
    """Run S17's budget/cache machinery on an independently checked joint tail."""
    require(type(problem) is JointProblem, "CONDITIONAL_JOINT_PROBLEM_REQUIRED")
    return search(problem, options)


@dataclass(frozen=True)
class FrozenDecision:
    """No-update proposal and separate current-state safety result.

    ``proposal`` contains only anchor-world scores/cache/history. Actual scores
    never enter that search. A failed shield returns WAIT without a new search.
    This is a conditional open-loop ablation, not a production qualification.
    """

    status: str
    anchor_sha256: str
    current_sha256: str
    proposal: object
    candidate: Candidate | None
    safety: Verification


class FrozenJointPolicy:
    """Freeze *all* delivered information at an explicitly retained anchor.

    Known initial facts, immutable configuration and future endogenous simulation
    remain available. New fatigue, failures, material/quality, occupancies, crews,
    preparation and event feedback cannot enter ranking, repair or nominal cache.
    The current world is used only after selection to reject unsafe execution.
    """

    def __init__(self, anchor):
        require(type(anchor) is JointProblem, "CONDITIONAL_ANCHOR_REQUIRED")
        self.anchor = JointProblem(
            anchor.feedback,
            anchor.world.s.intervals,
            anchor.targets,
            switches=anchor.switches,
            window_h=anchor.end - anchor.world.time,
            max_steps=anchor.max_steps,
            max_bindings=anchor.max_bindings,
        )

    def decide(self, current, options):
        require(type(current) is JointProblem, "CONDITIONAL_CURRENT_REQUIRED")
        anchor = self.anchor
        require(
            current.feedback.configuration == anchor.feedback.configuration
            and current.targets == anchor.targets
            and current.switches == anchor.switches
            and current.end == anchor.end
            and current.world.time == anchor.world.time
            and current.max_steps == anchor.max_steps
            and current.max_bindings == anchor.max_bindings,
            "ABLATION_COMMON_DOMAIN_WINDOW_CONTROLS",
        )
        n = len(anchor.feedback.state.events)
        require(
            current.feedback.state.events[:n] == anchor.feedback.state.events
            and current.world.s.intervals == anchor.world.s.intervals,
            "ANCHOR_ACTUAL_PREFIX_REQUIRED",
        )
        # Search only the retained anchor. No current-state admission, score,
        # rejection or timing is fed back into this search or its final cache.
        proposal = joint_search(anchor, options)
        safety = Verification(False, None, ("NO_NOMINAL_TAIL",))
        candidate = None
        if proposal.best is not None:
            try:
                world = copy.copy(current.world)
                actions = []
                for action in proposal.best.actions:
                    if action.command:
                        # Rebind receipt identity only. Times, modes, crew and
                        # order remain the frozen proposal; no adaptive repair.
                        action = replace(
                            action,
                            command=replace(
                                action.command,
                                id=f"S18-FROZEN-{len(world.s.events) + 1}",
                                expected_revision=world.s.revision,
                            ),
                        )
                    current._apply(world, action)
                    actions.append(action)
                rebound = Candidate(current.observation_hash, tuple(actions))
                safety = current.verify(rebound)
                if safety.valid:
                    candidate = rebound
            except (ContractError, ValueError, TypeError, KeyError, AttributeError) as exc:
                safety = Verification(False, None, (str(exc),))
        return FrozenDecision(
            "FEASIBLE" if candidate else "WAIT",
            anchor.observation_hash,
            current.observation_hash,
            proposal,
            candidate,
            safety,
        )
