"""P04.2 R01–R03: real transactions and independent archive rejection."""

import copy
import json
import unittest
from pathlib import Path

import test_dynamic_orders as baseline
from verify_dynamic_session import verify

from adaptive_hrc_scheduling.contracts.codec import ContractError
from adaptive_hrc_scheduling.contracts.session import digest, request_digest
from adaptive_hrc_scheduling.control.session import Session, make_spec
from adaptive_hrc_scheduling.production_backend import ProductionBackend


class DynamicRepairTests(unittest.TestCase):
    setUpClass = classmethod(baseline.DynamicOrderTests.setUpClass.__func__)
    setUp = baseline.DynamicOrderTests.setUp
    request = baseline.DynamicOrderTests.request
    apply = baseline.DynamicOrderTests.apply

    def cancel(self, target, sequence=3):
        r = self.request(f"NEW-{sequence}")
        r.update(kind="ORDER_CANCEL", target_id=target, payload={"reason": "REPAIR_TEST"})
        r["expected_target_revision"] = self.session.catalog["objects"][target]["revision"]
        r["request_digest"] = request_digest(r)
        return self.apply(r)

    def archive(self):
        self.session.persist()
        return verify(self.session.output, require_decisions=False)

    def damage(self, change, reason):
        self.apply(self.request(quantity=2))
        self.session.bind_observation(self.world.observe())
        self.session.persist()
        path = self.session.output / "session-state.json"
        original = json.loads(path.read_text())
        bad = copy.deepcopy(original)
        change(bad)
        path.write_text(json.dumps(bad))
        with self.assertRaisesRegex((ValueError, ContractError), reason):
            verify(self.session.output, require_decisions=False)
        path.write_text(json.dumps(original))
        self.assertEqual(self.archive()["status"], "PASS")

    def test_future_product_collision_preserves_order_and_cancel(self):
        self.assertEqual(self.apply(self.request(order_id="PRODUCT-3"))["status"], "APPLIED")
        before = self.world.snapshot()
        old_order = copy.deepcopy(self.session.catalog["objects"]["PRODUCT-3"])
        self.assertEqual(self.apply(self.request("NEW-2"))["reason"], "GENERATION_ID_COLLISION")
        self.assertEqual(self.world.snapshot(), before)
        self.assertEqual(self.session.catalog["objects"]["PRODUCT-3"], old_order)
        self.assertEqual(self.cancel("PRODUCT-3")["status"], "APPLIED")
        self.assertTrue(self.world._product("PRODUCT-2").cancelled)
        self.assertEqual(self.archive()["status"], "PASS")

    def test_collision_in_later_batch_member_rejects_whole_batch(self):
        self.apply(self.request(order_id="PRODUCT-4"))
        before = self.world.snapshot()
        self.assertEqual(
            self.apply(self.request("NEW-2", quantity=2))["reason"], "GENERATION_ID_COLLISION"
        )
        self.assertEqual(self.world.snapshot(), before)
        self.assertEqual(self.session.version, 1)
        self.assertEqual(self.archive()["products"], 2)

    def test_future_operation_namespace_collision_rejects(self):
        self.apply(self.request(order_id="PRODUCT-3.KIT.U1"))
        before = self.world.snapshot()
        self.assertEqual(self.apply(self.request("NEW-2"))["reason"], "GENERATION_ID_COLLISION")
        self.assertEqual(self.world.snapshot(), before)
        self.assertEqual(self.archive()["status"], "PASS")

    def test_initial_order_identity_is_also_reserved(self):
        from dataclasses import replace

        c = replace(
            self.config,
            products=tuple(replace(p, order_id="PRODUCT-2") for p in self.config.products),
        )
        w = ProductionBackend(c, run_id=self.world.run_id)
        spec = make_spec(c, self.profile, run_id=w.run_id, rates={p.id: 10 for p in c.people})
        self.world = w
        self.session = Session(spec, w, self.profile, Path(self.temp.name) / "reserved-initial")
        self.assertEqual(self.apply(self.request())["reason"], "GENERATION_ID_COLLISION")
        self.assertEqual(self.session.catalog["objects"]["PRODUCT-2"]["kind"], "order")

    def test_unrelated_orders_keep_cancel_and_archive(self):
        self.apply(self.request(order_id="CUSTOM-ORDER"))
        self.apply(self.request("NEW-2"))
        self.assertEqual(self.cancel("CUSTOM-ORDER")["status"], "APPLIED")
        self.assertEqual(self.archive()["status"], "PASS")

    def test_future_accepted_request_needs_no_applied_yet(self):
        self.apply(self.request())
        r = self.request("NEW-2")
        r.update(time_rule="AT_SIM_H", requested_sim_h=5)
        r["request_digest"] = request_digest(r)
        self.apply(r)
        self.assertEqual(self.session.receipts[-1]["status"], "WAITING_BOUNDARY")
        self.assertEqual(self.archive()["status"], "PASS")

    def test_application_time_resolves_original_request_not_mutable_admission(self):
        r = self.request()
        r.update(time_rule="AT_SIM_H", requested_sim_h=5)
        r["request_digest"] = request_digest(r)
        self.apply(r)
        self.world.advance(5)
        self.session.boundary()
        self.assertEqual(self.session.receipts[-1]["status"], "APPLIED")
        self.assertEqual(self.archive()["status"], "PASS")
        path = self.session.output / "session-state.json"
        saved = json.loads(path.read_text())
        saved["admissions"][r["request_id"]]["due_h"] = 4
        path.write_text(json.dumps(saved))
        with self.assertRaisesRegex(ValueError, "APPLIED_ACTUAL_BOUNDARY"):
            verify(self.session.output, require_decisions=False)

    def test_legitimate_idempotency_conflict_rejection_preserved(self):
        r = self.request()
        self.apply(r)
        conflict = copy.deepcopy(r)
        conflict["payload"]["due_sim_h"] += 1
        conflict["request_digest"] = request_digest(conflict)
        self.assertEqual(self.session.receive(conflict)["reason"], "IDEMPOTENCY_CONFLICT")
        self.assertEqual(self.archive()["status"], "PASS")

    def test_control_applied_without_catalog_delta_is_valid(self):
        self.apply(self.request())
        r = self.request("NEW-2")
        r.update(kind="STOP_REQUEST", target_id=self.world.run_id, payload={})
        r["request_digest"] = request_digest(r)
        self.apply(r)
        self.assertEqual(self.session.receipts[-1]["status"], "APPLIED")
        self.assertEqual(self.archive()["status"], "PASS")

    def test_missing_applied_rejects(self):
        self.damage(lambda s: s["receipts"].pop(), "APPLIED_REQUIRED")

    def test_wrong_applied_digest_rejects(self):
        self.damage(lambda s: s["receipts"][-1].update(request_digest="0" * 64), "RECEIPT_REQUEST")

    def test_wrong_applied_event_rejects(self):
        self.damage(
            lambda s: s["receipts"][-1].update(event_id="NO-EVENT"), "APPLIED_COMMIT_BINDING"
        )

    def test_wrong_applied_version_rejects(self):
        self.damage(
            lambda s: s["receipts"][-1].update(catalog_version_after=0), "APPLIED_COMMIT_BINDING"
        )

    def test_wrong_applied_time_rejects(self):
        self.damage(
            lambda s: s["receipts"][-1].update(actual_applied_sim_h=5), "APPLIED_COMMIT_BINDING"
        )

    def test_wrong_applied_revision_rejects(self):
        self.damage(lambda s: s["receipts"][-1].update(state_revision=0), "APPLIED_COMMIT_BINDING")

    def test_wrong_applied_accept_sequence_rejects(self):
        self.damage(lambda s: s["receipts"][-1].update(accept_sequence=99), "RECEIPT_ADMISSION")

    def test_duplicate_applied_rejects_even_with_valid_hash_chain(self):
        def duplicate(s):
            last = copy.deepcopy(s["receipts"][-1])
            last.update(
                receipt_sequence=len(s["receipts"]) + 1,
                receipt_id="RECEIPT-3",
                previous_receipt_hash=digest(s["receipts"][-1]),
            )
            s["receipts"].append(last)

        self.damage(duplicate, "TERMINAL_IMMUTABLE")

    def test_zero_counts_rejects(self):
        def zero(s):
            for row in s["capacity_events"]:
                row["counts"] = {k: 0 for k in row["counts"]}

        self.damage(zero, "CAPACITY_RECONSTRUCTED")

    def test_impossible_capacity_event_boundary_rejects(self):
        self.damage(
            lambda s: s["capacity_events"][-1].update(event_count=999999), "CAPACITY_EVENT_BOUNDARY"
        )

    def test_impossible_capacity_clock_rejects(self):
        self.damage(lambda s: s["capacity_events"][-1].update(sim_h=999999), "CAPACITY_CLOCK")

    def test_missing_capacity_history_rejects(self):
        self.damage(lambda s: s["capacity_events"].clear(), "CAPACITY_HISTORY_REQUIRED")

    def test_false_final_active_products_rejects(self):
        self.damage(lambda s: s["active_products"].clear(), "FINAL_ACTIVE_PRODUCTS")

    def test_missing_wip_admission_rejects(self):
        def remove(s):
            i = next(i for i, r in enumerate(s["capacity_events"]) if r["status"] == "WIP_ADMITTED")
            s["capacity_events"].pop(i)

        self.damage(remove, "WIP_ADMISSION")

    def test_wrong_wip_admission_order_rejects(self):
        def wrong(s):
            r = next(r for r in s["capacity_events"] if r["status"] == "WIP_ADMITTED")
            r["product_id"] = "PRODUCT-3"

        self.damage(wrong, "WIP_ADMISSION")

    def test_queue_underreport_rejects(self):
        self.damage(
            lambda s: s["capacity_events"][-1]["counts"].update(count_queued=2),
            "CAPACITY_RECONSTRUCTED",
        )

    def test_cancel_frees_empty_slot_and_promotes_queue(self):
        self.apply(self.request(quantity=3))
        self.assertNotIn("PRODUCT-4", self.session.active_products)
        self.assertEqual(self.cancel("ORDER-1")["status"], "APPLIED")
        self.assertIn("PRODUCT-4", self.session.active_products)
        self.assertEqual(self.archive()["capacity"]["count_space_reserved"], 3)

    def test_batch_queue_gate_reconstructed_before_promotion(self):
        self.apply(self.request(quantity=2))
        self.assertEqual(self.archive()["status"], "PASS")
        directory = self.session.output
        spec = json.loads((directory / "run-spec.json").read_text())
        spec["capacity"]["max_queued_products"] = 1
        binding = json.loads((directory / "launch-binding.json").read_text())
        binding["run_spec_sha256"] = digest(spec)
        saved = json.loads((directory / "session-state.json").read_text())
        saved["binding"] = binding
        for name, data in (
            ("run-spec.json", spec),
            ("launch-binding.json", binding),
            ("session-state.json", saved),
        ):
            (directory / name).write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError, "CREATE_CAPACITY_ADMISSION"):
            verify(directory, require_decisions=False)

    def test_promotion_cannot_precede_its_order_arrival(self):
        def move(s):
            for row in s["capacity_events"]:
                if row["status"] == "WIP_ADMITTED":
                    row["event_count"] -= 1

        self.damage(move, "WIP_ADMISSION|CAPACITY_RECONSTRUCTED|GENERATION_CAPACITY_COVERAGE")


if __name__ == "__main__":
    unittest.main()
