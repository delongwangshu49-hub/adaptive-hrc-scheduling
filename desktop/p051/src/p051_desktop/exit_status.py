"""Separate the launcher return code from a worker's saved completion."""

import hashlib
from pathlib import Path

from s19b_desktop.model import read_json


def saved_status(directory, launch):
    """Check small completion receipts; this is not an independent save audit."""
    result = dict(status="INCOMPLETE", reason=None)
    try:
        root = Path(directory)
        report = read_json(root / "report.json", 16_000_000)
        control = read_json(root / "control-state.json", 16_000_000)
        if not isinstance(report, dict) or not isinstance(control, dict):
            raise ValueError("COMPLETION_RECORD_SHAPE")
        identity = (launch["run_id"], launch["request_id"])
        if (report.get("run_id"), report.get("request_id")) != identity or (
            control.get("run_id"),
            control.get("request_id"),
        ) != identity:
            raise ValueError("COMPLETION_IDENTITY")
        if control.get("phase") not in ("STOPPED", "COMPLETED"):
            raise ValueError("COMPLETION_NOT_TERMINAL")
        if report.get("status") != "PASS":
            raise ValueError("COMPLETION_REPORT_FAILED")
        if report.get("closed") is not True:
            raise ValueError("COMPLETION_CLOSE_UNCONFIRMED")
        if launch.get("session"):
            final = read_json(root / "session/final-commit.json", 1_000_000)["final"]
            if not isinstance(final, dict):
                raise ValueError("COMPLETION_RECORD_SHAPE")
            if (
                (final.get("run_id"), final.get("epoch"))
                != (launch["run_id"], launch["session"]["spec"].get("epoch", 0))
                or final.get("phase") != control["phase"]
                or final.get("save_status") != "COMPLETE"
                or final.get("audit_status") != "PASS"
                or report.get("session_final") != final
            ):
                raise ValueError("COMPLETION_FINAL_MISMATCH")
        return dict(result, status="SAVED_COMPLETION_RECORDED", reason=None)
    except (OSError, ValueError, KeyError, TypeError) as error:
        return dict(result, reason=str(error))


def native_exit_code(directory, launch):
    """Return only a native exit receipt bound to this launch and request."""
    root = Path(directory)
    try:
        marker = read_json(root / "worker-launch.json", 1_000_000)
        native = read_json(root / "worker-native-exit.json", 1_000_000)
        binding = dict(
            run_id=launch["run_id"],
            request_id=launch["request_id"],
            launch_id=marker["launch_id"],
            request_sha256=hashlib.sha256((root / "request.json").read_bytes()).hexdigest(),
        )
        if (
            marker.get("format") == "S19B-NATIVE-LAUNCH-1"
            and native.get("format") == "S19B-NATIVE-EXIT-1"
            and isinstance(binding["launch_id"], str)
            and binding["launch_id"]
            and all(marker.get(k) == v and native.get(k) == v for k, v in binding.items())
            and native.get("state") == "EXITED"
            and type(native.get("pid")) is int
            and native["pid"] > 0
            and type(native.get("returncode")) is int
        ):
            return native["returncode"]
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        pass
    return None


def completion_status(directory, launch, launcher_code):
    if launcher_code != 0:
        return dict(launcher_code=launcher_code, status="INCOMPLETE", reason="LAUNCHER_NONZERO")
    result = saved_status(directory, launch)
    if (
        result["status"] == "SAVED_COMPLETION_RECORDED"
        and launch.get("backend") == "isaac"
        and native_exit_code(directory, launch) != 0
    ):
        result = dict(status="INCOMPLETE", reason="COMPLETION_NATIVE_EXIT_UNCONFIRMED")
    return dict(result, launcher_code=launcher_code)
