"""S18 current-production boundary; joint mode execution stays fail-closed.

The fixed-domain no-update control exercises existing S15 interfaces without
adding HR qualification or changing any frozen production schema/executor.
"""

from dataclasses import dataclass, replace

from adaptive_hrc_scheduling.algorithms.joint_lns import admission
from adaptive_hrc_scheduling.algorithms.lns import Verification, fingerprint, search
from adaptive_hrc_scheduling.algorithms.production_lns import ProductionProblem
from adaptive_hrc_scheduling.contracts.codec import require


@dataclass(frozen=True)
class ProductionBoundary:
    status: str
    reasons: tuple[str, ...]
    observation_sha256: str
    protected_sha256: str
    candidate: object | None = None


def joint_production_boundary(problem):
    """Bind rejection to a fully audited actual prefix, without dispatch/search."""
    require(type(problem) is ProductionProblem, "AUDITED_PRODUCTION_PROBLEM_REQUIRED")
    gate = admission(problem.config)
    require(gate.status == "BLOCKED", "REVIEWED_PRODUCTION_MIGRATION_REQUIRED")
    state = problem.prefix.state
    return ProductionBoundary(
        "BLOCKED",
        gate.reasons,
        fingerprint(problem.value.observation),
        fingerprint(
            (state.running, state.reservations, state.owners, state.positions, state.supports)
        ),
    )


@dataclass(frozen=True)
class FrozenProductionDecision:
    status: str
    anchor_sha256: str
    current_sha256: str
    proposal: object
    candidate: object | None
    safety: Verification


class FrozenProductionPolicy:
    """Existing fixed S15 current-window proposal with no delivered updates.

    Search/cache/score consume the retained audited anchor alone. New fatigue,
    positions, supply, failure, quality, receipt and rejection information only
    enters the final independent execution/causal shield. No shield-driven retry.
    Not an HR-seq planner, full future schedule or production A comparison.
    """

    def __init__(self, anchor):
        require(type(anchor) is ProductionProblem, "AUDITED_PRODUCTION_ANCHOR_REQUIRED")
        self.anchor = ProductionProblem(
            anchor.config,
            anchor.value,
            anchor.prefix,
            decisions=anchor.decisions,
            sequence=anchor.sequence,
            rejected=anchor.rejected,
            rule=anchor.rule,
        )

    def decide(self, current, options):
        require(type(current) is ProductionProblem, "AUDITED_PRODUCTION_CURRENT_REQUIRED")
        anchor = self.anchor
        a, o = anchor.value.observation, current.value.observation
        require(
            anchor.config == current.config
            and (a.run_id, a.epoch, a.sampled_h) == (o.run_id, o.epoch, o.sampled_h)
            and anchor.value.budget_ms == current.value.budget_ms
            and anchor.rule == current.rule
            and anchor.sequence == current.sequence,
            "ABLATION_COMMON_PRODUCTION_DOMAIN_CONTROLS",
        )
        require(
            current.prefix.events[: len(anchor.prefix.events)] == anchor.prefix.events
            and current.prefix.state.intervals == anchor.prefix.state.intervals
            and current.decisions == anchor.decisions,
            "ANCHOR_ACTUAL_PRODUCTION_PREFIX_REQUIRED",
        )
        proposal = search(anchor, options)
        safety = Verification(False, None, ("NO_NOMINAL_PLAN",))
        candidate = None
        if proposal.best is not None:
            rebound = replace(
                proposal.best,
                observation_id=o.id,
                commands=tuple(
                    replace(
                        cmd,
                        id=cmd.id + "-FROZEN",
                        expected_revision=o.state.revision,
                    )
                    for cmd in proposal.best.commands
                ),
            )
            safety = current.verify(rebound)
            if safety.valid:
                candidate = rebound
        return FrozenProductionDecision(
            "SHIELDED" if candidate is not None else "WAIT",
            fingerprint(a),
            fingerprint(o),
            proposal,
            candidate,
            safety,
        )


def simulation_production_problem(
    config, value, prefix, *, decisions=(), end_h, fixed_mode=None, rejected=()
):
    """Explicit migrated entry; the legacy current-window adapter stays separate."""
    from adaptive_hrc_scheduling.algorithms.simulation_joint import SimulationJointProblem

    require(config.schema_version == "S18-PROD-2.0", "SIMULATION_PRODUCTION_VERSION_REQUIRED")
    return SimulationJointProblem(
        config,
        value.observation,
        prefix,
        decisions=decisions,
        end_h=end_h,
        fixed_mode=fixed_mode,
        rejected=rejected,
    )
