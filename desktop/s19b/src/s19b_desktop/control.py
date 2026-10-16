"""B2 local single-writer control. No Qt, planner inputs, or command replay.

The inbox contains immutable content-addressed envelopes; one permanently claimed
run directory owns one worker. A crashed worker is never restarted in that run.
Acceptance is durably recorded before the driver latches the stop boundary.
"""

import ctypes
import hashlib
import os
import re
import time
import uuid
from pathlib import Path

from .model import InputError, atomic_json, canonical_digest, read_json

PROTOCOL = "S19B-CONTROL-1"
INPUTS = (
    "examples/online/limits.json",
    "examples/building_contracts/configuration.json",
    "src/adaptive_hrc_scheduling/production_recipe.json",
)
TERMINAL = ("STOPPED", "STOP_BLOCKED", "COMPLETED", "FAILED")
CAPABILITIES = {
    "start": "CONFIRMED_FRESH_DIRECTORY_SINGLE_WORKER",
    "stop": "NO_NEW_DISPATCH_DRAIN_STARTED_KEEP_HOLDS_AND_COMMITMENTS",
    "reconnect": "READ_SAME_IDENTITY_NO_REPLAY_NO_BACKEND_RESTART",
    "pause": "DISABLED_NOT_VALIDATED",
    "resume": "DISABLED_NOT_VALIDATED",
    "reset": "DISABLED_NOT_VALIDATED",
    "runtime_orders": "DISABLED_PRODUCTION_SCOPE_UNCHANGED",
}


def identity(request):
    return dict(run_id=request["run_id"], request_id=request["request_id"], epoch=0)


def input_digests(root):
    return {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in INPUTS}


def confirmation(request, root, directory):
    return dict(
        protocol=PROTOCOL,
        epoch=0,
        accepted=True,
        confirmed_at=time.time(),
        draft_sha256=canonical_digest(request["draft"]),
        backend=request["backend"],
        inputs=input_digests(root),
        directory=str(Path(directory).resolve()),
    )


def validate_control(request, root=None, directory=None):
    value = request.get("control")
    if not isinstance(value, dict) or set(value) != {
        "protocol",
        "epoch",
        "accepted",
        "confirmed_at",
        "draft_sha256",
        "backend",
        "inputs",
        "directory",
    }:
        raise InputError("CONTROL_CONFIRMATION_FIELDS")
    if (
        value["protocol"] != PROTOCOL
        or type(value["epoch"]) is not int
        or value["epoch"] != 0
        or value["accepted"] is not True
        or type(value["confirmed_at"]) not in (int, float)
        or not 0 < value["confirmed_at"] <= time.time() + 2
        or value["draft_sha256"] != canonical_digest(request["draft"])
        or value["backend"] != request["backend"]
        or not isinstance(value["directory"], str)
        or not Path(value["directory"]).is_absolute()
        or not isinstance(value["inputs"], dict)
        or set(value["inputs"]) != set(INPUTS)
        or any(
            not isinstance(v, str) or not re.fullmatch("[a-f0-9]{64}", v)
            for v in value["inputs"].values()
        )
    ):
        raise InputError("CONTROL_CONFIRMATION_MISMATCH")
    if root is not None and value["inputs"] != input_digests(root):
        raise InputError("CONTROL_INPUT_SOURCE_CHANGED")
    if directory is not None and Path(value["directory"]).resolve() != Path(directory).resolve():
        raise InputError("CONTROL_RUN_DIRECTORY_CHANGED")
    return value


def command(request, action, sequence, *, command_id=None):
    return dict(
        protocol=PROTOCOL,
        **identity(request),
        command_id=command_id or uuid.uuid4().hex,
        sequence=sequence,
        action=action,
        confirmed=True,
        request_sha256=canonical_digest(request),
    )


def validate_command(value, request):
    if not isinstance(value, dict) or set(value) != {
        "protocol",
        "run_id",
        "request_id",
        "epoch",
        "command_id",
        "sequence",
        "action",
        "confirmed",
        "request_sha256",
    }:
        raise InputError("CONTROL_FIELDS")
    if value["protocol"] != PROTOCOL or any(
        type(value[k]) is not type(v) or value[k] != v for k, v in identity(request).items()
    ):
        raise InputError("CONTROL_IDENTITY_EPOCH")
    if (
        not isinstance(value["command_id"], str)
        or not re.fullmatch("[a-zA-Z0-9-]{1,80}", value["command_id"])
        or type(value["sequence"]) is not int
        or value["sequence"] < 1
    ):
        raise InputError("CONTROL_SEQUENCE_ID")
    if value["confirmed"] is not True or value["request_sha256"] != canonical_digest(request):
        raise InputError("CONTROL_UNCONFIRMED_OR_CHANGED")
    if value["action"] not in ("start", "stop"):
        raise InputError("CONTROL_UNSUPPORTED")
    return value


def submit(directory, value):
    """Exclusive create + atomic rename; retries never rewrite an envelope."""
    inbox = Path(directory) / "control-inbox"
    inbox.mkdir(exist_ok=True)
    key = canonical_digest(value)
    path = inbox / (key + ".json")
    if path.exists():
        if read_json(path) != value:
            raise InputError("CONTROL_INBOX_DAMAGED")
        return key
    temp = inbox / (uuid.uuid4().hex + ".tmp")
    try:
        atomic_json(temp, value)
        # Identical content may be submitted by multiple clients; replace is
        # safe only because this path is the digest of the entire envelope.
        temp.replace(path)
    finally:
        temp.unlink(missing_ok=True)
    return key


def process_token(pid):
    """Kernel process creation time prevents PID reuse from becoming a reconnect."""
    if os.name != "nt":
        raise InputError("CONTROL_RECONNECT_WINDOWS_ONLY")
    from ctypes import wintypes

    api = ctypes.WinDLL("kernel32", use_last_error=True)
    api.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    api.OpenProcess.restype = wintypes.HANDLE
    api.GetProcessTimes.argtypes = (wintypes.HANDLE, *([ctypes.POINTER(wintypes.FILETIME)] * 4))
    api.CloseHandle.argtypes = (wintypes.HANDLE,)
    handle = api.OpenProcess(0x1000, False, pid)
    if not handle:
        return None
    try:
        values = [wintypes.FILETIME() for _ in range(4)]
        if not api.GetProcessTimes(handle, *(ctypes.byref(v) for v in values)):
            raise ctypes.WinError(ctypes.get_last_error())
        return (values[0].dwHighDateTime << 32) | values[0].dwLowDateTime
    finally:
        api.CloseHandle(handle)


class ProcessWatch:
    """Keep an actual kernel handle across reconnect until exit is observed."""

    def __init__(self, started):
        from ctypes import wintypes

        if process_token(started["pid"]) != started.get("process_token"):
            raise InputError("CONTROL_PROCESS_MISSING_OR_REUSED")
        self.api = ctypes.WinDLL("kernel32", use_last_error=True)
        self.api.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        self.api.OpenProcess.restype = wintypes.HANDLE
        self.api.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
        self.api.GetExitCodeProcess.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
        self.api.CloseHandle.argtypes = (wintypes.HANDLE,)
        self.handle = self.api.OpenProcess(0x100000 | 0x1000, False, started["pid"])
        if not self.handle:
            raise InputError("CONTROL_PROCESS_UNOBSERVABLE")
        # Check again after opening the retained handle.
        if process_token(started["pid"]) != started["process_token"]:
            self.close()
            raise InputError("CONTROL_PROCESS_REUSED")

    def exit_code(self):
        from ctypes import wintypes

        status = self.api.WaitForSingleObject(self.handle, 0)
        if status == 0x102:
            return None
        if status != 0:
            raise InputError("CONTROL_PROCESS_WAIT_FAILED")
        code = wintypes.DWORD()
        if not self.api.GetExitCodeProcess(self.handle, ctypes.byref(code)):
            raise ctypes.WinError(ctypes.get_last_error())
        return code.value

    def close(self):
        if self.handle:
            self.api.CloseHandle(self.handle)
            self.handle = None


class Controller:
    def __init__(self, directory, request):
        self.directory, self.request = Path(directory), request
        self.path = self.directory / "control-state.json"
        self.state = dict(
            protocol=PROTOCOL,
            **identity(request),
            request_sha256=canonical_digest(request),
            phase="STARTING",
            last_sequence=0,
            commands={},
            responses={},
            capabilities=CAPABILITIES,
            stop=None,
        )

    def save(self):
        atomic_json(self.path, self.state)

    def accept(self, value):
        key = canonical_digest(value)
        # Each envelope has one stable response, including rejected requests.
        if key in self.state["responses"]:
            return self.state["responses"][key]
        reason = None
        try:
            validate_command(value, self.request)
            old = self.state["commands"].get(value["command_id"])
            if old is not None:
                if old["digest"] != key:
                    raise InputError("CONTROL_ID_CONTENT_CONFLICT")
                return self.state["responses"][key]
            if value["sequence"] != self.state["last_sequence"] + 1:
                raise InputError("CONTROL_OUT_OF_ORDER")
            if value["action"] == "start":
                if self.state["phase"] != "STARTING" or self.state["commands"]:
                    raise InputError("CONTROL_ALREADY_STARTED")
            elif not self.state["commands"] or self.state["phase"] not in (
                "STARTING",
                "RUNNING",
                "STOPPING",
            ):
                raise InputError("CONTROL_ILLEGAL_STATE")
            self.state["last_sequence"] = value["sequence"]
            self.state["commands"][value["command_id"]] = dict(digest=key, request=value)
            if value["action"] == "stop":
                self.state["stop"] = self.state["stop"] or value["command_id"]
                self.state["phase"] = "STOPPING"
        except (ValueError, TypeError, KeyError) as error:
            reason = str(error)
        receipt = dict(
            **identity(self.request),
            envelope_sha256=key,
            command_id=value.get("command_id") if isinstance(value, dict) else None,
            accepted=reason is None,
            reason=reason or "ACCEPTED_NOT_COMPLETED",
            accepted_wall_s=time.time(),
            result=None,
        )
        self.state["responses"][key] = receipt
        self.save()  # durable acceptance precedes driver side effect
        return receipt

    def poll(self):
        inbox = self.directory / "control-inbox"
        rows = []
        for path in inbox.glob("*.json"):
            if path.stem in self.state["responses"]:
                continue
            try:
                value = read_json(path)
                if canonical_digest(value) != path.stem:
                    raise InputError("CONTROL_ENVELOPE_DAMAGED")
                rows.append(value)
            except (OSError, ValueError, TypeError) as error:
                # Damaged transport is a fault, never silently acted on.
                self.state["transport_error"] = str(error)
                self.save()
        rows.sort(
            key=lambda x: (
                x.get("sequence", -1)
                if isinstance(x, dict) and type(x.get("sequence")) is int
                else -1
            )
        )
        for row in rows:
            self.accept(row)
        return self.state["stop"] is not None

    def initialized(self):
        if not self.state["stop"]:
            self.state["phase"] = "RUNNING"
        for entry in self.state["commands"].values():
            if entry["request"]["action"] == "start":
                self.state["responses"][entry["digest"]]["result"] = "STARTED"
        self.save()

    def finish(self, phase, manifest):
        self.state["phase"] = phase
        self.state["final"] = manifest
        for entry in self.state["commands"].values():
            if entry["request"]["action"] == "stop":
                self.state["responses"][entry["digest"]]["result"] = phase
        self.save()


def recover(directory, request):
    """Read-only reconciliation. Never starts a process or submits an envelope."""
    from .model import validate_request

    directory = Path(directory)
    saved = validate_request(read_json(directory / "request.json"))
    validate_control(saved, directory=directory)
    if canonical_digest(saved) != canonical_digest(request) or "control" not in saved:
        raise InputError("CONTROL_RECOVERY_REQUEST_MISMATCH")
    state = read_json(directory / "control-state.json", 5_000_000)
    if (
        not isinstance(state, dict)
        or state.get("protocol") != PROTOCOL
        or any(
            type(state.get(k)) is not type(v) or state[k] != v for k, v in identity(saved).items()
        )
        or state.get("request_sha256") != canonical_digest(saved)
    ):
        raise InputError("CONTROL_RECOVERY_IDENTITY")
    for entry in state["commands"].values():
        validate_command(entry["request"], saved)
        if canonical_digest(entry["request"]) != entry["digest"]:
            raise InputError("CONTROL_RECOVERY_COMMAND_DAMAGED")
    pending = []
    for path in (directory / "control-inbox").glob("*.json"):
        value = read_json(path)
        if canonical_digest(value) != path.stem:
            raise InputError("CONTROL_RECOVERY_ENVELOPE_DAMAGED")
        if path.stem not in state["responses"]:
            validate_command(value, saved)
            pending.append(path.stem)
    return state, pending
