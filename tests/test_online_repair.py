"""S19 post-release regressions: independent provenance and exact cache boundaries."""

import copy
import gzip
import hashlib
import json
import math
import sys
import tempfile
import unittest
from dataclasses import dataclass, replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from audit_online_continuation import commitments
from audit_online_provenance import PlanHistory, decision_for, plan_rows
from build_simulation_production import configuration

from adaptive_hrc_scheduling.algorithms.simulation_joint import terminal
from adaptive_hrc_scheduling.contracts.codec import as_data, canonical_json, checked, decode
from adaptive_hrc_scheduling.control.audit_cache import DecisionCheckpoint, ExecutionCheckpoint
from adaptive_hrc_scheduling.control.production_decisions import check_decisions, record
from adaptive_hrc_scheduling.production_backend import ProductionBackend
from adaptive_hrc_scheduling.production_checker import check_run


class StrictCheckpointTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = configuration()
        cls.world = ProductionBackend(cls.config)
        cls.snapshot = cls.world.snapshot()
        cls.rows = (record(terminal(cls.config, cls.world.observe())),)

    def test_equal_numeric_revision_cannot_reuse_execution_certificate(self):
        checkpoint = ExecutionCheckpoint()
        self.assertEqual(checkpoint.verify(self.config, self.snapshot).status, "PASS")
        for value in (float(self.snapshot.state.revision), False):
            with self.subTest(value=value):
                bad = replace(self.snapshot, state=replace(self.snapshot.state, revision=value))
                full = check_run(self.config, bad)
                self.assertNotEqual(full.status, "PASS")
                self.assertEqual(checkpoint.verify(self.config, bad), full)

    def test_equal_numeric_epoch_cannot_restore_execution_ledger(self):
        checkpoint = ExecutionCheckpoint()
        checkpoint.verify(self.config, self.snapshot)
        bad = replace(self.snapshot, epoch=float(self.snapshot.epoch))
        self.assertEqual(checkpoint.restore(self.config, bad), (0, None))
        self.assertEqual(checkpoint.verify(self.config, bad), check_run(self.config, bad))
        self.assertNotEqual(checkpoint.verify(self.config, bad).status, "PASS")

    def test_equal_numeric_event_count_cannot_reuse_causal_certificate(self):
        checkpoint = DecisionCheckpoint()
        self.assertEqual(checkpoint.verify(self.config, self.snapshot, self.rows).status, "PASS")
        for value in (0.0, False):
            bad = copy.deepcopy(self.rows)
            bad[0]["event_count"] = value
            full = check_decisions(self.config, self.snapshot, bad)
            self.assertNotEqual(full.status, "PASS")
            self.assertEqual(checkpoint.verify(self.config, self.snapshot, bad), full)

    def test_appended_rows_do_not_hide_invalid_cached_prefix(self):
        checkpoint = DecisionCheckpoint()
        checkpoint.verify(self.config, self.snapshot, self.rows)
        # A nonterminal prefix is privately retained for subsequent append-only audits.
        checkpoint.save_rows(self.config, self.snapshot, self.rows + self.rows, {})
        bad = copy.deepcopy(self.rows)
        bad[0]["event_count"] = 0.0
        self.assertEqual(
            checkpoint.restore_rows(self.config, self.snapshot, bad + self.rows), (0, None)
        )

    def test_capture_preserves_changed_type_and_defensively_owns_mutable_rows(self):
        checkpoint = DecisionCheckpoint()
        checkpoint.verify(self.config, self.snapshot, self.rows)
        bad = copy.deepcopy(self.rows)
        bad[0]["event_count"] = 0.0
        captured = checkpoint._capture_rows(bad)
        self.assertIs(type(captured[0]["event_count"]), float)
        bad[0]["event_count"] = "changed after capture"
        self.assertEqual(captured[0]["event_count"], 0.0)

    def test_valid_copied_records_and_forks_keep_full_audit_result(self):
        checkpoint = DecisionCheckpoint()
        expected = check_decisions(self.config, self.snapshot, self.rows)
        self.assertEqual(checkpoint.verify(self.config, self.snapshot, self.rows), expected)
        self.assertEqual(
            checkpoint.fork().verify(self.config, self.snapshot, copy.deepcopy(self.rows)), expected
        )


class SignedZeroTests(unittest.TestCase):
    def test_exact_json_and_hash_are_independent_of_zero_call_order(self):
        for values in ((0.0, -0.0, 0.0), (-0.0, 0.0, -0.0)):
            for value in values:
                actual = canonical_json({"values": [value, True, 0, 1.0]})
                expected = json.dumps(
                    {"values": [value, True, 0, 1.0]},
                    sort_keys=True,
                    separators=(",", ":"),
                    allow_nan=False,
                )
                self.assertEqual(actual, expected)
                self.assertEqual(
                    hashlib.sha256(actual.encode()).hexdigest(),
                    hashlib.sha256(expected.encode()).hexdigest(),
                )

    def test_native_decode_preserves_zero_sign_after_opposite_cache_entry(self):
        @dataclass(frozen=True)
        class Item:
            x: float

        for value in (0.0, -0.0, 0.0, -0.0):
            item = Item(value)
            actual, expected = checked(item), decode(Item, as_data(item))
            self.assertEqual(math.copysign(1, actual.x), math.copysign(1, expected.x))
            self.assertEqual(
                canonical_json(actual), json.dumps(as_data(expected), separators=(",", ":"))
            )

    def test_normalized_json_still_intentionally_merges_zero_spellings(self):
        for value in (0, 0.0, -0.0):
            self.assertEqual(canonical_json((value,), normalize_numbers=True), "[0]")


class ProvenanceTests(unittest.TestCase):
    def setUp(self):
        self.command = dict(
            operation_id="A", product_id="P", attempt=0, mode_id="H", roles=[], issued_sim_h=1.0
        )
        self.proposal = plan_rows([self.command])[0]
        self.sources = {"candidate": ("observation", [self.proposal])}
        self.row = dict(
            run_id="RUN",
            epoch=0,
            observation_id="OBS",
            event_count=0,
            observation_sha256="observation",
            before=[],
            after=[self.proposal],
            cache_sha256="candidate",
            verified_candidate_sha256="candidate",
            cache_invalidated=False,
            selected_source="VERIFIED_CACHE",
            selected_proposal=self.proposal,
            commitments_after=[],
            plan_reason="EDD",
        )
        self.decision = dict(plan=dict(commands=[self.command]))

    def test_original_proposal_time_survives_actual_late_dispatch(self):
        actual = dict(self.command, issued_sim_h=1.25)
        PlanHistory(self.sources).check(self.row, {}, dict(plan=dict(commands=[actual])))

    def test_selected_time_cannot_be_replaced_by_actual_time(self):
        self.row["selected_proposal"] = dict(self.proposal, start_h=1.25)
        with self.assertRaisesRegex(ValueError, "SELECTED_PROPOSAL_SOURCE"):
            PlanHistory(self.sources).check(self.row, {}, self.decision)

    def test_joint_pending_and_selected_time_edit_cannot_hide_delay(self):
        self.row["selected_proposal"] = dict(self.proposal, start_h=1.25)
        self.row["after"] = [self.row["selected_proposal"]]
        with self.assertRaisesRegex(ValueError, "PENDING_PLAN_SOURCE"):
            PlanHistory(self.sources).check(self.row, {}, self.decision)

    def test_empty_before_cannot_remove_a_comparable_unstarted_plan(self):
        history = PlanHistory(self.sources)
        history.check(self.row, {}, self.decision)
        later = dict(self.row, verified_candidate_sha256=None)
        with self.assertRaisesRegex(ValueError, "PLAN_HISTORY"):
            history.check(later, {}, self.decision)

    def test_completed_plan_is_excluded_using_actual_state(self):
        history = PlanHistory(self.sources)
        history.check(self.row, {}, self.decision)
        later = dict(self.row, after=[], verified_candidate_sha256=None, selected_proposal=None)
        history.check(later, dict(completed=["A"]), dict(plan=dict(commands=[])))

    def test_candidate_from_another_observation_is_rejected(self):
        self.row["observation_sha256"] = "foreign"
        with self.assertRaisesRegex(ValueError, "CANDIDATE_OBSERVATION_SOURCE"):
            PlanHistory(self.sources).check(self.row, {}, self.decision)

    def test_current_rule_plan_is_bound_to_driver_command(self):
        self.row.update(selected_source="RULE", cache_sha256=None, verified_candidate_sha256=None)
        PlanHistory({}).check(self.row, {}, self.decision)
        self.row["after"] = [dict(self.proposal, start_h=0)]
        with self.assertRaisesRegex(ValueError, "PENDING_PLAN_SOURCE"):
            PlanHistory({}).check(self.row, {}, self.decision)

    def test_pending_order_is_bound_to_candidate(self):
        second = dict(self.proposal, operation="B")
        self.sources["candidate"] = ("observation", [self.proposal, second])
        self.row["after"] = [second, self.proposal]
        with self.assertRaisesRegex(ValueError, "PENDING_PLAN_SOURCE"):
            PlanHistory(self.sources).check(self.row, {}, self.decision)

    def test_invented_promise_cannot_override_candidate_time(self):
        changed = dict(self.proposal, start_h=1.25)
        self.row.update(commitments_after=[changed], after=[changed], selected_proposal=changed)
        with self.assertRaisesRegex(ValueError, "COMMITMENT_PLAN_SOURCE"):
            PlanHistory(self.sources).check(self.row, {}, self.decision)

    def test_stale_flag_cannot_erase_executed_plan_history(self):
        self.row["stale_dispatch_rejected"] = True
        with self.assertRaisesRegex(ValueError, "STALE_DISPATCH_SOURCE"):
            PlanHistory(self.sources).check(self.row, {}, self.decision)

    def test_shield_label_cannot_erase_a_dispatched_plan(self):
        self.row.update(plan_reason="S19:DISPATCH_SHIELD:edited", after=[])
        with self.assertRaisesRegex(ValueError, "SHIELD_DISPATCH_SOURCE"):
            PlanHistory(self.sources).check(self.row, {}, self.decision)

    def test_recovery_label_requires_an_actual_held_command(self):
        self.row["selected_source"] = "ACTUAL_RECOVERY"
        with self.assertRaisesRegex(ValueError, "RECOVERY_SOURCE"):
            PlanHistory(self.sources).check(self.row, {}, self.decision)

    def test_rule_label_cannot_bypass_future_promises(self):
        self.row.update(selected_source="RULE", commitments_after=[self.proposal])
        with self.assertRaisesRegex(ValueError, "RULE_BYPASSES_COMMITMENT"):
            PlanHistory(self.sources).check(self.row, {}, self.decision)

    def test_late_gate_wait_preserves_original_pending_proposal(self):
        for reason in ("S19:DECISION_DEADLINE", "S19:PAUSED", "S19:CANCELLED"):
            PlanHistory(self.sources).check(
                self.row, {}, dict(plan=dict(commands=[], reason=reason))
            )

    def test_stale_gate_binds_new_observation_at_original_decision_sequence(self):
        self.row.update(stale_dispatch_rejected=True, sequence=2, time_h=1.0)
        decision = dict(
            run_id="RUN",
            epoch=0,
            event_count=1,
            sampled_h=1.1,
            observation_id="NEW",
            plan=dict(commands=[], reason="S19:STALE_OBSERVATION"),
        )
        selected = decision_for(self.row, {("sequence", 2): decision})
        self.assertIs(selected, decision)
        PlanHistory(self.sources).check(self.row, {}, selected)
        self.assertIsNone(decision_for(self.row, {("sequence", 2): dict(decision, epoch=1)}))

    def test_saved_commitment_auditor_rejects_coordinated_delay_and_receipt_edits(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            candidate = dict(anchor_sha256="observation", steps=[dict(plan=self.decision["plan"])])
            sha = hashlib.sha256(
                json.dumps(candidate, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest()
            row = dict(
                self.row,
                cache_sha256=sha,
                verified_candidate_sha256=sha,
                commitments_before=[],
                commitment_releases=[],
                time_h=1.25,
                receipt_kind="STARTED",
                receipt_id="EV-1",
                actual_start=dict(
                    operation="A", attempt=0, proposed_h=1.0, actual_h=1.25, delay_h=0.25
                ),
            )
            event = dict(
                id="EV-1",
                kind="STARTED",
                command=dict(self.command, issued_sim_h=1.25),
                occurred_sim_h=1.25,
                state={},
            )
            decision = dict(
                plan=dict(commands=[event["command"]]),
                run_id="RUN",
                epoch=0,
                observation_id="OBS",
                receipt_id="EV-1",
            )
            for name, value in (
                ("configuration.json", dict(operations=[])),
                ("predeclared-online-limits.json", dict(future_commitment_h=0)),
                ("candidate-0.json", candidate),
            ):
                (folder / name).write_text(json.dumps(value), encoding="utf-8")
            for name, value in (("events", event), ("decisions", decision)):
                with gzip.open(folder / (name + ".jsonl.gz"), "wt", encoding="utf-8") as stream:
                    stream.write(json.dumps(value) + "\n")

            def check(value):
                (folder / "online-journal.json").write_text(json.dumps([value]), encoding="utf-8")
                return commitments(folder)

            self.assertEqual(check(row)["status"], "PASS")
            edited = copy.deepcopy(row)
            edited["selected_proposal"]["start_h"] = 1.25
            edited["actual_start"].update(proposed_h=1.25, delay_h=0)
            self.assertEqual(check(edited)["status"], "FAILED")
            edited = dict(row, receipt_id="EV-OTHER")
            self.assertEqual(check(edited)["status"], "FAILED")


if __name__ == "__main__":
    unittest.main()
