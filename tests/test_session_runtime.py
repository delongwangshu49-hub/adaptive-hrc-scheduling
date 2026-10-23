"""Actual P04.1 consumer invariants; no mock worker or alternate legal domain."""

import copy
import json
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from build_simulation_production import configuration

from adaptive_hrc_scheduling.contracts.codec import ContractError
from adaptive_hrc_scheduling.contracts.session import digest, loads, request_digest, validate_spec
from adaptive_hrc_scheduling.control.online import Limits
from adaptive_hrc_scheduling.control.session import Session, make_spec, submit_file
from adaptive_hrc_scheduling.control.session_budget import BudgetAccount, Profile
from adaptive_hrc_scheduling.planning.production import choose, planning_input
from adaptive_hrc_scheduling.production_backend import ProductionBackend


class SessionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.config = configuration()
        self.profile = Profile("TEST", Limits(decision_seconds=2, search_seconds=1), 10, 2)
        self.world = ProductionBackend(self.config, run_id="P041-TEST")
        self.spec = make_spec(
            self.config,
            self.profile,
            run_id=self.world.run_id,
            rates={p.id: 10 for p in self.config.people},
        )
        self.session = Session(self.spec, self.world, self.profile, Path(self.temp.name) / "run")
        self.target = self.config.devices[-1].id

    def request(self, key="R1", **changes):
        s = self.session
        r = dict(
            run_id=self.world.run_id,
            epoch=0,
            request_id=key,
            producer_id="TEST",
            client_sequence=int(key[1:]),
            source="CLI",
            kind="DEVICE_FAIL",
            target_id=self.target,
            payload=dict(reason="TEST"),
            expected_catalog_version=s.version,
            expected_state_revision=self.world.s.revision,
            expected_target_revision=s.catalog["objects"][self.target]["revision"],
            time_rule="IMMEDIATE",
            expires_sim_h=self.world.s.time_h + 2,
            submitted_at_utc="2026-10-22T08:00:00+00:00",
        )
        r.update(changes)
        r["request_digest"] = request_digest(r)
        return r

    def test_real_application_preserves_c0_engine_and_prefix(self):
        engine = id(self.world)
        r = self.request()
        self.session.submit(r)
        self.session.boundary()
        self.assertIn(self.target, self.world.s.failed_resources)
        self.assertEqual(self.session.version, 1)
        self.assertEqual(engine, id(self.session.world))
        self.assertEqual(self.world.config_hash, self.spec["initial_config_sha256"])
        state = loads((self.session.output / "session-state.json").read_bytes())
        self.assertEqual(state["execution"]["events"][0]["world"]["id"], "REQUEST-R1")
        self.assertEqual(state["receipts"][0]["status"], "ACCEPTED")
        self.assertEqual(state["receipts"][-1]["status"], "APPLIED")

    def test_idempotent_after_version_advance_and_conflicting_retry(self):
        r = self.request()
        self.session.receive(r)
        self.session.boundary()
        original = self.session.receive(r)
        conflict = dict(r, payload=dict(reason="OTHER"))
        conflict["request_digest"] = request_digest(conflict)
        self.assertEqual(self.session.receive(conflict)["reason"], "IDEMPOTENCY_CONFLICT")
        self.assertEqual(self.session.receive(r), original)
        self.assertEqual(self.session.version, 1)

    def test_stale_and_wrong_identity_reject_without_accept_sequence(self):
        for index, (change, reason) in enumerate(
            (
                (dict(epoch=1), "IDENTITY_EPOCH"),
                (dict(expected_catalog_version=5), "CATALOG_STALE"),
                (dict(expected_state_revision=5), "STATE_STALE"),
                (dict(expected_target_revision=5), "TARGET_STALE"),
            ),
            1,
        ):
            with self.subTest(reason=reason):
                receipt = self.session.receive(self.request("R" + str(index), **change))
                self.assertEqual(receipt["reason"], reason)
                self.assertNotIn("accept_sequence", receipt)
                self.assertEqual(self.session.version, 0)

    def test_future_rebases_unrelated_delta_but_retains_request(self):
        future = self.request(time_rule="AT_SIM_H", requested_sim_h=1)
        self.session.receive(future)
        other = self.config.devices[0].id
        self.session.receive(self.request("R2", target_id=other))
        self.session.boundary()
        self.assertEqual(self.session.version, 1)
        self.world.advance(1)
        self.session.boundary()
        self.assertEqual(self.session.version, 2)
        self.assertEqual(self.session.requests["R1"], future)
        self.assertEqual(self.session.transitions[-1]["rebase_from_version"], 0)

    def test_future_target_conflict(self):
        self.session.receive(self.request(time_rule="AT_SIM_H", requested_sim_h=1))
        self.session.receive(self.request("R2"))
        self.session.boundary()
        self.world.advance(1)
        self.session.boundary()
        self.assertEqual(self.session.receipts[-1]["reason"], "TARGET_CONFLICT")
        self.assertEqual(self.session.version, 1)

    def test_expiry_never_rewrites_payload(self):
        r = self.request(time_rule="AT_SIM_H", requested_sim_h=1, expires_sim_h=1)
        self.session.receive(r)
        self.world.advance(1.01)
        self.session.boundary()
        self.assertEqual(self.session.receipts[-1]["reason"], "EXPIRED")
        self.assertEqual(self.session.requests["R1"], r)

    def test_same_tick_failure_beats_repair(self):
        evidence = next(e.id for e in self.config.evidence if e.status == "PASS")
        self.session.receive(
            self.request(kind="DEVICE_REPAIR", payload=dict(repair_evidence_id=evidence))
        )
        self.session.receive(self.request("R2"))
        self.session.boundary()
        self.assertEqual(self.session.receipts[-1]["reason"], "SAME_TICK_CONFLICT")
        self.assertIn(self.target, self.world.s.failed_resources)

    def test_bad_repair_evidence_does_not_apply(self):
        r = self.request(kind="DEVICE_REPAIR", payload=dict(repair_evidence_id="UNKNOWN"))
        self.assertEqual(self.session.receive(r)["reason"], "REPAIR_EVIDENCE_INVALID")

    def test_sequence_reject_and_independent_producers(self):
        self.session.receive(self.request())
        self.assertEqual(
            self.session.receive(self.request("R2", client_sequence=1))["reason"],
            "CLIENT_SEQUENCE_OLD",
        )
        self.assertEqual(
            self.session.receive(self.request("R3", client_sequence=1, producer_id="OTHER"))[
                "status"
            ],
            "ACCEPTED",
        )

    def test_unimplemented_personnel_rejects_instead_of_fake_success(self):
        r = self.request(
            kind="PERSON_ABSENT",
            target_id=self.config.people[0].id,
            payload=dict(reason="ABSENT", safety_policy="HOLD_AND_VERIFY"),
        )
        self.assertEqual(self.session.receive(r)["reason"], "CAPABILITY_NOT_IMPLEMENTED")

    def test_atomic_mailbox_consumes_once_and_retains_invalid_raw(self):
        submit_file(self.session.output, self.request())
        (self.session.output / "inbox" / "bad.json").write_text('{"x":1,"x":2}')
        self.session.boundary()
        self.session.boundary()
        self.assertEqual(self.session.version, 1)
        self.assertEqual(len(self.session.protocol_errors), 1)

    def test_fixed_manual_rejected(self):
        spec = make_spec(
            self.config,
            self.profile,
            run_id=self.world.run_id,
            mode="FIXED_PROTOCOL",
            scenario="N",
            rates={p.id: 10 for p in self.config.people},
        )
        fixed = Session(spec, self.world, self.profile, Path(self.temp.name) / "fixed")
        self.assertEqual(fixed.receive(self.request())["reason"], "PROTOCOL_LOCKED")

    def test_wrong_source_profile_and_initial_inputs_rejected(self):
        for key, value in (
            ("source_sha256", "a" * 64),
            ("profile_sha256", "b" * 64),
            ("initial_config_sha256", "c" * 64),
        ):
            with self.subTest(key=key), self.assertRaises(ContractError):
                Session(
                    dict(self.spec, **{key: value}),
                    self.world,
                    self.profile,
                    Path(self.temp.name) / key,
                )

    def test_missing_or_duplicate_rates_rejected(self):
        for duplicate in (False, True):
            spec = copy.deepcopy(self.spec)
            if duplicate:
                spec["cost"]["rates"].append(spec["cost"]["rates"][0])
            else:
                spec["cost"]["rates"].pop()
            with self.assertRaises(ContractError):
                validate_spec(spec)

    def test_real_values_normalize_but_integer_bool_rejected(self):
        self.assertEqual(digest(dict(x=1.0)), digest(dict(x=1)))
        for value in (True, 0.0):
            with self.assertRaises(ContractError):
                validate_spec(dict(self.spec, epoch=value))
        for raw in ('{"a":1,"a":2}', '{"a":NaN}', '{"a":Infinity}'):
            with self.assertRaises((ContractError, ValueError)):
                loads(raw)

    def test_client_mutation_cannot_change_worker_spec(self):
        self.spec["method"] = "EDD"
        self.assertEqual(self.session.spec["method"], "ADAPTIVE")

    def test_saved_independent_reconstruction_and_six_corruptions(self):
        from verify_session import verify

        self.session.receive(self.request())
        self.session.boundary()
        self.session.bind_observation(self.world.observe())
        self.session.persist()
        path = self.session.output / "session-state.json"
        original = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(verify(self.session.output)["status"], "PASS")
        changes = (
            lambda d: d["versions"].__setitem__(1, "f" * 64),
            lambda d: d["deltas"][0].__setitem__("new_hash", "f" * 64),
            lambda d: d["receipts"][0].__setitem__("accept_sequence", None),
            lambda d: d["observations"][0].__setitem__("event_prefix_hash", "f" * 64),
            lambda d: d["budget"].__setitem__("used_s", 1),
            lambda d: d["requests"]["R1"]["payload"].__setitem__("reason", "FORGED"),
        )
        for index, mutate in enumerate(changes):
            damaged = copy.deepcopy(original)
            mutate(damaged)
            path.write_text(json.dumps(damaged), encoding="utf-8")
            with self.subTest(corruption=index), self.assertRaises(ValueError):
                verify(self.session.output)

    def test_shipped_parser_fields_match_frozen_contract_and_examples(self):
        from adaptive_hrc_scheduling.contracts.session import SCHEMA

        root = Path(__file__).resolve().parents[1]
        frozen = json.loads(
            (root / "docs/public_delivery_r2/p032_contract_schema_r3.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(
            SCHEMA,
            {
                key: {
                    name: {k: row[k] for k in ("type", "required")}
                    for name, row in record["fields"].items()
                }
                for key, record in frozen["records"].items()
            },
        )
        examples = json.loads(
            (root / "docs/public_backend/session_spec_examples.json").read_text(encoding="utf-8")
        )
        for row in examples["spec_cases"]:
            try:
                validate_spec(row["spec"])
                accepted = True
            except (ContractError, ValueError):
                accepted = False
            with self.subTest(case=row["id"]):
                self.assertEqual(accepted, row["expected"] == "VALID")

    def test_edd_shares_shield_and_disables_search(self):
        spec = dict(self.spec, method="EDD")
        edd = Session(spec, self.world, self.profile, Path(self.temp.name) / "edd")
        obs = self.world.observe()
        value = planning_input(self.config, obs)
        actual = edd.policy.decide(value, self.world.snapshot(), ())
        reference = choose(self.config, value)
        self.assertEqual(actual.commands, reference.commands)
        self.assertFalse(edd.policy.candidates)
        self.assertEqual(edd.binding["method"], "EDD")

    def test_unrelated_cache_preserved_and_promises_never_cleared(self):
        # Obtain an actual legal preparation from a delivered release fact.
        from adaptive_hrc_scheduling.domain.production import WorldEvent

        p = self.config.products[0]
        self.world.apply_world(
            WorldEvent(
                "RELEASE", self.world.run_id, 0, 0, "ORDER_ARRIVAL", p.id, p.id, 0, "PASS", "TEST"
            )
        )
        obs = self.world.observe()
        plan = choose(self.config, planning_input(self.config, obs, 10000))
        self.assertTrue(plan.commands)
        command = plan.commands[0]
        policy = self.session.policy
        policy.pending = policy.committed = (command,)
        policy.catalog_changed([self.target], self.world.operations)
        self.assertEqual(policy.committed, (command,))
        self.assertEqual(policy.pending, (command,))
        policy.committed = ()
        self.assertEqual(
            policy.catalog_changed(
                [command.operation_id], self.world.operations, protected_commands=(command,)
            ),
            [],
        )
        self.assertEqual(policy.pending, (command,))
        unrelated = next(
            d.id
            for d in self.config.devices
            if d.id
            not in (
                command.service.operation.equipment
                if command.service
                else self.world.operations[command.operation_id].equipment
            )
        )
        self.assertEqual(policy.catalog_changed([unrelated], self.world.operations), [])

    def test_old_completed_service_private_route_does_not_break_catalog_change(self):
        from adaptive_hrc_scheduling.domain.production import WorldEvent

        p = self.config.products[0]
        self.world.apply_world(
            WorldEvent(
                "RELEASE", self.world.run_id, 0, 0, "ORDER_ARRIVAL", p.id, p.id, 0, "PASS", "TEST"
            )
        )
        obs = self.world.observe()
        plan = choose(self.config, planning_input(self.config, obs, 10000))
        command = plan.commands[0]
        self.assertIsNotNone(command.service)
        receipt = self.world.dispatch(command)
        self.assertEqual(receipt.kind, "STARTED")
        self.world.advance(next(r.earliest_end_h for r in self.world.s.running))
        self.assertFalse(self.world.s.running)
        self.assertIn(command.operation_id, self.world.operations)
        self.session.receive(self.request())
        self.session.boundary()
        self.assertEqual(self.session.version, 1)
        self.assertEqual(self.session.receipts[-1]["status"], "APPLIED")


class BudgetTests(unittest.TestCase):
    def test_ordinary_search_cannot_spend_three_change_slots(self):
        profile = Profile("RESERVE", Limits(decision_seconds=30, search_seconds=25), 180, 3)
        account = BudgetAccount(profile)
        account.charge(dict(sequence=1, trigger="INITIAL", decision_seconds=90, search_call=1))
        self.assertFalse(account.can_search("PERIODIC"))
        for index in range(3):
            self.assertTrue(account.can_search("CATALOG_CHANGED"))
            account.charge(
                dict(
                    sequence=index + 2,
                    trigger="CATALOG_CHANGED",
                    decision_seconds=30,
                    search_call=index + 2,
                )
            )
        self.assertFalse(account.can_search("CATALOG_CHANGED"))
        self.assertEqual(account.change_calls, 3)

    def test_budget_overrun_is_reported(self):
        account = BudgetAccount(Profile("X", Limits(decision_seconds=2, search_seconds=1), 4, 1))
        account.charge(dict(sequence=1, trigger="FEEDBACK", decision_seconds=5, search_call=1))
        self.assertEqual(account.entries[-1]["overrun_s"], 1)
        self.assertFalse(account.can_search("FEEDBACK"))

    def test_profiles_validate_total_and_complete_search(self):
        profile = Profile("X", Limits(decision_seconds=2, search_seconds=1), 6, 1)
        for changed in (
            replace(profile, total_seconds=True),
            replace(profile, total_seconds=float("inf")),
            replace(profile, change_reserve_calls=0),
            replace(profile, limits=replace(profile.limits, search_seconds=0.05)),
        ):
            with self.assertRaises(ContractError):
                changed.validate()


if __name__ == "__main__":
    unittest.main()
