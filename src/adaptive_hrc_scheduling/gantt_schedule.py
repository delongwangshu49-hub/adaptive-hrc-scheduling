"""Versioned, independently replayable display forecasts; no dispatch authority."""

import json
import os
from copy import deepcopy

from .contracts.codec import as_data, decode, require
from .contracts.session import digest
from .domain import production as m

FORMAT = "P051-SCHEDULE-1"


def capture(problem, candidate):
    """Reuse the exact audited best preview, never run a second producer search."""
    checked = getattr(problem, "best_verified_display", None)
    require(checked is not None and checked[0] == candidate, "GANTT_AUDITED_PREVIEW_REQUIRED")
    history = problem.catalog
    return dict(
        format=FORMAT,
        candidate=as_data(candidate),
        configuration=as_data(problem.config),
        observation=as_data(problem.observation),
        prefix=as_data(problem.prefix),
        decisions=deepcopy(problem.decisions),
        rejected=list(problem.rejected),
        committed=[dict(command=as_data(c), reason=r) for c, r in problem.committed],
        fixed_mode=problem.fixed_mode,
        catalog_initial=as_data(history.initial) if history else None,
        catalog_generations=deepcopy(history.generations) if history else [],
        active_products=sorted(history.active_products) if history else [],
        snapshot=as_data(checked[1]),
        scope="HYPOTHETICAL_SUFFIX_NOT_ACTUAL_EXECUTION",
    )


def publish(session):
    """Immutable artifact once per candidate; small current pointer per packet."""
    from .algorithms.lns import fingerprint

    known = getattr(session, "_gantt_exports", {})
    for problem, candidate in session.policy.candidates:
        key = fingerprint(candidate)
        if key in known:
            continue
        data = capture(problem, candidate)
        checksum = digest(data)
        folder = session.output / "gantt-schedules"
        folder.mkdir(exist_ok=True)
        # Candidate fingerprint distinguishes 2 from 2.0. The old Session
        # canonical writer intentionally normalizes them; use an exact JSON
        # sidecar without changing the historical wire format.
        target = folder / (checksum + ".json")
        temporary = target.with_suffix(".tmp")
        with temporary.open("w", encoding="utf-8") as stream:
            json.dump(
                data,
                stream,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(target)
        known[key] = dict(
            candidate_sha256=key,
            artifact_sha256=checksum,
            observation_id=problem.observation.id,
            event_count=len(problem.prefix.events),
            event_prefix_sha256=digest(as_data(problem.prefix.events)),
            start_h=problem.observation.sampled_h,
            end_h=candidate.end_h,
            config_sha256=digest(as_data(problem.config)),
        )
    session._gantt_exports = known
    return dict(
        format=FORMAT,
        candidates=list(known.values()),
        active_candidate=session.policy.cache_hash,
        pending_commands=[as_data(c) for c in session.policy.pending],
        committed_commands=[as_data(c) for c in session.policy.committed],
    )


def verify(data, reference, *, initial, generations, events):
    """Rebuild from delivered prefix, then independently audit execution/causality."""
    from .algorithms.lns import fingerprint
    from .algorithms.simulation_joint import Genes, Schedule, SimulationJointProblem, Step
    from .dynamic_workforce import WorkforceHistory

    require(data["format"] == FORMAT, "GANTT_FORMAT")
    require(digest(data) == reference["artifact_sha256"], "GANTT_ARTIFACT_DIGEST")
    require(data["scope"] == "HYPOTHETICAL_SUFFIX_NOT_ACTUAL_EXECUTION", "GANTT_SCOPE")
    prefix = decode(m.ExecutionSnapshot, data["prefix"])
    n = len(prefix.events)
    require(
        n == reference["event_count"]
        and data["prefix"]["events"] == events[:n]
        and n <= len(events)
        and digest(events[:n]) == reference["event_prefix_sha256"],
        "GANTT_DELIVERED_ANCHOR",
    )
    observed = decode(m.PlanningObservation, data["observation"])
    require(observed.id == reference["observation_id"], "GANTT_OBSERVATION")
    source_generations = data["catalog_generations"]
    require(source_generations == generations[: len(source_generations)], "GANTT_GENERATIONS")
    require(all(g["event_id"] in observed.event_ids for g in source_generations), "GANTT_FUTURE")
    history = None
    if data["catalog_initial"] is not None:
        require(data["catalog_initial"] == initial, "GANTT_C0")
        history = WorkforceHistory(decode(m.Configuration, initial), source_generations)
        history.active_products = set(data["active_products"])
        config = history.current
    else:
        config = decode(m.Configuration, initial)
    require(as_data(config) == data["configuration"], "GANTT_CONFIGURATION")
    require(digest(data["configuration"]) == reference["config_sha256"], "GANTT_CONFIG_DIGEST")
    raw = data["candidate"]
    g = raw["genes"]
    genes = Genes(
        *(tuple(tuple(x) for x in g[k]) for k in ("modes", "crews", "order", "slots")),
        tuple(g["rests"]),
        g["initial_action_only"],
    )
    candidate = Schedule(
        raw["anchor_sha256"],
        raw["end_h"],
        genes,
        tuple(Step(decode(m.Plan, x["plan"]), x["advance_to_h"]) for x in raw["steps"]),
        raw["scope"],
    )
    # Wire numbers retain their original JSON spelling; decoding coerces domain
    # numeric types, so identity is checked on the exact received candidate.
    require(fingerprint(raw) == reference["candidate_sha256"], "GANTT_CANDIDATE_DIGEST")
    require(
        reference["start_h"] == observed.sampled_h and reference["end_h"] == candidate.end_h,
        "GANTT_WINDOW",
    )
    problem = SimulationJointProblem(
        config,
        observed,
        prefix,
        decisions=tuple(data["decisions"]),
        end_h=candidate.end_h,
        rejected=tuple(data["rejected"]),
        fixed_mode=data["fixed_mode"],
        committed=tuple(
            (decode(m.DispatchCommand, x["command"]), x["reason"]) for x in data["committed"]
        ),
        catalog=history,
    )
    report = problem.verify(candidate)
    require(report.valid, "GANTT_CANDIDATE_INVALID:" + ";".join(report.reasons))
    rebuilt = problem.last_verified_display[1]
    require(as_data(rebuilt) == data["snapshot"], "GANTT_PREDICTION_REBUILT")
    return forecast_rows(data, reference)


def forecast_rows(data, reference):
    rows = {}
    key = reference["candidate_sha256"]
    ongoing = {
        x["command"]["id"]
        for x in data["prefix"]["state"]["running"]
        if x["status"] in ("STARTED", "EXCEPTION")
    }
    anchors = [
        e for e in data["prefix"]["events"] if e["kind"] == "STARTED" and e["command_id"] in ongoing
    ]
    for event in anchors + data["snapshot"]["events"][reference["event_count"] :]:
        c = event["command"]
        if not c:
            continue
        if event["kind"] == "STARTED":
            rows[c["id"]] = dict(
                row_id="forecast:" + key + ":" + c["id"],
                row_kind="FORECAST",
                schedule_state="TENTATIVE",
                proposal_state="CANDIDATE",
                candidate_sha256=key,
                command_id=c["id"],
                product_id=c["product_id"],
                operation_id=c["operation_id"],
                activity_id=c["activity_id"],
                attempt=c["attempt"],
                mode=c["mode_id"],
                roles=c["roles"],
                start_h=event["occurred_sim_h"],
                end_status="WINDOW_CENSORED",
                forecast_until_h=reference["end_h"],
                observation_id=reference["observation_id"],
                prediction_scope=data["scope"],
            )
            if c["id"] in ongoing:
                rows[c["id"]]["continuation_command_id"] = c["id"]
                rows[c["id"]]["actual_start_event_id"] = event["id"]
        if event["kind"] == "COMPLETED" and c["id"] in rows:
            rows[c["id"]].update(end_h=event["occurred_sim_h"], end_status="PREDICTED")
    return list(rows.values())
