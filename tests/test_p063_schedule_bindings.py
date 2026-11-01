"""Delivered references must not borrow trust from a valid cached plan."""

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from p063_schedule_bindings import ScheduleBindings, validate_archive  # noqa: E402

from adaptive_hrc_scheduling.contracts.session import digest  # noqa: E402


class ScheduleBindingTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        (self.root / "full-schedules").mkdir()
        self.spec = dict(run_id="BINDING-RUN", epoch=2)
        self.events = [dict(id="E1"), dict(id="E2")]
        self.plans = []
        self.refs = []
        for version in [1, 2]:
            row = dict(
                command_id=f"C{version}",
                operation_id=f"O{version}",
                activity_id="A",
                product_id="P",
                roles=[],
                start_h=version,
                end_h=version + 1,
            )
            plan = dict(
                format="P051-FULL-SCHEDULE-1",
                plan_id="BINDING-RUN:FULL",
                version=version,
                anchor_events=version,
                anchor_h=version,
                event_prefix_sha256=digest(self.events[:version]),
                completion_h=10,
                intervals=[row],
            )
            checksum = digest(plan)
            self.write(f"full-schedules/{checksum}.json", plan)
            self.plans.append(plan)
            self.refs.append(
                dict(
                    format=plan["format"],
                    plan_id=plan["plan_id"],
                    version=version,
                    artifact_sha256=checksum,
                    failure=None,
                    solve_calls=version,
                    planning=False,
                    completion_h=10,
                    anchor_events=version,
                )
            )
        self.report = dict(
            version=2,
            used_calls=2,
            plan_sha256=self.refs[-1]["artifact_sha256"],
            failure=None,
            history=[
                dict(
                    status="ADOPTED",
                    version=i,
                    plan_sha256=self.refs[i - 1]["artifact_sha256"],
                    at_h=i,
                    anchor=[0, 0, i],
                )
                for i in [1, 2]
            ],
        )
        self.write("run-spec.json", self.spec)
        self.write("full-schedule-state.json", self.report)
        self.packets = [
            dict(
                events=[self.events[i - 1]],
                full_schedule=self.refs[i - 1],
                envelope=dict(
                    run_id=self.spec["run_id"],
                    epoch=2,
                    run_spec_sha256=digest(self.spec),
                    event_count=i,
                    sampled_sim_h=i,
                ),
            )
            for i in [1, 2]
        ]
        self.save_stream(self.packets)

    def write(self, name, value):
        (self.root / name).write_text(json.dumps(value) + "\n", encoding="utf-8")

    def save_stream(self, packets):
        (self.root / "timeline.jsonl").write_text(
            "".join(json.dumps(packet) + "\n" for packet in packets), encoding="utf-8"
        )
        self.write("timeline-latest.json", dict(full_schedule=packets[-1]["full_schedule"]))

    def view(self):
        return dict(
            full_schedule=copy.deepcopy(self.refs[-1]),
            rows=[
                dict(
                    plan["intervals"][0],
                    row_id=f"full:{i}:0",
                    row_kind="FULL_PLAN",
                    plan_id=plan["plan_id"],
                    plan_version=i,
                    proposal_state="CURRENT_PLAN" if i == 2 else "SUPERSEDED",
                )
                for i, plan in enumerate(self.plans, 1)
            ],
        )

    def test_valid_references_and_exact_current_and_superseded_rows(self):
        binding = validate_archive(self.root)
        self.assertEqual(binding.check_projection(self.view())["full_plan_rows"], 2)

    def test_resigned_reference_metadata_cannot_borrow_an_audited_digest(self):
        for key, value in [
            ("version", 102),
            ("plan_id", "OTHER:FULL"),
            ("anchor_events", 0),
            ("completion_h", 99),
            ("version", True),
        ]:
            with self.subTest(key=key, value=value):
                packets = copy.deepcopy(self.packets)
                packets[-1]["full_schedule"][key] = value
                self.save_stream(packets)
                with self.assertRaisesRegex(ValueError, "FULL_REFERENCE"):
                    validate_archive(self.root)

    def test_null_or_missing_or_empty_final_reference_is_rejected(self):
        for value in [None, {}, dict(self.refs[-1], artifact_sha256=None)]:
            with self.subTest(value=value):
                packets = copy.deepcopy(self.packets)
                packets[-1]["full_schedule"] = value
                self.save_stream(packets)
                with self.assertRaises(ValueError):
                    validate_archive(self.root)

    def test_future_or_wrong_prefix_anchor_is_rejected(self):
        packets = copy.deepcopy(self.packets)
        packets[0]["full_schedule"] = self.refs[-1]
        self.save_stream(packets)
        with self.assertRaisesRegex(ValueError, "VISIBLE_ANCHOR"):
            validate_archive(self.root)
        self.packets[-1]["events"][0]["id"] = "OTHER-EVENT"
        self.save_stream(self.packets)
        with self.assertRaisesRegex(ValueError, "VISIBLE_ANCHOR"):
            validate_archive(self.root)

    def test_self_consistent_stale_final_reference_cannot_replace_current_plan(self):
        packets = copy.deepcopy(self.packets)
        packets[-1]["full_schedule"] = self.refs[0]
        self.save_stream(packets)
        with self.assertRaisesRegex(ValueError, "FULL_REFERENCE_FINAL"):
            validate_archive(self.root)

    def test_latest_reference_must_match_delivered_stream(self):
        self.write("timeline-latest.json", dict(full_schedule=self.refs[0]))
        with self.assertRaisesRegex(ValueError, "FULL_REFERENCE_LATEST"):
            validate_archive(self.root)

    def test_writer_latest_without_a_full_reference_remains_valid(self):
        self.write("timeline-latest.json", dict(rows=[], envelope={}))
        self.assertEqual(validate_archive(self.root).reference, self.refs[-1])

    def test_zero_plan_placeholder_before_first_adoption_is_legal(self):
        placeholder = dict(
            self.refs[0],
            plan_id=None,
            artifact_sha256=None,
            version=0,
            completion_h=None,
            anchor_events=0,
            planning=True,
        )
        first = dict(
            self.packets[0],
            events=[],
            envelope=dict(self.packets[0]["envelope"], event_count=0, sampled_sim_h=0),
            full_schedule=placeholder,
        )
        self.save_stream([first] + self.packets)
        self.assertEqual(validate_archive(self.root).packets, 3)

    def test_missing_duplicate_or_altered_plan_rows_are_rejected(self):
        binding = validate_archive(self.root)
        for kind in ["missing", "duplicate", "time", "current", "plan_id"]:
            view = self.view()
            if kind == "missing":
                view["rows"] = []
            elif kind == "duplicate":
                view["rows"].append(view["rows"][0])
            elif kind == "time":
                view["rows"][0]["end_h"] = 100
            elif kind == "current":
                view["rows"][0]["proposal_state"] = "CURRENT_PLAN"
            else:
                view["rows"][0]["plan_id"] = "OTHER:FULL"
            with self.subTest(kind=kind), self.assertRaisesRegex(ValueError, "DISPLAY_PLAN"):
                binding.check_projection(view)

    def test_artifact_bytes_and_adoption_run_identity_are_checked(self):
        plan = copy.deepcopy(self.plans[0])
        plan["plan_id"] = "OTHER:FULL"
        self.write(f"full-schedules/{self.refs[0]['artifact_sha256']}.json", plan)
        with self.assertRaisesRegex(ValueError, "ARTIFACT_CHANGED"):
            ScheduleBindings(self.root)


if __name__ == "__main__":
    unittest.main()
