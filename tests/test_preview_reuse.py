"""Preview ownership, fallback, ordered blockers and independent audit boundaries."""

import sys
import tempfile
import threading
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from test_session_lifecycle import setup_session  # noqa: E402

from adaptive_hrc_scheduling import (  # noqa: E402
    full_schedule,
    preview_geometry,
    production_navigation,
)
from adaptive_hrc_scheduling.control import production_loop  # noqa: E402
from adaptive_hrc_scheduling.planning import production as planner  # noqa: E402
from adaptive_hrc_scheduling.preview_reuse import (  # noqa: E402
    PreviewPreparation,
    fork_seed,
    shareable_records,
)
from adaptive_hrc_scheduling.production_backend import ProductionBackend  # noqa: E402


class PreviewReuseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.session = setup_session(Path(cls.tmp.name) / "run")

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_share_only_native_immutable_records_and_detach_writes(self):
        world = self.session.world
        memo = shareable_records(world)
        self.assertIs(memo[id(world.config)], world.config)
        self.assertIs(memo[id(world.s)], world.s)
        clone = fork_seed(world)
        self.assertIsNot(clone.operations, world.operations)
        self.assertIsNot(clone.events, world.events)
        clone.operations["PRIVATE"] = None
        self.assertNotIn("PRIVATE", world.operations)
        with patch.object(world, "s", replace(world.s, positions=list(world.s.positions))):
            self.assertEqual(shareable_records(world), {})

        class Unknown(ProductionBackend):
            pass

        self.assertEqual(shareable_records(object.__new__(Unknown)), {})

    def test_seed_binds_config_run_epoch_and_containers(self):
        prep = PreviewPreparation()
        world = self.session.world
        a = prep.world(world.config, run_id=world.run_id, epoch=world.epoch)
        b = prep.world(world.config, run_id=world.run_id, epoch=world.epoch)
        self.assertIsNot(a, b)
        self.assertIs(a.config, b.config)
        self.assertIsNot(a.operations, b.operations)
        a.operations["PRIVATE"] = None
        self.assertNotIn("PRIVATE", b.operations)
        c = prep.world(world.config, run_id="OTHER", epoch=7)
        self.assertEqual((c.run_id, c.epoch), ("OTHER", 7))

    def overlap(self, first, failures):
        entered = {name: threading.Event() for name in ("a", "b")}
        release = {name: threading.Event() for name in ("a", "b")}
        preparations, geometries, errors = {}, {}, {}
        original = (planner.ProductionBackend, full_schedule.RulePolicy)

        def boundary(*args, session, joint_policy, **kwargs):
            name = threading.current_thread().name
            self.assertEqual((planner.ProductionBackend, full_schedule.RulePolicy), original)
            preparations[name] = joint_policy.preparation
            geometries[name] = preview_geometry.current()
            self.assertIsNot(session.world.events, self.session.world.events)
            entered[name].set()
            if not release[name].wait(15):
                raise RuntimeError("thread did not release")
            self.assertIs(preview_geometry.current(), geometries[name])
            raise ValueError("failure" if name in failures else "boundary")

        def worker():
            name = threading.current_thread().name
            try:
                full_schedule.preview(self.session, ())
            except BaseException as error:
                errors[name] = str(error)
                entered[name].set()
            finally:
                if preview_geometry.current() is not None:
                    errors[name] = "leaked context"

        threads = {name: threading.Thread(target=worker, name=name) for name in entered}
        try:
            with patch.object(production_loop, "run", boundary):
                for name in ("a", "b"):
                    threads[name].start()
                    self.assertTrue(entered[name].wait(15))
                self.assertIsNot(preparations["a"], preparations["b"])
                self.assertIsNot(geometries["a"], geometries["b"])
                for name in (first, "b" if first == "a" else "a"):
                    release[name].set()
                    threads[name].join(15)
                    self.assertFalse(threads[name].is_alive())
            self.assertEqual(
                errors, {n: "failure" if n in failures else "boundary" for n in entered}
            )
            self.assertIsNone(preview_geometry.current())
        finally:
            for event in release.values():
                event.set()
            for thread in threads.values():
                if thread.ident is not None:
                    thread.join(15)

    def test_a_exits_first(self):
        self.overlap("a", set())

    def test_b_exits_first(self):
        self.overlap("b", set())

    def test_first_exception(self):
        self.overlap("a", {"a"})

    def test_second_exception(self):
        self.overlap("b", {"b"})

    def test_both_exceptions(self):
        self.overlap("a", {"a", "b"})

    def test_nested_preview_restores_outer_context(self):
        contexts = []

        def boundary(*args, **kwargs):
            contexts.append(preview_geometry.current())
            if len(contexts) == 1:
                with self.assertRaisesRegex(ValueError, "nested"):
                    full_schedule.preview(self.session, ())
                self.assertIs(preview_geometry.current(), contexts[0])
            raise ValueError("nested")

        with patch.object(production_loop, "run", boundary):
            with self.assertRaisesRegex(ValueError, "nested"):
                full_schedule.preview(self.session, ())
        self.assertIsNot(contexts[0], contexts[1])
        self.assertIsNone(preview_geometry.current())

    def test_full_python_fallback_clones_every_record(self):
        def boundary(*args, session, joint_policy, **kwargs):
            self.assertIsNone(preview_geometry.current())
            self.assertIsNone(joint_policy.preparation)
            self.assertIsNot(session.world.config, self.session.world.config)
            self.assertIsNot(session.world.s, self.session.world.s)
            raise ValueError("fallback")

        with patch.object(production_loop, "run", boundary):
            with self.assertRaisesRegex(ValueError, "fallback"):
                full_schedule.preview(self.session, (), reuse=False)

    def test_geometry_and_original_cache_remain_separate(self):
        world = self.session.world
        for excluded in ((), ("W1",), ("FORK-01", "W2")):
            expected = production_navigation.boxes(world.config, world.s, excluded)
            before = production_navigation._boxes_cached.cache_info()
            with preview_geometry.geometry_scope(preview_geometry.ReplayGeometry()):
                actual = production_navigation.boxes(world.config, world.s, excluded)
            self.assertEqual(actual, expected)
            self.assertEqual(production_navigation._boxes_cached.cache_info(), before)

    def test_first_blocker_preserves_order_and_tangency(self):
        boxes = (("A", (1, -1, 0), (2, 1, 2)), ("B", (2, -1, 0), (3, 1, 2)))
        for obstacles in (boxes, boxes[::-1]):
            self.assertEqual(
                preview_geometry._first_blocking_obstacle(
                    (0, 0, 0), (4, 0, 0), obstacles, (0, 0, 0)
                ),
                obstacles[0],
            )
        self.assertIsNone(
            preview_geometry._first_blocking_obstacle((0, 1, 0), (4, 1, 0), boxes, (0, 0, 0), 0)
        )
