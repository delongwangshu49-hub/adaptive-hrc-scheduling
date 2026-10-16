import copy
import shutil
import tempfile
import time
import unittest
from pathlib import Path

from s19b_desktop.control import (
    Controller,
    command,
    confirmation,
    recover,
    submit,
    validate_control,
)
from s19b_desktop.model import (
    PROTOCOL,
    Draft,
    InputError,
    atomic_json,
    canonical_digest,
    validate_request,
)

ROOT = Path(__file__).resolve().parents[3]


def request(directory=None):
    value = dict(
        protocol=PROTOCOL,
        run_id="B2-test",
        request_id="req-test",
        backend="light",
        draft=Draft().data(),
        created_at="test",
        display_hold_s=0,
    )
    value["control"] = confirmation(value, ROOT, directory or ROOT / ".local/control-test")
    return value


class ControlTests(unittest.TestCase):
    def test_stop_before_start_acceptance_is_persistently_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            value = request(directory)
            controller = Controller(directory, value)
            stop = command(value, "stop", 1)
            receipt = controller.accept(stop)
            self.assertFalse(receipt["accepted"])
            self.assertEqual(receipt["reason"], "CONTROL_ILLEGAL_STATE")
            self.assertFalse(controller.state["commands"])
            self.assertEqual(controller.state["last_sequence"], 0)
            self.assertEqual(controller.accept(stop), receipt)
            self.assertTrue(controller.accept(command(value, "start", 1))["accepted"])

    def test_confirmation_binds_draft_backend_and_input_sources(self):
        value = request()
        validate_request(value)
        validate_control(value, ROOT)
        for change in (dict(draft={**value["draft"], "note": "changed"}), dict(backend="isaac")):
            with self.subTest(change=change), self.assertRaises(InputError):
                validate_request({**value, **change})
        for key, replacement in (
            ("epoch", True),
            ("accepted", 1),
            ("confirmed_at", float("nan")),
            ("confirmed_at", time.time() + 100),
            ("inputs", {}),
        ):
            with self.subTest(key=key), self.assertRaises(InputError):
                validate_request({**value, "control": {**value["control"], key: replacement}})
        changed = copy.deepcopy(value)
        name = next(iter(changed["control"]["inputs"]))
        changed["control"]["inputs"][name] = "0" * 64
        with self.assertRaisesRegex(InputError, "SOURCE_CHANGED"):
            validate_control(changed, ROOT)

    def test_backend_persistent_dedup_conflicts_epochs_order_and_state(self):
        with tempfile.TemporaryDirectory() as directory:
            value = request(directory)
            atomic_json(Path(directory) / "request.json", value)
            controller = Controller(directory, value)
            start = command(value, "start", 1)
            original = controller.accept(start)
            self.assertTrue(original["accepted"])
            self.assertEqual(controller.accept(start), original)
            controller.initialized()
            self.assertEqual(original["result"], "STARTED")
            for changes in (
                dict(action="stop"),
                dict(run_id="OLD"),
                dict(epoch=1),
                dict(epoch=True),
                dict(sequence=3, command_id="gap"),
                dict(confirmed=False),
                dict(action="pause"),
            ):
                row = {**start, **changes}
                with self.subTest(changes=changes):
                    receipt = controller.accept(row)
                    self.assertFalse(receipt["accepted"])
                    self.assertEqual(controller.accept(row), receipt)
            stop = command(value, "stop", 2)
            submit(directory, stop)
            self.assertTrue(controller.poll())
            self.assertTrue(controller.poll())
            self.assertEqual(controller.state["last_sequence"], 2)
            self.assertEqual(len(controller.state["commands"]), 2)
            state, pending = recover(directory, value)
            self.assertFalse(pending)
            self.assertEqual(state["phase"], "STOPPING")
            controller.finish("STOPPED", {"unfinished": True})
            self.assertEqual(controller.accept(stop)["result"], "STOPPED")
            self.assertFalse(controller.accept(command(value, "stop", 3))["accepted"])
            self.assertFalse(controller.accept(command(value, "start", 3))["accepted"])

    def test_recovery_pending_readonly_no_replay_and_corruption(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            value = request(directory)
            atomic_json(root / "request.json", value)
            controller = Controller(root, value)
            controller.accept(command(value, "start", 1))
            stop = command(value, "stop", 2)
            submit(root, stop)
            before = {p: p.read_bytes() for p in root.rglob("*.json")}
            for _ in range(3):
                state, pending = recover(root, value)
                self.assertEqual(pending, [canonical_digest(stop)])
                self.assertEqual(state["last_sequence"], 1)
            self.assertEqual(before, {p: p.read_bytes() for p in root.rglob("*.json")})
            controller.poll()
            state, pending = recover(root, value)
            self.assertEqual(pending, [])
            state["epoch"] = 1
            atomic_json(root / "control-state.json", state)
            with self.assertRaises(InputError):
                recover(root, value)

    def test_run_directory_is_bound_and_missing_damaged_records_are_unknown(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "original"
            root.mkdir()
            value = request(root)
            validate_control(value, ROOT, root)
            with self.assertRaisesRegex(InputError, "DIRECTORY_CHANGED"):
                validate_control(value, ROOT, root.parent / "copy")
            atomic_json(root / "request.json", value)
            controller = Controller(root, value)
            controller.accept(command(value, "start", 1))
            copy_dir = root.parent / "copy"
            shutil.copytree(root, copy_dir)
            with self.assertRaisesRegex(InputError, "DIRECTORY_CHANGED"):
                recover(copy_dir, value)
            for damaged in ([], {"run_id": "OLD"}, "damaged"):
                atomic_json(root / "control-state.json", damaged)
                with self.assertRaises(InputError):
                    recover(root, value)
            (root / "control-state.json").unlink()
            with self.assertRaises(FileNotFoundError):
                recover(root, value)


if __name__ == "__main__":
    unittest.main()
