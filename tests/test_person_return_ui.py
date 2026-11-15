"""Return-location defaults come from the verified live personnel state."""

import unittest

import test_p051_client as fixtures


class ReturnLocationTests(unittest.TestCase):
    setUp = fixtures.AdapterTests.setUp
    tearDown = fixtures.AdapterTests.tearDown

    def test_absent_person_retains_verified_return_location_without_mutating_packet(self):
        person = "AF1"
        location = self.session.world._position(person).location
        self.assertEqual(location, "CONTROL-AF1")
        request = self.client.build_request(
            dict(
                kind="PERSON_ABSENT",
                target_id=person,
                payload=dict(reason="TEST", safety_policy="HOLD_AND_VERIFY"),
            )
        )
        self.assertEqual(self.session.receive(request)["status"], "ACCEPTED")
        self.session.boundary()
        self.session.projection.publish(self.session.world.observe())
        view = self.client.poll()
        self.assertEqual(view["ui_options"]["person_locations"][person], location)
        self.assertNotIn("CUT1", view["ui_options"]["person_locations"])
        view["ui_options"]["person_locations"][person] = "F1"
        self.assertEqual(
            self.client.project_snapshot()["ui_options"]["person_locations"][person], location
        )
