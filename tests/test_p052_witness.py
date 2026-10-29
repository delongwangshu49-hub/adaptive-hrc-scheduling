"""E20 opt-in must not widen historical recipes or bypass physical controls."""

import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / p) for p in ("scripts", "desktop/p051/src", "desktop/s19b/src")]

from build_simulation_production import configuration as base  # noqa: E402
from p051_desktop.client import prepare_launch  # noqa: E402
from p051_desktop.gantt import audit_separately  # noqa: E402

from adaptive_hrc_scheduling.contracts.production import digest  # noqa: E402
from adaptive_hrc_scheduling.control.production_loop import (  # noqa: E402
    Scenario,
    validate_scenario,
)
from adaptive_hrc_scheduling.p052_witness import RECIPE, configuration  # noqa: E402


class WitnessTests(unittest.TestCase):
    def test_audit_budget_preserves_verifier_and_legacy_limits(self):
        for full, identity, expected in (
            (True, configuration(base()).id, 1800),
            (True, base().id, 240),
            (False, configuration(base()).id, 60),
        ):
            with patch("p051_desktop.gantt.subprocess.run") as run:
                run.return_value.returncode = 0
                run.return_value.stdout = '{"verified":true}'
                self.assertEqual(
                    audit_separately({"full_schedule": full, "initial": {"id": identity}}),
                    {"verified": True},
                )
                self.assertEqual(run.call_args.kwargs["timeout"], expected)
                self.assertEqual(run.call_args.args[0][2], "p051_desktop.forecast_worker")

    def test_recipe_preserves_all_physical_and_person_inputs(self):
        original = base()
        resolved = configuration(original)
        changes = {"id", "schema_version", "specification", "products"}
        for key in original.__dataclass_fields__:
            if key not in changes:
                self.assertEqual(getattr(original, key), getattr(resolved, key), key)
        self.assertEqual(
            resolved.products,
            (replace(original.products[0], order_id="ORD-BASE", due_h=2500.0),),
        )
        self.assertNotIn("W3", [p.id for p in resolved.people])
        with self.assertRaisesRegex(ValueError, "E20_INITIAL_ONE_PRODUCT"):
            configuration(base(products=2))

    def test_extended_window_is_confined_to_resolved_e20(self):
        resolved = configuration(base())
        validate_scenario(resolved, Scenario(id="INTERACTIVE", until_h=3000))
        for scenario in (
            Scenario(id="INTERACTIVE", until_h=3001),
            Scenario(id="NORMAL", until_h=3000),
            Scenario(id="INTERACTIVE", until_h=3000, actual_device_failure=True),
        ):
            with self.assertRaises(ValueError):
                validate_scenario(resolved, scenario)
        with self.assertRaises(ValueError):
            validate_scenario(base(), Scenario(id="INTERACTIVE", until_h=3000))

    def test_desktop_launch_binds_resolved_recipe_and_existing_capacity(self):
        with tempfile.TemporaryDirectory() as folder:
            _, request = prepare_launch(
                ROOT,
                folder,
                dict(witness_recipe=RECIPE, session_until_h=3000, wall_budget_s=14400),
            )
            spec = request["session"]["spec"]
            self.assertTrue(request["run_id"].startswith("P051-E20-"))
            self.assertEqual(spec["initial_config_sha256"], digest(configuration(base())))
            self.assertEqual(spec["initial_orders"][0]["order_id"], "ORD-BASE")
            self.assertEqual(spec["capacity"]["max_wip_products"], 3)
            self.assertEqual(spec["capacity"]["max_lifetime_products"], 4)
            self.assertEqual(spec["clock"]["session_until_h"], 3000)

    def test_explicit_e20_wip4_does_not_change_physical_configuration(self):
        with tempfile.TemporaryDirectory() as folder:
            _, request = prepare_launch(
                ROOT, folder, dict(witness_recipe=RECIPE, witness_wip_products=4)
            )
            spec = request["session"]["spec"]
            self.assertEqual(spec["capacity"]["max_wip_products"], 4)
            self.assertEqual(spec["capacity"]["max_lifetime_products"], 4)
            self.assertEqual(spec["initial_config_sha256"], digest(configuration(base())))
            for form in (
                dict(witness_wip_products=4),
                dict(witness_recipe=RECIPE, witness_wip_products=5),
                dict(witness_recipe=RECIPE, witness_wip_products=True),
            ):
                with self.assertRaisesRegex(ValueError, "WITNESS_CAPACITY_UNSUPPORTED"):
                    prepare_launch(ROOT, folder, form)


if __name__ == "__main__":
    unittest.main()
