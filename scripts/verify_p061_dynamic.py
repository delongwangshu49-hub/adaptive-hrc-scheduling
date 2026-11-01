"""Bounded final-interface transaction witness for P06.1, without production.

Creates a software-only Session fixture, records actual transactions, and calls
the independent saved-state verifier. Full production evidence is reused under
its original identity; this fixture makes no GUI, Kit, or completion claim.
"""

import argparse
import json
import sys
import time
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from build_simulation_production import configuration as base  # noqa: E402
from verify_workforce_session import verify  # noqa: E402

from adaptive_hrc_scheduling.contracts.codec import as_data  # noqa: E402
from adaptive_hrc_scheduling.contracts.production import digest as config_digest  # noqa: E402
from adaptive_hrc_scheduling.contracts.session import digest, request_digest  # noqa: E402
from adaptive_hrc_scheduling.control.online import Limits  # noqa: E402
from adaptive_hrc_scheduling.control.session import Session, source_identity  # noqa: E402
from adaptive_hrc_scheduling.control.session_budget import Profile  # noqa: E402
from adaptive_hrc_scheduling.dynamic_orders import template_registry  # noqa: E402
from adaptive_hrc_scheduling.dynamic_workforce import registry, status  # noqa: E402
from adaptive_hrc_scheduling.planning.production import choose, planning_input  # noqa: E402
from adaptive_hrc_scheduling.production_backend import ProductionBackend  # noqa: E402
from adaptive_hrc_scheduling.workforce_session import (  # noqa: E402
    arrival_payload,
    configuration,
    make_spec,
)


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def run(output):
    t0 = time.perf_counter()
    output.mkdir(parents=True, exist_ok=False)
    c = configuration(base())
    profile = Profile(
        "P061-SOFTWARE-TRANSACTIONS",
        Limits(decision_seconds=5, search_seconds=1),
        100,
        2,
        "P042_URGENCY_DUE_PROGRESS_EXPOSURE-r1",
    )
    run_id = "P061-SOFTWARE-TRANSACTION-PREFIX"
    w = ProductionBackend(c, run_id=run_id)
    spec = make_spec(
        c,
        profile,
        run_id=run_id,
        method="EDD",
        rates={k: 10 for k in [*(p.id for p in c.people), *registry()]},
    )
    s = Session(spec, w, profile, output / "session")
    source = source_identity()
    write(
        output / "started.json",
        dict(
            at=datetime.now(timezone(timedelta(hours=8))).isoformat(),
            command=sys.argv,
            source_sha256=source,
            scope="BOUNDED_SOFTWARE_TRANSACTION_FIXTURE",
        ),
    )
    seq = 0

    def req(kind, target, payload, **extra):
        nonlocal seq
        seq += 1
        value = dict(
            run_id=run_id,
            epoch=0,
            request_id=f"P061-REQUEST-{seq}",
            producer_id="P061",
            client_sequence=seq,
            source="CLI",
            kind=kind,
            target_id=target,
            payload=payload,
            expected_catalog_version=s.version,
            expected_state_revision=w.s.revision,
            expected_target_revision=s.catalog["objects"].get(target, {}).get("revision", 0),
            time_rule="IMMEDIATE",
            expires_sim_h=w.s.time_h + 2,
            submitted_at_utc=datetime.now(timezone.utc).isoformat(),
        )
        value.update(extra)
        value["request_digest"] = request_digest(value)
        return value

    trace = []

    def capture(label):
        state = w.snapshot()
        row = dict(
            label=label,
            run_id=w.run_id,
            epoch=w.epoch,
            sim_h=w.s.time_h,
            revision=w.s.revision,
            catalog_version=s.version,
            config_sha256=config_digest(w.config),
            event_count=len(state.events),
            event_prefix_hash=digest(as_data(state.events)),
            products=[p.id for p in w.config.products],
            people=[p.id for p in w.config.people],
            W3_status=status(w.s, "W3") if "W3" in w.people else "NOT_REGISTERED",
            W3_human=next((asdict(h) for h in w.s.humans if h.person_id == "W3"), None),
        )
        trace.append(row)
        return row

    capture("C0")
    assert "W3" not in w.people and len(w.config.products) == 1
    order = req(
        "ORDER_CREATE",
        "P061-NEW-ORDER",
        dict(
            order_id="P061-NEW-ORDER",
            template_id="SR-W1",
            template_revision="v1",
            template_sha256=template_registry()["SR-W1"],
            quantity=2,
            due_sim_h=300,
            priority="URGENT",
            material_plan_id="TEMPLATE-JIT-v1",
            arrival_rule="REQUEST_EFFECTIVE_TIME",
        ),
        time_rule="AT_SIM_H",
        requested_sim_h=0.05,
    )
    arrive = req(
        "PERSON_ARRIVE", "W3", arrival_payload(c, "W3"), time_rule="AT_SIM_H", requested_sim_h=0.05
    )
    assert s.receive(order)["status"] == s.receive(arrive)["status"] == "ACCEPTED"
    s.boundary()
    capture("ACCEPTED_BEFORE_DELIVERY")
    assert len(w.config.products) == 1 and "W3" not in w.people and s.version == 0

    # A second executor has exactly the same visible prefix and no future request.
    control = ProductionBackend(c, run_id=run_id)
    obs, control_obs = w.observe(), control.observe()
    assert obs == control_obs and w.snapshot() == control.snapshot()
    queued_plan = choose(c, planning_input(c, obs, 10000))
    control_plan = choose(c, planning_input(c, control_obs, 10000))
    assert queued_plan.commands == control_plan.commands
    prefix_proof = dict(
        status="PASS",
        visible_observation_sha256=config_digest(obs),
        queued_commands=as_data(queued_plan.commands),
        control_commands=as_data(control_plan.commands),
        same_current_action=True,
        future_order_and_person_not_in_visible_catalog=True,
        budget=dict(method="EDD", search_calls=0, profile=asdict(profile)),
        scope="EXACT_SAME_VISIBLE_PREFIX_SOFTWARE_CONTROL_NO_WALL_CLOCK_SEARCH_EQUIVALENCE_CLAIM",
    )
    s.bind_observation(obs)
    old_events = tuple(w.events)
    old_people = tuple(p.id for p in w.config.people)
    w.advance(0.05)
    s.boundary()
    capture("ORDER_AND_PERSON_ACTUALLY_APPLIED")
    assert len(w.config.products) == 3 and "W3" in w.people and s.version == 2
    assert tuple(w.events[: len(old_events)]) == old_events
    assert tuple(p.id for p in w.config.people if p.id != "W3") == old_people
    assert len(w.config.operations) == 3 * len(c.operations)
    ids = s.order_products["P061-NEW-ORDER"]
    assert len(ids) == 2 and not set(ids) & {p.id for p in c.products}
    new_lots = [lot for lot in w.config.lots if lot.product_id in ids]
    assert new_lots and all(
        not w._lot(lot.id).arrived and w._lot(lot.id).available == 0 for lot in new_lots
    )
    assert all(s.material_due[pid] == 0.05 for pid in ids)
    assert all(s.history.priorities[pid] == "URGENT" for pid in ids)
    count = len(s.history.generations)
    assert s.receive(order)["status"] == "APPLIED"
    assert len(s.history.generations) == count and s.version == 2
    w.advance(0.1)
    depart = req(
        "PERSON_DEPART",
        "W3",
        dict(reason="P061", handover_policy="SAFE_POINT_OR_VERIFIED_HANDOVER"),
    )
    assert s.receive(depart)["status"] == "ACCEPTED"
    s.boundary()
    capture("DEPARTED")
    assert status(w.s, "W3") == "DEPARTED"
    w.advance(0.3)
    before_return = next(h for h in w.s.humans if h.person_id == "W3")
    capture("ABSENT_INTERVAL")
    returned = req(
        "PERSON_RETURN",
        "W3",
        dict(arrival_location=w._position("W3").location, scene_entity_id="W3"),
    )
    assert s.receive(returned)["status"] == "ACCEPTED"
    s.boundary()
    capture("RETURNED_WITHOUT_RESET")
    assert next(h for h in w.s.humans if h.person_id == "W3") == before_return
    assert status(w.s, "W3") == "PRESENT"
    w.advance(0.4)
    s.bind_observation(w.observe())
    s.persist()
    capture("SAVED_PREFIX")
    checked = verify(s.output, require_decisions=False)
    assert checked["status"] == "PASS" and checked["execution_audit"] == "PASS"
    saved = json.loads((s.output / "session-state.json").read_bytes())
    stats = saved["workforce_statistics"]["people"]["W3"]
    assert abs(stats["presence_h"] - 0.15) < 1e-8
    assert abs(stats["labour_cost"] - 1.5) < 1e-8
    result = dict(
        identity="P061-FINAL-DYNAMIC-SOFTWARE-r1",
        status="PASS",
        source_sha256=source,
        run_id=run_id,
        epoch=0,
        trace=trace,
        requests=saved["requests"],
        receipts=saved["receipts"],
        deltas=saved["deltas"],
        generations=saved["generations"],
        new_products=ids,
        new_task_count=len(w.config.operations) - len(c.operations),
        new_bom_lots=[asdict(lot) for lot in new_lots],
        new_material_not_minted=True,
        original_prefix_preserved=True,
        person_return_did_not_reset_F_E=True,
        person_statistics=stats,
        same_id_same_content_applied_once=True,
        independent=checked,
        prefix_control=prefix_proof,
        elapsed_s=time.perf_counter() - t0,
        scope="SOFTWARE_TRANSACTIONS_ONLY_NO_PRODUCTION_GUI_KIT_OR_NEW_T08_OPTIMIZATION",
        causal_scope="NO_DISPATCH_IN_THIS_FIXTURE; real nonempty causal archive audited separately",
    )
    write(output / "event-chain-trace.json", result)
    write(output / "prefix-control.json", prefix_proof)
    print(
        json.dumps(
            {
                k: result[k]
                for k in (
                    "identity",
                    "status",
                    "new_products",
                    "new_task_count",
                    "elapsed_s",
                    "scope",
                )
            }
        )
    )
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-directory", type=Path, required=True)
    args = parser.parse_args()
    run(args.output_directory)
