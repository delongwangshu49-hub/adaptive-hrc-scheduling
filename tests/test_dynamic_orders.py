"""P042 real transactions, versioned audit and capacity/urgency counterexamples."""

import copy
import json
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from build_simulation_production import configuration
from verify_dynamic_session import verify

from adaptive_hrc_scheduling.contracts.codec import ContractError
from adaptive_hrc_scheduling.contracts.production import digest as config_digest
from adaptive_hrc_scheduling.contracts.production import validate
from adaptive_hrc_scheduling.contracts.session import request_digest, validate_request
from adaptive_hrc_scheduling.control.online import Limits
from adaptive_hrc_scheduling.control.session import Session, make_spec
from adaptive_hrc_scheduling.control.session_budget import Profile
from adaptive_hrc_scheduling.dynamic_orders import CatalogHistory, template_registry
from adaptive_hrc_scheduling.production_backend import ProductionBackend
from adaptive_hrc_scheduling.production_checker import check_run


class DynamicOrderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = configuration()
        cls.profile = Profile(
            "P042-TEST",
            Limits(decision_seconds=2, search_seconds=1),
            100,
            2,
            "P042_URGENCY_DUE_PROGRESS_EXPOSURE-r1",
        )

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.world = ProductionBackend(self.config, run_id="P042-TEST")
        self.spec = make_spec(
            self.config,
            self.profile,
            run_id=self.world.run_id,
            rates={p.id: 10 for p in self.config.people},
            method="EDD",
        )
        self.session = Session(
            self.spec, self.world, self.profile, Path(self.temp.name) / "session"
        )

    def request(self, key="NEW-1", **payload):
        n = int(key.split("-")[-1])
        p = dict(
            order_id=key,
            template_id="SR-W1",
            template_revision="v1",
            template_sha256=template_registry()["SR-W1"],
            quantity=1,
            due_sim_h=300,
            priority="NORMAL",
            material_plan_id="TEMPLATE-JIT-v1",
            arrival_rule="REQUEST_EFFECTIVE_TIME",
        )
        p.update(payload)
        r = dict(
            run_id=self.world.run_id,
            epoch=0,
            request_id="REQUEST-" + key,
            producer_id="TEST",
            client_sequence=n,
            source="CLI",
            kind="ORDER_CREATE",
            target_id=p["order_id"],
            payload=p,
            expected_catalog_version=self.session.version,
            expected_state_revision=self.world.s.revision,
            expected_target_revision=0,
            time_rule="IMMEDIATE",
            expires_sim_h=self.world.s.time_h + 10,
            submitted_at_utc="2026-10-22T11:00:00+00:00",
        )
        r["request_digest"] = request_digest(r)
        return r

    def apply(self, r):
        result = self.session.receive(r)
        self.session.boundary()
        return self.session.receipts[-1] if result["status"] == "ACCEPTED" else result

    def test_first_registration_generates_complete_unique_objects(self):
        old = self.world.config
        engine = id(self.world)
        self.assertEqual(self.apply(self.request(quantity=2))["status"], "APPLIED")
        self.assertEqual(self.session.order_products["NEW-1"], ["PRODUCT-2", "PRODUCT-3"])
        self.assertEqual(len(self.world.config.operations), 3 * len(old.operations))
        self.assertEqual(id(self.world), engine)
        self.assertEqual(self.world.epoch, 0)
        self.assertEqual(self.spec["initial_config_sha256"], config_digest(old))
        for pid in ("PRODUCT-2", "PRODUCT-3"):
            self.assertTrue(any(o.product_id == pid for o in self.world.config.operations))
            self.assertTrue(any(o.product_id == pid for o in self.world.config.lots))
            self.assertEqual(self.world._mass(pid), 0)
        self.assertEqual(
            check_run(
                self.world.config, self.world.snapshot(), catalog=self.session.history
            ).status,
            "PASS",
        )

    def test_S18_due_guard_remains_strict(self):
        altered = replace(
            self.config, products=tuple(replace(p, due_h=42) for p in self.config.products)
        )
        with self.assertRaisesRegex(ContractError, "SIM_PRESERVED_PRODUCT:due_h"):
            validate(altered)

    def test_material_plan_does_not_mint_inventory(self):
        self.apply(self.request(material_plan_id="TEMPLATE-DELAY-1H-v1"))
        self.assertFalse(self.session.material_ready("PRODUCT-2"))
        self.assertTrue(
            all(
                not self.world._lot(x.id).arrived and self.world._lot(x.id).available == 0
                for x in self.world.config.lots
                if x.product_id == "PRODUCT-2"
            )
        )
        self.world.advance(1)
        self.assertTrue(self.session.material_ready("PRODUCT-2"))
        self.assertTrue(
            all(
                not self.world._lot(x.id).arrived
                for x in self.world.config.lots
                if x.product_id == "PRODUCT-2"
            )
        )

    def test_future_request_is_not_observable_before_apply(self):
        r = self.request()
        r.update(time_rule="AT_SIM_H", requested_sim_h=1)
        r["request_digest"] = request_digest(r)
        self.apply(r)
        self.assertEqual(self.session.version, 0)
        self.assertEqual(len(self.world.config.products), 1)
        self.world.advance(1)
        self.session.boundary()
        self.assertEqual(self.session.version, 1)

    def test_due_is_rechecked_at_actual_application(self):
        r = self.request(due_sim_h=0.5)
        r.update(time_rule="AT_SIM_H", requested_sim_h=1)
        r["request_digest"] = request_digest(r)
        self.session.receive(r)
        self.world.advance(1)
        self.session.boundary()
        self.assertEqual(self.session.receipts[-1]["reason"], "DUE_PASSED")
        self.assertEqual(len(self.world.config.products), 1)

    def test_four_cumulative_products_are_not_wip_limit(self):
        self.apply(self.request(quantity=3))
        cap = self.session.capacity()
        self.assertEqual(
            (cap["count_registered"], cap["count_instantiated"], cap["count_queued"]), (4, 4, 1)
        )
        self.assertEqual(cap["count_space_reserved"], 3)
        self.assertEqual(cap["count_wip"], 0)

    def test_lifetime_overflow_is_atomic(self):
        self.session.spec["capacity"]["max_lifetime_products"] = 4
        before = config_digest(self.world.config)
        self.assertEqual(self.apply(self.request(quantity=4))["reason"], "LIFETIME_LIMIT")
        self.assertEqual(config_digest(self.world.config), before)

    def test_open_overflow_is_atomic(self):
        self.session.spec["capacity"]["max_lifetime_products"] = 20
        self.assertEqual(self.apply(self.request(quantity=4))["reason"], "QUEUE_LIMIT")
        self.assertEqual(self.session.version, 0)

    def test_queue_overflow_has_separate_gate(self):
        self.session.spec["capacity"]["max_queued_products"] = 1
        self.assertEqual(self.apply(self.request(quantity=2))["reason"], "QUEUE_LIMIT")

    def test_capacity_rechecked_after_two_future_admissions(self):
        self.session.spec["capacity"]["max_open_products"] = 3
        self.session.spec["capacity"]["max_lifetime_products"] = 20
        a, b = self.request(quantity=2), self.request("NEW-2", quantity=2)
        self.assertEqual(self.session.receive(a)["status"], "ACCEPTED")
        self.assertEqual(self.session.receive(b)["status"], "ACCEPTED")
        self.session.boundary()
        self.assertEqual(self.session.receipts[-1]["reason"], "QUEUE_LIMIT")
        self.assertEqual(len(self.world.config.products), 3)

    def test_rejected_id_stays_rejected(self):
        r = self.request(template_sha256="0" * 64)
        first = self.apply(r)
        self.assertEqual(first["reason"], "TEMPLATE_DIGEST")
        self.assertEqual(self.session.receive(r), first)

    def test_duplicate_applied_is_not_regenerated(self):
        r = self.request()
        self.apply(r)
        n = len(self.world.events)
        self.assertEqual(self.session.receive(r)["status"], "APPLIED")
        self.assertEqual(len(self.world.events), n)

    def test_historical_order_id_cannot_be_reused(self):
        self.assertEqual(self.apply(self.request(order_id="ORDER-1"))["reason"], "ORDER_ID_USED")

    def test_unknown_material_plan_rejects(self):
        self.assertEqual(
            self.apply(self.request(material_plan_id="UNCONTROLLED"))["reason"],
            "MATERIAL_PLAN_UNSUPPORTED",
        )

    def test_quantity_wire_rejects_bool_and_zero(self):
        for q in (True, 0, -1, 1.0):
            with self.assertRaises(ContractError):
                validate_request(self.request(quantity=q))

    def test_product_order_generated_id_collision_rolls_back(self):
        r = self.request(order_id="PRODUCT-2")
        self.assertEqual(self.apply(r)["reason"], "GENERATION_ID_COLLISION")
        self.assertEqual(len(self.world.config.products), 1)

    def test_SRW2_new_template_has_own_bom(self):
        self.apply(self.request(template_id="SR-W2", template_sha256=template_registry()["SR-W2"]))
        self.assertEqual(self.world.config.products[-1].variant, "SR-W2")
        self.assertEqual(self.world.config.products[-1].mass_t, 8.05)

    def test_saved_generations_independently_rebuild(self):
        self.apply(self.request(quantity=2))
        self.session.persist()
        self.assertEqual(verify(self.session.output, require_decisions=False)["status"], "PASS")

    def test_saved_template_tamper_rejects(self):
        self.apply(self.request())
        g = copy.deepcopy(self.session.history.generations)
        g[0]["payload"]["template_sha256"] = "0" * 64
        with self.assertRaises(ContractError):
            CatalogHistory(self.config, g)

    def test_missing_generation_rejects_execution(self):
        self.apply(self.request())
        self.assertNotEqual(
            check_run(
                self.world.config, self.world.snapshot(), catalog=CatalogHistory(self.config)
            ).status,
            "PASS",
        )

    def test_initial_multi_product_order_is_grouped(self):
        from build_simulation_production import configuration

        c = configuration(products=2)
        c = replace(c, products=tuple(replace(p, order_id="ONE-ORDER") for p in c.products))
        spec = make_spec(c, self.profile, run_id="MULTI", rates={p.id: 10 for p in c.people})
        self.assertEqual(len(spec["initial_orders"]), 1)
        self.assertEqual(spec["initial_orders"][0]["quantity"], 2)

    def test_unstarted_queue_promotes_after_empty_cancel(self):
        self.apply(self.request(quantity=3))
        self.assertNotIn("PRODUCT-4", self.session.active_products)
        self.world.apply_world(
            __import__(
                "adaptive_hrc_scheduling.domain.production", fromlist=["WorldEvent"]
            ).WorldEvent(
                "CANCEL-EMPTY",
                self.world.run_id,
                0,
                0,
                "CANCEL",
                "PRODUCT-1",
                "PRODUCT-1",
                0,
                "PASS",
                "ML-METHOD",
            )
        )
        self.session.refresh_capacity()
        self.assertIn("PRODUCT-4", self.session.active_products)

    def test_incremental_prefix_hash_is_exact_original_canonical_digest(self):
        from adaptive_hrc_scheduling.contracts.codec import as_data
        from adaptive_hrc_scheduling.contracts.session import digest

        self.assertEqual(self.session.event_prefix_hash(), digest([]))
        self.apply(self.request())
        self.assertEqual(
            self.session.event_prefix_hash(), digest([as_data(e) for e in self.world.events])
        )
        self.world.advance(0.1)
        self.assertEqual(
            self.session.event_prefix_hash(), digest([as_data(e) for e in self.world.events])
        )

    def test_original_running_command_completes_after_generation_without_resigning(self):
        from adaptive_hrc_scheduling.control.production_loop import run

        run(
            self.world,
            self.session.scenario(),
            session=self.session,
            joint_policy=self.session.policy,
            stop_condition=lambda w: bool(w.s.running),
            max_turns=50,
        )
        self.assertTrue(self.world.s.running)
        old = tuple(self.world.s.running)
        old_commands = {r.command.id: config_digest(r.command) for r in old}
        prefix = tuple(self.world.events)
        self.apply(self.request())
        self.assertEqual(tuple(self.world.s.running), old)
        self.assertEqual(tuple(self.world.events[: len(prefix)]), prefix)
        self.world.advance(min(r.earliest_end_h for r in old))
        for e in self.world.events[len(prefix) :]:
            if e.command and e.command.id in old_commands:
                self.assertEqual(config_digest(e.command), old_commands[e.command.id])
        self.assertEqual(
            check_run(
                self.world.config, self.world.snapshot(), catalog=self.session.history
            ).status,
            "PASS",
        )

    def test_saved_corruptions_rejected(self):
        self.apply(self.request(quantity=2))
        self.session.bind_observation(self.world.observe())
        self.session.persist()
        path = self.session.output / "session-state.json"
        original = json.loads(path.read_text())

        def missing_scene(s):
            s["scene_bindings"].pop()

        def wrong_scene(s):
            s["scene_bindings"][0]["scene_entity_id"] = "WRONG"

        def missing_generation(s):
            s["generations"].clear()

        def wrong_chain(s):
            s["deltas"][0]["new_hash"] = "0" * 64

        def wrong_observation(s):
            s["observations"][0]["catalog_version"] = 0

        def wrong_wip(s):
            s["capacity_events"][-1]["counts"]["count_wip"] = 99

        def wrong_catalog(s):
            s["catalog"]["objects"]["NEW-1"]["product_ids"] = ["WRONG"]

        def wrong_protection(s):
            s["generations"][0]["protected_after_sha256"] = "0" * 64

        def wrong_budget(s):
            s["budget"]["profile_sha256"] = "0" * 64

        for damage in (
            missing_scene,
            wrong_scene,
            missing_generation,
            wrong_chain,
            wrong_observation,
            wrong_wip,
            wrong_catalog,
            wrong_protection,
            wrong_budget,
        ):
            bad = copy.deepcopy(original)
            damage(bad)
            path.write_text(json.dumps(bad))
            with (
                self.subTest(damage=damage.__name__),
                self.assertRaises((ValueError, ContractError, KeyError)),
            ):
                verify(self.session.output, require_decisions=False)
        path.write_text(json.dumps(original))

    def test_future_promise_is_preserved_byte_for_byte(self):
        from adaptive_hrc_scheduling.domain import production as m

        op = next(o for o in self.config.operations if o.action == "TRANSFER")
        command = m.DispatchCommand(
            self.config.schema_version,
            self.config.id,
            config_digest(self.config),
            self.world.run_id,
            0,
            "PROMISED",
            op.product_id,
            op.activity_id,
            op.id,
            op.attempt_index,
            op.unit_index,
            "MOVE",
            5,
            0,
            tuple(m.RoleBinding(r.id, r.id) for r in op.roles),
            research=self.config.research,
        )
        validate(command, config=self.config)
        self.session.policy.pending = self.session.policy.committed = (command,)
        before = config_digest(command)
        self.apply(self.request())
        self.assertEqual(self.session.policy.committed, (command,))
        self.assertIs(self.session.policy.committed[0], command)
        self.assertEqual(config_digest(command), before)

    def test_equal_due_priority_control_changes_legal_clearance(self):
        from adaptive_hrc_scheduling.planning.production import choose, planning_input

        self.apply(self.request(due_sim_h=100))
        self.apply(self.request("NEW-2", due_sim_h=100, priority="URGENT"))
        place = next(p.id for p in self.world.config.places if p.parent == "RECEIVE")
        self.world.s = replace(
            self.world.s,
            positions=tuple(
                replace(p, location=place, support=place) if p.id == "FORK-01" else p
                for p in self.world.s.positions
            ),
        )
        obs = self.world.observe()
        value = planning_input(self.world.config, obs, 10000)
        urgent = choose(self.world.config, value, order_bias=self.session.history.priority_bias())
        neutral = choose(self.world.config, value)
        self.assertEqual(urgent.commands[0].product_id, "PRODUCT-3")
        self.assertEqual(neutral.commands[0].product_id, "PRODUCT-2")

    def test_initial_four_split_wip_reservation_and_queue(self):
        c = configuration(products=4)
        world = ProductionBackend(c, run_id="INITIAL-FOUR")
        spec = make_spec(c, self.profile, run_id=world.run_id, rates={p.id: 10 for p in c.people})
        session = Session(spec, world, self.profile, Path(self.temp.name) / "initial-four")
        self.assertEqual(session.capacity()["count_registered"], 4)
        self.assertEqual(session.capacity()["count_space_reserved"], 3)
        self.assertEqual(session.capacity()["count_queued"], 1)

    def test_initial_lifetime_overflow_rejects_before_session_output(self):
        c = configuration(products=5)
        world = ProductionBackend(c, run_id="INITIAL-FIVE")
        spec = make_spec(c, self.profile, run_id=world.run_id, rates={p.id: 10 for p in c.people})
        output = Path(self.temp.name) / "initial-five"
        with self.assertRaisesRegex(ContractError, "INITIAL_LIFETIME_LIMIT"):
            Session(spec, world, self.profile, output)
        self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
