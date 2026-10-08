"""Conditional C04 receding-tail execution from delivered feedback only.

Every search checks a complete suffix to the original common window. Only its
first action is executed; actual feedback replaces predictions at the next call.
This is a mechanism driver, not S19 budget/fallback policy or S15 HR admission.
"""

from dataclasses import dataclass, replace

from adaptive_hrc_scheduling.algorithms.joint_lns import JointProblem, joint_search
from adaptive_hrc_scheduling.algorithms.lns import fingerprint
from adaptive_hrc_scheduling.checker import check_run
from adaptive_hrc_scheduling.contracts.codec import ContractError, require
from adaptive_hrc_scheduling.control.joint_rolling_loop import Journal
from adaptive_hrc_scheduling.control.light_loop import audit_decisions, capture


@dataclass(frozen=True)
class Replan:
    observation_sha256: str
    observed_h: float
    end_h: float
    proposal: object
    action: object


@dataclass(frozen=True)
class AdaptiveResult:
    status: str
    reason: str
    replans: tuple[Replan, ...]
    turns: tuple
    trace: object
    execution_audit: object
    decision_findings: tuple[str, ...]
    window_complete: bool
    actual_score: tuple[float, ...] | None


def run_adaptive(journal, anchor, options, *, max_calls=1000):
    """Execute one checked action per feedback under explicit per-call bounds.

    All calls use the same options and fixed-mode switch. Total search cost is
    recorded, not equated with the one-search frozen control. No legal suffix,
    negative receipt or exhausted call budget stops without fabricating recovery.
    """
    require(
        type(journal) is Journal
        and type(anchor) is JointProblem
        and type(max_calls) is int
        and max_calls > 0,
        "ADAPTIVE_DRIVER_BOUNDS",
    )
    options.validate()
    require(
        capture(journal.world) == anchor.feedback
        and journal.world.s.intervals == anchor.world.s.intervals,
        "DRIVER_ANCHOR_MISMATCH",
    )
    # Reconstruct instead of trusting mutable adapter attributes.
    root = JointProblem(
        anchor.feedback,
        anchor.world.s.intervals,
        anchor.targets,
        switches=anchor.switches,
        window_h=anchor.end - anchor.world.time,
        max_steps=anchor.max_steps,
        max_bindings=anchor.max_bindings,
    )
    end = root.end
    prefix = root.feedback.state.events
    intervals = root.world.s.intervals
    replans = []
    reason = "CALL_BUDGET"
    for _ in range(max_calls):
        feedback = capture(journal.world)
        now = feedback.observation.observed_h
        if now == end:
            reason = "ACTUAL_WINDOW_END"
            break
        try:
            require(root.world.time <= now < end, "CLOCK_OUTSIDE_WINDOW")
            require(feedback.configuration == root.feedback.configuration, "DOMAIN_CHANGED")
            require(
                feedback.state.events[: len(prefix)] == prefix
                and journal.world.s.intervals[: len(intervals)] == intervals,
                "ACTUAL_PREFIX_CHANGED",
            )
            current = JointProblem(
                feedback,
                journal.world.s.intervals,
                root.targets,
                switches=root.switches,
                window_h=end - now,
                max_steps=root.max_steps,
                max_bindings=root.max_bindings,
            )
            require(current.end == end, "COMMON_WINDOW_CHANGED")
            proposal = joint_search(current, options)
            action = None
            if proposal.best is not None:
                # Explicit final whole-suffix audit immediately before execution.
                report = current.verify(proposal.best)
                require(report.valid, "FINAL_SUFFIX_REJECTED:" + ";".join(report.reasons))
                require(proposal.best.actions, "EMPTY_SUFFIX")
                action = proposal.best.actions[0]
                if action.command:
                    action = replace(
                        action,
                        command=replace(
                            action.command,
                            id=f"S12-CMD-{len(journal.turns) + 1}",
                        ),
                    )
            replans.append(Replan(current.observation_hash, now, end, proposal, action))
            if action is None:
                reason = "NO_LEGAL_VISIBLE_SUFFIX"
                break
            prefix, intervals = feedback.state.events, journal.world.s.intervals
            receipt = journal.act(
                action,
                "CHECKED_VISIBLE_JOINT_SUFFIX",
                stop_on_feedback=True,
                triggers=("CONDITIONAL_ADAPTIVE_REPLAN", fingerprint(feedback)),
            )
            if not receipt.accepted:
                reason = "ACTUAL_RECEIPT_REJECTED:" + receipt.reason
                break
        except (ContractError, ValueError, TypeError, KeyError, AttributeError) as exc:
            reason = str(exc)
            break
    journal.act(None, reason, triggers=("CONDITIONAL_ADAPTIVE_STOP",))
    trace = journal.world.snapshot
    audit = check_run(journal.world.config, trace)
    findings = audit_decisions(journal.world.config, trace, tuple(journal.turns))
    complete = trace.time_h == end
    score = None
    if complete and root._done(journal.world) and audit.status == "PASS" and not findings:
        finish = max(
            e.time_h
            for e in trace.events
            if e.kind in ("COMPLETED", "ACTIVITY_COMPLETE") and e.entity_id in root.targets
        )
        score = (
            finish,
            sum(h.exposure for h in trace.people),
            max(h.exposure for h in trace.people),
        )
        if reason == "CALL_BUDGET":
            reason = "CALL_BUDGET_EXIT_AFTER_COMPLETION"
    status = "COMPLETED" if score is not None else "WINDOW_CENSORED"
    if audit.status != "PASS" or findings:
        status = "INVALID_TRACE"
    return AdaptiveResult(
        status,
        reason,
        tuple(replans),
        tuple(journal.turns),
        trace,
        audit,
        findings,
        complete,
        score,
    )
