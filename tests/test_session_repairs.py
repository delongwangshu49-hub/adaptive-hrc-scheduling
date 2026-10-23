"""Regression cases for the six P04.1 review findings, using real CPU state."""

import copy
import json
import sys
import unittest
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "desktop" / "s19b" / "src"))

import test_session_runtime as baseline
from run_session import execute
from verify_session import verify

from adaptive_hrc_scheduling.contracts.codec import ContractError
from adaptive_hrc_scheduling.contracts.session import digest, request_digest, validate_bundle
from adaptive_hrc_scheduling.control.session import Session, make_spec
from adaptive_hrc_scheduling.domain.production import WorldEvent
from adaptive_hrc_scheduling.planning.production import choose, planning_input


class RepairTests(unittest.TestCase):
    setUp = baseline.SessionTests.setUp
    request = baseline.SessionTests.request

    def release(self):
        p = self.config.products[0]
        self.world.apply_world(
            WorldEvent(
                "REVIEW-ARRIVAL",
                self.world.run_id,
                0,
                0,
                "ORDER_ARRIVAL",
                p.id,
                p.id,
                0,
                "PASS",
                "TEST",
            )
        )

    def dispatch_one(self, sequence):
        obs = self.world.observe()
        binding = self.session.bind_observation(obs)
        plan = choose(self.config, planning_input(self.config, obs, 30000), sequence=sequence)
        self.assertTrue(plan.commands)
        receipt = self.world.dispatch(plan.commands[0])
        self.assertEqual(receipt.kind, "STARTED")
        self.session.bind_dispatch(plan, receipt, binding)
        return receipt

    def fixture(self):
        self.release()
        self.dispatch_one(1)
        self.world.advance(min(r.earliest_end_h for r in self.world.s.running))
        self.session.receive(self.request())
        self.session.boundary()
        receipt = self.dispatch_one(2)
        self.session.persist()
        self.assertEqual(verify(self.session.output)["status"], "PASS")
        return receipt

    def damage(self, mutate, reason):
        path = self.session.output / "session-state.json"
        state = json.loads(path.read_text(encoding="utf-8"))
        mutate(state)
        path.write_text(json.dumps(state), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, reason):
            verify(self.session.output)

    def test_R01_inbox_shapes_reject_and_next_valid_request_applies(self):
        for i, value in enumerate(([], None, "bad", True, 7)):
            (self.session.output / "inbox" / f"bad-{i}.json").write_text(json.dumps(value))
        self.session.submit(self.request())
        self.session.boundary()
        self.assertEqual(len(self.session.protocol_errors), 5)
        self.assertEqual(self.session.version, 1)
        saved = json.loads((self.session.output / "session-state.json").read_text())
        self.assertEqual(len(saved["protocol_errors"]), 5)

    def test_R01_queue_shapes_do_not_abort_writer(self):
        for value in ([], None, "bad"):
            self.session.submit(value)
        self.session.submit(self.request())
        self.session.boundary()
        self.assertEqual(len(self.session.protocol_errors), 3)
        self.assertEqual(self.session.version, 1)

    def test_R02_rejected_retry_is_terminal_after_state_becomes_valid(self):
        req = self.request(expected_state_revision=1)
        original = self.session.receive(req)
        self.release()
        self.assertEqual(self.session.receive(req), original)
        self.session.boundary()
        self.assertEqual([r["status"] for r in self.session.receipts], ["REJECTED"])
        self.assertEqual(self.session.version, 0)
        self.assertEqual(self.session.requests[req["request_id"]], req)
        self.assertEqual(verify(self.session.output)["status"], "PASS")

    def test_R02_rejected_id_conflict_retains_original_and_sequence(self):
        req = self.request(expected_state_revision=1)
        original = self.session.receive(req)
        changed = dict(req, expected_state_revision=0)
        changed["request_digest"] = request_digest(changed)
        self.assertEqual(self.session.receive(changed)["reason"], "IDEMPOTENCY_CONFLICT")
        self.assertEqual(self.session.receive(req), original)
        fresh = self.request("R2", client_sequence=1)
        self.assertEqual(self.session.receive(fresh)["status"], "ACCEPTED")

    def test_R03_real_order_identity_cancels_original_product(self):
        product = self.config.products[0]
        self.assertEqual(self.spec["initial_orders"][0]["order_id"], product.order_id)
        self.session.receive(self.request(kind="ORDER_CANCEL", target_id=product.order_id))
        self.session.boundary()
        self.assertEqual(self.session.receipts[-1]["status"], "APPLIED")
        self.assertEqual(self.world.events[-1].world.entity_id, product.id)
        self.assertEqual(
            self.session.catalog["objects"][product.order_id]["product_ids"], [product.id]
        )
        self.assertEqual(verify(self.session.output)["status"], "PASS")

    def test_R03_product_alias_is_not_an_order(self):
        product = self.config.products[0]
        result = self.session.receive(self.request(kind="ORDER_CANCEL", target_id=product.id))
        self.assertEqual(result["reason"], "TARGET_KIND")
        wrong = copy.deepcopy(self.spec)
        wrong["initial_orders"][0]["order_id"] = product.id
        with self.assertRaisesRegex(ContractError, "INITIAL_OVERRIDE_NOT_MATERIALIZED"):
            Session(wrong, self.world, self.profile, Path(self.temp.name) / "bad-spec")

    def replay_bundle(self):
        req = self.request(source="REPLAY")
        source = dict(requests=[req])
        spec = make_spec(
            self.config,
            self.profile,
            run_id=self.world.run_id,
            mode="INTERACTIVE_REPLAY",
            method="EDD",
            until_h=0.02,
            rates={p.id: 10 for p in self.config.people},
            replay_source=source,
        )
        return dict(
            spec=spec, profile=asdict(self.profile), fixed_requests=[], replay_source=source
        )

    def test_R04_actual_CLI_replay_consumes_bound_journal(self):
        bundle = self.replay_bundle()
        result, session = execute(
            self.config, bundle, Path(self.temp.name) / "replay", max_turns=20
        )
        self.assertEqual(result.audit.status, "PASS")
        self.assertEqual(result.decision_audit.status, "PASS")
        self.assertEqual(session.receipts[-1]["status"], "APPLIED")
        self.assertEqual(session.version, 1)
        self.assertEqual(verify(session.output, require_decisions=True)["decision_audit"], "PASS")
        unlisted = self.request("R2", source="REPLAY")
        self.assertEqual(session.receive(unlisted)["reason"], "PROTOCOL_LOCKED")
        self.assertEqual(verify(session.output, require_decisions=True)["status"], "PASS")

    def test_R04_missing_and_changed_sources_reject_before_output(self):
        bundle = self.replay_bundle()
        for changed in (
            dict(bundle, replay_source=dict(requests=[])),
            {k: v for k, v in bundle.items() if k != "replay_source"},
        ):
            with self.subTest(keys=sorted(changed)), self.assertRaises(ContractError):
                execute(self.config, changed, Path(self.temp.name) / "invalid-replay")
            self.assertFalse((Path(self.temp.name) / "invalid-replay").exists())
        self.assertEqual(
            validate_bundle(bundle)["spec"]["replay_source_sha256"], digest(bundle["replay_source"])
        )

    def test_R04_replay_case_uses_its_bound_manifest(self):
        bundle = self.replay_bundle()
        bundle["spec"]["scenario"] = "F"
        result, session = execute(
            self.config, bundle, Path(self.temp.name) / "replay-f", max_turns=20
        )
        self.assertEqual(result.audit.status, "PASS")
        self.assertEqual(session.version, 1)
        self.assertEqual(session.binding["case"], "F")

    def test_R04_desktop_envelope_checks_same_source_content(self):
        from s19b_desktop.model import PROTOCOL, Draft, InputError, validate_request

        bundle = self.replay_bundle()
        envelope = dict(
            protocol=PROTOCOL,
            run_id=self.world.run_id,
            request_id="DESKTOP-1",
            backend="light",
            draft=Draft().data(),
            created_at="2026-10-22T10:00:00+00:00",
            display_hold_s=0,
            session=bundle,
        )
        self.assertEqual(validate_request(envelope)["session"], bundle)
        altered = copy.deepcopy(envelope)
        altered["session"]["replay_source"]["requests"] = []
        with self.assertRaisesRegex(InputError, "REPLAY_SOURCE_BINDING"):
            validate_request(altered)

    def test_R06_missing_actual_command_binding_rejects(self):
        receipt = self.fixture()
        self.damage(
            lambda s: s["command_bindings"].pop(receipt.command.id), "COMMAND_BINDING_COVERAGE"
        )

    def test_R06_stale_view_and_command_reject(self):
        receipt = self.fixture()

        def mutate(s):
            s["observations"][-1].update(catalog_version=0, catalog_hash=s["versions"][0])
            s["command_bindings"][receipt.command.id].update(
                admitted_catalog_version=0, admitted_catalog_hash=s["versions"][0]
            )

        self.damage(mutate, "APPLICABLE_CATALOG")

    def test_R06_observation_identity_rejects(self):
        self.fixture()
        self.damage(
            lambda s: s["observations"][-1].update(run_id="OTHER", epoch=999, state_revision=-1),
            "OBSERVATION_IDENTITY",
        )

    def test_R06_missing_scene_binding_rejects(self):
        self.fixture()
        self.damage(lambda s: s.update(scene_bindings=[]), "SCENE_BINDING_COVERAGE")

    def test_R06_wrong_scene_mapping_rejects(self):
        self.fixture()
        self.damage(
            lambda s: s["scene_bindings"][0].update(prim_path="/World/FORGED"),
            "SCENE_ACTUAL_MAPPING",
        )

    def test_R06_wrong_budget_profile_rejects(self):
        self.fixture()
        self.damage(
            lambda s: s["budget"].update(
                profile_sha256="f" * 64, profile=dict(s["budget"]["profile"], total_seconds=1)
            ),
            "TOTAL_BUDGET_PROFILE",
        )

    def test_R06_missing_config_rejects_and_decision_scope_is_explicit(self):
        self.fixture()
        result = verify(self.session.output)
        self.assertEqual(result["scope"], "EXECUTION_AND_SESSION_BINDINGS")
        self.assertEqual(result["decision_audit"], "NOT_PROVIDED")
        with self.assertRaisesRegex(ValueError, "DECISIONS_REQUIRED"):
            verify(self.session.output, require_decisions=True)
        (self.session.output / "configuration.json").unlink()
        with self.assertRaisesRegex(ValueError, "CONFIGURATION_REQUIRED"):
            verify(self.session.output)


if __name__ == "__main__":
    unittest.main()
