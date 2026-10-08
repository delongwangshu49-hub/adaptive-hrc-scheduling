"""Trusted conditional driver/journal; independent S12 audit stays unchanged.

The driver has the actual backend, including hidden events. The policy gets only
captured Feedback and actual intervals. The journal starts at time zero so prior
preparation and every subsequent action remain covered by the original auditor.
"""

from dataclasses import dataclass, replace

from adaptive_hrc_scheduling.algorithms.joint_lns import Action
from adaptive_hrc_scheduling.algorithms.joint_rolling import FrozenTailPolicy
from adaptive_hrc_scheduling.building_backend import Receipt
from adaptive_hrc_scheduling.checker import check_run
from adaptive_hrc_scheduling.contracts.codec import require
from adaptive_hrc_scheduling.control.light_loop import Decision, Turn, audit_decisions, capture
from adaptive_hrc_scheduling.domain import building as b


class Journal:
    """Trusted preparation helper, not an additional planner input channel."""

    def __init__(self, world):
        require(world.time == 0 and not world.snapshot.events, "JOURNAL_REQUIRES_PRISTINE_WORLD")
        self.world = world
        self.turns = []

    def __getattr__(self, name):
        return getattr(self.world, name)

    def act(
        self, action, reason, *, stop_on_feedback=False, triggers=("CONDITIONAL_FIXED_PROGRAM",)
    ):
        feedback = capture(self.world)
        o = feedback.observation
        sequence = len(self.turns) + 1
        kind = "STOP" if action is None else "WAIT" if action.kind == "ADVANCE" else action.kind
        commands = ()
        if action is not None and action.command:
            command = replace(action.command, id=f"S12-CMD-{sequence}")
            commands = (command,)
        decision = Decision(
            f"S12-D-{sequence}",
            o.id,
            o.state_revision,
            o.observed_h,
            triggers,
            kind,
            b.Plan(
                "C04-1.0",
                feedback.configuration.id,
                o.id,
                commands,
                tuple(b.Prediction(p.product_id, None) for p in o.products),
                "INCOMPLETE",
            ),
            people=action.people if action else (),
            until_h=action.until_h if action else None,
            reason=reason,
        )
        before = len(self.world.snapshot.events)
        if kind == "STOP":
            accepted, receipt = True, reason
        elif kind == "DISPATCH":
            result = self.world.dispatch(commands[0])
            accepted, receipt = result.accepted, result.reason
        elif kind == "REST":
            self.world.rest(action.people, action.until_h - self.world.time)
            accepted, receipt = True, "REST_COMMITTED"
        else:
            result = self.world.advance(action.until_h, stop_on_feedback=stop_on_feedback)
            accepted, receipt = result.accepted, result.reason
        turn = Turn(
            feedback,
            decision,
            accepted,
            receipt,
            tuple(e.id for e in self.world.snapshot.events[before:]),
            self.world.snapshot.revision,
            self.world.time,
            before,
            len(self.world.snapshot.events),
        )
        self.turns.append(turn)
        return Receipt(accepted, receipt)

    def dispatch(self, command):
        return self.act(Action("DISPATCH", command=command), "CONDITIONAL_PREPARATION")

    def rest(self, people, duration):
        return self.act(
            Action("REST", people=tuple(people), until_h=self.world.time + duration),
            "CONDITIONAL_PREPARATION_REST",
        )

    def advance(self, until, *, stop_on_feedback=False):
        return self.act(
            Action("ADVANCE", until_h=until),
            "CONDITIONAL_PREPARATION_WAIT",
            stop_on_feedback=stop_on_feedback,
        )


@dataclass(frozen=True)
class RollingResult:
    status: str
    reason: str
    proposal: object
    requests: tuple
    turns: tuple
    trace: object
    execution_audit: object
    decision_findings: tuple[str, ...]
    window_complete: bool
    actual_score: tuple[float, ...] | None


def run_frozen(journal, anchor, options, *, max_calls=1000):
    require(
        type(journal) is Journal and type(max_calls) is int and max_calls > 0,
        "ROLLING_DRIVER_BOUNDS",
    )
    require(
        capture(journal.world) == anchor.feedback
        and journal.world.s.intervals == anchor.world.s.intervals,
        "DRIVER_ANCHOR_MISMATCH",
    )
    policy = FrozenTailPolicy(anchor, options)
    requests = []
    reason = "CALL_BUDGET"
    done = False
    for _ in range(max_calls):
        request = policy.propose(
            capture(journal.world), journal.world.s.intervals, sequence=len(journal.turns) + 1
        )
        requests.append(request)
        receipt = journal.act(request.action, request.reason, stop_on_feedback=True)
        policy.confirm(request, accepted=receipt.accepted, after_h=journal.world.time)
        if request.action is None or not receipt.accepted:
            reason = request.reason if receipt.accepted else receipt.reason
            done = request.status == "DONE"
            break
    else:
        journal.act(None, reason)
    trace = journal.world.snapshot
    audit = check_run(journal.world.config, trace)
    findings = audit_decisions(journal.world.config, trace, tuple(journal.turns))
    complete = trace.time_h == anchor.end
    if (
        reason == "CALL_BUDGET"
        and complete
        and anchor._done(journal.world)
        and audit.status == "PASS"
        and not findings
    ):
        done = True
        reason = "CALL_BUDGET_EXIT_AFTER_COMPLETION"
    score = None
    if done and complete and audit.status == "PASS" and not findings:
        finish = max(
            e.time_h
            for e in trace.events
            if e.kind in ("COMPLETED", "ACTIVITY_COMPLETE") and e.entity_id in anchor.targets
        )
        score = (
            finish,
            sum(h.exposure for h in trace.people),
            max(h.exposure for h in trace.people),
        )
    status = "COMPLETED" if score is not None else "WINDOW_CENSORED"
    if audit.status != "PASS" or findings:
        status = "INVALID_TRACE"
    return RollingResult(
        status,
        reason,
        policy.proposal,
        tuple(requests),
        tuple(journal.turns),
        trace,
        audit,
        findings,
        complete,
        score,
    )
