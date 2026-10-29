"""Fixed-hour scenario and lossless progress transport boundaries."""

import copy
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from build_simulation_production import configuration as base

from adaptive_hrc_scheduling.contracts.production import digest
from adaptive_hrc_scheduling.full_schedule import configuration, is_fixed, mode_proposal
from adaptive_hrc_scheduling.production_backend import ProductionBackend
from adaptive_hrc_scheduling.schedule_proof import decode, encode
from adaptive_hrc_scheduling.timeline_transport import pack, unpack


class FixedHoursTests(unittest.TestCase):
    def test_identity_opt_in_preserves_historical_parameters(self):
        original = base()
        checksum = digest(original)
        fixed = configuration(original)
        self.assertTrue(is_fixed(fixed))
        self.assertEqual(digest(original), checksum)
        self.assertEqual(fixed.operations, original.operations)
        self.assertEqual(fixed.people, original.people)
        self.assertNotEqual(digest(fixed), checksum)
        self.assertEqual(configuration(fixed), fixed)

    def test_four_hour_work_is_fixed_with_nonzero_fatigue(self):
        original = base()
        op = replace(next(o for o in original.operations if o.action == "WORK"), base_h=4)
        from types import SimpleNamespace

        command = SimpleNamespace(roles=(SimpleNamespace(person_id="W1"),))
        for config in (original, configuration(original)):
            w = ProductionBackend(config)
            w.s = replace(w.s, humans=tuple(replace(h, fatigue=0.6) for h in w.s.humans))
            duration = w._duration(op, command)
            self.assertAlmostEqual(duration, 4 if is_fixed(config) else 4 * (1 + op.kappa * 0.6))
            self.assertEqual(w.s.humans[0].fatigue, 0.6)

    def test_cp_result_is_explicitly_a_relaxation_not_execution_proof(self):
        modes, report = mode_proposal(configuration(base()), 0.2)
        self.assertTrue(modes)
        self.assertIn(report["status"], ("OPTIMAL", "FEASIBLE"))
        self.assertEqual(report["bound_scope"], "CORE_RESOURCE_RELAXATION_REQUIRES_FULL_REPLAY")


class ProgressTransportTests(unittest.TestCase):
    def packet(self, n):
        return dict(
            source=dict(
                intervals=list(range(n)),
                plans=[],
                command_bindings={str(i): dict(id=i) for i in range(n)},
                observation=dict(time=n),
            ),
            workforce_statistics=dict(
                people={
                    "W": dict(
                        activity_intervals=list(range(n)),
                        presence_intervals=list(range(n)),
                        availability_intervals=list(range(n)),
                        fatigue=n / 100,
                    )
                }
            ),
        )

    def test_progress_round_trip_and_constant_increment(self):
        producer, consumer = {}, {}
        for n in range(1, 5):
            packet = self.packet(n)
            original = copy.deepcopy(packet)
            producer = pack(packet, producer)
            self.assertEqual(len(packet["source"]["intervals"]), 1)
            self.assertEqual(len(packet["source"]["command_bindings"]), 1)
            consumer = unpack(packet, consumer)
            packet.pop("progress_delta")
            self.assertEqual(packet, original)

    def test_missing_or_repeated_prefix_is_rejected(self):
        first = self.packet(1)
        state = pack(first, {})
        later = self.packet(2)
        pack(later, state)
        with self.assertRaisesRegex(ValueError, "PROGRESS_OFFSET"):
            unpack(later, {})
        with self.assertRaisesRegex(ValueError, "PROGRESS_PREFIX_CHANGED"):
            pack(self.packet(0), state)

    def test_forged_metric_offset_is_rejected(self):
        packet = self.packet(1)
        pack(packet, {})
        packet["progress_delta"]["metrics"]["W"]["activity_intervals"] = 1
        with self.assertRaisesRegex(ValueError, "PROGRESS_METRIC_OFFSET"):
            unpack(packet, {})


class ProofGraphTests(unittest.TestCase):
    def test_lossless_shared_records_and_reference_rejection(self):
        world = ProductionBackend(configuration(base()))
        snapshot = world.snapshot()
        graph = encode(snapshot)
        self.assertEqual(decode(graph), snapshot)
        graph["root"] = {"ref": len(graph["nodes"])}
        with self.assertRaisesRegex(ValueError, "PROOF_GRAPH_REFERENCE"):
            decode(graph)


class OrderUpdateTests(unittest.TestCase):
    def test_metadata_update_preserves_state_rebuilds_and_rejects_tampering(self):
        from test_session_lifecycle import request
        from verify_workforce_session import verify

        from adaptive_hrc_scheduling.contracts.session import request_digest
        from adaptive_hrc_scheduling.control.online import Limits
        from adaptive_hrc_scheduling.control.session import Session
        from adaptive_hrc_scheduling.control.session_budget import Profile
        from adaptive_hrc_scheduling.dynamic_workforce import WorkforceHistory, registry
        from adaptive_hrc_scheduling.workforce_session import configuration as workforce
        from adaptive_hrc_scheduling.workforce_session import make_spec

        c = configuration(workforce(base()))
        p = Profile(
            "UPDATE-TEST",
            Limits(decision_seconds=5, search_seconds=1),
            100,
            2,
            "P042_URGENCY_DUE_PROGRESS_EXPOSURE-r1",
        )
        spec = make_spec(
            c,
            p,
            run_id="UPDATE-TEST",
            method="EDD",
            rates={k: 10 for k in [*[x.id for x in c.people], *registry()]},
        )
        with tempfile.TemporaryDirectory() as folder:
            s = Session(spec, ProductionBackend(c, run_id=spec["run_id"]), p, Path(folder) / "run")
            before = s.world.s
            payload = dict(order_id="ORDER-1", due_sim_h=500, priority="URGENT")
            req = request(s, 1, "ORDER_UPDATE", "ORDER-1", payload)
            s.submit(req)
            s.boundary()
            self.assertEqual(s.receipts[-1]["status"], "APPLIED")
            self.assertEqual(replace(s.world.s, revision=before.revision), before)
            self.assertEqual(s.world.config.products[0].due_h, 500)
            self.assertEqual(s.history.priorities["PRODUCT-1"], "URGENT")
            self.assertEqual(s.policy.dirty, "CATALOG_CHANGE")
            self.assertEqual(WorkforceHistory(c, s.history.generations).current, s.world.config)
            bad = copy.deepcopy(s.history.generations)
            bad[0]["payload"]["due_sim_h"] = 501
            with self.assertRaisesRegex(ValueError, "GENERATION_RECONSTRUCTION"):
                WorkforceHistory(c, bad)
            stale = request(s, 2, "ORDER_UPDATE", "ORDER-1", payload)
            stale["expected_target_revision"] = 0
            stale["request_digest"] = request_digest(stale)
            self.assertEqual(s.receive(stale)["reason"], "TARGET_STALE")
            s.persist()
            result = verify(s.output, require_decisions=False)
            self.assertEqual(result["status"], "PASS")


if __name__ == "__main__":
    unittest.main()
