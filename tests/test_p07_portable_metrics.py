"""Published P07 copies of the eight original S21 arithmetic witnesses.

Method bodies and assertions are preserved; only the import binding changes.
"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "analysis/p07"))
import portable_metrics as a  # noqa: E402


class ActualDistanceTests(unittest.TestCase):
    def test_different_segment_speeds(self):
        route = dict(
            points=[dict(x=0, y=0, z=0), dict(x=4, y=0, z=0), dict(x=4, y=0, z=4)],
            speed_m_s=4,
            vertical_speed_m_s=1,
        )
        self.assertEqual(a.actual_arc(route, 0.5), 5.5)
        self.assertEqual(a.actual_arc(route, 1), 8)
        self.assertEqual(a.actual_arc(route, 0), 0)

    def test_resume_and_device_entity_do_not_duplicate_or_hide_empty_travel(self):
        route = dict(
            id="R",
            points=[dict(x=0, y=0, z=0), dict(x=10, y=0, z=0)],
            speed_m_s=1,
            vertical_speed_m_s=1,
        )
        op = dict(id="O", action="EMPTY_RETURN", route_id="R", entity_id="FORK-01")
        c = dict(id="C", operation_id="O", service=None, resume_of=None)
        resumed = dict(c, id="C2", resume_of="C")
        events = [
            dict(command=c, kind="STARTED", readback=None),
            dict(command=None, kind="PROGRESS", readback=dict(command_id="C", progress=0.5)),
            dict(command=resumed, kind="STARTED", readback=None),
            dict(command=resumed, kind="COMPLETED", readback=None),
        ]
        m = a.transport(dict(operations=[op], routes=[route]), events)
        self.assertEqual(m["total_m"], 10)
        self.assertEqual(m["empty_m"], 10)
        self.assertEqual(m["commands"], 1)
        self.assertEqual(m["empty_ratio"], 1)

    def test_walk_is_separate_and_zero_transport_is_undefined(self):
        route = dict(
            id="R",
            points=[dict(x=0, y=0, z=0), dict(x=3, y=4, z=0)],
            speed_m_s=1,
            vertical_speed_m_s=1,
        )
        op = dict(id="O", action="WALK", route_id="R", entity_id="PERSON")
        c = dict(id="C", operation_id="O", service=None, resume_of=None)
        events = [
            dict(command=c, kind="STARTED", readback=None),
            dict(command=c, kind="COMPLETED", readback=None),
        ]
        m = a.transport(dict(operations=[op], routes=[route]), events)
        self.assertEqual(m["walk_m"], 5)
        self.assertEqual(m["total_m"], 0)
        self.assertIsNone(m["empty_ratio"])


def event(time, ready, received, started=False):
    return dict(
        occurred_sim_h=time,
        kind="STARTED" if started else "WORLD",
        command=dict(product_id="P", service=None) if started else None,
        state=dict(products=[dict(product_id="P", ready_h=ready, received_h=received)]),
    )


class ActualOccupancyTests(unittest.TestCase):
    def test_zero_duration_ready_still_has_an_actual_peak(self):
        m = a.occupancy([event(0, None, None, True), event(3, 3, None), event(3, 3, 3)], 10)
        self.assertEqual(m["internal_finished"]["peak_products"], 1)
        self.assertEqual(m["internal_finished"]["area_product_h"], 0)
        self.assertEqual(m["wip"]["peak_products"], 1)
        self.assertEqual(m["wip"]["area_product_h"], 3)

    def test_positive_dwell_and_incomplete_wip(self):
        m = a.occupancy([event(1, None, None, True), event(4, 4, None), event(7, 4, 7)], 10)
        self.assertEqual(m["internal_finished"]["area_product_h"], 3)
        self.assertEqual(m["wip"]["area_product_h"], 3)
        incomplete = a.occupancy([event(2, None, None, True)], 10)
        self.assertEqual(incomplete["wip"]["area_product_h"], 8)

    def test_reversed_clock_rejected(self):
        with self.assertRaises(ValueError):
            a.occupancy([event(2, None, None), event(1, None, None)], 10)


class ActualTriggerTests(unittest.TestCase):
    def test_delayed_arrival_fact_is_not_a_wait_proof(self):
        m = dict(
            scenario=dict(delayed_lot="L", arrival_after_h=12),
            actual_world_events=[dict(kind="ARRIVAL", entity_id="L", time_h=12)],
            waiting=dict(
                intervals=[
                    dict(
                        start_h=0, end_h=12, reason="S18_NOMINAL_WAIT", category="MIXED_OR_UNKNOWN"
                    )
                ]
            ),
        )
        self.assertTrue(a.disturbance(m)["assignment_applied"])
        self.assertIsNone(a.disturbance(m)["triggered"])

    def test_ready_before_receipt_gate_and_actual_failure(self):
        m = dict(
            scenario=dict(receive_after_h=480),
            observed_end_h=720,
            products=[dict(ready_h=400, received_h=500)],
            actual_world_events=[dict(kind="RECEIVE_PERMIT", time_h=480)],
        )
        self.assertTrue(a.disturbance(m)["triggered"])
        m["products"][0]["ready_h"] = 500
        self.assertFalse(a.disturbance(m)["triggered"])
        m = dict(
            scenario=dict(loaded_failure=True),
            failure_triggered=True,
            actual_world_events=[dict(kind="FAILURE")],
        )
        self.assertTrue(a.disturbance(m)["triggered"])
