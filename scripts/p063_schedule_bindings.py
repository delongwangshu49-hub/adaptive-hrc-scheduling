"""Bind delivered full-plan references and display rows to audited artifacts.

This metadata gate supplements the original execution/proof checkers. It never
replaces their audits and never changes a live consumer or a production writer.
"""

import json

from adaptive_hrc_scheduling.contracts.session import digest


def require(value, reason):
    if not value:
        raise ValueError("P063_" + reason)


class ScheduleBindings:
    def __init__(self, directory):
        self.directory = directory
        self.spec = self.read("run-spec.json")
        self.report = self.read("full-schedule-state.json")
        self.plans = {}
        self.versions = {}
        for entry in self.report["history"]:
            if entry["status"] != "ADOPTED":
                continue
            key = entry["plan_sha256"]
            require(
                isinstance(key, str)
                and len(key) == 64
                and all(c in "0123456789abcdef" for c in key),
                "PLAN_ARTIFACT_PATH",
            )
            plan = self.read("full-schedules/" + key + ".json")
            require(digest(plan) == key, "PLAN_ARTIFACT_CHANGED")
            require(
                plan["format"] == "P051-FULL-SCHEDULE-1"
                and plan["plan_id"] == self.spec["run_id"] + ":FULL"
                and type(plan["version"]) is int
                and plan["version"] == entry["version"]
                and plan["anchor_h"] == entry["at_h"]
                and plan["anchor_events"] == entry["anchor"][2]
                and plan["version"] not in self.versions,
                "PLAN_ADOPTION_IDENTITY",
            )
            self.plans[key] = plan
            self.versions[plan["version"]] = key
        require(
            sorted(self.versions) == list(range(1, self.report["version"] + 1))
            and self.versions.get(self.report["version"]) == self.report["plan_sha256"],
            "PLAN_FINAL_HISTORY",
        )
        self.reference = None
        self.packets = 0
        self.seen_plan = False

    def read(self, name):
        return json.loads((self.directory / name).read_bytes())

    def check_reference(self, packet, prefix_hashes):
        self.packets += 1
        ref = packet.get("full_schedule")
        require(type(ref) is dict, "FULL_REFERENCE_REQUIRED")
        require(
            set(ref)
            == {
                "format",
                "plan_id",
                "version",
                "artifact_sha256",
                "failure",
                "solve_calls",
                "planning",
                "completion_h",
                "anchor_events",
            }
            and ref["format"] == "P051-FULL-SCHEDULE-1"
            and type(ref["version"]) is int
            and type(ref["anchor_events"]) is int
            and type(ref["solve_calls"]) is int
            and type(ref["planning"]) is bool
            and 0 <= ref["version"] <= ref["solve_calls"] <= self.report["used_calls"],
            "FULL_REFERENCE_SHAPE",
        )
        envelope = packet["envelope"]
        require(
            (envelope["run_id"], envelope["epoch"], envelope["run_spec_sha256"])
            == (self.spec["run_id"], self.spec["epoch"], digest(self.spec)),
            "FULL_REFERENCE_RUN",
        )
        key = ref["artifact_sha256"]
        if key is None:
            # A first planning attempt may legitimately have no adopted plan.
            require(
                not self.seen_plan
                and ref["version"] == 0
                and ref["plan_id"] is None
                and ref["completion_h"] is None
                and ref["anchor_events"] == 0,
                "FULL_REFERENCE_EMPTY_AFTER_ADOPTION",
            )
        else:
            require(isinstance(key, str) and key in self.plans, "FULL_REFERENCE_ARTIFACT")
            plan = self.plans[key]
            require(
                all(
                    ref[field] == plan[field]
                    for field in (
                        "format",
                        "plan_id",
                        "version",
                        "anchor_events",
                        "completion_h",
                    )
                ),
                "FULL_REFERENCE_IDENTITY",
            )
            require(
                0 <= plan["anchor_events"] <= envelope["event_count"]
                and plan["anchor_h"] <= envelope["sampled_sim_h"]
                and prefix_hashes.get(plan["anchor_events"]) == plan["event_prefix_sha256"],
                "FULL_REFERENCE_VISIBLE_ANCHOR",
            )
            self.seen_plan = True
        self.reference = ref

    def finish(self, latest):
        require(self.packets > 0, "FULL_REFERENCE_STREAM_EMPTY")
        # The writer's latest materialization contains rows/envelope/hash, not
        # a full-plan reference. If a carrier includes one, it must agree too.
        if "full_schedule" in latest:
            require(latest["full_schedule"] == self.reference, "FULL_REFERENCE_LATEST")
        require(
            self.seen_plan
            and self.reference["version"] == self.report["version"]
            and self.reference["artifact_sha256"] == self.report["plan_sha256"]
            and self.reference["solve_calls"] == self.report["used_calls"]
            and self.reference["failure"] == self.report["failure"]
            and self.reference["planning"] is False,
            "FULL_REFERENCE_FINAL",
        )

    def check_projection(self, view):
        require(view.get("full_schedule") == self.reference, "DISPLAY_REFERENCE")
        rows = [row for row in view["rows"] if row["row_kind"] == "FULL_PLAN"]
        by_id = {row["row_id"]: row for row in rows}
        expected = {}
        for key, plan in self.plans.items():
            for index, interval in enumerate(plan["intervals"]):
                expected[f"full:{plan['version']}:{index}"] = (key, plan, interval)
        require(
            len(by_id) == len(rows) and by_id.keys() == expected.keys(), "DISPLAY_PLAN_COVERAGE"
        )
        for name, (key, plan, interval) in expected.items():
            row = by_id[name]
            current = key == self.reference["artifact_sha256"]
            state = "RETAINED_BLOCKED" if self.reference["failure"] else "CURRENT_PLAN"
            require(
                row["plan_id"] == plan["plan_id"]
                and row["plan_version"] == plan["version"]
                and row["proposal_state"] == (state if current else "SUPERSEDED")
                and all(
                    row[field] == interval[field]
                    for field in (
                        "command_id",
                        "operation_id",
                        "activity_id",
                        "product_id",
                        "roles",
                        "start_h",
                        "end_h",
                    )
                ),
                "DISPLAY_PLAN_BINDING",
            )
        return dict(
            status="PASS",
            delivered_references=self.packets,
            plans=len(self.plans),
            full_plan_rows=len(rows),
            final_reference=self.reference,
        )


def validate_archive(directory):
    """Check the complete sealed stream before any plan is added to a cache."""
    import hashlib

    from adaptive_hrc_scheduling.contracts.session import canonical, loads

    binding = ScheduleBindings(directory)
    event_hash = hashlib.sha256(b"[")
    prefix_hashes = {0: digest([])}
    count = 0
    with (directory / "timeline.jsonl").open("rb") as stream:
        while line := stream.readline(128_000_001):
            require(len(line) <= 128_000_000 and line.endswith(b"\n"), "SEALED_TIMELINE_LINE")
            packet = loads(line)
            for event in packet["events"]:
                if count:
                    event_hash.update(b",")
                event_hash.update(canonical(event))
                count += 1
                closed = event_hash.copy()
                closed.update(b"]")
                prefix_hashes[count] = closed.hexdigest()
            require(count == packet["envelope"]["event_count"], "REFERENCE_EVENT_COUNT")
            binding.check_reference(packet, prefix_hashes)
    binding.finish(binding.read("timeline-latest.json"))
    return binding
