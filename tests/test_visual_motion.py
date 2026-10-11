"""Meaningful display-direction and hard-envelope boundaries without Kit."""

import math
import unittest

from sim.isaac.scene.visual_motion import (
    angle_delta,
    bounded_scale,
    facing_yaw,
    foot_offset,
    route_heading,
)


class VisualMotionTests(unittest.TestCase):
    def test_positive_y_front_matches_all_four_directions(self):
        for vector in ((1, 0), (0, 1), (-1, 0), (0, -1)):
            yaw = math.radians(facing_yaw(vector))
            actual = (-math.sin(yaw), math.cos(yaw))
            self.assertAlmostEqual(sum(x * y for x, y in zip(vector, actual)), 1)

    def test_zero_and_nonfinite_direction_rejected(self):
        for direction in ((0, 0), (math.nan, 0), (1, math.inf)):
            with self.assertRaises(ValueError):
                facing_yaw(direction)

    def test_every_turn_fits_original_asymmetric_envelope(self):
        width, depth = 0.64, 0.684408
        for yaw in range(-360, 361):
            scale = bounded_scale(width, depth, yaw)
            c, s = abs(math.cos(math.radians(yaw))), abs(math.sin(math.radians(yaw)))
            self.assertLessEqual(scale, 1)
            self.assertLessEqual(scale * (width * c + depth * s), width + 1e-12)
            self.assertLessEqual(scale * (width * s + depth * c), depth + 1e-12)

    def test_invalid_envelopes_rejected(self):
        for width, depth, yaw in ((0, 1, 0), (1, -1, 0), (1, 1, math.nan)):
            with self.assertRaises(ValueError):
                bounded_scale(width, depth, yaw)

    def test_corner_turn_is_continuous_and_finishes_at_new_heading(self):
        path = ((0, 0, 0), (0, 2, 0), (2, 2, 0))
        values = [route_heading(path, i / 120) for i in range(121)]
        self.assertEqual(values[0], 0)
        self.assertEqual(values[-1], -90)
        self.assertAlmostEqual(values[60], -45)
        self.assertLess(max(abs(angle_delta(a, b)) for a, b in zip(values, values[1:])), 5)

    def test_fold_back_and_zero_length_segments(self):
        path = ((0, 0, 0), (0, 0, 0), (0, 2, 0), (0, 0, 0))
        self.assertEqual(route_heading(path, 0), 0)
        self.assertEqual(abs(route_heading(path, 1)), 180)
        self.assertIsNone(route_heading(((0, 0, 0), (0, 0, 1)), 0.5))

    def test_invalid_fraction_is_not_silently_clamped(self):
        for fraction in (-0.1, 1.1, math.nan):
            with self.assertRaises(ValueError):
                route_heading(((0, 0, 0), (1, 0, 0)), fraction)

    def test_stop_removes_gait_and_feet_never_move_down(self):
        for i in range(100):
            t = i / 30
            self.assertEqual(foot_offset(t, 0, False), (0, 0, 0))
            for side in (0, 1):
                _, y, z = foot_offset(t, side, True)
                self.assertLessEqual(abs(y), 0.025)
                self.assertGreaterEqual(z, 0)
                self.assertLessEqual(z, 0.015)

    def test_shortest_angle_crosses_wrap_without_full_spin(self):
        self.assertEqual(angle_delta(179, -179), 2)
        self.assertEqual(angle_delta(-179, 179), -2)
