"""Cross-tick execution of a sealed conditional C04 no-update proposal.

No search consumes subsequent feedback. Feedback only gates the next fixed
action, binds current receipt metadata and confirms actual clock/acceptance.
Current S15 HR research remains blocked; this is not its migration.
"""

import copy
from dataclasses import dataclass, replace

from adaptive_hrc_scheduling.algorithms.joint_lns import (
    Action,
    FrozenJointPolicy,
    JointProblem,
    joint_search,
)
from adaptive_hrc_scheduling.algorithms.lns import Verification, fingerprint
from adaptive_hrc_scheduling.checker import check_run
from adaptive_hrc_scheduling.contracts.codec import ContractError, require
from adaptive_hrc_scheduling.control.light_loop import Feedback


@dataclass(frozen=True)
class TimedAction:
    at_h: float
    action: Action


@dataclass(frozen=True)
class Request:
    sequence: int
    step: int
    plan_sha256: str
    observation_sha256: str
    observed_h: float
    status: str
    action: Action | None
    reason: str
    safety: Verification


class FrozenTailPolicy:
    """Fixed absolute-time actions, with no state-dependent repair or retry.

    An early feedback wake resumes the same ADVANCE deadline; it does not choose
    another action. A late clock, unsafe action or negative receipt latches STOP.
    Actual safety scores are never used to rank or change the sealed program.
    """

    def __init__(self, anchor, options):
        self.anchor = FrozenJointPolicy(anchor).anchor
        self.proposal = joint_search(self.anchor, options)
        world = copy.copy(self.anchor.world)
        steps = []
        if self.proposal.best is not None:
            for action in self.proposal.best.actions:
                steps.append(TimedAction(world.time, action))
                self.anchor._apply(world, action)
        self.steps = tuple(steps)
        self.plan_sha256 = fingerprint((self.anchor.observation_hash, options, self.steps))
        self._seal = fingerprint((self.steps, self.proposal.best))
        self.cursor = 0
        self.pending = None
        self.stopped = None
        self.last_sequence = 0

    def propose(self, feedback, intervals, *, sequence):
        require(self.pending is None, "ACTUAL_RECEIPT_REQUIRED_BEFORE_NEXT_REQUEST")
        require(type(sequence) is int and sequence > self.last_sequence, "REQUEST_SEQUENCE")
        require(type(feedback) is Feedback, "DELIVERED_FEEDBACK_REQUIRED")
        require(fingerprint((self.steps, self.proposal.best)) == self._seal, "SEALED_PLAN_CHANGED")
        o = feedback.observation
        current_hash = fingerprint((feedback, tuple(intervals)))

        def response(status, reason, action=None, valid=False):
            request = Request(
                sequence,
                self.cursor,
                self.plan_sha256,
                current_hash,
                o.observed_h,
                status,
                action,
                reason,
                Verification(valid, None, (reason,)),
            )
            self.pending = request
            return request

        if self.stopped:
            return response("STOP", self.stopped)
        try:
            require(
                feedback.configuration == self.anchor.feedback.configuration,
                "VISIBLE_DOMAIN_CHANGED",
            )
            n = len(self.anchor.feedback.state.events)
            require(
                feedback.state.events[:n] == self.anchor.feedback.state.events
                and tuple(intervals)[: len(self.anchor.world.s.intervals)]
                == self.anchor.world.s.intervals,
                "ANCHOR_ACTUAL_PREFIX_CHANGED",
            )
            require(
                self.anchor.world.time <= o.observed_h <= self.anchor.end, "CLOCK_OUTSIDE_WINDOW"
            )
            current = JointProblem(
                feedback,
                tuple(intervals),
                self.anchor.targets,
                switches=self.anchor.switches,
                window_h=max(1e-6, self.anchor.end - o.observed_h),
                max_steps=self.anchor.max_steps,
                max_bindings=self.anchor.max_bindings,
            )
            if self.proposal.best is None:
                return response("STOP", "NO_NOMINAL_TAIL")
            if self.cursor == len(self.steps):
                require(
                    current._done(current.world) and o.observed_h == self.anchor.end,
                    "ACTUAL_TAIL_NOT_COMPLETE",
                )
                return response("DONE", "FIXED_PROGRAM_COMPLETED", valid=True)
            timed = self.steps[self.cursor]
            action = timed.action
            if action.kind == "ADVANCE":
                require(timed.at_h <= o.observed_h < action.until_h, "FIXED_ADVANCE_CLOCK")
            else:
                require(o.observed_h == timed.at_h, "FIXED_START_CLOCK_MISSED")
            if action.command:
                action = replace(
                    action,
                    command=replace(
                        action.command,
                        id=f"S12-CMD-{sequence}",
                        expected_revision=o.state_revision,
                    ),
                )
            world = copy.copy(current.world)
            current._apply(world, action)
            report = check_run(feedback.configuration, world.snapshot)
            require(
                report.status == "PASS",
                "S10_NEXT_ACTION:" + ";".join(f.code for f in report.findings),
            )
            return response("CANDIDATE", "FIXED_NEXT_ACTION_CHECKED", action, valid=True)
        except (ContractError, ValueError, TypeError, KeyError, AttributeError) as exc:
            self.stopped = str(exc)
            return response("STOP", self.stopped)

    def confirm(self, request, *, accepted, after_h):
        require(request == self.pending and request is not None, "UNBOUND_OR_DUPLICATE_RECEIPT")
        require(type(accepted) is bool, "ACTUAL_ACCEPTANCE_REQUIRED")
        require(request.observed_h <= after_h <= self.anchor.end, "ACTUAL_RETURN_CLOCK")
        if request.action is None:
            require(after_h == request.observed_h, "STOP_CANNOT_ADVANCE_CLOCK")
        elif request.action.kind == "ADVANCE":
            require(after_h <= request.action.until_h, "ADVANCE_OVERSHOOT")
            require(after_h > request.observed_h or not accepted, "ADVANCE_DID_NOT_PROGRESS")
        else:
            require(after_h == request.observed_h, "DISPATCH_OR_REST_CHANGED_CLOCK")
        self.pending = None
        self.last_sequence = request.sequence
        if not accepted:
            self.stopped = "ACTUAL_RECEIPT_REJECTED"
        elif request.action:
            if request.action.kind != "ADVANCE" or after_h == request.action.until_h:
                self.cursor += 1
