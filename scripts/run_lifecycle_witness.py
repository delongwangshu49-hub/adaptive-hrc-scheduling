"""Finite P044 asynchronous drain/stop witnesses on the shared CPU or Kit worker."""

import argparse
import gzip
import json
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from adaptive_hrc_scheduling.contracts.codec import as_data
from adaptive_hrc_scheduling.contracts.session import request_digest
from adaptive_hrc_scheduling.control.production_decisions import record
from adaptive_hrc_scheduling.control.production_loop import run
from adaptive_hrc_scheduling.control.session import Session, save_atomic, submit_file
from adaptive_hrc_scheduling.control.session_lifecycle import enable
from adaptive_hrc_scheduling.dynamic_workforce import registry
from adaptive_hrc_scheduling.workforce_session import arrival_payload, make_spec


def execute(backend, profile, output, *, case="drain", update=lambda: None):
    w = getattr(backend, "world", backend)
    spec = enable(
        make_spec(
            w.config,
            profile,
            run_id=w.run_id,
            method="EDD",
            until_h=0.2,
            backend="ISAAC" if hasattr(backend, "world") else "CPU",
            rates={k: 10 for k in [*[p.id for p in w.config.people], *registry()]},
        ),
        simulation_rate=0.05,
        idle_step_h=0.0025,
        boundary_poll_wall_s=0.05,
        wall_budget_s=180,
    )
    s = Session(spec, backend, profile, output)
    sent = []
    errors = []
    done = threading.Event()

    def req(n, kind, target, payload=None, **changes):
        value = dict(
            run_id=spec["run_id"],
            epoch=0,
            request_id=f"LIVE-{n}",
            producer_id="LIVE",
            client_sequence=n,
            source="CLI",
            kind=kind,
            target_id=target,
            payload=payload or {},
            expected_catalog_version=s.version,
            expected_state_revision=w.s.revision,
            expected_target_revision=s.catalog["objects"].get(target, {}).get("revision", 0),
            time_rule="IMMEDIATE",
            expires_sim_h=1,
            submitted_at_utc=datetime.now(timezone.utc).isoformat(),
        )
        value.update(changes)
        value["request_digest"] = request_digest(value)
        return value

    if case == "drain":
        s.submit(
            req(
                1,
                "ORDER_CANCEL",
                next(iter(s.order_products)),
                dict(reason="LIFETIME_LOCAL_CANCEL"),
            )
        )

    def producer():
        try:
            while not done.wait(0.005):
                ready = (
                    (s.lifecycle.phase == "WAITING_INPUT" and w.s.time_h >= 0.005)
                    if case == "drain"
                    else bool(w.s.running)
                )
                if ready:
                    if case == "drain":
                        payload = arrival_payload(w.config, "W3")
                        if spec["backend"] == "ISAAC":
                            payload["scene_reference"]["prim_path"] = "/World/P043/People/W3"
                        rows = [
                            req(
                                10,
                                "PERSON_ARRIVE",
                                "W3",
                                payload,
                                time_rule="AT_SIM_H",
                                requested_sim_h=w.s.time_h + 0.01,
                            ),
                        ]
                    elif case == "active-drain":
                        rows = [
                            req(
                                10,
                                "ORDER_CANCEL",
                                next(iter(s.order_products)),
                                dict(reason="CLOSE_WITH_STARTED_COMMAND"),
                            )
                        ]
                    else:
                        rows = [req(10, "STOP_REQUEST", spec["run_id"])]
                    for r in rows:
                        submit_file(s.output, r)
                        sent.append(
                            dict(
                                request=r,
                                published_wall_s=time.perf_counter() - s.lifecycle.started,
                                published_sim_h=w.s.time_h,
                            )
                        )
                    if case in ("drain", "active-drain"):
                        while not done.wait(0.002):
                            if "LIVE-10" in s.admissions and (
                                case == "drain"
                                or any(
                                    r["request_id"] == "LIVE-10" and r["status"] == "APPLIED"
                                    for r in s.receipts
                                )
                            ):
                                r = req(11, "CLOSE_INPUT", spec["run_id"])
                                submit_file(s.output, r)
                                sent.append(
                                    dict(
                                        request=r,
                                        published_wall_s=time.perf_counter() - s.lifecycle.started,
                                        published_sim_h=w.s.time_h,
                                    )
                                )
                                return
                    return
        except Exception as exc:
            errors.append(repr(exc))

    thread = threading.Thread(target=producer, name="p044-file-producer", daemon=True)
    thread.start()
    began = time.perf_counter()
    try:
        result = run(
            backend,
            s.scenario(),
            session=s,
            joint_policy=s.policy,
            execution_hook=lambda backend, phase: update(),
        )
    finally:
        done.set()
        thread.join(2)
    save_atomic(s.output / "report.json", result.manifest)
    save_atomic(
        s.output / "audits.json",
        dict(execution=as_data(result.audit), decisions=as_data(result.decision_audit)),
    )
    save_atomic(s.output / "online-journal.json", s.policy.journal)
    for name, rows in (
        ("events", (as_data(e) for e in result.snapshot.events)),
        ("decisions", (record(d) for d in result.decisions)),
    ):
        with gzip.open(s.output / (name + ".jsonl.gz"), "wt", encoding="utf-8") as stream:
            for row in rows:
                stream.write(json.dumps(row) + "\n")
    elapsed = time.perf_counter() - began
    success = (
        result.audit.status == result.decision_audit.status == "PASS"
        and not errors
        and s.lifecycle.final["phase"] == ("STOPPED" if case == "stop" else "COMPLETED")
        and bool(sent)
    )
    if case == "drain":
        success = (
            success
            and "W3" in w.people
            and any(x["phase"] == "WAITING_INPUT" for x in s.lifecycle.transitions)
        )
    else:
        success = (
            success
            and any(e.kind == "STARTED" for e in w.events)
            and any(e.kind == "COMPLETED" for e in w.events)
        )
    save_atomic(
        s.output / "witness.json",
        dict(
            identity="P044-LOCAL-LIFETIME-r1",
            case=case,
            success=success,
            producer=sent,
            producer_errors=errors,
            elapsed_s=elapsed,
            events=len(w.events),
            events_per_s=len(w.events) / elapsed,
            projection_packets=s.projection.cursor,
            projection_rows=len(s.projection.rows),
            projection_bytes=(s.output / "timeline.jsonl").stat().st_size,
            scope="LOCAL_CANCEL_DRAIN_AND_PERSON_ARRIVAL"
            if case == "drain"
            else "LOCAL_STARTED_COMMAND_CLOSE_DRAIN"
            if case == "active-drain"
            else "LOCAL_STARTED_COMMAND_ORDERLY_STOP",
            final=s.lifecycle.final,
            process_exit="UNKNOWN",
        ),
    )
    print(
        json.dumps(
            dict(
                success=success,
                case=case,
                phase=s.lifecycle.phase,
                events=len(w.events),
                elapsed_s=elapsed,
            )
        ),
        flush=True,
    )
    return result, s, success


def main():
    from build_simulation_production import configuration as base

    from adaptive_hrc_scheduling.control.session_budget import load_profile
    from adaptive_hrc_scheduling.production_backend import ProductionBackend
    from adaptive_hrc_scheduling.workforce_session import configuration

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--case", choices=("drain", "stop", "active-drain"), default="drain")
    args = parser.parse_args()
    _, _, success = execute(
        ProductionBackend(configuration(base()), run_id="P044-" + args.output.name.upper()),
        load_profile(json.loads(args.profile.read_text())),
        args.output,
        case=args.case,
    )
    return 0 if success else 1


if __name__ == "__main__":
    raise SystemExit(main())
