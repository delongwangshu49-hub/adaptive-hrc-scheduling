"""Display the milestones of the original safe-stop command."""

import time

from s19b_desktop.control import PROTOCOL, identity, submit

from .exit_status import native_exit_code, saved_status
from .planning import read_feedback
from .write_fence import TERMINAL_PHASES


class StopFeedback:
    def __init__(self):
        self.command_id = self.key = self.submitted_at = None
        self.request_sha = None
        self.envelope = None
        self.receipt = {}
        self.saved = False
        self.worker_code = None

    def send(self, directory, envelope):
        if self.command_id == envelope["command_id"] or self.holding:
            return self.command_id, self.key
        self.key = submit(directory, envelope)
        self.command_id, self.submitted_at = envelope["command_id"], time.monotonic()
        self.request_sha = envelope["request_sha256"]
        self.envelope = dict(envelope)
        self.receipt = {}
        return self.command_id, self.key

    @property
    def holding(self):
        return self.command_id is not None and self.receipt.get("accepted") is not False

    def control_record(self, directory, launch):
        return (
            read_feedback(
                directory / "control-state.json",
                dict(identity(launch), protocol=PROTOCOL, request_sha256=self.request_sha),
                32_000_000,
            )
            or {}
        )

    def missing_envelope(self, directory, state):
        sequence = state.get("last_sequence")
        if not (
            self.envelope
            and not self.receipt
            and time.monotonic() - self.submitted_at >= 3
            and state.get("phase") in ("STARTING", "RUNNING")
            and "stop" in state
            and state["stop"] is None
            and type(sequence) is int
            and sequence >= 1
            and sequence + 1 == self.envelope["sequence"]
            and isinstance(state.get("commands"), dict)
            and self.command_id not in state["commands"]
            and isinstance(state.get("responses"), dict)
            and self.key not in state["responses"]
        ):
            return False
        path = directory / "control-inbox" / (self.key + ".json")
        try:
            path.lstat()
        except FileNotFoundError:
            return True
        except OSError:
            return False
        return False

    def restore_missing(self, directory, launch, envelope):
        """Explicit recovery reuses the exact original command and digest."""
        if envelope != self.envelope or not self.missing_envelope(
            directory, self.control_record(directory, launch)
        ):
            return False
        submit(directory, self.envelope)
        return True

    def status(self, directory, launch, launcher_code):
        if not self.command_id:
            return None
        binding = identity(launch)
        state = self.control_record(directory, launch)
        responses = state.get("responses")
        receipt = responses.get(self.key) if isinstance(responses, dict) else None
        if (
            isinstance(receipt, dict)
            and receipt.get("command_id") == self.command_id
            and receipt.get("envelope_sha256") == self.key
            and all(receipt.get(k) == v for k, v in binding.items())
            and type(receipt.get("accepted")) is bool
            and (not self.receipt or receipt["accepted"] == self.receipt["accepted"])
            and (not self.receipt.get("result") or receipt.get("result") == self.receipt["result"])
        ):
            self.receipt = receipt
        accepted = self.receipt.get("accepted")
        if accepted is None:
            acceptance = (
                "UNKNOWN"
                if launcher_code is not None or time.monotonic() - self.submitted_at >= 3
                else "PENDING"
            )
        else:
            acceptance = "ACCEPTED" if accepted else "REJECTED"
        if accepted and self.receipt.get("result") == "STOPPED" and not self.saved:
            self.saved = saved_status(directory, launch)["status"] == "SAVED_COMPLETION_RECORDED"
        if launch["backend"] == "isaac":
            if self.worker_code is None:
                self.worker_code = native_exit_code(directory, launch)
        else:
            self.worker_code = launcher_code
        save = "PENDING"
        if self.saved:
            save = "SAVED"
        elif self.receipt.get("result") in TERMINAL_PHASES or launcher_code is not None:
            save = "UNCONFIRMED"
        return dict(
            request_id=self.command_id,
            acceptance=acceptance,
            save=save,
            worker_exit=self.worker_code,
            launcher_exit=launcher_code,
            recoverable=launcher_code is None and self.missing_envelope(directory, state),
        )
