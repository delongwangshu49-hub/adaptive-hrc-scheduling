"""Identity-bound display telemetry. Timeline and control remain authoritative."""

import re
import time

from s19b_desktop.model import read_json

FORMAT = "P051-PLANNING-1"


def read_feedback(path, identity, limit=4096):
    try:
        value = read_json(path, limit)
    except (OSError, ValueError, TypeError):
        return None
    if isinstance(value, dict) and all(
        type(value.get(k)) is type(v) and value[k] == v for k, v in identity.items()
    ):
        return value
    return None


def age(timestamp, now):
    if type(timestamp) in (int, float) and 0 <= timestamp <= now:
        return now - timestamp
    return None


class PlanningFeedback:
    def __init__(self, launch=None, *, require_stage=True, spec=None):
        self.identity = (
            dict(
                run_id=launch["run_id"],
                epoch=launch["session"]["spec"]["epoch"],
                request_id=launch["request_id"],
            )
            if launch and launch.get("session")
            else None
        )
        if self.identity is None and spec is not None:
            self.identity = {k: spec[k] for k in ("run_id", "epoch")}
        self.latest = {}
        self.requires_stage = bool(launch and self.identity and require_stage)
        self.stage_available = False
        self.stage_invalid = False
        self.heartbeat = {}
        self.confirmed_versions = set()
        self.frozen = False
        self.started_at = time.monotonic()

    def refresh(self, directory, *, terminal=False, exited=False):
        self.frozen |= terminal
        if not self.identity or "request_id" not in self.identity or exited:
            return
        now = time.monotonic()
        pulse = read_feedback(directory / "live.json", self.identity, 2_000_000)
        if (
            pulse
            and type(pulse.get("sequence")) is int
            and pulse["sequence"] > self.heartbeat.get("sequence", 0)
            and age(pulse.get("published_monotonic_s"), now) is not None
            and pulse["published_monotonic_s"] >= self.heartbeat.get("published_monotonic_s", 0)
        ):
            self.heartbeat = pulse
            if pulse.get("planning_feedback") == FORMAT:
                self.requires_stage = True
        self.refresh_stage(directory)

    def refresh_stage(self, directory):
        if not self.identity or "request_id" not in self.identity or self.frozen:
            return
        path = directory / "p051-planning.json"
        record = read_feedback(path, self.identity)
        self.stage_available = False
        self.stage_invalid = path.is_file()
        if not record or record.get("format") != FORMAT:
            if self.stage_invalid:
                self.requires_stage = True
            return
        self.requires_stage = True
        if record == self.latest:
            self.stage_available = True
            self.stage_invalid = False
            return
        now = time.monotonic()
        task, sequence, version = (record.get(k) for k in ("task", "sequence", "version"))
        phase, key = record.get("phase"), record.get("artifact_sha256")
        if (
            any(type(value) is not int or value < 1 for value in (task, sequence, version))
            or phase not in ("PLANNING", "AWAITING_VERIFICATION", "FAILED")
            or sequence != 2 * task - (phase == "PLANNING")
            or sequence <= self.latest.get("sequence", 0)
            or age(record.get("started_monotonic_s"), now) is None
            or age(record.get("changed_monotonic_s"), now) is None
            or not record["started_monotonic_s"] <= record["changed_monotonic_s"]
            or record["started_monotonic_s"] < self.latest.get("started_monotonic_s", 0)
            or record["changed_monotonic_s"] < self.latest.get("changed_monotonic_s", 0)
            or (
                task == self.latest.get("task")
                and (
                    version != self.latest["version"]
                    or record["started_monotonic_s"] != self.latest["started_monotonic_s"]
                )
            )
        ):
            return
        if phase == "AWAITING_VERIFICATION":
            if not isinstance(key, str) or not re.fullmatch(r"[0-9a-f]{64}", key):
                return
        elif key is not None:
            return
        self.latest = record
        self.stage_available = True
        self.stage_invalid = False

    def matches(self, plan, reference):
        if (
            not plan
            or reference.get("failure")
            or reference.get("planning")
            or reference.get("solve_calls") != plan["task"]
            or any(reference.get(k) != plan[k] for k in ("version", "artifact_sha256"))
        ):
            return False
        return not self.requires_stage or (
            self.stage_available
            and self.latest.get("phase") == "AWAITING_VERIFICATION"
            and all(self.latest[k] == plan[k] for k in ("task", "version", "artifact_sha256"))
        )

    def project(self, view, previous, *, hold=False):
        """Commit plan rows separately so observations can advance during a hold."""
        plan = view.get("verified_full_schedule")
        prior = previous.get("verified_full_schedule")
        if not self.identity or not (plan or prior):
            return view
        # While a newer task is in progress or STOP is outstanding, keep the
        # entire previous confirmed layer. Never promote late audit results.
        if (
            self.frozen
            or hold
            or not self.matches(plan, view.get("full_schedule") or {})
            or any(
                (view.get("envelope") or {}).get(k) != self.identity[k] for k in ("run_id", "epoch")
            )
            or view.get("status") == "STALE_CORRUPT"
            or (prior and plan["version"] <= prior["version"])
        ):
            rows = [r for r in view.get("rows", []) if r["row_kind"] != "FULL_PLAN"]
            rows.extend(r for r in previous.get("rows", []) if r["row_kind"] == "FULL_PLAN")
            return dict(view, rows=rows, verified_full_schedule=prior)
        self.confirmed_versions.add(plan["version"])
        return dict(
            view,
            rows=[
                r
                for r in view["rows"]
                if r["row_kind"] != "FULL_PLAN" or r["plan_version"] in self.confirmed_versions
            ],
        )

    def status(self, view, *, hold=False, failed=False):
        now = time.monotonic()
        record = self.latest
        shown = view.get("verified_full_schedule")
        ref = view.get("full_schedule") or {}
        state = record.get("phase")
        candidate = record.get("version")
        waiting = None
        if failed:
            state, candidate = "FAILED", None
        elif self.frozen or hold:
            state, candidate = "HELD", None
        elif view.get("full_reference_error"):
            state, candidate = "FAILED", None
        elif self.requires_stage:
            ref_task = ref.get("solve_calls") or 0
            task = record.get("task", 0)
            conflicts = (
                state == "AWAITING_VERIFICATION"
                and ref_task == task
                and not (ref.get("planning") or ref.get("failure"))
                and (
                    ref.get("artifact_sha256") != record["artifact_sha256"]
                    or ref.get("version") != record["version"]
                )
            )
            if ref.get("failure") and ref_task >= task:
                state = "FAILED"
                candidate = candidate if ref_task == task else None
                if record.get("phase") == "FAILED" and ref_task == task:
                    waiting = record["changed_monotonic_s"] - record["started_monotonic_s"]
            elif not self.stage_available or ref_task > task or conflicts:
                if (
                    self.stage_invalid
                    or record
                    or ref.get("artifact_sha256")
                    or ref.get("solve_calls")
                ):
                    state, candidate = "UNAVAILABLE", ref.get("version") or None
                else:
                    state, candidate = "WAITING", None
                    waiting = age(self.started_at, now)
            elif self.matches(shown, ref):
                state, candidate = "AVAILABLE", None
            elif state == "AWAITING_VERIFICATION" and (
                ref.get("artifact_sha256") == record["artifact_sha256"]
                and view.get("full_schedule_audit_error")
            ):
                state = "FAILED"
            elif state in ("PLANNING", "AWAITING_VERIFICATION"):
                waiting = age(record["started_monotonic_s"], now)
            elif state == "FAILED":
                waiting = record["changed_monotonic_s"] - record["started_monotonic_s"]
            elif not state:
                state = "WAITING"
                waiting = age(self.started_at, now)
        elif ref:
            if ref.get("failure") or view.get("full_schedule_audit_error"):
                state = "FAILED"
            elif self.matches(shown, ref):
                state = "AVAILABLE"
            elif ref.get("planning"):
                state, candidate = "PLANNING", ref["version"] + 1
            elif not ref.get("artifact_sha256"):
                state = "WAITING"
            else:
                state, candidate = "AWAITING_VERIFICATION", ref.get("version") or None
        elif self.identity:
            state = "WAITING"
            waiting = age(self.started_at, now)
        return dict(
            identity=self.identity
            or (
                {k: view["envelope"][k] for k in ("run_id", "epoch")}
                if view.get("envelope")
                else None
            ),
            sequence=record.get("sequence"),
            task=record.get("task"),
            changed_monotonic_s=record.get("changed_monotonic_s"),
            phase=state,
            wait_s=waiting,
            candidate_version=candidate,
            shown_version=shown["version"] if shown else None,
            plan_age_s=age(shown["sampled_monotonic_s"], now) if shown and self.identity else None,
            plan_sample_h=shown["sampled_sim_h"] if shown else None,
            heartbeat_age_s=age(self.heartbeat.get("published_monotonic_s"), now),
        )
