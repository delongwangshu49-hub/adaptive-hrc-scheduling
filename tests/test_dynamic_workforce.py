"""P043 real single-writer personnel transactions and independent rejection probes."""

import copy
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from build_simulation_production import configuration as base
from verify_workforce_session import verify

from adaptive_hrc_scheduling.contracts.codec import ContractError
from adaptive_hrc_scheduling.contracts.production import digest, validate
from adaptive_hrc_scheduling.contracts.session import request_digest
from adaptive_hrc_scheduling.control.online import Limits
from adaptive_hrc_scheduling.control.session import Session
from adaptive_hrc_scheduling.control.session_budget import Profile
from adaptive_hrc_scheduling.domain import production as m
from adaptive_hrc_scheduling.dynamic_workforce import registry, status
from adaptive_hrc_scheduling.production_backend import ProductionBackend
from adaptive_hrc_scheduling.production_checker import check_run
from adaptive_hrc_scheduling.production_geometry import route
from adaptive_hrc_scheduling.production_navigation import walk
from adaptive_hrc_scheduling.workforce_session import arrival_payload, configuration, make_spec


def service_command(world, pid, *, rest=False, destination="PRE-IN", resume=None):
    c = world.config
    source = world._position(pid).location
    ident = "P043-SERVICE-" + str(world.s.revision)
    rt = None if rest else route(c, "ROUTE-" + ident, source, destination, None, person=pid)
    if rt:
        rt = replace(
            rt, points=tuple(m.Point(*p) for p in walk(c, world.s, pid, source, destination))
        )
    op = m.Operation(
        ident,
        c.products[0].id,
        ident,
        "REST" if rest else "WALK",
        "REST" if rest else "WALK",
        (),
        (m.Role(pid, world.people[pid].qualifications[0]),),
        (m.PersonPosition(pid, source),),
        (),
        source,
        None if rest else destination,
        rt.id if rt else None,
        pid,
        (),
        (),
        0,
        c.min_rest_h if rest else 0,
        0,
        ("ML-METHOD",),
        (),
        None,
        None,
        None,
    )
    return m.DispatchCommand(
        c.schema_version,
        c.id,
        digest(c),
        world.run_id,
        world.epoch,
        ident,
        c.products[0].id,
        ident,
        ident,
        0,
        0,
        "WAIT" if rest else "MOVE",
        world.s.time_h,
        world.s.revision,
        (m.RoleBinding(pid, pid),),
        service=m.Service(op, rt),
        research=c.research,
    )


class WorkforceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.c = configuration(base())
        self.w = ProductionBackend(self.c, run_id="P043-TEST")
        self.p = Profile(
            "P043-TEST",
            Limits(decision_seconds=5, search_seconds=1),
            100,
            2,
            "P042_URGENCY_DUE_PROGRESS_EXPOSURE-r1",
        )
        self.spec = make_spec(
            self.c,
            self.p,
            run_id=self.w.run_id,
            method="EDD",
            rates={k: 10 for k in [*[p.id for p in self.c.people], *registry()]},
        )
        self.s = Session(self.spec, self.w, self.p, Path(self.tmp.name) / "run")
        self.n = 0

    def req(self, kind="PERSON_ARRIVE", pid="W3", payload=None, **kwargs):
        self.n += 1
        if payload is None:
            payload = (
                arrival_payload(self.c, pid)
                if kind == "PERSON_ARRIVE"
                else dict(arrival_location=self.w._position(pid).location, scene_entity_id=pid)
                if kind == "PERSON_RETURN"
                else dict(
                    reason="TEST",
                    **(
                        {"handover_policy": "SAFE_POINT_OR_VERIFIED_HANDOVER"}
                        if kind == "PERSON_DEPART"
                        else {"safety_policy": "HOLD_AND_VERIFY"}
                    ),
                )
            )
        r = dict(
            run_id=self.w.run_id,
            epoch=0,
            request_id="R" + str(self.n),
            producer_id="TEST",
            client_sequence=self.n,
            source="CLI",
            kind=kind,
            target_id=pid,
            payload=payload,
            expected_catalog_version=self.s.version,
            expected_state_revision=self.w.s.revision,
            expected_target_revision=self.s.catalog["objects"].get(pid, {}).get("revision", 0),
            time_rule="IMMEDIATE",
            expires_sim_h=self.w.s.time_h + 2,
            submitted_at_utc="2026-10-23T04:00:00+00:00",
        )
        r.update(kwargs)
        r["request_digest"] = request_digest(r)
        return r

    def apply(self, r):
        got = self.s.receive(r)
        if got["status"] == "ACCEPTED":
            self.s.boundary()
        return self.s.receipts[-1]

    def audit(self):
        self.assertEqual(
            check_run(self.w.config, self.w.snapshot(), catalog=self.s.history).status, "PASS"
        )
        self.s.persist()
        return verify(self.s.output, require_decisions=False)

    def dispatch(self, cmd):
        obs = self.w.observe()
        self.w.deliver()
        bound = self.s.bind_observation(obs)
        receipt = self.w.dispatch(cmd)
        self.s.bind_dispatch(None, receipt, bound)
        return receipt

    def test_genuine_registration_same_engine_and_prefix(self):
        self.w.advance(0.1)
        prefix = tuple(self.w.events)
        engine = id(self.w)
        self.assertEqual(self.apply(self.req())["status"], "APPLIED")
        self.assertEqual(len(self.w.people), 16)
        self.assertNotIn("W3", [p.id for p in self.c.people])
        self.assertEqual(self.w.s.humans[-1], m.HumanState("W3", 0.1, 0, 0.1, 0))
        self.assertEqual(tuple(self.w.events[: len(prefix)]), prefix)
        self.assertEqual(id(self.w), engine)
        self.w.advance(0.2)
        self.audit()

    def test_template_and_qualification_rejections(self):
        for key, value in (
            ("parameter_template_id", "BAD"),
            ("parameter_template_sha256", "0" * 64),
            ("qualification_evidence_id", "BAD"),
            ("qualifications", ["ROBOT"]),
            ("calendar_id", "BAD"),
            ("calendar_sha256", "0" * 64),
            ("initial_f", 0.95),
            ("arrival_location", "NOWHERE"),
            ("valid_until_h", 99999),
        ):
            with self.subTest(key=key):
                p = arrival_payload(self.c, "W3")
                p[key] = value
                self.assertEqual(self.apply(self.req(payload=p))["status"], "REJECTED")
        self.assertEqual(len(self.w.people), 15)

    def test_scene_identity_rejections(self):
        for key, value in (
            ("domain_id", "OTHER"),
            ("scene_entity_id", "OTHER"),
            ("prim_path", "/World/Wrong"),
            ("template_revision", "v2"),
        ):
            with self.subTest(key=key):
                p = arrival_payload(self.c, "W3")
                p["scene_reference"][key] = value
                self.assertEqual(self.apply(self.req(payload=p))["status"], "REJECTED")

    def test_id_collision_and_limit(self):
        for pid in ("W1", "R1", "PRODUCT-1", "PRODUCT-1.CUT.U1"):
            self.assertEqual(self.apply(self.req(pid=pid))["status"], "REJECTED")
        for pid in ("W3", "W4", "W5"):
            self.assertEqual(self.apply(self.req(pid=pid))["status"], "APPLIED")
        self.assertEqual(self.apply(self.req(pid="W6"))["reason"], "WORKFORCE_TESTED_LIMIT")

    def test_future_not_in_catalog_and_idempotency(self):
        r = self.req(time_rule="AT_SIM_H", requested_sim_h=0.1)
        self.apply(r)
        self.assertNotIn("W3", self.w.people)
        self.w.advance(0.1)
        self.s.boundary()
        last = self.s.receive(r)
        self.assertEqual(last["status"], "APPLIED")
        self.assertEqual(len(self.w.people), 16)
        self.audit()

    def test_depart_return_continuous_and_cost(self):
        self.apply(self.req())
        self.w.advance(0.1)
        self.apply(self.req("PERSON_DEPART"))
        self.assertEqual(status(self.w.s, "W3"), "DEPARTED")
        old = self.w.s.humans[-1]
        self.w.advance(0.3)
        new = self.w.s.humans[-1]
        self.assertLess(new.fatigue, old.fatigue)
        self.assertGreater(new.exposure, old.exposure)
        self.apply(self.req("PERSON_RETURN"))
        self.assertEqual(self.w.s.humans[-1], new)
        self.w.advance(0.4)
        self.audit()
        stats = json.loads((self.s.output / "session-state.json").read_text())[
            "workforce_statistics"
        ]["people"]["W3"]
        self.assertAlmostEqual(stats["presence_h"], 0.2)
        self.assertAlmostEqual(stats["labour_cost"], 2)

    def test_depart_pending_finishes_started_then_leaves(self):
        cmd = service_command(self.w, "W1")
        self.assertEqual(self.dispatch(cmd).kind, "STARTED")
        owners = self.w.s.owners
        self.apply(self.req("PERSON_DEPART", "W1"))
        self.assertEqual(status(self.w.s, "W1"), "DEPARTURE_PENDING")
        self.assertEqual(self.w.s.owners, owners)
        self.w.advance(self.w.s.running[0].earliest_end_h)
        self.s.boundary()
        self.assertEqual(status(self.w.s, "W1"), "DEPARTED")
        self.audit()

    def test_absence_holds_and_return_resumes_same_command(self):
        cmd = service_command(self.w, "W1", rest=True)
        self.assertEqual(self.dispatch(cmd).kind, "STARTED")
        owners = self.w.s.owners
        self.apply(self.req("PERSON_ABSENT", "W1"))
        self.assertEqual(self.w.s.running[0].status, "EXCEPTION")
        self.assertEqual(self.w.s.owners, owners)
        self.w.advance(0.02)
        h = self.w.s.humans[0]
        self.apply(self.req("PERSON_RETURN", "W1"))
        self.assertEqual(self.w.s.humans[0], h)
        resumed = replace(
            cmd,
            id="RESUMED",
            config_sha256=self.w.config_hash,
            expected_revision=self.w.s.revision,
            issued_sim_h=self.w.s.time_h,
            resume_of=cmd.id,
        )
        self.assertEqual(self.dispatch(resumed).kind, "STARTED")
        self.w.advance(self.w.s.running[0].earliest_end_h)
        self.audit()

    def test_unavailable_rejects_regular_dispatch(self):
        self.apply(self.req("PERSON_DEPART", "W1"))
        self.assertIn(
            "PERSON_DISPATCH_DISABLED",
            self.w.dispatch(service_command(self.w, "W1", rest=True)).reason,
        )
        self.audit()

    def test_new_person_actual_walk_and_readback(self):
        self.apply(self.req())
        cmd = service_command(self.w, "W3")
        self.assertEqual(self.dispatch(cmd).kind, "STARTED")
        self.w.advance(self.w.s.running[0].earliest_end_h)
        self.assertEqual(self.w.events[-1].readback.source, "LIGHT_EXECUTOR")
        self.audit()

    def test_return_rejects_unknown_present_and_location(self):
        self.assertEqual(
            self.apply(
                self.req(
                    "PERSON_RETURN",
                    "UNKNOWN",
                    dict(arrival_location="J2", scene_entity_id="UNKNOWN"),
                )
            )["reason"],
            "UNKNOWN_PERSON",
        )
        self.assertEqual(self.apply(self.req("PERSON_RETURN", "W1"))["reason"], "PERSON_STATE")
        self.apply(self.req("PERSON_DEPART", "W1"))
        self.assertEqual(
            self.apply(
                self.req("PERSON_RETURN", "W1", dict(arrival_location="J3", scene_entity_id="W1"))
            )["reason"],
            "PERSON_RETURN_LOCATION",
        )

    def test_s18_person_guard_not_relaxed(self):
        c = base()
        p = replace(c.people[0], id="W3")
        with self.assertRaises(ContractError):
            validate(
                replace(
                    c,
                    people=(*c.people, p),
                    person_positions=(*c.person_positions, m.PersonPosition("W3", "J2")),
                )
            )
        with self.assertRaises(ContractError):
            validate(
                replace(
                    self.c, people=(replace(self.c.people[0], work_rate=0.01), *self.c.people[1:])
                )
            )

    def test_missing_rate_rejects_arrival(self):
        self.s.spec["cost"]["rates"] = [
            r for r in self.s.spec["cost"]["rates"] if r["template_id"] != "P043-W1-v1"
        ]
        self.assertEqual(self.apply(self.req())["reason"], "COST_RATE_REQUIRED")

    def test_saved_damage_rejected(self):
        self.apply(self.req())
        self.w.advance(0.1)
        self.audit()
        path = self.s.output / "session-state.json"
        original = json.loads(path.read_text())
        for field in ("labour_cost", "exposure", "available_h", "defined_from_h"):
            bad = copy.deepcopy(original)
            bad["workforce_statistics"]["people"]["W3"][field] += 1
            path.write_text(json.dumps(bad))
            with self.assertRaises(ValueError):
                verify(self.s.output, require_decisions=False)
        path.write_text(json.dumps(original))

    def test_occupied_arrival_is_atomic(self):
        prefix = tuple(self.w.events)
        config = self.w.config
        p = arrival_payload(self.c, "W3", location="J2")
        self.assertEqual(self.apply(self.req(payload=p))["reason"], "PERSON_ARRIVAL_OCCUPIED")
        self.assertEqual(self.w.config, config)
        self.assertEqual(tuple(self.w.events), prefix)
        self.assertNotIn("W3", self.w.people)

    def test_absence_precedes_same_tick_departure(self):
        a = self.req("PERSON_DEPART", "W1")
        b = self.req("PERSON_ABSENT", "W1")
        self.s.receive(a)
        self.s.receive(b)
        self.s.boundary()
        rows = {r["request_id"]: r for r in self.s.receipts}
        self.assertEqual(rows[b["request_id"]]["status"], "APPLIED")
        self.assertEqual(rows[a["request_id"]]["reason"], "SAME_TICK_CONFLICT")
        self.assertEqual(status(self.w.s, "W1"), "ABSENT")
        self.audit()

    def test_future_arrival_rechecks_qualification(self):
        p = arrival_payload(self.c, "W3")
        p["valid_until_h"] = 0.1
        self.apply(self.req(payload=p, time_rule="AT_SIM_H", requested_sim_h=0.2))
        self.w.advance(0.2)
        self.s.boundary()
        self.assertEqual(self.s.receipts[-1]["reason"], "PERSON_QUALIFICATION_EXPIRED")
        self.assertNotIn("W3", self.w.people)

    def test_expired_arrival_never_creates_person(self):
        self.apply(self.req(time_rule="AT_SIM_H", requested_sim_h=0.1, expires_sim_h=0.1))
        self.w.advance(0.2)
        self.s.boundary()
        self.assertEqual(self.s.receipts[-1]["reason"], "EXPIRED")
        self.assertNotIn("W3", self.w.people)

    def test_departed_geometry_is_excluded_without_deletion(self):
        from adaptive_hrc_scheduling.production_navigation import boxes

        self.assertIn("W1", {b[0] for b in boxes(self.c, self.w.s)})
        self.apply(self.req("PERSON_DEPART", "W1"))
        self.assertNotIn("W1", {b[0] for b in boxes(self.c, self.w.s)})
        self.assertIn("W1", self.w.people)
        self.assertTrue(any(h.person_id == "W1" for h in self.w.s.humans))

    def test_rest_has_presence_and_separate_activity(self):
        cmd = service_command(self.w, "W1", rest=True)
        self.dispatch(cmd)
        self.w.advance(self.c.min_rest_h)
        self.s.persist()
        self.audit()
        row = json.loads((self.s.output / "session-state.json").read_text())[
            "workforce_statistics"
        ]["people"]["W1"]
        self.assertAlmostEqual(row["labour_cost"], self.c.min_rest_h * 10)
        self.assertTrue(all(i["phase"] == "REST" for i in row["activity_intervals"]))
        self.assertEqual(status(self.w.s, "W1"), "PRESENT")

    def test_hold_boundary_stops_before_original_cap(self):
        self.dispatch(service_command(self.w, "W1", rest=True))
        self.apply(self.req("PERSON_ABSENT", "W1"))
        horizon = min(self.s.request_boundaries())
        self.assertGreater(horizon, self.w.s.time_h)
        self.w.advance(horizon)
        self.assertLessEqual(self.w.s.humans[1].fatigue, self.c.cap)
        self.assertEqual(self.w.s.running[0].status, "EXCEPTION")
        self.audit()

    def test_return_rechecks_calendar(self):
        self.apply(self.req("PERSON_DEPART", "W1"))
        self.w.advance(4.1)
        self.assertEqual(
            self.apply(self.req("PERSON_RETURN", "W1"))["reason"], "PERSON_RETURN_CALENDAR"
        )

    def test_qualification_must_cover_action_end(self):
        p = arrival_payload(self.c, "W3")
        p["valid_until_h"] = 0.01
        self.apply(self.req(payload=p))
        cmd = service_command(self.w, "W3", destination="PRE-IN")
        self.assertIn("CALENDAR", self.w.dispatch(cmd).reason)

    def test_missing_generation_or_scene_rejected(self):
        self.apply(self.req())
        self.w.advance(0.1)
        self.audit()
        path = self.s.output / "session-state.json"
        original = json.loads(path.read_text())
        for field in ("generations", "scene_bindings", "workforce_results"):
            bad = copy.deepcopy(original)
            bad[field] = []
            path.write_text(json.dumps(bad))
            with self.assertRaises((ValueError, ContractError, KeyError)):
                verify(self.s.output, require_decisions=False)
        path.write_text(json.dumps(original))

    def test_expired_qualification_availability_is_zero(self):
        p = arrival_payload(self.c, "W3")
        p["valid_until_h"] = 0.05
        self.apply(self.req(payload=p))
        self.w.advance(0.1)
        self.w.advance(0.2)
        self.s.persist()
        self.audit()
        row = json.loads((self.s.output / "session-state.json").read_text())[
            "workforce_statistics"
        ]["people"]["W3"]
        self.assertAlmostEqual(row["available_h"], 0.05)
        self.assertFalse(row["activity_intervals"][-1]["availability"])


if __name__ == "__main__":
    unittest.main()
