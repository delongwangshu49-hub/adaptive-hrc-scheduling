"""Guard the scalar-only fast path and its exact public output contract."""

import unittest
from dataclasses import dataclass, fields, replace

from adaptive_hrc_scheduling.contracts.codec import as_data
from adaptive_hrc_scheduling.contracts.session import canonical
from adaptive_hrc_scheduling.domain.production import HumanInterval
from adaptive_hrc_scheduling.workforce_metrics import _interval_data


class IntervalDataTests(unittest.TestCase):
    def setUp(self):
        self.row = HumanInterval("W1", None, 0.0, 1.25, "WAIT", 0.0, -0.0, 0.2, 0.125)

    def test_every_contract_field_is_scalar_and_preserved(self):
        self.assertTrue(
            all(
                type(getattr(self.row, f.name)) in (str, int, float, type(None))
                for f in fields(self.row)
            )
        )
        for phase in ("WAIT", "WORK", "OFF_SHIFT", "EMERGENCY_HOLD"):
            for command in (None, "CMD-1"):
                row = replace(self.row, phase=phase, command_id=command)
                self.assertEqual(canonical(_interval_data(row)), canonical(as_data(row)))

    def test_outputs_are_fresh(self):
        result = _interval_data(self.row)
        result["start_h"] = 999
        self.assertEqual(_interval_data(self.row)["start_h"], 0.0)

    def test_other_dataclasses_keep_recursive_conversion(self):
        @dataclass(frozen=True)
        class Nested:
            value: tuple

        value = Nested((self.row,))
        self.assertEqual(_interval_data(value), as_data(value))

    def test_subclass_keeps_recursive_conversion(self):
        @dataclass(frozen=True)
        class Extended(HumanInterval):
            extra: tuple = (1, 2)

        value = Extended(**as_data(self.row))
        self.assertEqual(_interval_data(value), as_data(value))
