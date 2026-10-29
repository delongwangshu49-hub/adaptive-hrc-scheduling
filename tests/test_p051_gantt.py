"""Schedule source fidelity and display invariants using actual engine forecasts."""

import copy
import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path
from time import perf_counter
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "scripts"), str(ROOT / "desktop/p051/src")]

from build_simulation_production import configuration  # noqa: E402
from p051_desktop.gantt import NAMES, ScheduleReader, audit_separately, enrich  # noqa: E402
from p051_desktop.geometry import plan  # noqa: E402

from adaptive_hrc_scheduling.algorithms.lns import fingerprint  # noqa: E402
from adaptive_hrc_scheduling.algorithms.simulation_joint import SimulationJointProblem  # noqa: E402
from adaptive_hrc_scheduling.contracts.codec import as_data  # noqa: E402
from adaptive_hrc_scheduling.contracts.session import digest  # noqa: E402
from adaptive_hrc_scheduling.gantt_schedule import (  # noqa: E402
    capture,
    forecast_rows,
    publish,
    verify,
)
from adaptive_hrc_scheduling.production_backend import ProductionBackend  # noqa: E402


class ForecastTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = configuration()
        cls.world = ProductionBackend(cls.config, run_id="P051-GANTT-TEST")
        cls.problem = SimulationJointProblem(
            cls.config, cls.world.observe(), cls.world.snapshot(), end_h=0.1
        )
        cls.candidate = cls.problem.initial(perf_counter() + 60).candidate
        assert cls.candidate is not None
        report = cls.problem.verify(cls.candidate)
        assert report.valid, report.reasons
        cls.problem.best_verified_display = cls.problem.last_verified_display
        cls.data = capture(cls.problem, cls.candidate)
        cls.ref = dict(
            candidate_sha256=fingerprint(cls.candidate),
            artifact_sha256=digest(cls.data),
            event_count=0,
            event_prefix_sha256=digest([]),
            observation_id=cls.world.observe().id,
            start_h=0,
            end_h=0.1,
            config_sha256=digest(as_data(cls.config)),
        )

    def check(self, data, ref):
        return verify(data, ref, initial=as_data(self.config), generations=[], events=[])

    def test_real_candidate_rebuild_provides_fixed_forecast_intervals(self):
        rows = self.check(self.data, self.ref)
        self.assertTrue(rows)
        self.assertTrue(any(r.get("end_h", 0) > r["start_h"] for r in rows))
        self.assertTrue(all(r["schedule_state"] == "TENTATIVE" for r in rows))
        self.assertEqual(self.check(self.data, self.ref), rows)

    def test_resigned_predicted_completion_corruption_rejected(self):
        data, ref = copy.deepcopy(self.data), dict(self.ref)
        event = next(e for e in data["snapshot"]["events"] if e["kind"] == "COMPLETED")
        event["occurred_sim_h"] += 0.01
        ref["artifact_sha256"] = digest(data)
        with self.assertRaisesRegex(ValueError, "GANTT_PREDICTION_REBUILT"):
            self.check(data, ref)

    def test_resigned_truncated_candidate_rejected(self):
        data, ref = copy.deepcopy(self.data), dict(self.ref)
        data["candidate"]["steps"].pop()
        ref.update(artifact_sha256=digest(data), candidate_sha256=fingerprint(data["candidate"]))
        with self.assertRaises(ValueError):
            self.check(data, ref)

    def test_wrong_anchor_or_window_rejected(self):
        for field, value in [("event_count", 1), ("end_h", 99), ("observation_id", "OBS-OTHER")]:
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.check(self.data, dict(self.ref, **{field: value}))

    def test_display_mapping_keeps_full_business_dag_without_fictional_dates(self):
        config = as_data(self.config)
        v = enrich(dict(rows=[]), config, [])
        self.assertEqual(v["gantt_dependencies"], config["core_edges"])
        self.assertEqual(
            len(v["gantt_groups"]), len(config["core_activities"]) + len(config["products"])
        )
        self.assertEqual(v["rows"], [])
        self.assertTrue(all("start_h" not in g for g in v["gantt_groups"]))

    def test_atomic_publication_roundtrip_preserves_exact_candidate_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            session = SimpleNamespace(
                output=Path(directory),
                policy=SimpleNamespace(
                    candidates=[(self.problem, self.candidate)],
                    cache_hash=self.ref["candidate_sha256"],
                    pending=[],
                    committed=[],
                ),
            )
            extension = publish(session)
            ref = extension["candidates"][0]
            artifact = session.output / "gantt-schedules" / (ref["artifact_sha256"] + ".json")
            saved = json.loads(artifact.read_text(encoding="utf-8"))
            self.assertEqual(fingerprint(saved["candidate"]), ref["candidate_sha256"])
            self.assertEqual(self.check(saved, ref), self.check(self.data, self.ref))
            self.assertEqual(publish(session), extension)

    def test_existing_running_work_gets_candidate_completion_not_just_new_starts(self):
        data = copy.deepcopy(self.data)
        events = data["snapshot"]["events"]
        first = next(i for i, e in enumerate(events) if e["kind"] == "STARTED")
        event = events[first]
        data["prefix"]["events"] = events[: first + 1]
        data["prefix"]["state"] = event["state"]
        rows = forecast_rows(data, dict(self.ref, event_count=first + 1))
        row = next(r for r in rows if r["command_id"] == event["command_id"])
        self.assertEqual(row["continuation_command_id"], event["command_id"])
        self.assertEqual(row["start_h"], event["occurred_sim_h"])
        self.assertTrue(row.get("end_h", row["forecast_until_h"]) >= row["start_h"])

    def test_subprocess_rebuild_matches_direct_audit(self):
        payload = dict(
            data=self.data,
            reference=self.ref,
            initial=as_data(self.config),
            generations=[],
            events=[],
        )
        self.assertEqual(audit_separately(payload), self.check(self.data, self.ref))

    def test_invalidated_future_is_old_but_actual_adoption_keeps_identity(self):
        ref = dict(self.ref)
        row = self.check(self.data, ref)[0]
        command = dict(
            operation_id=row["operation_id"],
            attempt=row["attempt"],
            mode_id=row["mode"],
            roles=row["roles"],
            id="ACTUAL-1",
        )
        event = dict(kind="STARTED", command_id="ACTUAL-1", id="EV-ACTUAL")
        reader = ScheduleReader()
        reader.verified[digest(ref)] = [row]
        extension = dict(
            format="P051-SCHEDULE-1",
            candidates=[ref],
            active_candidate=ref["candidate_sha256"],
            pending_commands=[],
            committed_commands=[],
        )
        client = SimpleNamespace(
            packet=dict(display_schedule=extension, source=dict(plans=[])),
            consumer=SimpleNamespace(events=[]),
        )
        self.assertEqual(reader.read(client)[0]["proposal_state"], "SUPERSEDED")
        extension["pending_commands"] = [command]
        self.assertEqual(reader.read(client)[0]["proposal_state"], "CANDIDATE")
        extension["committed_commands"] = [command]
        self.assertEqual(reader.read(client)[0]["schedule_state"], "COMMITTED")
        client.packet["source"]["plans"] = [
            dict(
                journal=dict(
                    cache_sha256=ref["candidate_sha256"], selected_source="VERIFIED_CACHE"
                ),
                plan=dict(commands=[command]),
            )
        ]
        client.consumer.events = [event]
        adopted = reader.read(client)[0]
        self.assertEqual(adopted["adoption_event_id"], "EV-ACTUAL")
        self.assertEqual(adopted["actual_command_id"], "ACTUAL-1")
        self.assertEqual(adopted["start_h"], row["start_h"])
        reader.close()

    def test_non_process_metrics_are_not_decorated_or_mutated(self):
        row = dict(row_id="person:1", row_kind="PERSON_INTERVAL", person_id="W1")
        original = copy.deepcopy(row)
        view = enrich(dict(rows=[row]), as_data(self.config), [])
        self.assertEqual(view["rows"], [original])
        self.assertEqual(row, original)

    def test_chinese_names_match_frozen_process_specification(self):
        rows = csv.DictReader(
            (ROOT / "docs/model/steel_process.tsv").read_text(encoding="utf-8").splitlines(),
            delimiter="\t",
        )
        for row in rows:
            self.assertEqual(NAMES[row["activity"]][0], row["output"])

    def test_equal_panels_allow_native_fill_and_readable_labels(self):
        for width, height in [(1280, 720), (1366, 768), (1920, 1080)]:
            p = plan(width, height, form_open=True)
            self.assertTrue(p.geometry_admissible)
            self.assertGreaterEqual(p.label_width, 210)
            self.assertEqual(p.plots[0].width, p.plots[1].width + p.label_width)
            self.assertGreaterEqual(p.plots[1].width, 300)


if __name__ == "__main__":
    unittest.main()
