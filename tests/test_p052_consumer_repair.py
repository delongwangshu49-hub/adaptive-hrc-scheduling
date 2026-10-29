"""Consumer load fixes retain immutable ownership and corruption rejection."""

import copy
import json
import random
import time
import unittest
from dataclasses import dataclass, replace
from types import SimpleNamespace
from unittest.mock import patch

import test_p051_client as fixtures

from adaptive_hrc_scheduling.contracts.codec import ContractError, _checked_records, decode
from adaptive_hrc_scheduling.control.audit_cache import ExecutionCheckpoint, exact_equal
from adaptive_hrc_scheduling.domain.production import ExecutionEvent
from adaptive_hrc_scheduling.timeline_memory import share_json, share_record
from adaptive_hrc_scheduling.timeline_validation import validate


@dataclass(frozen=True)
class Config:
    values: tuple[int, ...]


@dataclass(frozen=True)
class Event:
    revision: int


class OwnershipTests(unittest.TestCase):
    def setUp(self):
        self.config = Config((1, 2))
        self.snapshot = SimpleNamespace(run_id="R", epoch=0, config_sha256="H", events=())

    def test_evicted_codec_proof_survives_fork_and_ledger_remains_private(self):
        checkpoint = ExecutionCheckpoint()
        ledger = {"items": [1]}
        checkpoint.save(self.config, self.snapshot, ledger)
        _checked_records.clear()
        fork = checkpoint.fork()
        fork.save(self.config, self.snapshot, {"items": [2]})
        ledger["items"].append(9)
        restored = checkpoint.restore(self.config, self.snapshot)[1]
        restored["items"].append(8)
        self.assertEqual(checkpoint.restore(self.config, self.snapshot)[1], {"items": [1]})
        self.assertEqual(fork.restore(self.config, self.snapshot)[1], {"items": [2]})

    def test_different_config_identity_is_checked_after_saved_proof(self):
        checkpoint = ExecutionCheckpoint()
        checkpoint.save(self.config, self.snapshot, {})
        with self.assertRaises(ContractError):
            checkpoint.save(replace(self.config, values=(True,)), self.snapshot, {})
        self.assertIs(checkpoint._config, self.config)

    def test_mutable_config_never_establishes_reusable_identity_proof(self):
        config = Config([1, 2])
        checkpoint = ExecutionCheckpoint()
        checkpoint.save(config, self.snapshot, {})
        self.assertEqual(checkpoint.restore(config, self.snapshot), (0, None))
        config.values.append(False)
        with self.assertRaises(ContractError):
            checkpoint.save(config, self.snapshot, {})

    def test_appended_or_replaced_event_still_gets_strict_check(self):
        checkpoint = ExecutionCheckpoint()
        valid = Event(1)
        self.snapshot.events = (valid,)
        checkpoint.save(self.config, self.snapshot, {})
        for events in [(valid, Event(False)), (Event(1.0),)]:
            with self.subTest(events=events), self.assertRaises(ContractError):
                checkpoint.save(
                    self.config, SimpleNamespace(**dict(vars(self.snapshot), events=events)), {}
                )
            self.assertEqual(checkpoint._events, (valid,))


class RowOwnershipTests(unittest.TestCase):
    setUp = fixtures.AdapterTests.setUp
    tearDown = fixtures.AdapterTests.tearDown

    def test_read_slice_checks_contiguous_packets_before_projecting_once(self):
        for n in range(1, 8):
            self.session.world.advance(n / 100)
            self.session.projection.publish(self.session.world.observe())
        old_sequence = self.client.consumer.sequence
        tick = iter(n / 5 for n in range(20))
        clock = SimpleNamespace(perf_counter=lambda: next(tick), monotonic=time.monotonic)
        with patch("p051_desktop.client.time", clock):
            view = self.client.poll()
        self.assertEqual(self.client.consumer.sequence, old_sequence + 3)
        self.assertEqual(view["reader_metrics"]["packets"], 3)
        self.assertEqual(view["status"], "VERIFIED")
        while self.client.consumer.sequence < old_sequence + 7:
            self.client.poll()
        self.assertEqual(self.client.consumer.sequence, old_sequence + 7)
        self.assertIsNone(self.client.error)

    def test_nested_corruption_rejected_without_changing_rows_or_cache(self):
        self.session.world.advance(0.01)
        self.session.projection.publish(self.session.world.observe())
        self.client.poll()
        c = self.client.consumer
        rows = copy.deepcopy(c.rows)
        row = next(r for r in rows.values() if r["row_kind"] != "PLAN")
        row["unexpected_nested"] = {"values": [True, 1.0]}
        before = copy.deepcopy(rows)
        cache = dict(c._validation_cache)
        with self.assertRaisesRegex(ValueError, "TIMELINE_ROWS_FROM_SOURCE"):
            validate(
                self.client.packet,
                c.events,
                rows,
                c.basis,
                prefix_hashes=c._prefix_hashes,
                cache=cache,
            )
        self.assertEqual(rows, before)
        self.assertEqual(cache, c._validation_cache)
        good = copy.deepcopy(c.rows)
        validate(
            self.client.packet,
            c.events,
            c.rows,
            c.basis,
            prefix_hashes=c._prefix_hashes,
            cache=cache,
        )
        self.assertEqual(c.rows, good)

    def test_shared_events_equal_original_decode_and_incoming_packet_stays_owned(self):
        for time_h in (0.01, 0.02, 0.03):
            self.session.world.advance(time_h)
            self.session.projection.publish(self.session.world.observe())
            packet = json.loads((self.path / "timeline.jsonl").read_text().splitlines()[-1])
            before = copy.deepcopy(packet)
            self.client.consumer.consume(packet)
            self.assertTrue(exact_equal(packet, before))
            c = self.client.consumer
            original = tuple(decode(ExecutionEvent, e) for e in c.events)
            self.assertTrue(exact_equal(c._validation_cache["decoded_events"], original))
            if packet["events"]:
                packet["events"][-1]["state"]["revision"] = False
                self.assertIs(type(c.events[-1]["state"]["revision"]), int)


class SharingTests(unittest.TestCase):
    def test_blocked_reason_is_not_repeated_per_forecast_interval(self):
        from p051_desktop.gantt import ScheduleReader

        row = dict(
            command_id="C",
            operation_id="O",
            activity_id="A",
            product_id="P",
            start_h=1,
            end_h=2,
            roles=[],
            command=dict(mode_id="M", attempt=0, service=None),
        )
        reader = ScheduleReader()
        reader.verified["current"] = dict(
            format="P051-FULL-SCHEDULE-1", plan_id="PLAN", version=2, intervals=[row] * 4000
        )
        reader.verified["old"] = dict(
            format="P051-FULL-SCHEDULE-1", plan_id="PLAN", version=1, intervals=[row]
        )
        reason = "FULL_NO_FEASIBLE_SCHEDULE:" + "detail;" * 10000
        ref = dict(artifact_sha256="current", failure=reason)
        result = reader.read_full(None, ref)
        self.assertEqual(ref["failure"], reason)
        self.assertTrue(all(r["proposal_state"] == "RETAINED_BLOCKED" for r in result[:-1]))
        self.assertEqual(result[-1]["proposal_state"], "SUPERSEDED")
        self.assertTrue(all("blocked_reason" not in r for r in result))
        self.assertLess(len(json.dumps(result)), 3_000_000)
        reader.close()

    def test_json_sharing_preserves_all_scalar_types_and_previous_values(self):
        rng = random.Random(52)
        atoms = [None, True, False, 0, 1, -1, 0.0, -0.0, 1.0, "a", "b"]
        for _ in range(500):
            previous = {"x": [rng.choice(atoms) for _ in range(8)], "y": {"v": rng.choice(atoms)}}
            current = copy.deepcopy(previous)
            current["x"][rng.randrange(8)] = rng.choice(atoms)
            old = copy.deepcopy(previous)
            result = share_json(copy.deepcopy(current), previous)
            self.assertTrue(exact_equal(result, current))
            self.assertTrue(exact_equal(previous, old))

    def test_native_sharing_keeps_numeric_types_and_reuses_only_equal_subtrees(self):
        previous = Config((1, 2))
        self.assertIs(share_record(Config((1, 2)), previous), previous)
        for value in (True, 1.0):
            current = Config((value, 2))
            result = share_record(current, previous)
            self.assertTrue(exact_equal(current, result))
            self.assertIsNot(result, previous)
        self.assertEqual(share_record(-0.0, 0.0).hex(), "-0x0.0p+0")
        self.assertIs(share_record([1], (1,)).__class__, list)
