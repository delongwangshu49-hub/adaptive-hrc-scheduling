"""Bounded P043 local personnel witness through the common production worker.

Not a full-lifetime/E20 run. The caller owns the real CPU or Kit backend.
"""

import gzip
import json
from time import perf_counter

from adaptive_hrc_scheduling.contracts.codec import as_data
from adaptive_hrc_scheduling.contracts.session import request_digest
from adaptive_hrc_scheduling.control.production_decisions import record
from adaptive_hrc_scheduling.control.production_loop import run
from adaptive_hrc_scheduling.control.session import Session, save_atomic, source_identity
from adaptive_hrc_scheduling.dynamic_workforce import registry
from adaptive_hrc_scheduling.workforce_session import arrival_payload, make_spec


def execute(backend, profile, output, *, update=lambda: None, method="EDD"):
    w = getattr(backend, "world", backend)
    spec = make_spec(
        w.config,
        profile,
        run_id=w.run_id,
        backend="ISAAC" if hasattr(backend, "world") else "CPU",
        method=method,
        until_h=72,
        rates={k: 10 for k in [*[p.id for p in w.config.people], *registry()]},
    )
    s = Session(spec, backend, profile, output, source="P043_LOCAL_COMMON_WORKER")
    sent = []
    marks = {}
    engine = id(w)

    def submit(kind, pid, payload, *, delay_h=0):
        r = dict(
            run_id=w.run_id,
            epoch=0,
            request_id="P043-" + str(len(sent) + 1),
            producer_id="P043-RUNTIME",
            client_sequence=len(sent) + 1,
            source="CLI",
            kind=kind,
            target_id=pid,
            payload=payload,
            expected_catalog_version=s.version,
            expected_state_revision=w.s.revision,
            expected_target_revision=s.catalog["objects"].get(pid, {}).get("revision", 0),
            time_rule="IMMEDIATE",
            expires_sim_h=w.s.time_h + 2,
            submitted_at_utc="2026-10-23T05:00:00+00:00",
        )
        if delay_h:
            r.update(time_rule="AT_SIM_H", requested_sim_h=w.s.time_h + delay_h)
        r["request_digest"] = request_digest(r)
        s.submit(r)
        sent.append(r)
        s.boundary()

    def hook(backend, phase):
        update()
        if phase != "before_decision":
            return
        if not sent and w.s.running:
            p = arrival_payload(w.config, "W3", location="PRE-IN", initial_f=0.05)
            if hasattr(backend, "world"):
                p["scene_reference"]["prim_path"] = "/World/P043/People/W3"
            submit("PERSON_ARRIVE", "W3", p)
            marks["arrival_prefix_count"] = len(w.events)
        elif len(sent) == 1 and "W3" in w.people:
            submit(
                "PERSON_DEPART",
                "W1",
                dict(reason="PLANNED_SHIFT", handover_policy="SAFE_POINT_OR_VERIFIED_HANDOVER"),
            )
        elif len(sent) == 2 and any(
            r.command.service
            and r.command.service.operation.action == "WALK"
            and r.status == "STARTED"
            for r in w.s.running
        ):
            held = next(
                r
                for r in w.s.running
                if r.command.service
                and r.command.service.operation.action == "WALK"
                and r.status == "STARTED"
            )
            pid = held.command.roles[0].person_id
            marks.update(absent_person=pid, held_command=held.command.id, absent_h=w.s.time_h)
            submit(
                "PERSON_ABSENT",
                pid,
                dict(reason="UNEXPECTED_ABSENCE", safety_policy="HOLD_AND_VERIFY"),
            )
            submit(
                "PERSON_RETURN",
                pid,
                dict(arrival_location=w._position(pid).location, scene_entity_id=pid),
                delay_h=0.01,
            )
        elif len(sent) == 3 and any(
            r["request_id"] == sent[-1]["request_id"] and r["status"] == "APPLIED"
            for r in s.receipts
        ):
            pid = marks["absent_person"]
            submit(
                "PERSON_RETURN",
                pid,
                dict(arrival_location=w._position(pid).location, scene_entity_id=pid),
                delay_h=0.01,
            )
        elif len(sent) == 4 and any(
            e.kind == "COMPLETED"
            and e.command
            and any(r.person_id == "W3" for r in e.command.roles)
            and not e.command.service
            for e in w.events
        ):
            submit(
                "PERSON_RETURN",
                "W1",
                dict(arrival_location=w._position("W1").location, scene_entity_id="W1"),
            )
        elif len(sent) == 5 and any(r.command.roles and r.status == "STARTED" for r in w.s.running):
            # A planned departure of an actually running member must stay pending.
            active = next(r for r in w.s.running if r.command.roles and r.status == "STARTED")
            pid = active.command.roles[0].person_id
            marks["pending_person"] = pid
            submit(
                "PERSON_DEPART",
                pid,
                dict(reason="PLANNED_FINISH", handover_policy="SAFE_POINT_OR_VERIFIED_HANDOVER"),
            )

    def enough(world):
        if len(sent) < 6 or not any(
            r["request_id"] == sent[-1]["request_id"] and r["status"] == "APPLIED"
            for r in s.receipts
        ):
            return False
        return any(
            e.kind == "COMPLETED" and e.command and e.command.resume_of == marks.get("held_command")
            for e in world.events
        ) and any(e.world and e.world.kind == "PERSON_LEFT" for e in world.events)

    start = perf_counter()
    try:
        result = run(
            backend,
            s.scenario(),
            session=s,
            joint_policy=s.policy,
            execution_hook=hook,
            stop_condition=enough,
            max_turns=1800,
        )
    except BaseException:
        s.persist()
        raise
    s.persist()
    for name, rows in (
        ("events", (as_data(e) for e in result.snapshot.events)),
        ("decisions", (record(d) for d in result.decisions)),
    ):
        with gzip.open(s.output / (name + ".jsonl.gz"), "wt", encoding="utf-8") as stream:
            for row in rows:
                stream.write(json.dumps(row) + "\n")
    save_atomic(s.output / "report.json", result.manifest)
    save_atomic(
        s.output / "audits.json",
        dict(execution=as_data(result.audit), decisions=as_data(result.decision_audit)),
    )
    save_atomic(s.output / "online-journal.json", s.policy.journal)
    for i, (problem, candidate) in enumerate(s.policy.candidates, 1):
        problem.checkpoint = lambda: None
        snapshot, decisions = problem.preview(candidate)
        save_atomic(
            s.output / f"candidate-{i}.json",
            dict(
                candidate=as_data(candidate),
                prefix_event_count=len(problem.prefix.events),
                end_h=problem.end_h,
                observation=as_data(problem.observation),
                snapshot=as_data(snapshot),
                decisions=decisions,
                catalog_generations=problem.catalog.generations if problem.catalog else [],
            ),
        )
    save_atomic(
        s.output / "witness.json",
        dict(
            source_sha256=source_identity(),
            elapsed_s=perf_counter() - start,
            sent=sent,
            marks=marks,
            same_engine=id(w) == engine,
            success=enough(w),
            termination=result.manifest["termination"],
            events=len(w.events),
            candidates=len(s.policy.candidates),
        ),
    )
    print(
        result.manifest["termination"],
        result.audit.status,
        result.decision_audit.status,
        "sent",
        len(sent),
        "time",
        w.s.time_h,
        "events",
        len(w.events),
        flush=True,
    )
    print(
        [f.reason for f in result.audit.findings][:12],
        [f.reason for f in result.decision_audit.findings][:12],
        flush=True,
    )
    return result, s


if __name__ == "__main__":
    import argparse
    from pathlib import Path

    from build_simulation_production import configuration as base

    from adaptive_hrc_scheduling.control.session_budget import load_profile
    from adaptive_hrc_scheduling.production_backend import ProductionBackend
    from adaptive_hrc_scheduling.workforce_session import configuration

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--method", choices=("EDD", "ADAPTIVE"), default="EDD")
    args = parser.parse_args()
    r, s = execute(
        ProductionBackend(configuration(base()), run_id="P043-" + args.output.name.upper()),
        load_profile(json.loads(args.profile.read_text())),
        args.output,
        method=args.method,
    )
    raise SystemExit(
        0
        if r.audit.status == r.decision_audit.status == "PASS"
        and json.loads((s.output / "witness.json").read_text())["success"]
        else 1
    )
