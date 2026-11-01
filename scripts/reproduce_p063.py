"""Reproduce P06.3 CPU cases using an explicitly installed final candidate.

Run with an isolated interpreter (-I). Configuration and budget profile are
explicit inputs; this script does not redirect imports to checkout sources.
"""

import argparse
import gzip
import hashlib
import json
import platform
import sys
import time
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from adaptive_hrc_scheduling.contracts.codec import as_data
from adaptive_hrc_scheduling.contracts.production import decode
from adaptive_hrc_scheduling.contracts.session import request_digest
from adaptive_hrc_scheduling.control.production_decisions import record
from adaptive_hrc_scheduling.control.production_loop import run
from adaptive_hrc_scheduling.control.session import Session, save_atomic
from adaptive_hrc_scheduling.control.session_budget import load_profile
from adaptive_hrc_scheduling.control.session_lifecycle import enable
from adaptive_hrc_scheduling.domain.production import Configuration
from adaptive_hrc_scheduling.dynamic_workforce import registry
from adaptive_hrc_scheduling.production_backend import ProductionBackend
from adaptive_hrc_scheduling.workforce_session import make_spec


def request(session, sequence, kind, target, payload):
    value = dict(
        run_id=session.spec["run_id"],
        epoch=session.spec["epoch"],
        request_id=f"P063-{kind}-{sequence}",
        producer_id="P063-REPRODUCTION",
        client_sequence=sequence,
        source="CLI",
        kind=kind,
        target_id=target,
        payload=payload,
        expected_catalog_version=session.version,
        expected_state_revision=session.world.s.revision,
        expected_target_revision=session.catalog["objects"].get(target, {}).get("revision", 0),
        time_rule="IMMEDIATE",
        expires_sim_h=720,
        submitted_at_utc=datetime.now(timezone.utc).isoformat(),
    )
    value["request_digest"] = request_digest(value)
    return value


def execute(configuration, profile, output, case, run_id=None):
    started = time.perf_counter()
    config = decode(Configuration, json.loads(configuration.read_bytes()))
    budget = load_profile(json.loads(profile.read_bytes()))
    run_id = run_id or f"P063-{case.upper()}"
    spec = enable(
        make_spec(
            config,
            budget,
            run_id=run_id,
            method="EDD",
            mode="INTERACTIVE_PRODUCTION",
            scenario="INTERACTIVE",
            until_h=720,
            rates={key: 10 for key in [*[p.id for p in config.people], *registry()]},
        ),
        simulation_rate=1000,
        idle_step_h=2,
        boundary_poll_wall_s=0.25,
        wall_budget_s=7200,
    )
    session = Session(spec, ProductionBackend(config, run_id=run_id), budget, output)
    if case == "normal":
        session.submit(request(session, 1, "CLOSE_INPUT", run_id, {}))
    changed = False
    stopped = False

    def hook(world, phase):
        nonlocal changed, stopped
        if case != "dynamic" or phase != "before_decision":
            return
        if world.s.time_h >= 0.5 and not changed:
            order = config.products[0].order_id
            value = request(
                session,
                1,
                "ORDER_UPDATE",
                order,
                dict(order_id=order, due_sim_h=200, priority="URGENT"),
            )
            session.submit(value)
            changed = True
        if changed and session.version == 1 and session.policy.version >= 2 and not stopped:
            session.submit(request(session, 2, "STOP_REQUEST", run_id, {}))
            stopped = True

    save_atomic(
        output / "reproduction-input.json", dict(case=case, spec=spec, profile=asdict(budget))
    )
    result = run(
        session.backend,
        session.scenario(),
        joint_policy=session.policy,
        session=session,
        execution_hook=hook,
        orderly_stop=lambda world: session.stopped,
        max_turns=20000,
    )
    for name, data in (
        ("configuration.json", as_data(config)),
        ("report.json", result.manifest),
        ("online-journal.json", session.policy.journal),
        (
            "audits.json",
            dict(execution=as_data(result.audit), decisions=as_data(result.decision_audit)),
        ),
    ):
        save_atomic(output / name, data)
    for name, rows in (
        ("events", (as_data(e) for e in result.snapshot.events)),
        ("decisions", (record(d) for d in result.decisions)),
    ):
        with gzip.open(output / f"{name}.jsonl.gz", "wt", encoding="utf-8") as stream:
            for row in rows:
                stream.write(json.dumps(row, ensure_ascii=False) + "\n")
    received = sum(p.received_h is not None for p in result.snapshot.state.products)
    final = session.lifecycle.final
    passed = result.audit.status == result.decision_audit.status == "PASS"
    if case == "normal":
        passed = passed and final["phase"] == "COMPLETED" and received == len(config.products)
        passed = passed and session.lifecycle.clear() and not session.stopped
    else:
        passed = passed and changed and session.version == 1 and session.policy.version == 2
        passed = passed and final["phase"] == "STOPPED" and stopped
        statuses = [
            r["status"] for r in session.receipts if r["request_id"] == "P063-ORDER_UPDATE-1"
        ]
        passed = passed and statuses == ["ACCEPTED", "APPLIED"]
        stop_statuses = [
            r["status"] for r in session.receipts if r["request_id"] == "P063-STOP_REQUEST-2"
        ]
        passed = passed and stop_statuses == ["ACCEPTED", "APPLIED"]
        passed = passed and not session.protocol_errors
    summary = dict(
        status="PASS" if passed else "FAIL",
        case=case,
        python=sys.executable,
        python_version=platform.python_version(),
        elapsed_s=time.perf_counter() - started,
        termination=result.manifest["termination"],
        final=final,
        received=received,
        products=len(config.products),
        configuration_operations=len(config.operations),
        completed_operations=len(result.snapshot.state.completed),
        events=len(result.snapshot.events),
        execution_audit=result.audit.status,
        decision_audit=result.decision_audit.status,
        catalog_version=session.version,
        full_schedule_version=session.policy.version,
        script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    )
    save_atomic(output / "reproduction-result.json", summary)
    print(json.dumps(summary), flush=True)
    return 0 if passed else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--configuration", type=Path, required=True)
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--case", choices=("normal", "dynamic"), required=True)
    parser.add_argument("--run-id", help="Explicit identity for a separate reproduction attempt")
    args = parser.parse_args()
    return execute(args.configuration, args.profile, args.output, args.case, args.run_id)


if __name__ == "__main__":
    raise SystemExit(main())
