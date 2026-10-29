"""Isolated CPU control-flow fixtures. No Isaac imports or production execution."""

import ast
import copy
import hashlib
import json
import unittest
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace as NS

from kit_failure_context_r1 import CaptureUnavailable, KitFailureContext

OUTPUT = Path(__file__).parent


@dataclass(frozen=True)
class Configuration:
    id: str
    schema_version: str
    products: int


@dataclass
class Snapshot:
    run_id: str
    epoch: int
    config_id: str
    schema_version: str
    config_sha256: str
    state: object = None
    events: tuple = ()


def digest(c):
    return hashlib.sha256(json.dumps([c.id, c.schema_version, c.products]).encode()).hexdigest()


def fixtures(unit="U", products=1):
    c = Configuration("CONFIG-" + unit, "FIXTURE-ONLY", products)
    scene = object()
    world = NS(run_id="RUN-" + unit, epoch=0, config=c, snapshot_calls=0)

    def snapshot():
        world.snapshot_calls += 1
        return Snapshot(
            world.run_id,
            world.epoch,
            world.config.id,
            world.config.schema_version,
            digest(world.config),
        )

    world.snapshot = snapshot
    backend = NS(world=world, port=NS(run_id=world.run_id, epoch=0, scene=scene))
    context = KitFailureContext(unit, world.run_id, 0, OUTPUT / "not-created" / unit, c, digest)
    context.backend = backend
    context.scene = scene
    return c, scene, world, backend, context


def main_try(source):
    return next(n for n in ast.parse(source).body if isinstance(n, ast.Try))


class FailureIdentityTests(unittest.TestCase):
    def test_exact_next_row_initialization_clears_previous_backend(self):
        source = (OUTPUT / "kit_witness_r5.py").read_text(encoding="utf-8")
        loop = next(n for n in main_try(source).body if isinstance(n, ast.For))
        setup = []
        for stmt in loop.body:
            setup.append(stmt)
            if isinstance(stmt, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "backend" for t in stmt.targets
            ):
                # Skip the deliberate reset; stop at the actual adapter constructor.
                if (
                    isinstance(stmt.value, ast.Call)
                    and isinstance(stmt.value.func, ast.Name)
                    and stmt.value.func.id == "IsaacAdapter"
                ):
                    break
        c, scene, old_world, old_backend, previous = fixtures("F", 2)
        fresh = Configuration("CONFIG-U", "FIXTURE-ONLY", 1)

        def failing_adapter(*args, **kwargs):
            raise RuntimeError("fixture-current-adapter-init-failed")

        env = dict(
            row=dict(
                unit_id="U-KIT", bundle="fixture-bundle.json", configuration="fixture-config.json"
            ),
            backend=old_backend,
            scene=scene,
            c=c,
            failure_context=previous,
            OUTPUT=OUTPUT,
            perf_counter=lambda: 0,
            json=NS(
                loads=lambda raw: (
                    {"spec": {"run_id": "RUN-U", "epoch": 0}} if raw == b"bundle" else {}
                )
            ),
            decode=lambda *args: fresh,
            Configuration=Configuration,
            configuration_digest=digest,
            KitFailureContext=KitFailureContext,
            omni=NS(
                usd=NS(get_context=lambda: NS(new_stage=lambda: None, get_stage=lambda: object()))
            ),
            TargetScene=lambda *args: object(),
            load_config=lambda *args: None,
            R=OUTPUT,
            USDProductionPort=lambda *args: object(),
            IsaacAdapter=failing_adapter,
        )
        # Supply only the two immutable fixture input bytes, not real run inputs.
        from unittest.mock import patch

        def read_fixture(path):
            return b"bundle" if path.name == "fixture-bundle.json" else b"config"

        with patch.object(Path, "read_bytes", read_fixture):
            with self.assertRaisesRegex(RuntimeError, "fixture-current-adapter-init-failed"):
                exec(
                    compile(
                        ast.Module(body=setup, type_ignores=[]), "<actual-r5-row-setup>", "exec"
                    ),
                    env,
                )
        self.assertIsNone(env["backend"])
        self.assertIsNone(env["failure_context"].backend)
        with self.assertRaisesRegex(CaptureUnavailable, "CURRENT_ROW_NOT_INITIALIZED"):
            env["failure_context"].capture()
        self.assertEqual(old_world.snapshot_calls, 0)
        self.assertFalse((OUTPUT / "not-created").exists())

    def test_valid_current_capture_keeps_matching_pair(self):
        c, scene, world, backend, context = fixtures()
        capture = context.capture()
        self.assertIs(capture.configuration, c)
        self.assertIs(capture.scene, scene)
        self.assertEqual(capture.actual_configuration_sha256, capture.snapshot.config_sha256)

    def test_generated_catalog_saves_actual_configuration_not_C0(self):
        c, scene, world, backend, context = fixtures(products=1)
        world.config = Configuration(c.id, c.schema_version, 2)
        capture = context.capture()
        self.assertIs(capture.configuration, world.config)
        self.assertNotEqual(
            capture.initial_configuration_sha256, capture.actual_configuration_sha256
        )
        self.assertEqual(capture.actual_configuration_sha256, capture.snapshot.config_sha256)

    def test_wrong_world_run_or_epoch_rejected_before_snapshot(self):
        for key, value in [("run_id", "RUN-OTHER"), ("epoch", 1)]:
            with self.subTest(key=key):
                c, scene, world, backend, context = fixtures()
                setattr(world, key, value)
                with self.assertRaisesRegex(CaptureUnavailable, "WORLD_IDENTITY"):
                    context.capture()
                self.assertEqual(world.snapshot_calls, 0)

    def test_wrong_port_identity_or_scene_rejected_before_snapshot(self):
        for key, value in [("run_id", "RUN-OTHER"), ("epoch", 1), ("scene", object())]:
            with self.subTest(key=key):
                c, scene, world, backend, context = fixtures()
                setattr(backend.port, key, value)
                with self.assertRaises(CaptureUnavailable):
                    context.capture()
                self.assertEqual(world.snapshot_calls, 0)

    def test_wrong_snapshot_identity_or_config_rejected(self):
        for key, value in [
            ("run_id", "RUN-OTHER"),
            ("epoch", 1),
            ("config_id", "OTHER"),
            ("schema_version", "OTHER"),
            ("config_sha256", "bad"),
        ]:
            with self.subTest(key=key):
                c, scene, world, backend, context = fixtures()
                snapshot = world.snapshot()
                setattr(snapshot, key, value)
                world.snapshot = lambda: snapshot
                with self.assertRaises(CaptureUnavailable):
                    context.capture()

    def test_actual_exception_handler_retains_original_error_without_writes(self):
        source = (OUTPUT / "kit_witness_r5.py").read_text(encoding="utf-8")
        handler = main_try(source).handlers[0]
        capture_try = next(n for n in handler.body if isinstance(n, ast.Try))
        c, scene, world, backend, context = fixtures()
        context.backend = None
        original = dict(
            type="RuntimeError", message="original adapter constructor exception", unit="U-KIT"
        )
        env = dict(
            failure_context=context,
            current_unit="U-KIT",
            preservation=[],
            failure=copy.deepcopy(original),
        )
        exec(
            compile(
                ast.Module(body=[capture_try], type_ignores=[]),
                "<actual-r5-preservation-handler>",
                "exec",
            ),
            env,
        )
        self.assertEqual(env["failure"], original)
        self.assertEqual(
            env["preservation"][0]["status"], "UNKNOWN_NO_IDENTITY_BOUND_COMPLETE_COPY"
        )
        self.assertIn("CURRENT_ROW_NOT_INITIALIZED", env["preservation"][0]["preservation_error"])
        self.assertFalse((OUTPUT / "not-created").exists())

    def test_prepared_repair_packet_does_not_enable_new_production(self):
        packet = json.loads((OUTPUT / "kit-protocol-r5.json").read_bytes())
        self.assertFalse(packet["execution_enabled"])
        self.assertEqual(packet["rows"], [])
        self.assertTrue(packet["requires_fresh_run_and_input_binding_before_execution"])


if __name__ == "__main__":
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(FailureIdentityTests)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    (OUTPUT / "targeted-check-result.json").write_text(
        json.dumps(
            dict(
                tests=result.testsRun,
                failures=len(result.failures),
                errors=len(result.errors),
                passed=result.wasSuccessful(),
                scope="isolated CPU/stub control-flow checks; real r5 AST setup and error handler; no actual Kit or production",
                names=unittest.defaultTestLoader.getTestCaseNames(FailureIdentityTests),
            ),
            indent=2,
        ),
        encoding="utf-8",
    )
    raise SystemExit(0 if result.wasSuccessful() else 1)
