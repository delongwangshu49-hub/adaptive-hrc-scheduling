"""Read small, identity-bound stop/final receipts before publishing a request."""

from pathlib import Path

from s19b_desktop.model import read_json

from adaptive_hrc_scheduling.contracts.session import digest

TERMINAL_PHASES = {
    "COMPLETED",
    "STOPPED",
    "STOP_BLOCKED",
    "WINDOW_CENSORED",
    "WALL_CENSORED",
    "DRAIN_BLOCKED",
    "FAILED",
}
BLOCKED_PHASES = TERMINAL_PHASES | {"STOPPING", "UNKNOWN"}


def control_phase(directory, launch):
    path = Path(directory) / "control-state.json"
    try:
        state = read_json(path, 32_000_000)
    except FileNotFoundError:
        return None
    except (OSError, ValueError, TypeError):
        return "UNKNOWN"
    if (
        not isinstance(state, dict)
        or (state.get("run_id"), state.get("request_id"))
        != (launch["run_id"], launch["request_id"])
        or not isinstance(state.get("phase"), str)
        or state.get("phase") not in BLOCKED_PHASES | {"STARTING", "RUNNING"}
    ):
        return "UNKNOWN"
    return state["phase"]


class WriteFence:
    def __init__(self, directory, spec):
        self.directory = Path(directory)
        self.identity = (spec["run_id"], spec["epoch"], digest(spec))
        self.latched = None
        self.launch = None
        self.control_directory = (
            self.directory.parent if self.directory.name == "session" else self.directory
        )
        path = self.control_directory / "request.json"
        try:
            launch = read_json(path, 16_000_000)
            if (
                not isinstance(launch, dict)
                or launch.get("run_id") != spec["run_id"]
                or not isinstance(launch.get("request_id"), str)
                or digest(launch.get("session", {}).get("spec")) != self.identity[2]
            ):
                self.latched = "LAUNCH_IDENTITY_UNKNOWN"
            else:
                self.launch = launch
        except FileNotFoundError:
            pass  # A standalone Session has no desktop control transport.
        except (OSError, ValueError, TypeError, AttributeError):
            self.latched = "LAUNCH_IDENTITY_UNKNOWN"

    def reason(self):
        if self.latched:
            return self.latched
        if self.launch:
            phase = control_phase(self.control_directory, self.launch)
            if phase in BLOCKED_PHASES:
                self.latched = "CONTROL_" + phase
                return self.latched
        try:
            record = read_json(self.directory / "final-commit.json", 1_000_000)
        except FileNotFoundError:
            return None
        except (OSError, ValueError, TypeError):
            return "FINAL_STATE_UNKNOWN"
        if not isinstance(record, dict) or not isinstance(record.get("final"), dict):
            return "FINAL_STATE_UNKNOWN"
        final = record["final"]
        if (
            (
                final.get("run_id"),
                final.get("epoch"),
                final.get("run_spec_sha256"),
            )
            != self.identity
            or not isinstance(final.get("phase"), str)
            or final["phase"] not in TERMINAL_PHASES
        ):
            return "FINAL_IDENTITY_OR_PHASE_UNKNOWN"
        self.latched = "SESSION_TERMINAL"
        return self.latched
