"""Real input transition handling must preserve fast clicks and camera gestures."""

import sys
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path[:0] = [
    str(Path(__file__).resolve().parents[1] / p) for p in ("scripts", "desktop/s19b/src")
]
from p051_scene_link import SceneInputProbe, pointer_pick_region  # noqa: E402


class PointerSelectionTests(unittest.TestCase):
    def setup_probe(self):
        probe = object.__new__(SceneInputProbe)
        probe.pointer_start = None
        probe.pointer_position = None
        probe.pointer_trace = []
        probe.pick_count = 0
        probe.last_pick = None
        probe.rectangle = Mock()
        probe.rectangle_shape = Mock()
        viewport = Mock()
        viewport.map_ndc_to_texture_pixel = lambda p: (
            (round((p[0] + 1) * 500), round((1 - p[1]) * 250)),
            True,
        )
        probe.viewport_window = Mock(viewport_api=viewport)
        window = Mock()
        window.get_width.return_value = 1500
        window.get_height.return_value = 750
        window.get_ui_scale.return_value = 1.5
        carb = types.ModuleType("carb")
        carb.input = types.SimpleNamespace(
            KEYBOARD_MODIFIER_FLAG_ALT=4,
            KEYBOARD_MODIFIER_FLAG_SHIFT=1,
            KEYBOARD_MODIFIER_FLAG_CONTROL=2,
        )
        omni = types.ModuleType("omni")
        omni.usd = types.SimpleNamespace(
            PickingMode=types.SimpleNamespace(
                MERGE_SELECTION="ADD", INVERT_SELECTION="TOGGLE", RESET_AND_SELECT="REPLACE"
            )
        )
        omni.ui = types.SimpleNamespace(Pixel=lambda x: x)
        modules = patch.dict(
            sys.modules,
            {
                "carb": carb,
                "carb.input": carb.input,
                "omni": omni,
                "omni.usd": omni.usd,
                "omni.ui": omni.ui,
            },
        )
        modules.start()
        self.addCleanup(modules.stop)
        return probe, viewport, window

    def test_down_and_up_in_one_update_still_request_exact_render_pixel(self):
        probe, viewport, window = self.setup_probe()
        event = types.SimpleNamespace(modifiers=0, pixel_coords=(750, 375))
        probe.pointer_event("LEFT_BUTTON_DOWN", event, window)
        probe.pointer_event("LEFT_BUTTON_UP", event, window)
        viewport.request_pick.assert_called_once_with((500, 250), (500, 250), "REPLACE")
        self.assertEqual(probe.last_pick["source"], "ACTUAL_KIT_MOUSE_EVENTS_RENDERER_PICK")
        self.assertFalse(probe.last_pick["dragging"])
        probe.pointer_event("LEFT_BUTTON_UP", event, window)
        self.assertEqual(viewport.request_pick.call_count, 1)

    def test_reverse_rectangle_and_shift_ctrl_modes_preserve_physical_scale(self):
        for modifier, mode in ((0, "REPLACE"), (1, "ADD"), (2, "TOGGLE")):
            with self.subTest(modifier=modifier):
                probe, viewport, window = self.setup_probe()
                probe.pointer_event(
                    "LEFT_BUTTON_DOWN",
                    types.SimpleNamespace(modifiers=modifier, pixel_coords=(1200, 600)),
                    window,
                )
                probe.pointer_event(
                    "MOVE",
                    types.SimpleNamespace(modifiers=modifier, pixel_coords=(300, 150)),
                    window,
                )
                self.assertTrue(probe.rectangle.visible)
                probe.pointer_event(
                    "LEFT_BUTTON_UP",
                    types.SimpleNamespace(modifiers=modifier, pixel_coords=(300, 150)),
                    window,
                )
                viewport.request_pick.assert_called_once_with((200, 100), (800, 400), mode)
                self.assertFalse(probe.rectangle.visible)

    def test_alt_or_resize_cancels_selection_without_swallowing_camera(self):
        probe, viewport, window = self.setup_probe()
        event = types.SimpleNamespace(modifiers=0, pixel_coords=(200, 200))
        probe.pointer_event("LEFT_BUTTON_DOWN", event, window)
        event.modifiers = 4
        self.assertTrue(probe.pointer_event("MOVE", event, window))
        self.assertTrue(probe.pointer_event("LEFT_BUTTON_UP", event, window))
        viewport.request_pick.assert_not_called()
        event.modifiers = 0
        probe.pointer_event("LEFT_BUTTON_DOWN", event, window)
        window.get_width.return_value = 1400
        self.assertTrue(probe.pointer_event("LEFT_BUTTON_UP", event, window))
        viewport.request_pick.assert_not_called()

    def test_invalid_and_outside_pointer_geometries_do_not_pick(self):
        self.assertIsNone(pointer_pick_region((-1, 10), (30, 30), (100, 100)))
        with self.assertRaises(ValueError):
            pointer_pick_region((0, 0), (20, 20), (0, 100))
        with self.assertRaises(ValueError):
            pointer_pick_region((0, 0), (float("nan"), 20), (100, 100))

    def test_buffered_button_coordinates_do_not_replace_ordered_moves(self):
        probe, viewport, window = self.setup_probe()
        for name, xy in [
            ("MOVE", (150, 75)),
            ("LEFT_BUTTON_DOWN", (1200, 600)),
            ("MOVE", (1200, 600)),
            ("LEFT_BUTTON_UP", (1200, 600)),
        ]:
            probe.pointer_event(name, types.SimpleNamespace(modifiers=0, pixel_coords=xy), window)
        viewport.request_pick.assert_called_once_with((100, 50), (800, 400), "REPLACE")
        self.assertEqual(probe.last_pick["start"], [150, 75])
        self.assertTrue(probe.last_pick["dragging"])


if __name__ == "__main__":
    unittest.main()
