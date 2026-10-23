"""Independent scene coverage and preserved commitment binding for P043-r2."""

from adaptive_hrc_scheduling.contracts.codec import decode
from adaptive_hrc_scheduling.contracts.production import digest, validate
from adaptive_hrc_scheduling.contracts.session import digest as sha
from adaptive_hrc_scheduling.domain import production as m
from adaptive_hrc_scheduling.production_geometry import standing_point


def verify_integrity(spec, saved, history, snapshot, check):
    current = saved["dynamic_format"] == "P043-WORKFORCE-2"
    check(
        saved["session_format"]
        == saved["binding"]["session_format"]
        == ("P043-SESSION-r2" if current else "P043-SESSION-r1"),
        "WORKFORCE_PROTOCOL_BINDING",
    )
    events = {e.id: e for e in snapshot.events}
    deltas = {d["commit_event_id"]: d for d in saved["deltas"]}
    generations = {g["event_id"]: g for g in saved["generations"]}
    arrivals = {
        g["target_id"]: g
        for g in saved["generations"]
        if g.get("workforce_kind") == "PERSON_ARRIVE"
    }
    expected = {
        e.id
        for e in snapshot.events
        if e.world
        and (
            e.world.kind == "PERSON_ARRIVE"
            or e.world.kind == "PERSON_RETURN"
            and (current or spec["backend"] == "ISAAC")
        )
    }
    rows = [s for s in saved["scene_bindings"] if s["scope"] == "P043_PERSON_ACTUAL_READBACK"]
    check(
        len(rows) == len(expected) and {s["event_id"] for s in rows} == expected,
        "PERSON_SCENE_EXACT_COVERAGE",
    )
    for s in rows:
        e = events[s["event_id"]]
        pid = e.world.entity_id
        g = generations[e.id]
        loc = g["payload"]["arrival_location"]
        view = history.views[g["config_sha256"]]
        check(
            s["domain_id"] == s["scene_entity_id"] == pid
            and s["ready"] is True
            and s["template_revision"] == "v1"
            and s["catalog_version"] == deltas[e.id]["new_version"]
            and s["actual_location"] == loc
            and next(p.location for p in e.state.positions if p.id == pid) == loc,
            "PERSON_SCENE_EVENT_BINDING:" + e.id,
        )
        if spec["backend"] == "ISAAC":
            expected_path = (
                arrivals[pid]["payload"]["scene_reference"]["prim_path"]
                if pid in arrivals
                else "/World/People/" + pid
            )
            if loc == "IN_TRANSIT":
                proof = next((x for x in e.state.motions if x.entity_id == pid), None)
                check(
                    proof is not None and proof.source == "ISAAC_USD",
                    "RETURN_HELD_POSITION_PROOF:" + e.id,
                )
                point = proof.position_m
            else:
                point = standing_point(view, pid, loc)
            check(
                s["source"] == "ISAAC_USD"
                and s["prim_path"] == expected_path
                and (s["run_id"], s["epoch"]) == (spec["run_id"], spec["epoch"])
                and len(s["actual_position_m"]) == 3
                and all(abs(a - b) < 1e-6 for a, b in zip(s["actual_position_m"], point)),
                "PERSON_REAL_POSITION_IDENTITY:" + e.id,
            )
        else:
            check(
                s["source"] == "CPU_LOCATION_EXECUTOR" and s["prim_path"] == "CPU:N/A",
                "PERSON_CPU_POSITION_SOURCE:" + e.id,
            )
    for result in saved["workforce_results"]:
        e = events[result["event_id"]]
        delta = deltas[e.id]
        transitions = [
            t
            for t in saved["cache_transitions"]
            if t["new_catalog_version"] == delta["new_version"]
            and t["old_catalog_version"] == delta["old_version"]
            and e.id in t["reason_event_ids"]
        ]
        check(len(transitions) == 1, "PERSON_COMMITMENT_TRANSITION:" + e.id)
        transition = transitions[0]
        # r1 formal archives had no protected promises. A nonempty historical
        # hash cannot be reconstructed from an absent command snapshot.
        check(not current or "committed_commands" in result, "COMMITMENT_SNAPSHOT_REQUIRED:" + e.id)
        commands = result.get("committed_commands", [])
        check(
            sha(commands)
            == transition["protected_before_hash"]
            == transition["protected_after_hash"],
            "COMMITMENT_SNAPSHOT_BINDING:" + e.id,
        )
        check(len({c["id"] for c in commands}) == len(commands), "COMMITMENT_UNIQUE:" + e.id)
        expected_blocked = []
        pid = result["person_id"]
        for raw in commands:
            c = decode(m.DispatchCommand, raw)
            check(
                c.config_sha256 in history.views
                and c.run_id == spec["run_id"]
                and c.epoch == spec["epoch"],
                "COMMITMENT_IDENTITY:" + c.id,
            )
            validate(c, config=history.views[c.config_sha256])
            dependent = any(r.person_id == pid for r in c.roles) or any(
                a.activity_id == c.activity_id
                and a.state != "COMPLETE"
                and any(r.person_id == pid for r in a.crew)
                for a in e.state.mode_attempts
            )
            if e.world.kind in ("PERSON_DEPART", "PERSON_ABSENT") and dependent:
                expected_blocked.append(
                    dict(
                        command_id=c.id,
                        command_sha256=digest(c),
                        reason_event_id=e.id,
                        status="COMMITMENT_BLOCKED",
                    )
                )
        check(
            result["blocked_commitments"] == expected_blocked, "COMMITMENT_BLOCKED_COVERAGE:" + e.id
        )
